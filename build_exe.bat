@echo off
REM ==========================================================================
REM  Patronix - construir el ejecutable de Windows
REM  Requisito (solo para quien construye, NO para los usuarios finales):
REM    Python 3.12 de https://www.python.org/downloads/  (marcar "Add to PATH")
REM  Uso:  doble clic en build_exe.bat   o   build_exe.bat onedir
REM ==========================================================================
setlocal
cd /d "%~dp0"
set "MODO=%~1"
if "%MODO%"=="" set "MODO=onefile"
set "SGVA_BUILD_MODE=%MODO%"

echo.
echo === Patronix: construyendo el ejecutable (%MODO%) ===
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro Python. Instala Python 3.12 desde python.org y vuelve a intentar.
  pause & exit /b 1
)

if not exist .venv-build (
  py -3.12 -m venv .venv-build 2>nul || py -3 -m venv .venv-build
  if errorlevel 1 goto :error
)
call .venv-build\Scripts\activate.bat

python -m pip install --upgrade pip >nul
pip install -r requirements-app.txt
if errorlevel 1 goto :error

if not exist assets\icon.ico python assets\generar_icono.py

pyinstaller --noconfirm --clean packaging\sgva_matchmaker.spec
if errorlevel 1 goto :error

if /i "%MODO%"=="onedir" (
  set "EXE=dist\Patronix\Patronix.exe"
) else (
  set "EXE=dist\Patronix.exe"
)

echo.
echo === Autoprueba del ejecutable (navegador, PDF, credenciales) ===
start "" /wait "%EXE%" --autoprueba --sin-red
if errorlevel 1 (
  echo [AVISO] La autoprueba encontro problemas. Revisa el reporte:
) else (
  echo [OK] Autoprueba superada. Reporte:
)
type "%LOCALAPPDATA%\Patronix\autoprueba.json"

echo.
certutil -hashfile "%EXE%" SHA256 | findstr /v "hash CertUtil"
echo.
echo === Listo: %EXE% ===
echo Comparte ese archivo (y su SHA256) con tus usuarios.
pause
exit /b 0

:error
echo.
echo [ERROR] La construccion fallo. Revisa los mensajes de arriba.
pause
exit /b 1
