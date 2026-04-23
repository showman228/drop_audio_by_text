"""
resolve_timeline.py
===================

Автоматизация для DaVinci Resolve Studio 18.1+:
  1. Подключается к активному проекту.
  2. Находит папку `final/` рядом со скриптом.
  3. Импортирует все аудио из неё в Media Pool.
  4. Создаёт новый пустой таймлайн.
  5. Раскладывает клипы «лесенкой» — один префикс имени = одна аудиодорожка,
     все клипы встык по времени.

Запускать извне Resolve (через терминал) или из Workspace → Console → Py3.
См. README_RESOLVE.md для настройки окружения.
"""

import os
import sys

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

FINAL_FOLDER_NAME = "final"        # имя папки с аудио рядом со скриптом
TIMELINE_NAME     = "Assembled Scene"  # имя создаваемого таймлайна
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".ogg")


def extract_prefix(filename: str) -> str:
    """
    Возвращает «префикс» — ключ для группировки клипов по дорожкам.
    Один префикс = одна аудиодорожка.

    По умолчанию: ВТОРАЯ секция имени через «_». Это удобно для файлов
    из нашего конвейера вида `001_Blueberry_001.mp3` → "Blueberry"
    (один актёр = одна дорожка).

    Если вам нужен другой формат — просто перепишите тело функции.
    Примеры альтернатив:
        # до первого подчёркивания:
        return os.path.splitext(filename)[0].split("_", 1)[0]

        # первые 3 символа имени (без расширения):
        return os.path.splitext(filename)[0][:3]
    """
    base = os.path.splitext(filename)[0]
    parts = base.split("_")
    if len(parts) >= 2:
        return parts[1]
    return parts[0]


# ============================================================
# ПОДКЛЮЧЕНИЕ К RESOLVE
# ============================================================

def get_resolve():
    """Подключается к запущенному Resolve Studio."""
    try:
        import DaVinciResolveScript as dvr_script
    except ImportError:
        sys.exit(
            "[!] Не найден модуль DaVinciResolveScript.\n"
            "    Настройте переменные окружения RESOLVE_SCRIPT_API / "
            "RESOLVE_SCRIPT_LIB / PYTHONPATH.\n"
            "    Подробности — в README_RESOLVE.md."
        )

    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        sys.exit(
            "[!] DaVinci Resolve не отвечает. Убедитесь, что:\n"
            "     - запущена версия Studio (не бесплатная);\n"
            "     - External scripting use включён (Preferences → System → General)."
        )
    return resolve


# ============================================================
# ПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def collect_audio_files(folder: str):
    """Возвращает отсортированный список путей к аудиофайлам из folder."""
    files = sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(AUDIO_EXTS)
        and os.path.isfile(os.path.join(folder, f))
    )
    return files


def ensure_audio_tracks(timeline, needed: int):
    """Добавляет аудиодорожки, пока их число не достигнет `needed`."""
    current = timeline.GetTrackCount("audio")
    while current < needed:
        timeline.AddTrack("audio")
        current += 1


def get_clip_frames(item) -> int:
    """Возвращает длительность клипа в кадрах (int)."""
    raw = item.GetClipProperty("Frames")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def order_items_by_filename(imported_items, ordered_paths):
    """
    ImportMedia не гарантирует порядок элементов. Сопоставляем их с исходными
    путями по имени файла, чтобы раскладывать в том же порядке, в котором
    файлы лежат в final/.
    """
    by_name = {item.GetName(): item for item in imported_items}
    ordered = []
    for path in ordered_paths:
        name = os.path.basename(path)
        if name in by_name:
            ordered.append(by_name[name])
        else:
            print(f"[!] В Media Pool не найден клип: {name}")
    return ordered


# ============================================================
# ОСНОВНАЯ ЛОГИКА
# ============================================================

