"""Register Clausage to start automatically on login (Windows).

Writes a small VBScript launcher into the user's Startup folder. VBScript is used
rather than a .bat so that pythonw runs without flashing a console window.
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRAY = os.path.join(HERE, "tray.py")


def launcher():
    """Path to a windowed interpreter, falling back to the current one."""
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def startup_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("ERROR: APPDATA is not set; cannot locate the Startup folder.")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def main():
    if not os.path.exists(TRAY):
        raise SystemExit(f"ERROR: tray.py not found next to this script ({TRAY}).")

    python = launcher()
    target = startup_dir()
    if not os.path.isdir(target):
        raise SystemExit(f"ERROR: Startup folder not found ({target}).")
    vbs_path = os.path.join(target, "clausage.vbs")

    vbs = (
        'Set ws = CreateObject("WScript.Shell")\r\n'
        f'ws.Run Chr(34) & "{python}" & Chr(34) & " " & '
        f'Chr(34) & "{TRAY}" & Chr(34), 0, False\r\n'
    )

    # UTF-16 (BOM) so a non-ASCII username survives regardless of the ANSI codepage.
    try:
        # newline="" keeps the explicit CRLFs above from becoming CR CRLF.
        with io.open(vbs_path, "w", encoding="utf-16", newline="") as handle:
            handle.write(vbs)
    except OSError as error:
        raise SystemExit(f"ERROR: could not write {vbs_path}: {error}")

    print(f"Startup entry written to:\n  {vbs_path}")
    print(f"  interpreter: {python}")
    print(f"  tray.py    : {TRAY}")


if __name__ == "__main__":
    main()
