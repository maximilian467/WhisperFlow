' Startet WhisperFlow ohne sichtbares Konsolenfenster (fuer den Autostart).
' Ausgaben landen in whisperflow.log im Projektordner.
Set fso = CreateObject("Scripting.FileSystemObject")
rootDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = rootDir
pyw = """" & rootDir & "\venv\Scripts\pythonw.exe"""
shell.Run pyw & " -m whisperflow", 0, False
