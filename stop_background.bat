@echo off
echo Stopping Dad Bills Local Admin...
powershell -Command "Get-CimInstance Win32_Process -Filter 'Name = ''python.exe''' | Where-Object CommandLine -like '*local_admin.py*' | Remove-CimInstance" >nul 2>&1
echo Local Admin stopped successfully.
pause
