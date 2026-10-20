"""The print watcher's brain on the GUI side: when to watch, alert, pause.

Rules (the user's):

* Alert whenever something *might* be wrong — the model's warning level, or
  an unusual sound. Alerts show on the video, in a Windows notification,
  with a beep and a saved snapshot.
* Pause through Studio's Pause button only when the model is very sure
  (its failure level, held for several checks — see failure_detect), and
  only if "auto-pause" is on.
* Never stop a print on its own: Stop is a button on the alert, and it asks
  first.

While Studio is open we only watch when it shows a print running (its Pause
button is visible), which also keeps the CPU idle between prints. Without
Studio there's no way to know, so we watch whenever the stream is live
(alerts only: there's nothing to pause through).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import cv2
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from .. import failure_model, studio_win32
from ..config import save_settings
from ..failure_detect import FAILURE, SENSITIVITY, WARNING, Baseline, FailureScorer, draw_detections
from ..print_watch import SoundWorker, VisionResult, VisionWorker
from ..sound_watch import describe as describe_sound

STUDIO_POLL_MS = 3000
WARNING_REPEAT_S = 15 * 60  # don't nag: one warning alert per this long
LOOKS_FINE_SNOOZE_S = 30 * 60
BASELINE_SAVE_EVERY = 30  # checks


@dataclass
class Alert:
    severity: str  # "warning" | "failure" | "paused" | "sound"
    title: str
    message: str
    snapshot: str = ""
    can_pause: bool = False
    can_resume: bool = False
    can_stop: bool = False
    at: float = 0.0


class PrintWatch(QObject):
    alert_changed = Signal(object)  # Alert or None
    notify = Signal(str, str)  # title, message (tray notification)
    status_changed = Signal()  # status_text() / risk changed
    download_progress = Signal(int, int)
    download_finished = Signal(bool, str)  # ok, message

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.alert: Alert | None = None
        self.risk = 0.0
        self.last_check = 0.0
        self._vision: VisionWorker | None = None
        self._retired: list = []  # stopped workers still finishing
        self._sound: SoundWorker | None = None
        self._sound_status = ""
        self._url = ""
        self._scorer = FailureScorer(Baseline.from_dict(main.settings.ai_baseline))
        self._studio_controls: dict[str, int] = {}
        self._studio_seen = False
        self._printing: bool | None = None  # None: unknown (no Studio)
        self._paused_by_us = False
        self._last_warning = -1e9
        self._snooze_until = 0.0
        self._checks = 0
        self._error = ""
        self._download: threading.Thread | None = None
        self._download_cancel = False
        self._poll = QTimer(self)
        self._poll.setInterval(STUDIO_POLL_MS)
        self._poll.timeout.connect(self._poll_studio)

    # ------------------------------------------------------------------ setup
    @property
    def settings(self):
        return self.main.settings

    def model_ready(self) -> bool:
        return failure_model.is_installed()

    def enabled(self) -> bool:
        return bool(self.settings.ai_watch) and self.model_ready()

    def apply_settings(self) -> None:
        """(Re)start or stop the workers to match the settings."""
        self._restart_workers()

    def set_stream(self, url: str | None) -> None:
        """The video stream started (url) or stopped (None)."""
        url = url or ""
        if url == self._url:
            return
        self._url = url
        self._restart_workers()

    def _restart_workers(self) -> None:
        self._stop_workers()
        self._scorer.sensitivity = SENSITIVITY.get(self.settings.ai_sensitivity, 1.0)
        if not self._url:
            self._poll.stop()
            self.status_changed.emit()
            return
        self._error = ""
        if self.enabled():
            self._vision = VisionWorker(failure_model.model_path(), self._latest_frame, self._scorer, parent=self)
            self._vision.checked.connect(self._on_checked)
            self._vision.failed.connect(self._on_failed)
            self._vision.start(VisionWorker.LowPriority)
        if self.settings.ai_watch and self.settings.sound_alerts:
            self._sound = SoundWorker(self._url, parent=self)
            self._sound.unusual.connect(self._on_sound)
            self._sound.status.connect(self._on_sound_status)
            self._sound.start(SoundWorker.LowPriority)
        if self._vision or self._sound:
            self._poll.start()
            self._poll_studio()
        self.status_changed.emit()

    def _stop_workers(self) -> None:
        for worker in (self._vision, self._sound):
            if worker is not None:
                for signal in (getattr(worker, n, None) for n in ("checked", "failed", "unusual", "status")):
                    if signal is not None:
                        try:
                            signal.disconnect()
                        except (RuntimeError, TypeError):
                            pass
                worker.request_stop()
                if worker.isRunning():
                    # Never let a running QThread be destroyed: keep it until done.
                    self._retired.append(worker)
                    worker.finished.connect(lambda w=worker: self._retired.remove(w) if w in self._retired else None)
        self._vision = self._sound = None
        self._sound_status = ""
        self._save_baseline()

    def shutdown(self) -> None:
        self._poll.stop()
        self._download_cancel = True
        self._stop_workers()
        for worker in list(self._retired):
            worker.wait(12000)  # each network wait is bounded by its timeout
        self._retired.clear()

    def _latest_frame(self):
        reader = self.main._reader
        return reader.last_frame if reader is not None else None

    def _save_baseline(self) -> None:
        data = self._scorer.baseline.to_dict()
        if data != self.settings.ai_baseline:
            self.settings.ai_baseline = data
            try:
                save_settings(self.settings)
            except OSError:
                pass

    # ------------------------------------------------------------------ Studio
    def _poll_studio(self) -> None:
        top = studio_win32.find_studio()
        controls = studio_win32.find_print_controls(top) if top else {}
        self._studio_seen = bool(top)
        self._studio_controls = controls
        printing = ("pause" in controls or "resume" in controls) if top else None
        if printing and not self._printing:
            # A print started (or Studio appeared mid-print): fresh session.
            self._reset_session()
            self._paused_by_us = False
            self._snooze_until = 0.0
            if self._sound is not None:
                self._sound.anomaly.reset()
        if self._printing and printing is False and self.alert and self.alert.severity != "paused":
            self._set_alert(None)  # print ended: an old warning is moot
        self._printing = printing
        # Only spend CPU while something is printing (or we can't tell).
        idle = printing is False or "resume" in controls  # finished, or paused
        for worker in (self._vision, self._sound):
            if worker is not None:
                worker.paused = idle
        if self.alert is not None:
            self.alert.can_pause = "pause" in controls
            self.alert.can_resume = "resume" in controls
            self.alert.can_stop = "stop" in controls
            self.alert_changed.emit(self.alert)
        self.status_changed.emit()

    def _reset_session(self) -> None:
        # The scorer belongs to the vision thread while it runs.
        if self._vision is not None:
            self._vision.reset_requested = True
        else:
            self._scorer.reset_session()

    def can_pause(self) -> bool:
        return "pause" in self._studio_controls

    def pause_print(self) -> bool:
        hwnd = self._studio_controls.get("pause")
        ok = bool(hwnd) and studio_win32.press(hwnd)
        if ok:
            QTimer.singleShot(1500, self._poll_studio)
        return ok

    def resume_print(self) -> bool:
        hwnd = self._studio_controls.get("resume")
        ok = bool(hwnd) and studio_win32.press(hwnd)
        if ok:
            self._paused_by_us = False
            self._reset_session()
            self._set_alert(None)
            QTimer.singleShot(1500, self._poll_studio)
        return ok

    def stop_print(self, parent: QWidget | None = None) -> bool:
        """Stop — only after the user confirms (Studio may ask again)."""
        hwnd = self._studio_controls.get("stop")
        if not hwnd:
            return False
        answer = QMessageBox.warning(
            parent,
            "Stop the print?",
            "This stops the print in eufyMake Studio. It can't be resumed afterwards.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return False
        ok = studio_win32.press(hwnd)
        if ok:
            self._set_alert(None)
            QTimer.singleShot(1500, self._poll_studio)
        return ok

    def looks_fine(self) -> None:
        """The user checked: it's fine. Quiet for a while, and re-learn."""
        self._snooze_until = time.monotonic() + LOOKS_FINE_SNOOZE_S
        self._reset_session()
        self._set_alert(None)

    def dismiss(self) -> None:
        self._set_alert(None)

    # ------------------------------------------------------------------ results
    def _on_checked(self, result: VisionResult) -> None:
        self.risk = result.risk
        self.last_check = time.time()
        self._checks += 1
        if self._checks % BASELINE_SAVE_EVERY == 0:
            self._save_baseline()
        self.status_changed.emit()
        now = time.monotonic()
        if result.level == FAILURE:
            self._on_failure(result, now)
        elif result.level == WARNING and now >= self._snooze_until:
            if now - self._last_warning >= WARNING_REPEAT_S and (self.alert is None or self.alert.severity == "sound"):
                self._last_warning = now
                self._raise(
                    "warning",
                    "Possible print problem",
                    "The AI sees something that may be a failure (spaghetti, a blob or a loose part). Take a look.",
                    result,
                )

    def _on_failure(self, result: VisionResult, now: float) -> None:
        if self.alert is not None and self.alert.severity in ("failure", "paused"):
            return  # already handling it
        if self._paused_by_us:
            return
        if self.settings.ai_auto_pause and self.can_pause() and self.pause_print():
            self._paused_by_us = True
            self._raise(
                "paused",
                "Print paused — it looks like it failed",
                "The AI was very sure for over 30 seconds, so it pressed Pause in Studio. "
                "Check the printer, then Resume or Stop.",
                result,
            )
        else:
            why = "" if self.settings.ai_auto_pause else " (auto-pause is off)"
            self._raise(
                "failure",
                "The print looks like it failed",
                f"The AI is very sure something went wrong{why}. Check the printer now.",
                result,
            )

    def _on_sound(self, event) -> None:
        if time.monotonic() < self._snooze_until or (self.alert is not None and self.alert.severity != "sound"):
            return
        self._raise("sound", "Unusual printer sound", describe_sound(event), None)

    def _on_sound_status(self, status: str) -> None:
        self._sound_status = status
        self.status_changed.emit()

    def _on_failed(self, message: str) -> None:
        self._error = message
        self._vision = None
        self.status_changed.emit()
        self.main.status_message.emit(message)

    # ------------------------------------------------------------------ alerting
    def _raise(self, severity: str, title: str, message: str, result: VisionResult | None) -> None:
        snapshot = self._save_snapshot(result, severity)
        controls = self._studio_controls
        alert = Alert(
            severity,
            title,
            message,
            snapshot,
            can_pause="pause" in controls,
            can_resume="resume" in controls,
            can_stop="stop" in controls,
            at=time.time(),
        )
        self._set_alert(alert)
        self.notify.emit(title, message)
        _beep(severity in ("failure", "paused"))

    def _set_alert(self, alert: Alert | None) -> None:
        self.alert = alert
        self.alert_changed.emit(alert)

    def _save_snapshot(self, result: VisionResult | None, severity: str) -> str:
        frame = result.frame if result is not None else self._latest_frame()
        if frame is None:
            return ""
        if result is not None:
            frame = draw_detections(frame, result.detections)
        folder = self.settings.resolved_snapshot_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"print-watch-{severity}-{time.strftime('%Y%m%d-%H%M%S')}.jpg")
            if cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 88]):
                self.main.capture_saved.emit(path)
                return path
        except (OSError, cv2.error):
            pass
        return ""

    # ------------------------------------------------------------------ status
    def status_text(self) -> str:
        if not self.settings.ai_watch:
            return ""
        if not self.model_ready():
            return "Print watch: model not downloaded"
        if self._error:
            return "Print watch: stopped (model error)"
        if not self._url:
            return "Print watch: waiting for video"
        if self._printing is False:
            return "Print watch: idle (no print running)"
        if self._printing and "resume" in self._studio_controls:
            return "Print watch: print paused"
        if not self.last_check:
            return "Print watch: starting…"
        return f"Print watch: {_risk_word(self.risk)}"

    # ------------------------------------------------------------------ model download
    def downloading(self) -> bool:
        return self._download is not None and self._download.is_alive()

    def download_model(self) -> None:
        if self.downloading():
            return
        self._download_cancel = False

        def work() -> None:
            try:
                failure_model.download_model(
                    progress=lambda done, total: self.download_progress.emit(done, total),
                    cancelled=lambda: self._download_cancel,
                )
            except failure_model.DownloadCancelled:
                self.download_finished.emit(False, "Download cancelled.")
            except Exception as exc:  # network, disk, checksum
                self.download_finished.emit(False, f"Couldn't download the model: {exc}")
            else:
                self.download_finished.emit(True, "Model downloaded and verified.")

        self._download = threading.Thread(target=work, name="model-download", daemon=True)
        self._download.start()

    def cancel_download(self) -> None:
        self._download_cancel = True

    def remove_model(self) -> None:
        self._stop_workers()
        failure_model.remove_model()
        self._restart_workers()


def _risk_word(risk: float) -> str:
    if risk >= 2 / 3:
        return "looks like a failure"
    if risk >= 1 / 3:
        return "something may be wrong"
    return "all good"


def _beep(urgent: bool) -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONHAND if urgent else winsound.MB_ICONEXCLAMATION)
    except (ImportError, RuntimeError):
        pass
