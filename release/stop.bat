@echo off
rem Vertex AI Factory: stop (Windows).
rem Stops and removes the app containers. Your files, settings and key stay.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "LNG=en"
for /f %%L in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do set "LNG=%%L"
call :text_en
if /i "%LNG%"=="ru" call :text_ru
if /i "%LNG%"=="uk" call :text_uk

where docker >nul 2>&1
if errorlevel 1 set "PATH=%PATH%;%ProgramFiles%\Docker\Docker\resources\bin"
docker info >nul 2>&1
if errorlevel 1 goto no_docker

echo %T_STOPPING%
rem --remove-orphans also removes app, render and stt, which the updater started.
docker compose down --remove-orphans
if errorlevel 1 goto failed
echo %T_DONE%
timeout /t 5 >nul
exit /b 0

:no_docker
echo %T_NO_DOCKER%
timeout /t 5 >nul
exit /b 0

:failed
echo %T_FAILED%
echo.
pause
exit /b 1

:text_en
set "T_NO_DOCKER=Docker Desktop is not running, so the app is already stopped."
set "T_STOPPING=Stopping Vertex AI Factory..."
set "T_DONE=Done, the app is stopped. Your files and settings are kept."
set "T_FAILED=Could not stop. Open Docker Desktop and stop vertexai-factory there."
exit /b 0

:text_ru
set "T_NO_DOCKER=Docker Desktop не запущен, значит программа уже остановлена."
set "T_STOPPING=Останавливаю Vertex AI Factory..."
set "T_DONE=Готово, программа остановлена. Ваши файлы и настройки сохранены."
set "T_FAILED=Не удалось остановить. Откройте Docker Desktop и остановите vertexai-factory там."
exit /b 0

:text_uk
set "T_NO_DOCKER=Docker Desktop не запущено, отже програму вже зупинено."
set "T_STOPPING=Зупиняю Vertex AI Factory..."
set "T_DONE=Готово, програму зупинено. Ваші файли та налаштування збережено."
set "T_FAILED=Не вдалося зупинити. Відкрийте Docker Desktop і зупиніть vertexai-factory там."
exit /b 0
