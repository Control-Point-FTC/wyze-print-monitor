"""Check for updates / install the latest release, from inside the app.

``UpdateManager`` checks GitHub shortly after startup and every few hours
(Settings → "Check for updates automatically"), and on demand from
Help → Check for updates. When a newer release exists it emits
``available``; the window's status bar, the Studio dock and the tray then
show an Update button. Installing downloads the release's installer
(verified, see ``updater``), runs it silently and quits; the installer
reopens the app when it's done.

Self-install only happens in the installed (packaged) app. Run from source,
"Update" opens the release page instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .. import __version__
from ..updater import ReleaseInfo, UpdateError, download_installer, fetch_latest, is_newer

FIRST_CHECK_DELAY_MS = 8_000
CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
# Inno Setup flags: no wizard pages, no prompts, close the running app.
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")


class _Worker(QThread):
    """Runs one blocking network call off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, job, parent=None) -> None:
        super().__init__(parent)
        self._job = job
        self.cancel_requested = False

    def run(self) -> None:
        try:
            result = self._job(self)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never crashes the app
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(result)


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
        self._download_worker: _Worker | None = None
        self._progress: QProgressDialog | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(lambda: self.check(silent=True))

    def start(self) -> None:
        """Begin automatic checks (if enabled in Settings)."""
        QTimer.singleShot(FIRST_CHECK_DELAY_MS, lambda: self.check(silent=True))
        self._timer.start()

    def busy(self) -> bool:
        return any(
            w is not None and w.isRunning() for w in (self._check_worker, self._download_worker)
        )

    def wait(self) -> None:
        """Join worker threads before the app exits."""
        for worker in (self._check_worker, self._download_worker):
            if worker is not None and worker.isRunning():
                worker.cancel_requested = True
                worker.wait()

    # ------------------------------------------------------------------ check
    def check(self, silent: bool) -> None:
        if silent and not self.main.settings.check_updates:
            return
        if self._check_worker is not None and self._check_worker.isRunning():
            return
        worker = _Worker(lambda _w: fetch_latest(), self)
        worker.succeeded.connect(lambda info: self._on_checked(info, silent))
        worker.failed.connect(lambda error: self._on_check_failed(error, silent))
        self._check_worker = worker
        worker.start()

    def _on_checked(self, info: ReleaseInfo | None, silent: bool) -> None:
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
        if self._download_worker is not None and self._download_worker.isRunning():
            return
        main = self.main
        if main._compile_worker is not None and main._compile_worker.isRunning():
            QMessageBox.information(
                main, "Update", "A timelapse is still being compiled — update once it's saved."
            )
            return
        warning = ""
        if main._recorder is not None or main._timelapse is not None:
            warning = "\n\nThe recording / timelapse in progress will be stopped and saved first."
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
            ),
            self,
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
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _on_download_failed(self, error: str) -> None:
        self._close_progress()
        if error != "Download cancelled.":
            QMessageBox.warning(self.main, "Update failed", error)

    def _on_downloaded(self, path: str) -> None:
        self._close_progress()
        try:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([path, *INSTALLER_ARGS], close_fds=True, creationflags=flags)  # noqa: S603
        except OSError as exc:
            QMessageBox.warning(self.main, "Update failed", f"Couldn't start the installer:\n{exc}")
            return
        # The installer waits for us to exit (and closes us if needed), then
        # reopens the app once the new version is in place.
        self.main.quit_app()
