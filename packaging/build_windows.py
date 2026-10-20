"""Build the Windows app (PyInstaller) and its installer (Inno Setup).

    python packaging/build_windows.py                 # exe, + installer if ISCC is found
    python packaging/build_windows.py --expect-tag v1.2.0 --require-installer   # CI release

Outputs:
    build/dist/WyzePrintMonitor/WyzePrintMonitor.exe   the app (one folder)
    build/installer/WyzePrintMonitor-<version>-setup.exe

Run from the repository root with the build requirements installed
(packaging/requirements-build.txt) and the package importable
(``pip install --no-deps .``).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
ASSETS = ROOT / "src" / "wyze_print_monitor" / "assets"
ISS = ROOT / "installer" / "wyze-print-monitor.iss"
APP_NAME = "WyzePrintMonitor"

VERSION_INFO = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Control Point FTC'),
      StringStruct('FileDescription', 'Wyze Print Monitor'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', 'Wyze Print Monitor'),
      StringStruct('ProductVersion', '{v}'),
      StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def app_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from wyze_print_monitor import __version__

    return __version__


def find_iscc(explicit: str | None) -> str | None:
    candidates = [explicit] if explicit else []
    candidates.append(shutil.which("iscc") or "")
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
            candidates.append(os.path.join(base, "Programs", "Inno Setup 6", "ISCC.exe"))
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def run(cmd: list[str]) -> None:
    print("+", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def build_exe(version: str) -> Path:
    numeric = [int(p) for p in version.split(".")[:4] if p.isdigit()]
    numeric += [0] * (4 - len(numeric))
    work = BUILD / "work"
    work.mkdir(parents=True, exist_ok=True)
    version_file = work / "version_info.txt"
    version_file.write_text(
        VERSION_INFO.format(t=", ".join(map(str, numeric)), v=version, name=APP_NAME), encoding="utf-8"
    )
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--icon", str(ASSETS / "icon.ico"),
        "--version-file", str(version_file),
        "--add-data", f"{ASSETS}{os.pathsep}wyze_print_monitor/assets",
        # keyring finds its OS backends by entry point, which freezing loses.
        "--collect-submodules", "keyring.backends",
        "--hidden-import", "win32ctypes.core",
        "--exclude-module", "tkinter",
        "--distpath", str(BUILD / "dist"),
        "--workpath", str(work),
        "--specpath", str(work),
        str(ROOT / "packaging" / "launcher.py"),
    ])
    exe = BUILD / "dist" / APP_NAME / f"{APP_NAME}.exe"
    if not exe.is_file():
        raise SystemExit(f"PyInstaller finished but {exe} is missing")
    return exe


def build_installer(version: str, iscc: str) -> Path:
    run([iscc, f"/DAppVersion={version}", str(ISS)])
    setup = BUILD / "installer" / f"{APP_NAME}-{version}-setup.exe"
    if not setup.is_file():
        raise SystemExit(f"Inno Setup finished but {setup} is missing")
    return setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect-tag", help="fail unless the package version matches this git tag (vX.Y.Z)")
    parser.add_argument("--iscc", help="path to Inno Setup's ISCC.exe")
    parser.add_argument("--require-installer", action="store_true", help="fail if Inno Setup isn't available")
    parser.add_argument("--skip-exe", action="store_true", help="reuse an existing build/dist (installer only)")
    args = parser.parse_args()

    version = app_version()
    if args.expect_tag and args.expect_tag.lstrip("vV") != version:
        raise SystemExit(
            f"Tag {args.expect_tag} doesn't match the app version {version} "
            "(src/wyze_print_monitor/__init__.py). Bump __version__ before tagging."
        )
    print(f"Building Wyze Print Monitor {version}", flush=True)
    if not args.skip_exe:
        print(f"App: {build_exe(version)}", flush=True)

    iscc = find_iscc(args.iscc)
    if iscc is None:
        if args.require_installer:
            raise SystemExit("Inno Setup (ISCC.exe) not found; install it or pass --iscc.")
        print("Inno Setup not found: skipped the installer (the app folder is ready).", flush=True)
        return 0
    setup = build_installer(version, iscc)
    print(f"Installer: {setup} ({setup.stat().st_size / 1_048_576:.1f} MB)", flush=True)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"installer={setup}\nversion={version}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
