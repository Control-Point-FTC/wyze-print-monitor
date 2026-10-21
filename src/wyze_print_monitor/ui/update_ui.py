"""Check for updates / install the latest release, from inside the app.

``UpdateManager`` checks GitHub shortly after startup and every few hours
(Settings → "Check for updates automatically"), and on demand from
Help → Check for updates. When a newer release exists it emits
``available``; the window's status bar, the Studio dock and the tray then
show an Update button. Installing downloads the release's installer
(verified, see ``updater``), quits, and a small hidden helper starts the
installer once this process has fully exited; the installer reopens the app
when it's done.

Self-install only happens in the installed (packaged) app. Run from source,
"Update" opens the release page instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .. import __version__
from ..updater import (
    ReleaseInfo,
    UpdateError,
    download_installer,
    fetch_latest,
    installer_launch_command,
    is_newer,
)

FIRST_CHECK_DELAY_MS = 8_000
CHECK_INTERVAL_MS = 60 * 60 * 1000  # hourly: a new release shows up the same day


class _Worker(QObject):
    """Runs one blocking network call on a daemon thread.

    Daemon threads never hold up quitting (a stalled GitHub request can't
    freeze the app on exit). The QObject has no Qt parent, so it stays valid
    for as long as the thread holds it; signals reach the GUI thread queued.
    """

    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, job) -> None:
        super().__init__()
        self._job = job
        self.cancel_requested = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            result = self._job(self)
        except UpdateError as exc:
            outcome = (self.failed, str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never crashes the app
            outcome = (self.failed, f"Unexpected error: {exc}")
        else:
            outcome = (self.succeeded, result)
        try:
            outcome[0].emit(outcome[1])
        except RuntimeError:
            pass  # app already shutting down


def can_self_install() -> bool:
    """Only the packaged Windows app can replace itself with an installer."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


class UpdateManager(QObject):
    available = Signal(object)  # ReleaseInfo, newer than the running version

    def __init__(self, main) -> None:
        super().__init__(main)
        self.main = main
        self.latest: ReleaseInfo | None = None
        self._check_worker: _Worker | None = None
        self._check_silent = True  # the running check's: a manual click can upgrade it
        self._download_worker: _Worker | None = None
        self._progress: QProgressDialog | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(lambda: self.check(silent=True))

    def start(self) -> None:
        """Begin automatic checks (if enabled in Settings)."""
        QTimer.singleShot(FIRST_CHECK_DELAY_MS, lambda: self.check(silent=True))
        self._timer.start()

    def shutdown(self) -> None:
        """Called on exit: stop a download; never waits on the network."""
        self._timer.stop()
        if self._download_worker is not None:
            self._download_worker.cancel_requested = True

    # ------------------------------------------------------------------ check
    def check(self, silent: bool) -> None:
        if silent and not self.main.settings.check_updates:
            return
        if self._check_worker is not None and self._check_worker.is_running():
            if not silent:
                self._check_silent = False  # the user asked: answer when it finishes
            return
        self._check_silent = silent
        worker = _Worker(lambda _w: fetch_latest())
        worker.succeeded.connect(lambda info: self._on_checked(info, self._check_silent))
        worker.failed.connect(lambda error: self._on_check_failed(error, self._check_silent))
        self._check_worker = worker
        worker.start()

    def _on_checked(self, info: ReleaseInfo | None, silent: bool) -> None:
        self._check_worker = None  # finished: let it be collected
        if info is not None and is_newer(info.version, __version__):
            if self.latest != info:
                self.latest = info
                self.available.emit(info)
            if not silent:
                self.install()
        elif not silent:
            QMessageBox.information(
                self.main,
                "Check for updates",
                f"You're up to date — Wyze Print Monitor {__version__} is the latest version.",
            )

    def _on_check_failed(self, error: str, silent: bool) -> None:
        self._check_worker = None
        if not silent:
            QMessageBox.warning(self.main, "Check for updates", error)

    # ------------------------------------------------------------------ install
    def install(self) -> None:
        info = self.latest
        if info is None:
            return
        if not can_self_install() or not info.installer_url:
            QDesktopServices.openUrl(QUrl(info.page_url))
            return
        if self._download_worker is not None:
            return  # already downloading
        main = self.main
        if main._timelapse is not None or (
            main._compile_worker is not None and main._compile_worker.isRunning()
        ):
            # Quitting mid-timelapse would leave its frames without a video.
            QMessageBox.information(
                main,
                "Update",
                "A timelapse is in progress. Stop it (it'll be saved as a video), "
                "then click Update again.",
            )
            return
        warning = ""
        if main._recorder is not None:
            warning = "\n\nThe recording in progress will be stopped and saved first."
        size_mb = info.installer_size / 1_048_576 if info.installer_size else 0
        answer = QMessageBox.question(
            main,
            "Update Wyze Print Monitor",
            f"Version {info.version} is available (you have {__version__}).\n\n"
            f"The update ({size_mb:.0f} MB) downloads now, then the app closes, "
            f"installs it and reopens by itself.{warning}\n\nUpdate now?",
        )
        if answer != QMessageBox.Yes:
            return
        self._start_download(info)

    def _start_download(self, info: ReleaseInfo) -> None:
        dest = os.path.join(tempfile.gettempdir(), "WyzePrintMonitor-update")
        progress = QProgressDialog("Downloading update…", "Cancel", 0, 100, self.main)
        progress.setWindowTitle("Update Wyze Print Monitor")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        self._progress = progress

        worker = _Worker(
            lambda w: download_installer(
                info,
                dest,
                progress=lambda received, total: w.progress.emit(received, total),
                cancelled=lambda: w.cancel_requested,
            )
        )
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_downloaded)
        worker.failed.connect(self._on_download_failed)
        progress.canceled.connect(lambda: setattr(worker, "cancel_requested", True))
        self._download_worker = worker
        worker.start()
        progress.show()

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress is None:
            return
        if total:
            self._progress.setValue(int(received * 100 / total))
            self._progress.setLabelText(
                f"Downloading update… {received / 1_048_576:.1f} of {total / 1_048_576:.1f} MB"
            )

    def _close_progress(self) -> None:
        if self._progress is not None:
            # QProgressDialog.close() emits canceled(); don't let our own
            # cleanup register as the user cancelling.
            self._progress.blockSignals(True)
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _on_download_failed(self, error: str) -> None:
        self._download_worker = None
        self._close_progress()
        if error != "Download cancelled.":
            QMessageBox.warning(self.main, "Update failed", error)

    def _on_downloaded(self, path: str) -> None:
        worker, self._download_worker = self._download_worker, None
        cancelled = worker is None or worker.cancel_requested  # read before closing the dialog
        self._close_progress()
        if cancelled:
            # Cancelled after the last chunk arrived: honor it.
            try:
                os.remove(path)
            except OSError:
                pass
            return
        try:
            # A hidden console, not DETACHED_PROCESS: PowerShell won't run
            # at all without a console. New process group so it outlives us.
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(  # noqa: S603 - fixed command, our own installer path
                installer_launch_command(os.getpid(), path), close_fds=True, creationflags=flags
            )
        except OSError as exc:
            QMessageBox.warning(self.main, "Update failed", f"Couldn't start the installer:\n{exc}")
            return
        # The helper starts setup once we've exited; setup reopens the app.
        self.main.quit_app()
