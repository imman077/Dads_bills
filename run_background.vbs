Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath
WshShell.Run "python server.py", 0, false
MsgBox "Dad Bills Server is starting in the background! 🟢" & vbCrLf & vbCrLf & "To stop it at any time, double-click 'stop_background.bat'.", 64, "Dad Bills Server"
