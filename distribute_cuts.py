import os
import shutil

# --- КОНФИГУРАЦИЯ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Перемещать (True) или копировать (False) файлы из cut/<актёр>/ в <актёр>/.
# Перемещение «вытаскивает» нарезку, оставляя cut/ пустой.
MOVE_FILES = True

# Удалять пустые подпапки cut/<актёр>/ и саму cut/ после распределения.
CLEANUP_EMPTY_DIRS = True


def move_or_copy(src, dst):
    """Перемещает/копирует файл в зависимости от MOVE_FILES."""
    if MOVE_FILES:
        shutil.move(src, dst)
    else:
        shutil.copy2(src, dst)


def distribute_actor(cut_actor_dir, target_actor_dir, actor_name):
    """
    Переносит всё содержимое cut/<actor_name>/ в <actor_name>/cut/.
    Нарезка хранится в отдельной подпапке, чтобы не смешиваться
    с исходным аудио и сценарием в папке актёра.

    Возвращает кортеж (moved, skipped_exists).
    """
    # Нарезка идёт в <actor>/cut/, а не в сам <actor>/ — так файлы не «разбросаны»
    dest_dir = os.path.join(target_actor_dir, "cut")
    os.makedirs(dest_dir, exist_ok=True)

    moved = 0
    skipped_exists = []

    for fname in sorted(os.listdir(cut_actor_dir)):
        src = os.path.join(cut_actor_dir, fname)
        if not os.path.isfile(src):
            # Вложенные папки не трогаем — не наш сценарий
            continue

        dst = os.path.join(dest_dir, fname)
        if os.path.exists(dst):
            skipped_exists.append(fname)
            continue

        move_or_copy(src, dst)
        print(f"  [v] {actor_name}/cut/{fname}")
        moved += 1

    # Чистим пустую cut/<actor_name>/ после перемещения
    if CLEANUP_EMPTY_DIRS and MOVE_FILES:
        try:
            if not os.listdir(cut_actor_dir):
                os.rmdir(cut_actor_dir)
        except OSError:
            pass

    return moved, skipped_exists


def main():
    cut_root = os.path.join(BASE_DIR, "cut")
    action = "Перемещение" if MOVE_FILES else "Копирование"
    print(f"🔧 Режим: {action} файлов из cut/<актёр>/ → <актёр>/cut/\n")

    if not os.path.isdir(cut_root):
        print(f"[!] Папка cut/ не найдена: {cut_root}")
        print("    Сначала запустите main.py, чтобы нарезать аудио.")
        return

    total_moved = 0
    total_skipped = 0
    missing_target = []

    for actor_name in sorted(os.listdir(cut_root)):
        src_actor_dir = os.path.join(cut_root, actor_name)
        if not os.path.isdir(src_actor_dir):
            continue

        target_actor_dir = os.path.join(BASE_DIR, actor_name)

        print(f"--- 🎭 {actor_name} ---")

        if not os.path.isdir(target_actor_dir):
            # Оригинальной папки актёра нет — сами её не создаём,
            # это почти наверняка опечатка или удалённая папка.
            print(f"  [!] Оригинальная папка не найдена: {target_actor_dir}")
            print(f"      Нарезка остаётся в cut/{actor_name}/.")
            missing_target.append(actor_name)
            print()
            continue

        moved, skipped_exists = distribute_actor(src_actor_dir, target_actor_dir, actor_name)
        total_moved += moved
        total_skipped += len(skipped_exists)

        if skipped_exists:
            print(f"  ⚠️  Пропущено {len(skipped_exists)} файл(ов) — уже существуют в {actor_name}/cut/:")
            for f in skipped_exists[:10]:
                print(f"     {f}")
            if len(skipped_exists) > 10:
                print(f"     …и ещё {len(skipped_exists) - 10}")

        print(f"  📊 Перемещено: {moved} файл(ов).\n")

    # Если cut/ осталась пустой — прибираем и её
    if CLEANUP_EMPTY_DIRS and MOVE_FILES:
        try:
            if not os.listdir(cut_root):
                os.rmdir(cut_root)
                print("🧹 Папка cut/ пустая — удалена.")
        except OSError:
            pass

    # --- Общий итог ---
    print(f"\n📊 Итого: {total_moved} файл(ов) распределено.")
    if total_skipped:
        print(f"⚠️  Пропущено {total_skipped} (уже существовали в целевой папке).")
    if missing_target:
        print(f"⚠️  Для {len(missing_target)} актёр(ов) не было оригинальной папки: "
              f"{', '.join(missing_target)}")


if __name__ == "__main__":
    main()
    print("\n✅ ВСЕ ПАПКИ ОБРАБОТАНЫ")
