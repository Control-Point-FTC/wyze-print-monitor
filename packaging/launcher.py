"""Entry point PyInstaller freezes into WyzePrintMonitor.exe."""
from wyze_print_monitor.app import main

if __name__ == "__main__":
    raise SystemExit(main())