def main():
    # --- 1. Путь до final/ рядом со скриптом ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    final_dir = os.path.join(script_dir, FINAL_FOLDER_NAME)

    if not os.path.isdir(final_dir):
        sys.exit(f"[!] Не найдена папка: {final_dir}")

    audio_files = collect_audio_files(final_dir)
    if not audio_files:
        sys.exit(f"[!] В папке {final_dir} нет поддерживаемых аудиофайлов.")
    print(f"Найдено {len(audio_files)} аудиофайл(ов) в {final_dir}.")

    # --- 2. Подключение к Resolve, проекту, Media Pool, Media Storage ---
    resolve = get_resolve()
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if not project:
        sys.exit("[!] Нет открытого проекта. Создайте/откройте проект в Resolve.")

    media_pool    = project.GetMediaPool()
    media_storage = resolve.GetMediaStorage()  # зарезервировано под расширение

    print(f"Проект: {project.GetName()}")

    # --- 3. Импорт аудио в Media Pool ---
    imported = media_pool.ImportMedia(audio_files)
    if not imported:
        sys.exit("[!] Импорт не удался. Проверьте доступ к файлам и их формат.")
    print(f"Импортировано в Media Pool: {len(imported)} клип(ов).")

    # Восстанавливаем порядок по имени файла (важно для back-to-back раскладки).
    ordered_items = order_items_by_filename(imported, audio_files)
    if not ordered_items:
        sys.exit("[!] После импорта не удалось сопоставить ни один клип.")

    # --- 4. Создание пустого таймлайна ---
    timeline = media_pool.CreateEmptyTimeline(TIMELINE_NAME)
    if not timeline:
        sys.exit(f"[!] Не удалось создать таймлайн «{TIMELINE_NAME}».")
    print(f"Создан таймлайн: {timeline.GetName()}")

    # --- 5. Раскладка: префикс → дорожка, клипы встык ---
    prefix_to_track = {}   # { "Blueberry": 1, "Hawk": 2, ... }
    next_track_idx = 1
    current_record_frame = 0
    clip_infos = []

    for item in ordered_items:
        name   = item.GetName()
        prefix = extract_prefix(name)
        frames = get_clip_frames(item)

        if frames <= 0:
            print(f"  [!] Нулевая длительность у {name} — пропускаем.")
            continue

        # Назначение дорожки
        if prefix not in prefix_to_track:
            prefix_to_track[prefix] = next_track_idx
            # У пустого таймлайна обычно уже есть A1 — добавим только недостающие.
            ensure_audio_tracks(timeline, next_track_idx)
            next_track_idx += 1
        track_index = prefix_to_track[prefix]

        # Клип уходит «лесенкой» по времени: recordFrame = предыдущий end.
        clip_info = {
            "mediaPoolItem": item,
            "startFrame":    0,          # весь клип от начала
            "endFrame":      frames,     # до конца (в кадрах исходника)
            "mediaType":     2,          # 1 = video, 2 = audio
            "trackIndex":    track_index,
            "recordFrame":   current_record_frame,
        }
        clip_infos.append(clip_info)

        print(
            f"  [{prefix:>12}]  track A{track_index}  "
            f"@ {current_record_frame} → {current_record_frame + frames}  "
            f"({frames} frames)  {name}"
        )

        current_record_frame += frames

    if not clip_infos:
        sys.exit("[!] Нет клипов для размещения.")

    # --- 6. Батч-добавление на таймлайн ---
    # ВАЖНО: в официальном API Blackmagic метод живёт на MediaPool, а не Timeline.
    # Если запустить timeline.AppendToTimeline(...) — будет AttributeError.
    result = media_pool.AppendToTimeline(clip_infos)
    if not result:
        sys.exit(
            "[!] AppendToTimeline вернул пустой результат.\n"
            "    Проверьте вывод консоли Resolve (Workspace → Console)."
        )

    print(
        f"\n✅ Готово: размещено {len(clip_infos)} клип(ов) "
        f"на {len(prefix_to_track)} дорожк(ах)."
    )
    print(f"   Префикс → дорожка: {prefix_to_track}")


if __name__ == "__main__":
    main()
