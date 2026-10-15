#!/bin/bash
# Vertex AI Factory: start (macOS; also works on Linux).
# Starts Docker Desktop if needed, starts the app and opens it in the browser.
cd "$(dirname "$0")" || exit 1
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"

PORT=8787
if [ -f .env ]; then
  value="$(sed -n 's/^VF_PORT=\([0-9][0-9]*\).*/\1/p' .env | tail -n 1)"
  [ -n "$value" ] && PORT="$value"
fi
URL="http://127.0.0.1:$PORT"

lang="$(defaults read -g AppleLanguages 2>/dev/null | sed -n 's/[^a-z]*\([a-z][a-z]\).*/\1/p' | head -n 1)"
[ -n "$lang" ] || lang="${LANG%%_*}"
case "$lang" in
  ru)
    T_ALREADY="Vertex AI Factory уже работает. Открываю браузер."
    T_NO_DOCKER="Не найден Docker Desktop. Установите его с https://www.docker.com/products/docker-desktop/ , запустите один раз и снова откройте этот файл."
    T_START_DOCKER="Запускаю Docker Desktop..."
    T_NO_ENGINE="Docker Desktop не запустился за 3 минуты. Откройте его вручную, дождитесь зелёного статуса Engine running и снова откройте этот файл."
    T_STARTING="Запускаю Vertex AI Factory..."
    T_UP_FAILED="Не удалось запустить. Проверьте интернет и что Docker Desktop работает, потом попробуйте ещё раз."
    T_WAIT="Жду, пока программа будет готова. Первый запуск скачивает несколько гигабайт и может занять 5-20 минут."
    T_STILL="Всё ещё готовлюсь"
    T_READY="Готово. Открываю в браузере: "
    T_TIMEOUT="Программа не ответила за 30 минут. Откройте Docker Desktop: там видно, что происходит. Можно закрыть это окно и открыть этот файл ещё раз."
    T_CLOSE="Это окно можно закрыть. Нажмите Enter."
    ;;
  uk)
    T_ALREADY="Vertex AI Factory вже працює. Відкриваю браузер."
    T_NO_DOCKER="Не знайдено Docker Desktop. Встановіть його з https://www.docker.com/products/docker-desktop/ , запустіть один раз і знову відкрийте цей файл."
    T_START_DOCKER="Запускаю Docker Desktop..."
    T_NO_ENGINE="Docker Desktop не запустився за 3 хвилини. Відкрийте його вручну, дочекайтеся зеленого статусу Engine running і знову відкрийте цей файл."
    T_STARTING="Запускаю Vertex AI Factory..."
    T_UP_FAILED="Не вдалося запустити. Перевірте інтернет і що Docker Desktop працює, потім спробуйте ще раз."
    T_WAIT="Чекаю, поки програма буде готова. Перший запуск завантажує кілька гігабайт і може тривати 5-20 хвилин."
    T_STILL="Ще готуюся"
    T_READY="Готово. Відкриваю в браузері: "
    T_TIMEOUT="Програма не відповіла за 30 хвилин. Відкрийте Docker Desktop: там видно, що відбувається. Можна закрити це вікно і відкрити цей файл ще раз."
    T_CLOSE="Це вікно можна закрити. Натисніть Enter."
    ;;
  *)
    T_ALREADY="Vertex AI Factory is already running. Opening the browser."
    T_NO_DOCKER="Docker Desktop was not found. Install it from https://www.docker.com/products/docker-desktop/ , start it once, then open this file again."
    T_START_DOCKER="Starting Docker Desktop..."
    T_NO_ENGINE="Docker Desktop did not start in 3 minutes. Open it yourself, wait for the green Engine running status, then open this file again."
    T_STARTING="Starting Vertex AI Factory..."
    T_UP_FAILED="Could not start. Check the internet connection and that Docker Desktop is running, then try again."
    T_WAIT="Waiting for the app to get ready. The first start downloads several gigabytes and can take 5-20 minutes."
    T_STILL="Still getting ready"
    T_READY="Ready. Opening in the browser: "
    T_TIMEOUT="The app did not answer in 30 minutes. Open Docker Desktop to see what is going on. You can close this window and open this file again."
    T_CLOSE="You can close this window. Press Enter."
    ;;
esac

finish() {
  echo
  echo "$T_CLOSE"
  read -r _
  exit "$1"
}

app_ready() { curl -fsS --max-time 3 "$URL/health" >/dev/null 2>&1; }

open_browser() {
  if [ "$(uname)" = Darwin ]; then open "$URL"; else xdg-open "$URL" >/dev/null 2>&1 || true; fi
}

if app_ready; then
  echo "$T_ALREADY"
  open_browser
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "$T_NO_DOCKER"
  finish 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "$T_START_DOCKER"
  if [ "$(uname)" = Darwin ]; then open -a Docker >/dev/null 2>&1 || true; fi
  waited=0
  until docker info >/dev/null 2>&1; do
    if [ "$waited" -ge 180 ]; then
      echo "$T_NO_ENGINE"
      finish 1
    fi
    sleep 3
    waited=$((waited + 3))
  done
fi

echo "$T_STARTING"
# The updater adds app, render and stt to the same project: never remove them here.
if ! COMPOSE_IGNORE_ORPHANS=1 docker compose up -d; then
  echo
  echo "$T_UP_FAILED"
  finish 1
fi

echo "$T_WAIT"
waited=0
until app_ready; do
  if [ "$waited" -ge 1800 ]; then
    echo "$T_TIMEOUT"
    finish 1
  fi
  sleep 5
  waited=$((waited + 5))
  if [ $((waited % 60)) -eq 0 ]; then
    echo "$T_STILL... $((waited / 60)) min"
  fi
done

echo "$T_READY$URL"
open_browser
exit 0
