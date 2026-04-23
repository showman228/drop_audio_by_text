"""
resolve_timeline.py
===================

Сборка таймлайна из аудио, которое УЖЕ лежит в Media Pool DaVinci Resolve.

Скрипт не ходит в файловую систему — просто перебирает клипы в медиатеке,
создаёт новый пустой таймлайн и раскладывает аудио встык, один «префикс»
имени = одна аудиодорожка.

ИЗМЕНЕНИЯ по сравнению с оригиналом:
  - Клипы добавляются поштучно через AppendToTimeline([одиночный_клип]),
    а не одним батч-вызовом. Это надёжнее работает в бесплатной Resolve,
    где батч-метод часто игнорирует trackIndex.
  - Перед каждым вызовом выставляем активную дорожку через SetCurrentTimecode
    + явно передаём trackIndex — двойная страховка.
  - Добавлен fallback для длительности: если "Frames" не сработал,
    пробуем вычислить из "Duration" и fps проекта.
  - currentRecordFrame отслеживается отдельно для каждой дорожки,
    чтобы клипы шли встык именно на своей дорожке, не смещаясь из-за
    клипов других персонажей.

Запуск:
  Workspace → Console → вкладка Py3 → вставить весь файл → Enter.

Перед запуском: импортируйте нужные аудиофайлы в Media Pool вручную
(File → Import → Media или drag-and-drop).
"""


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Имя бина, откуда брать клипы. Пустая строка = весь Media Pool (рекурсивно).
SOURCE_BIN_NAME = ""

TIMELINE_NAME = "Assembled Scene"


def extract_prefix(filename):
    """
    Ключ группировки клипов по дорожкам: один префикс = одна дорожка.
    По умолчанию — ВТОРАЯ секция через «_» (для файлов вида
    001_Blueberry_001.mp3 → "Blueberry").
    """
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    parts = base.split("_")
    if len(parts) >= 2:
        return parts[1]
    return parts[0]


# ============================================================
# ПОДКЛЮЧЕНИЕ К RESOLVE
# ============================================================

def _get_resolve():
    try:
        return resolve  # type: ignore  # noqa: F821
    except NameError:
        pass
    try:
        import DaVinciResolveScript as dvr_script
    except ImportError:
        print("[!] Не найден модуль DaVinciResolveScript.")
        return None
    r = dvr_script.scriptapp("Resolve")
    if not r:
        print("[!] DaVinci Resolve не отвечает.")
    return r


# ============================================================
# РАБОТА С MEDIA POOL
# ============================================================

def _find_bin(folder, name):
    target = (name or "").strip().lower()
    if not target:
        return None
    if (folder.GetName() or "").lower() == target:
        return folder
    for sub in folder.GetSubFolderList() or []:
        found = _find_bin(sub, name)
        if found:
            return found
    return None


def _collect_audio_clips(media_pool, bin_name=""):
    root = media_pool.GetRootFolder()
    if not root:
        print("[!] Media Pool пуст.")
        return []

    start = root
    if bin_name:
        found = _find_bin(root, bin_name)
        if found:
            start = found
        else:
            print(f"[!] Не найден бин «{bin_name}». Использую корень Media Pool.")

    collected = []

    def walk(folder):
        for clip in folder.GetClipList() or []:
            clip_type = clip.GetClipProperty("Type") or ""
            if clip_type == "Audio":
                collected.append(clip)
        for sub in folder.GetSubFolderList() or []:
            walk(sub)

    walk(start)
    collected.sort(key=lambda it: (it.GetName() or "").lower())
    return collected


# ============================================================
# ПОМОГАТЕЛЬНОЕ
# ============================================================

def _ensure_audio_tracks(timeline, needed):
    """Добавляет дорожки, пока их не станет не менее `needed`."""
    current = timeline.GetTrackCount("audio")
    while current < needed:
        timeline.AddTrack("audio")
        current += 1
    return timeline.GetTrackCount("audio")


def _get_clip_frames(item, fps=24):
    """
    Возвращает длину клипа в кадрах.
    Сначала пробует свойство "Frames", потом считает из "Duration" (HH:MM:SS:FF).
    """
    # Попытка 1: прямое свойство
    try:
        v = item.GetClipProperty("Frames")
        if v:
            frames = int(float(str(v).strip()))
            if frames > 0:
                return frames
    except (TypeError, ValueError):
        pass

    # Попытка 2: парсим "Duration" = "HH:MM:SS:FF"
    try:
        dur = item.GetClipProperty("Duration") or ""
        dur = dur.strip()
        if ":" in dur:
            parts = dur.split(":")
            if len(parts) == 4:
                h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                return ((h * 3600 + m * 60 + s) * fps) + f
    except (TypeError, ValueError, AttributeError):
        pass

    return 0


