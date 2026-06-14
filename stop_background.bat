@echo off
echo Stopping Dad Bills server...
powershell -Command "Get-CimInstance Win32_Process -Filter 'Name = ''python.exe''' | Where-Object CommandLine -like '*server.py*' | Remove-CimInstance" >nul 2>&1
echo Server stopped successfully.
pause
