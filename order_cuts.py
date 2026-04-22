import os
import re
import shutil

# --- КОНФИГУРАЦИЯ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Куда складывать итоговую последовательность (создаётся, если нет).
OUTPUT_DIR_NAME = "final"

# True — копируем файлы из <Actor>/cut/ в final/ (оригиналы остаются на месте).
# False — перемещаем, per-actor cut/ пустеет.
COPY_FILES = True

# Перезаписывать файлы в final/ при повторном запуске.
OVERWRITE = True

# Поддерживаемые расширения (такие же, как в остальных скриптах).
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")

# Регулярка и префиксы-ремарки — такие же, как в split_by_actors.py,
# чтобы номерация реплик совпадала.
CHARACTER_LINE_RE = re.compile(
    r"^([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s\-']{0,39}):\s*(.+)$"
)
STAGE_PREFIXES = ("*(", "*{", "(", "[")


def find_master_script():
    """Ищет .txt-сценарий в корне BASE_DIR (как split_by_actors.py)."""
    candidates = sorted(
        f for f in os.listdir(BASE_DIR)
        if f.lower().endswith(".txt")
        and os.path.isfile(os.path.join(BASE_DIR, f))
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return os.path.join(BASE_DIR, candidates[0])

    print("Найдено несколько .txt-файлов:")
    for i, f in enumerate(candidates, 1):
        print(f"  {i}. {f}")
    try:
        choice = int(input("Выберите номер: ").strip())
    except (ValueError, KeyboardInterrupt, EOFError):
        return None
    if 1 <= choice <= len(candidates):
        return os.path.join(BASE_DIR, candidates[choice - 1])
    return None


def parse_ordered_lines(script_path):
    """
    Возвращает список (character, dialogue) в порядке появления в сценарии.
    Фильтрация — та же, что в split_by_actors.py: пропускаем пустые строки,
    ремарки (*(…), *{…}, …) и строки без двоеточия.

    Важно: нумерация тут совпадает с порядком, в котором split_by_actors.py
    писал реплики в <Actor>.txt. Значит, N-я реплика актёра в сценарии = его
    N-я строка в <Actor>.txt = <Actor>_NNN.mp3 после main.py. Так мы
    находим нужный файл, не сравнивая тексты — только по номеру.
    """
    result = []
    with open(script_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(STAGE_PREFIXES):
                continue
            m = CHARACTER_LINE_RE.match(line)
            if not m:
                continue
            character = m.group(1).strip()
            dialogue = m.group(2).strip()
            if not dialogue:
                continue
            result.append((character, dialogue))
    return result


def find_actor_folder(character_name):
    """Ищет существующую папку актёра (совпадение имени без учёта регистра)."""
    target = character_name.lower()
    for entry in os.listdir(BASE_DIR):
        full = os.path.join(BASE_DIR, entry)
        if not os.path.isdir(full):
            continue
        if entry.lower() == target:
            return full
    return None


def find_cut_file(actor_dir, folder_name, per_actor_index):
    """
    Ищет <actor_dir>/cut/<folder_name>_<NNN>.<ext>.
    Пробует все поддерживаемые расширения — main.py по умолчанию
    делает .mp3, но если кто-то поменял — всё равно найдём.
    """
    cut_dir = os.path.join(actor_dir, "cut")
    if not os.path.isdir(cut_dir):
        return None
    base = f"{folder_name}_{per_actor_index:03}"
    for ext in AUDIO_EXTS:
        candidate = os.path.join(cut_dir, base + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def main():
    print(f"🔍 Сборка последовательности в: {BASE_DIR}")

    script_path = find_master_script()
    if not script_path:
        print("[!] Не найдено .txt-файла сценария в корне.")
        return

    print(f"🎬 Сценарий: {os.path.basename(script_path)}")

    lines = parse_ordered_lines(script_path)
    if not lines:
        print("[!] В сценарии не распознано ни одной реплики.")
        return

    total = len(lines)
    # Ширина глобального индекса: минимум 3 цифры, больше для длинных сценариев.
    width = max(3, len(str(total)))

    output_dir = os.path.join(BASE_DIR, OUTPUT_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)

    per_actor_counter = {}  # {character_name_lower: сколько реплик уже встретилось}
    placed = 0
    missing = []

    action = "Копирование" if COPY_FILES else "Перемещение"
    print(f"📂 Целевая папка: {output_dir}/")
    print(f"🔧 Режим: {action} из <Actor>/cut/ → {OUTPUT_DIR_NAME}/\n")

    for global_idx, (character, dialogue) in enumerate(lines, start=1):
        # Счёт ведём по нижнему регистру — чтобы «Blueberry» и «blueberry»
        # воспринимались как один актёр, даже если в сценарии написание
        # колеблется.
        key = character.lower()
        per_actor_counter[key] = per_actor_counter.get(key, 0) + 1
        actor_index = per_actor_counter[key]

        actor_dir = find_actor_folder(character)
        if not actor_dir:
            missing.append((global_idx, character, actor_index, "нет папки актёра"))
            continue

        # Имя файла в cut/ основано на реальном имени папки
        folder_name = os.path.basename(actor_dir)
        src = find_cut_file(actor_dir, folder_name, actor_index)
        if not src:
            missing.append((
                global_idx, character, actor_index,
                f"нет файла {folder_name}_{actor_index:03}.* в {folder_name}/cut/",
            ))
            continue

        ext = os.path.splitext(src)[1]
        # Формат: <глобальный_номер>_<Актёр>_<его_номер>.<ext>
        # Глобальный префикс нужен, чтобы файлы сортировались в порядке сценария.
        out_name = f"{global_idx:0{width}}_{folder_name}_{actor_index:03}{ext}"
        dst = os.path.join(output_dir, out_name)

        if os.path.exists(dst) and not OVERWRITE:
            print(f"  [~] {out_name} уже существует, пропускаем.")
            continue

        if COPY_FILES:
            shutil.copy2(src, dst)
        else:
            shutil.move(src, dst)

        snippet = dialogue[:50] + ("…" if len(dialogue) > 50 else "")
        print(f"  [v] {out_name}  ←  {folder_name}: «{snippet}»")
        placed += 1

    # --- Итоговый отчёт ---
    print(f"\n📊 Собрано: {placed}/{total} реплик в {OUTPUT_DIR_NAME}/.")
    if missing:
        print(f"⚠️  Пропущено {len(missing)} реплик(и):")
        for idx, char, actor_idx, reason in missing[:20]:
            print(f"   [{idx:0{width}}] {char} #{actor_idx}: {reason}")
        if len(missing) > 20:
            print(f"   …и ещё {len(missing) - 20}")


if __name__ == "__main__":
    main()
    print("\n✅ ГОТОВО")
