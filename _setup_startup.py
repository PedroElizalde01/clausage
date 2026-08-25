import sys, os

pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
tray = r"C:\Users\Pedro\projects\clausage\tray.py"
startup = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
vbs_path = os.path.join(startup, "clausage.vbs")

vbs = (
    'Set ws = CreateObject("WScript.Shell")\r\n'
    f'ws.Run Chr(34) & "{pythonw}" & Chr(34) & " " & Chr(34) & "{tray}" & Chr(34), 0, False\r\n'
)

with open(vbs_path, "w") as f:
    f.write(vbs)

print(f"Startup entry written to:\n  {vbs_path}")
print(f"pythonw: {pythonw}")
print(f"tray.py: {tray}")
