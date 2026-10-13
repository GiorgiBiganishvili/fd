# Guitar Tab AI

Локальное Windows desktop-приложение: видео → аудионоты → аппликатура →
редактируемая TAB с временной шкалой. Интерфейс — PySide6. Пальцы могут быть
не видны: тогда используется Audio + FingeringSolver.

## Установка

Для Basic Pitch нужен **Python 3.11 x64**. Python 3.12 поддерживает спектральный режим.
Установите [uv](https://docs.astral.sh/uv/getting-started/installation/),
[FFmpeg](https://ffmpeg.org/download.html) и `ffprobe`, а для OCR —
[Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html). Добавьте инструменты
в PATH. При отсутствии Tesseract анализ аудио продолжает работать.

В корне репозитория:

```powershell
uv sync --locked --python 3.11 --extra ml --extra dev
uv run --no-sync guitar-tab-ai
```

Без ML: `uv sync --locked --python 3.11 --extra dev`.
Базовый backend — спектральный CPU-анализ. При установленном extra `ml` выберите
**Basic Pitch** справа перед анализом: полифоническая модель с ONNX CPU inference.
Веса входят в пакет; сеть при анализе не нужна. Спектральный backend подходит
для одиночных мелодий/простых риффов. Фоновые инструменты, сложные аккорды и
дисторшн особенно требуют ручной проверки.

В облачной среде окружение уже установлено: `/workspace/fd/.venv/bin/guitar-tab-ai`.
Для GUI нужен дисплей. `QT_QPA_PLATFORM=offscreen` предназначен для тестов.
Используйте существующий checkout; создавать worktree не требуется.

## Работа с приложением

1. Нажмите «Загрузить видео» или перетащите MP4/MOV/MKV/AVI/WEBM в окно.
2. Выберите строй, капо и backend; «Анализировать видео» обновляет результат.
   Custom tuning задаётся от низкой струны к высокой: `D2 A2 D3 G3 B3 E4`.
3. Клик по ноте переводит видео к её времени; двойной клик открывает редактор
   струны, лада, MIDI, времени и техники. Перетаскивание меняет время/струну;
   при смене струны pitch пересчитывается.
4. `?` отмечает неопределённость. Режим проверки предлагает альтернативы.
   Ручные правки и удалённые автоматические ноты сохраняются при повторном анализе.
5. A–B задаёт повторяемый или повторно анализируемый участок.
6. Сохраните `.gtabproject`. Открытие не запускает анализ; видео хранится по ссылке.
   После перемещения файла используйте «Перепривязать видео».
7. Экспорт: ASCII TXT, JSON, MIDI, MusicXML, PNG, PDF; Copy TAB копирует текст.

Space — play/pause; стрелки — ±1 с; Shift+стрелки — ±10 с; Ctrl+Z/Redo — история;
Ctrl+E — редактирование; Ctrl+C/Ctrl+V — копирование/вставка выбранной ноты.
Техники можно указывать вручную; автоматическое распознавание техник не реализовано.

## OCR и CV

OCR ищет 6–8 TAB-линий и распознаёт целые номера ладов, включая 10–24. Цветная
подсветка даёт временные подсказки. Статичные цифры без временной привязки не
выдаются за синхронизированные ноты. OCR символов техник, ASCII TAB и надёжный
scroll tracking требуют дальнейшей разработки.

Для кандидатов по пальцам:

```powershell
uv sync --locked --python 3.11 --extra ml --extra dev --extra hands
```

Предоставьте локальный `hand_landmarker.task` из официального
[MediaPipe Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker).
Укажите путь в окне. Модели не скачиваются автоматически.
«Указать гриф вручную» задаёт четыре угла, высокую/низкую струну и физические лады.
Калибровка рассчитана на неподвижную камеру. Hough-detector даёт только предложение
грифа, не угадывая номер лада. Контакт пальца не доказывает сыгранную ноту.

Точность на произвольных видео не гарантируется. Confidence — оценка анализатора,
а не калиброванная вероятность. Строй и капо задаёт пользователь.
[Архитектура и границы реализации](docs/ARCHITECTURE.md).

## Настройки, данные и кэш

Windows: `%LOCALAPPDATA%\GuitarTabAI`; Linux: `~/.local/share/guitar-tab-ai`.
Внутри: `config.yaml`, SQLite preferences, `app.log`, кэш аудио/нот.
`GTAB_DATA_DIR` меняет папку. [Пример настроек](config.example.yaml) содержит пути
FFmpeg/Tesseract, веса fusion/аппликатуры, пороги, частоту кадров и лимит длительности.
По умолчанию один проход ограничен 30 минутами; длинное видео анализируйте участками.
Кэш можно удалить при закрытом приложении. Видео пользователя остаётся локально.

## Проверки

```powershell
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync guitar-tab-ai --analyze video.mp4 --backend basic-pitch --audio-only --output result.gtabproject
```

В Linux без дисплея задайте `QT_QPA_PLATFORM=offscreen` перед GUI-тестами.

## Windows .exe и установщик

Готовый portable-файл находится в `dist/GuitarTabAI.exe` (Windows 10/11 x64).
Его можно запускать двойным кликом: Python, FFmpeg/ffprobe и модель Basic Pitch
включены внутрь. Для ML-анализа выберите Basic Pitch в поле «Аудио».
Tesseract для OCR и модель MediaPipe для рук подключаются отдельно.
Файл собран Windows Python/PyInstaller под Wine; запуск окна и анализ видео
проверены под Wine. Проверка на физической Windows-машине пока не выполнена.

Повторная сборка одного portable `.exe` на Windows:

```powershell
.\scripts\build_windows.ps1 -SingleFile -SkipInstaller
```

Установите Inno Setup 6. Сборка включает runtime: Python на машине пользователя не нужен.
FFmpeg/ffprobe копируются из PATH. При установленном Tesseract копируются его файлы
и tessdata; иначе OCR можно подключить отдельной установкой.

```powershell
.\scripts\build_windows.ps1
```

Результат: `dist\GuitarTabAI\GuitarTabAI.exe` и `dist_installer\GuitarTabAISetup.exe`.
CI проверяет тесты, сборку, silent install/launch/uninstall и сохраняет артефакты.
Wine-проверки не заменяют проверку на чистой Windows. Перед выпуском проверьте
[лицензии](docs/THIRD_PARTY.md), codecs/OCR на чистой Windows и accuracy на размеченных видео.

`RussianTranscriberSource.zip` — старый повреждённый артефакт другого приложения.
Новый код находится в `src/guitar_tab_ai` и не использует этот архив.
