# resolve_timeline.py — сборка таймлайна в DaVinci Resolve

Автоматизация импорта аудио и сборки таймлайна в **DaVinci Resolve Studio 18.1+**.

Скрипт читает все аудиофайлы из папки `final/`, лежащей **рядом со скриптом**, импортирует их в Media Pool текущего открытого проекта, создаёт новый таймлайн и раскладывает клипы встык по времени — каждому префиксу имени файла достаётся своя аудиодорожка.

---

## Требования

| Что | Комментарий |
|---|---|
| **DaVinci Resolve Studio** | Бесплатная версия внешний API не открывает. Нужна именно Studio (платная). |
| **Версия 18.1 и новее** | Обязательна для `AppendToTimeline` с батчем словарей `{clipInfo}`. |
| **Python 3.6+** | Подойдёт любой свежий CPython. Мост для скриптов ставится вместе с Resolve. |
| **«External scripting use» включён** | Resolve → **Preferences → System → General** → *External scripting use* → **Local** (или **Network**). |
| **Открытый проект в Resolve** | Скрипт цепляется к *текущему активному* проекту. |

---

## Структура папок

Положите `resolve_timeline.py` рядом с папкой `final/`, в которой лежит аудио:

```
your_project_dir/
├── resolve_timeline.py
└── final/
    ├── 001_Blueberry_001.mp3
    ├── 002_Hawk_001.mp3
    ├── 003_Blueberry_002.mp3
    └── ...
```

Поддерживаемые расширения: `.mp3 .wav .m4a .aac .aif .aiff .flac .ogg`.

### Как префикс имени превращается в дорожку

Функция `extract_prefix()` в начале скрипта решает, как группировать клипы. **По умолчанию:** вторая секция имени через «_».

| Файл | Префикс | Дорожка |
|---|---|---|
| `001_Blueberry_001.mp3` | `Blueberry` | A1 |
| `002_Hawk_001.mp3`      | `Hawk`      | A2 |
| `003_Blueberry_002.mp3` | `Blueberry` | A1 |
| `004_Mia_001.mp3`       | `Mia`       | A3 |

Если у вас другая схема имён — перепишите тело `extract_prefix()`. Альтернативные реализации («до первого подчёркивания», «первые N символов») даны рядом в комментариях.

---

## Настройка окружения

Модуль `DaVinciResolveScript` не лежит в `sys.path` по умолчанию. Нужно выставить три переменные окружения, чтобы Python его нашёл.

### macOS

Допишите в `~/.zshrc` (или `~/.bash_profile`):

```bash
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

И перезагрузите:

```bash
source ~/.zshrc
```

### Windows (постоянно — через пользовательские переменные)

Открой **Пуск → «Изменить переменные среды для вашей учётной записи» → Переменные среды…** и добавь в раздел **Переменные среды пользователя**:

| Переменная | Значение |
|---|---|
| `RESOLVE_SCRIPT_API` | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` |
| `RESOLVE_SCRIPT_LIB` | `C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll` |
| `PYTHONPATH` | `%PYTHONPATH%;%RESOLVE_SCRIPT_API%\Modules\` |

Или из PowerShell (только для текущей сессии):

```powershell
$env:RESOLVE_SCRIPT_API = "$env:PROGRAMDATA\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$env:PYTHONPATH         = "$env:PYTHONPATH;$env:RESOLVE_SCRIPT_API\Modules\"
```

### Linux (для справки — в задаче не требуется)

```bash
export RESOLVE_SCRIPT_API="/opt/resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/opt/resolve/libs/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

### Проверка

```bash
python3 -c "import DaVinciResolveScript as d; print(d.scriptapp('Resolve'))"
```

Если Resolve запущен — увидите что-то вроде `<PyRemoteObject ...>`. `None` или `ImportError` означают, что переменные не подхватились — перепроверьте пути и откройте свежий терминал.

---

## Запуск

### Вариант 1 — из терминала (рекомендуется)

1. Запустите **DaVinci Resolve Studio**.
2. Откройте проект, в который будете собирать таймлайн.
3. В терминале, где переменные окружения уже выставлены:

   **macOS / Linux:**
   ```bash
   cd /path/to/your_project_dir
   python3 resolve_timeline.py
   ```

   **Windows:**
   ```cmd
   cd C:\path\to\your_project_dir
   python resolve_timeline.py
   ```

### Вариант 2 — изнутри Resolve (Workspace → Scripts / Console)

1. Скопируйте (или сделайте симлинк) `resolve_timeline.py` в папку скриптов Resolve — тогда он появится в меню:

   | ОС | Папка |
   |---|---|
   | macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/` |
   | Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Comp\` |

2. В Resolve: **Workspace → Scripts → Comp → resolve_timeline**.

   Альтернатива: **Workspace → Console**, переключиться на вкладку **Py3**, вставить `exec(open("/полный/путь/к/resolve_timeline.py").read())`.

При запуске изнутри Resolve переменные окружения **не нужны** — встроенный интерпретатор уже знает, где лежит модуль.

---

## Ожидаемый вывод в консоли

```
Найдено 18 аудиофайл(ов) в /Users/you/project/final.
Проект: MyProject
Импортировано в Media Pool: 18 клип(ов).
Создан таймлайн: Assembled Scene
  [   Blueberry]  track A1  @ 0 → 142  (142 frames)  001_Blueberry_001.mp3
  [        Hawk]  track A2  @ 142 → 251  (109 frames)  002_Hawk_001.mp3
  [   Blueberry]  track A1  @ 251 → 368  (117 frames)  003_Blueberry_002.mp3
  ...
✅ Готово: размещено 18 клип(ов) на 7 дорожк(ах).
   Префикс → дорожка: {'Blueberry': 1, 'Hawk': 2, 'Mia': 3, 'Christal': 4, ...}
```

---

## Возможные проблемы

| Сообщение | Что делать |
|---|---|
| `Не найден модуль DaVinciResolveScript` | Переменные окружения не видны Python-процессу. Перезапустите терминал или экспортируйте их в текущем шелле перед запуском. |
| `DaVinci Resolve не отвечает` | Resolve не запущен, либо это бесплатная версия. Нужна Studio. Проверьте, что *External scripting use* = **Local** в Preferences → System → General. |
| `Нет открытого проекта` | Откройте или создайте проект в Resolve перед запуском. |
| `Импорт не удался` | Resolve не читает один из файлов. Проверьте расширения, права доступа и отсутствие символов в пути, которые локаль не декодирует. |
| Клипы уехали не на те дорожки | Имена файлов не попадают под правило по умолчанию. Поправьте `extract_prefix()` в начале скрипта — альтернативы в комментариях. |
| `AppendToTimeline вернул пустой результат` | Несовпадение частоты кадров клипа и таймлайна или битые файлы. Загляните в консоль самого Resolve: **Workspace → Console** (вкладка Py3). |

---

## Шпаргалка по настройкам (верх `resolve_timeline.py`)

| Параметр | Назначение |
|---|---|
| `FINAL_FOLDER_NAME` | Имя исходной папки рядом со скриптом. По умолчанию `"final"`. |
| `TIMELINE_NAME` | Имя создаваемого таймлайна. По умолчанию `"Assembled Scene"`. |
| `AUDIO_EXTS` | Кортеж допустимых расширений. Дополняйте при необходимости. |
| `extract_prefix(filename)` | Функция, возвращающая ключ группировки для файла. Перепишите под вашу схему имён. |
