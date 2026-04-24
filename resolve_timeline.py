# ============================================================
# НАСТРОЙКИ
# ============================================================

# Имя бина, откуда брать клипы. Пустая строка = весь Media Pool (рекурсивно).
# Пример: SOURCE_BIN_NAME = "final"  — если вы сложили всё в бин «final».
SOURCE_BIN_NAME = ""

TIMELINE_NAME = "Assembled Scene"


def extract_prefix(filename):
    """
    Ключ группировки клипов по дорожкам: один префикс = одна дорожка.
    По умолчанию — ВТОРАЯ секция через «_» (для файлов вида
    001_Blueberry_001.mp3 → "Blueberry").

    Альтернативы:
        # до первого подчёркивания:
        return filename.rsplit(".", 1)[0].split("_", 1)[0]
        # первые 3 символа:
        return filename.rsplit(".", 1)[0][:3]
    """
    # Убираем расширение, если оно есть
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    parts = base.split("_")
    if len(parts) >= 2:
        return parts[1]
    return parts[0]


# ============================================================
# ПОДКЛЮЧЕНИЕ К RESOLVE
# ============================================================

def _get_resolve():
    """
    В консоли Py3 объект `resolve` уже в глобалах — берём его.
    Иначе подключаемся через DaVinciResolveScript (внешний запуск).
    """
    try:
        return resolve  # type: ignore  # noqa: F821
    except NameError:
        pass

    try:
        import DaVinciResolveScript as dvr_script
    except ImportError:
        print("[!] Не найден модуль DaVinciResolveScript.")
        print("    Для запуска извне Resolve нужны RESOLVE_SCRIPT_API /")
        print("    RESOLVE_SCRIPT_LIB / PYTHONPATH. См. README_RESOLVE.md.")
        return None

    r = dvr_script.scriptapp("Resolve")
    if not r:
        print("[!] DaVinci Resolve не отвечает. Запустите Studio и откройте проект.")
    return r


# ============================================================
# РАБОТА С MEDIA POOL
# ============================================================

def _find_bin(folder, name):
    """Рекурсивно ищет подпапку по имени (без учёта регистра)."""
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
    """
    Собирает все чисто-аудио-клипы из Media Pool.
    Если bin_name задан — только из этой папки и её подпапок; иначе — из всей медиатеки.
    Результат отсортирован по имени (что совпадает со сценарной последовательностью
    для файлов вида 001_<Actor>_NNN.mp3).
    """
    root = media_pool.GetRootFolder()
    if not root:
        print("[!] Media Pool пуст — нет корневой папки.")
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
            # Берём только чистое аудио. «Video + Audio» — это видео с аудиодорожкой,
            # его сюда не пускаем.
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
    current = timeline.GetTrackCount("audio")
    while current < needed:
        timeline.AddTrack("audio")
        current += 1


def _get_clip_frames(item):
    try:
        return int(item.GetClipProperty("Frames"))
    except (TypeError, ValueError):
        return 0


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
        print("[!] Нет открытого проекта. Откройте проект в Resolve.")
        return

    media_pool = project.GetMediaPool()

    # --- 2. Забираем аудио из Media Pool ---
    audio_items = _collect_audio_clips(media_pool, SOURCE_BIN_NAME)
    if not audio_items:
        where = f"в бине «{SOURCE_BIN_NAME}»" if SOURCE_BIN_NAME else "в Media Pool"
        print(f"[!] Не найдено ни одного аудио-клипа {where}.")
        print("    Импортируйте файлы в Media Pool перед запуском скрипта.")
        return

    print(f"Проект: {project.GetName()}")
    print(f"Найдено {len(audio_items)} аудио-клип(ов) в медиатеке.")

    # --- 3. Пустой таймлайн ---
    timeline = media_pool.CreateEmptyTimeline(TIMELINE_NAME)
    if not timeline:
        print(f"[!] Не удалось создать таймлайн «{TIMELINE_NAME}».")
        return
    print(f"Создан таймлайн: {timeline.GetName()}")

    # --- 4. Раскладка: префикс → дорожка, клипы встык ---
    prefix_to_track = {}
    next_track_idx = 1
    current_record_frame = 0
    clip_infos = []

    for item in audio_items:
        name   = item.GetName() or ""
        prefix = extract_prefix(name)
        frames = _get_clip_frames(item)

        if frames <= 0:
            print(f"  [!] Нулевая длительность у {name} — пропускаем.")
            continue

        if prefix not in prefix_to_track:
            prefix_to_track[prefix] = next_track_idx
            _ensure_audio_tracks(timeline, next_track_idx)
            next_track_idx += 1
        track_index = prefix_to_track[prefix]

        clip_infos.append({
            "mediaPoolItem": item,
            "startFrame":    0,
            "endFrame":      frames,
            "mediaType":     2,          # 1 = video, 2 = audio
            "trackIndex":    track_index,
            "recordFrame":   current_record_frame,
        })

        print(
            f"  [{prefix:>12}]  A{track_index}  "
            f"@ {current_record_frame} → {current_record_frame + frames}  "
            f"({frames} frames)  {name}"
        )
        current_record_frame += frames

    if not clip_infos:
        print("[!] Нет клипов для размещения.")
        return

    # --- 5. Батч-добавление на таймлайн ---
    # В официальном API метод живёт на MediaPool, не на Timeline.
    result = media_pool.AppendToTimeline(clip_infos)
    if not result:
        print("[!] AppendToTimeline вернул пустой результат.")
        print("    Проверьте вывод в консоли Resolve (Workspace → Console).")
        return

    print(
        f"\n✅ Готово: размещено {len(clip_infos)} клип(ов) "
        f"на {len(prefix_to_track)} дорожк(ах)."
    )
    print(f"   Префикс → дорожка: {prefix_to_track}")
    return timeline


# Вызываем «на лету» — удобно и для вставки в Py3-консоль, и для обычного запуска.
build_timeline()
