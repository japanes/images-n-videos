#!/bin/bash
# Vertex AI Factory: stop (macOS; also works on Linux).
# Stops and removes the app containers. Your files, settings and key stay.
cd "$(dirname "$0")" || exit 1
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"

lang="$(defaults read -g AppleLanguages 2>/dev/null | sed -n 's/[^a-z]*\([a-z][a-z]\).*/\1/p' | head -n 1)"
[ -n "$lang" ] || lang="${LANG%%_*}"
case "$lang" in
  ru)
    T_NO_DOCKER="Docker Desktop не запущен, значит программа уже остановлена."
    T_STOPPING="Останавливаю Vertex AI Factory..."
    T_DONE="Готово, программа остановлена. Ваши файлы и настройки сохранены."
    T_FAILED="Не удалось остановить. Откройте Docker Desktop и остановите vertexai-factory там."
    T_CLOSE="Это окно можно закрыть. Нажмите Enter."
    ;;
  uk)
    T_NO_DOCKER="Docker Desktop не запущено, отже програму вже зупинено."
    T_STOPPING="Зупиняю Vertex AI Factory..."
    T_DONE="Готово, програму зупинено. Ваші файли та налаштування збережено."
    T_FAILED="Не вдалося зупинити. Відкрийте Docker Desktop і зупиніть vertexai-factory там."
    T_CLOSE="Це вікно можна закрити. Натисніть Enter."
    ;;
  *)
    T_NO_DOCKER="Docker Desktop is not running, so the app is already stopped."
    T_STOPPING="Stopping Vertex AI Factory..."
    T_DONE="Done, the app is stopped. Your files and settings are kept."
    T_FAILED="Could not stop. Open Docker Desktop and stop vertexai-factory there."
    T_CLOSE="You can close this window. Press Enter."
    ;;
esac

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "$T_NO_DOCKER"
  exit 0
fi

echo "$T_STOPPING"
# --remove-orphans also removes app, render and stt, which the updater started.
if docker compose down --remove-orphans; then
  echo "$T_DONE"
  exit 0
fi
echo "$T_FAILED"
echo "$T_CLOSE"
read -r _
exit 1
