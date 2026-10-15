@echo off
rem Vertex AI Factory: start (Windows).
rem Starts Docker Desktop if needed, starts the app and opens it in the browser.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PORT=8787"
if exist ".env" for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="VF_PORT" set "PORT=%%B"
set "URL=http://127.0.0.1:%PORT%"

set "LNG=en"
for /f %%L in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do set "LNG=%%L"
call :text_en
if /i "%LNG%"=="ru" call :text_ru
if /i "%LNG%"=="uk" call :text_uk

curl.exe -fsS -o nul --max-time 3 "%URL%/health" >nul 2>&1
if not errorlevel 1 goto already

where docker >nul 2>&1
if errorlevel 1 set "PATH=%PATH%;%ProgramFiles%\Docker\Docker\resources\bin"
where docker >nul 2>&1
if errorlevel 1 goto no_docker

docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
echo %T_START_DOCKER%
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a WAITED=0
:wait_docker
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
if %WAITED% geq 180 goto no_engine
timeout /t 3 /nobreak >nul
set /a WAITED+=3
goto wait_docker

:docker_ok
echo %T_STARTING%
rem The updater adds app, render and stt to the same project: never remove them here.
set "COMPOSE_IGNORE_ORPHANS=1"
docker compose up -d
if errorlevel 1 goto up_failed

echo %T_WAIT%
set /a WAITED=0
:wait_app
curl.exe -fsS -o nul --max-time 3 "%URL%/health" >nul 2>&1
if not errorlevel 1 goto ready
if %WAITED% geq 1800 goto app_timeout
timeout /t 5 /nobreak >nul
set /a WAITED+=5
set /a REST=WAITED %% 60
set /a MIN=WAITED / 60
if %REST%==0 echo %T_STILL%... %MIN% min
goto wait_app

:ready
echo %T_READY% %URL%
start "" "%URL%"
timeout /t 5 >nul
exit /b 0

:already
echo %T_ALREADY%
start "" "%URL%"
timeout /t 3 >nul
exit /b 0

:no_docker
echo %T_NO_DOCKER%
goto fail

:no_engine
echo %T_NO_ENGINE%
goto fail

:up_failed
echo.
echo %T_UP_FAILED%
goto fail

:app_timeout
echo %T_TIMEOUT%
goto fail

:fail
echo.
pause
exit /b 1

:text_en
set "T_ALREADY=Vertex AI Factory is already running. Opening the browser."
set "T_NO_DOCKER=Docker Desktop was not found. Install it from https://www.docker.com/products/docker-desktop/ , start it once, then open this file again."
set "T_START_DOCKER=Starting Docker Desktop..."
set "T_NO_ENGINE=Docker Desktop did not start in 3 minutes. Open it yourself, wait for the green Engine running status, then open this file again."
set "T_STARTING=Starting Vertex AI Factory..."
set "T_UP_FAILED=Could not start. Check the internet connection and that Docker Desktop is running, then try again."
set "T_WAIT=Waiting for the app to get ready. The first start downloads several gigabytes and can take 5-20 minutes."
set "T_STILL=Still getting ready"
set "T_READY=Ready. Opening in the browser:"
set "T_TIMEOUT=The app did not answer in 30 minutes. Open Docker Desktop to see what is going on. You can close this window and open this file again."
exit /b 0

:text_ru
set "T_ALREADY=Vertex AI Factory уже работает. Открываю браузер."
set "T_NO_DOCKER=Не найден Docker Desktop. Установите его с https://www.docker.com/products/docker-desktop/ , запустите один раз и снова откройте этот файл."
set "T_START_DOCKER=Запускаю Docker Desktop..."
set "T_NO_ENGINE=Docker Desktop не запустился за 3 минуты. Откройте его вручную, дождитесь зелёного статуса Engine running и снова откройте этот файл."
set "T_STARTING=Запускаю Vertex AI Factory..."
set "T_UP_FAILED=Не удалось запустить. Проверьте интернет и что Docker Desktop работает, потом попробуйте ещё раз."
set "T_WAIT=Жду, пока программа будет готова. Первый запуск скачивает несколько гигабайт и может занять 5-20 минут."
set "T_STILL=Всё ещё готовлюсь"
set "T_READY=Готово. Открываю в браузере:"
set "T_TIMEOUT=Программа не ответила за 30 минут. Откройте Docker Desktop: там видно, что происходит. Можно закрыть это окно и открыть этот файл ещё раз."
exit /b 0

:text_uk
set "T_ALREADY=Vertex AI Factory вже працює. Відкриваю браузер."
set "T_NO_DOCKER=Не знайдено Docker Desktop. Встановіть його з https://www.docker.com/products/docker-desktop/ , запустіть один раз і знову відкрийте цей файл."
set "T_START_DOCKER=Запускаю Docker Desktop..."
set "T_NO_ENGINE=Docker Desktop не запустився за 3 хвилини. Відкрийте його вручну, дочекайтеся зеленого статусу Engine running і знову відкрийте цей файл."
set "T_STARTING=Запускаю Vertex AI Factory..."
set "T_UP_FAILED=Не вдалося запустити. Перевірте інтернет і що Docker Desktop працює, потім спробуйте ще раз."
set "T_WAIT=Чекаю, поки програма буде готова. Перший запуск завантажує кілька гігабайт і може тривати 5-20 хвилин."
set "T_STILL=Ще готуюся"
set "T_READY=Готово. Відкриваю в браузері:"
set "T_TIMEOUT=Програма не відповіла за 30 хвилин. Відкрийте Docker Desktop: там видно, що відбувається. Можна закрити це вікно і відкрити цей файл ще раз."
exit /b 0
