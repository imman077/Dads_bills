Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath
WshShell.Run "python local_admin.py", 0, false
MsgBox "Dad Bills Local Admin is starting in the background! 🟢" & vbCrLf & vbCrLf & "To stop it at any time, double-click 'stop_background.bat'.", 64, "Dad Bills Local Admin"