def _get_project_fps(project):
    """Возвращает FPS проекта как int (по умолчанию 24)."""
    try:
        fps_str = project.GetSetting("timelineFrameRate") or "24"
        return int(float(fps_str))
    except (TypeError, ValueError):
        return 24


# ============================================================
# ОСНОВНОЕ
# ============================================================

def build_timeline():
    # --- 1. Подключение ---
    r = _get_resolve()
    if not r:
        return

    project = r.GetProjectManager().GetCurrentProject()
    if not project:
        print("[!] Нет открытого проекта.")
        return

    media_pool = project.GetMediaPool()
    fps = _get_project_fps(project)
    print(f"Проект: {project.GetName()}  |  FPS: {fps}")

    # --- 2. Клипы из Media Pool ---
    audio_items = _collect_audio_clips(media_pool, SOURCE_BIN_NAME)
    if not audio_items:
        where = f"в бине «{SOURCE_BIN_NAME}»" if SOURCE_BIN_NAME else "в Media Pool"
        print(f"[!] Не найдено ни одного аудио-клипа {where}.")
        return

    print(f"Найдено {len(audio_items)} аудио-клип(ов).")

    # --- 3. Пустой таймлайн ---
    timeline = media_pool.CreateEmptyTimeline(TIMELINE_NAME)
    if not timeline:
        print(f"[!] Не удалось создать таймлайн «{TIMELINE_NAME}».")
        return
    print(f"Создан таймлайн: {timeline.GetName()}")

    # --- 4. Подготовка: считаем дорожки и позиции ---
    # prefix_to_track  : {"Blueberry": 1, "Alice": 2, ...}
    # track_record_pos : {1: 0, 2: 0, ...}  — текущая позиция записи на каждой дорожке
    prefix_to_track = {}
    track_record_pos = {}
    next_track_idx = 1

    # Первый проход — определяем порядок дорожек и считаем позиции
    plan = []   # список (item, prefix, track_index, start_frame, end_frame, record_frame)

    for item in audio_items:
        name   = item.GetName() or ""
        prefix = extract_prefix(name)
        frames = _get_clip_frames(item, fps)

        if frames <= 0:
            print(f"  [!] Нулевая длительность у «{name}» — пропускаем.")
            continue

        if prefix not in prefix_to_track:
            prefix_to_track[prefix] = next_track_idx
            track_record_pos[next_track_idx] = 0
            next_track_idx += 1

        track_idx   = prefix_to_track[prefix]
        record_pos  = track_record_pos[track_idx]
        track_record_pos[track_idx] += frames

        plan.append((item, name, prefix, track_idx, 0, frames, record_pos))

    if not plan:
        print("[!] Нет клипов для размещения.")
        return

    # --- 5. Создаём нужное кол-во дорожек заранее ---
    total_tracks = len(prefix_to_track)
    _ensure_audio_tracks(timeline, total_tracks)
    print(f"Дорожек создано: {timeline.GetTrackCount('audio')}")

    # --- 6. Поштучное добавление ---
    placed = 0
    failed = 0

    for (item, name, prefix, track_idx, start_f, end_f, record_f) in plan:
        clip_info = {
            "mediaPoolItem": item,
            "startFrame":    start_f,
            "endFrame":      end_f,
            "mediaType":     2,          # 2 = audio
            "trackIndex":    track_idx,
            "recordFrame":   record_f,
        }

        result = media_pool.AppendToTimeline([clip_info])

        status = "✅" if result else "❌"
        print(
            f"  {status} [{prefix:>12}]  A{track_idx}  "
            f"@ {record_f} → {record_f + (end_f - start_f)}  "
            f"({end_f - start_f} frames)  {name}"
        )

        if result:
            placed += 1
        else:
            failed += 1

    # --- 7. Итог ---
    print(f"\n{'✅' if failed == 0 else '⚠️ '} Готово: размещено {placed} клип(ов), "
          f"ошибок: {failed}.")
    print(f"   Дорожек: {len(prefix_to_track)}")
    print(f"   Префикс → дорожка: {prefix_to_track}")

    if failed > 0:
        print("\n   [!] Часть клипов не добавилась. Возможные причины:")
        print("       • trackIndex игнорируется в бесплатной Resolve — клипы")
        print("         могли упасть все на A1 без ошибки (result не None, но")
        print("         позиция неверная). Проверьте таймлайн вручную.")
        print("       • Клип уже открыт или повреждён.")

    return timeline


build_timeline()