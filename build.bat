@echo off
REM Build the standalone pyS7commplus_cli.exe on Windows 7 (Python 3.8.10).
REM Python 3.8 is the last release supporting Windows 7; the vendored
REM s7commplus backend in this folder has been back-ported to run on it.

set PY=C:\Users\dave\AppData\Local\Programs\Python\Python38\python.exe
if not exist "%PY%" set PY=python

"%PY%" -m pip install --disable-pip-version-check "cryptography==3.3.2" "pyinstaller>=6.0"
"%PY%" -m PyInstaller --clean -y pyS7commplus_cli.spec

echo.
echo Built: dist\pyS7commplus_cli.exe
