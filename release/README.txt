VERTEX AI FACTORY

Русский: ниже. Українська: нижче. English: below.

==============================================================
РУССКИЙ
==============================================================

Программа для создания картинок и видео моделями Google.
Работает на вашем компьютере и открывается в браузере.
Ваш ключ Google и ваши файлы остаются у вас.

Что нужно
- Windows 10/11 или macOS (подходят и Mac на Apple Silicon).
- Docker Desktop: https://www.docker.com/products/docker-desktop/
- Свободно: около 4 ГБ памяти (RAM) и 5 ГБ на диске.
  Для субтитров к видео нужно ещё около 1,6 ГБ - скачается само,
  когда вы впервые их включите.

Установка
1. Установите Docker Desktop и запустите его один раз.
2. Распакуйте этот архив в любую папку, например в Документы.
3. Откройте папку и запустите:
   - на Windows: start.bat (двойной щелчок);
   - на Mac: start.command (двойной щелчок).
4. Первый запуск скачивает несколько гигабайт - это может занять
   5-20 минут. Потом программа сама откроется в браузере.
   Адрес: http://127.0.0.1:8787

Если система не даёт запустить файл
- Mac: «не удалось проверить разработчика». Нажмите «Готово»,
  откройте Системные настройки - Конфиденциальность и безопасность,
  внизу нажмите «Всё равно открыть» и подтвердите. На старых macOS
  достаточно щёлкнуть по файлу правой кнопкой и выбрать «Открыть».
- Windows: «Система Windows защитила ваш компьютер». Нажмите
  «Подробнее», затем «Выполнить в любом случае». Если появилось
  окно «Не удаётся проверить издателя» - нажмите «Запустить».

Как остановить
Запустите stop.bat (Windows) или stop.command (Mac).
Ваши файлы, настройки и ключ сохранятся.

Обновления
Программа сама проверяет обновления и ставит их. Перед обновлением
она делает копию базы, а если новая версия не запустилась -
возвращает прежнюю. Когда и как обновляться, можно настроить
в самой программе.

Если порт 8787 занят
В папке есть скрытый файл .env со строкой VF_PORT=8787.
Поменяйте число (например на 8788) и запустите start ещё раз.
(На Mac скрытые файлы показывает сочетание Cmd+Shift+точка.)

Как удалить
1. Запустите stop.
2. Чтобы удалить и все ваши данные, выполните в терминале:
   docker volume rm vertexai-factory-data
3. В Docker Desktop, в разделе Images, удалите образы
   ghcr.io/japanes/images-n-videos/...
4. Удалите эту папку.

==============================================================
УКРАЇНСЬКА
==============================================================

Програма для створення зображень і відео моделями Google.
Працює на вашому комп'ютері й відкривається в браузері.
Ваш ключ Google і ваші файли залишаються у вас.

Що потрібно
- Windows 10/11 або macOS (підходять і Mac на Apple Silicon).
- Docker Desktop: https://www.docker.com/products/docker-desktop/
- Вільно: близько 4 ГБ пам'яті (RAM) і 5 ГБ на диску.
  Для субтитрів до відео потрібно ще близько 1,6 ГБ - завантажиться
  саме, коли ви вперше їх увімкнете.

Встановлення
1. Встановіть Docker Desktop і запустіть його один раз.
2. Розпакуйте цей архів у будь-яку папку, наприклад у Документи.
3. Відкрийте папку і запустіть:
   - на Windows: start.bat (подвійне клацання);
   - на Mac: start.command (подвійне клацання).
4. Перший запуск завантажує кілька гігабайт - це може тривати
   5-20 хвилин. Потім програма сама відкриється в браузері.
   Адреса: http://127.0.0.1:8787

Якщо система не дає запустити файл
- Mac: «не вдалося перевірити розробника». Натисніть «Готово»,
  відкрийте Системні параметри - Приватність і безпека,
  унизу натисніть «Усе одно відкрити» і підтвердьте. На старих
  macOS достатньо клацнути по файлу правою кнопкою і вибрати
  «Відкрити».
- Windows: «Система Windows захистила ваш комп'ютер». Натисніть
  «Докладніше», потім «Усе одно запустити». Якщо з'явилося вікно
  «Не вдається перевірити видавця» - натисніть «Запустити».

Як зупинити
Запустіть stop.bat (Windows) або stop.command (Mac).
Ваші файли, налаштування і ключ збережуться.

Оновлення
Програма сама перевіряє оновлення і встановлює їх. Перед оновленням
вона робить копію бази, а якщо нова версія не запустилася -
повертає попередню. Коли і як оновлюватися, можна налаштувати
в самій програмі.

Якщо порт 8787 зайнятий
У папці є прихований файл .env з рядком VF_PORT=8787.
Змініть число (наприклад на 8788) і запустіть start ще раз.
(На Mac приховані файли показує комбінація Cmd+Shift+крапка.)

Як видалити
1. Запустіть stop.
2. Щоб видалити й усі ваші дані, виконайте в терміналі:
   docker volume rm vertexai-factory-data
3. У Docker Desktop, у розділі Images, видаліть образи
   ghcr.io/japanes/images-n-videos/...
4. Видаліть цю папку.

==============================================================
ENGLISH
==============================================================

An app for making images and videos with Google models.
It runs on your computer and opens in your browser.
Your Google key and your files stay with you.

What you need
- Windows 10/11 or macOS (Apple Silicon Macs work too).
- Docker Desktop: https://www.docker.com/products/docker-desktop/
- Free: about 4 GB of memory (RAM) and 5 GB of disk space.
  Subtitles for videos need about 1.6 GB more - they download
  by themselves the first time you turn them on.

Install
1. Install Docker Desktop and start it once.
2. Unzip this archive into any folder, for example Documents.
3. Open the folder and start:
   - on Windows: start.bat (double-click);
   - on Mac: start.command (double-click).
4. The first start downloads several gigabytes - it can take
   5-20 minutes. Then the app opens in your browser by itself.
   Address: http://127.0.0.1:8787

If the system does not let you open the file
- Mac: "could not verify the developer". Click "Done", open
  System Settings - Privacy & Security, click "Open Anyway" at
  the bottom and confirm. On older macOS, right-click the file
  and choose "Open".
- Windows: "Windows protected your PC". Click "More info", then
  "Run anyway". If a window says "The publisher could not be
  verified", click "Run".

Stop
Start stop.bat (Windows) or stop.command (Mac).
Your files, settings and key are kept.

Updates
The app checks for updates and installs them by itself. Before an
update it makes a copy of the database, and if the new version does
not start, it brings the previous one back. When and how to update
can be set in the app itself.

If port 8787 is busy
The folder has a hidden file .env with the line VF_PORT=8787.
Change the number (for example to 8788) and start again.
(On Mac, Cmd+Shift+period shows hidden files.)

Uninstall
1. Run stop.
2. To delete all your data too, run in a terminal:
   docker volume rm vertexai-factory-data
3. In Docker Desktop, under Images, delete the images
   ghcr.io/japanes/images-n-videos/...
4. Delete this folder.
