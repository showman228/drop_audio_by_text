import os
import re

# --- КОНФИГУРАЦИЯ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Перезаписывать ли существующие <Actor>/<Actor>.txt без вопросов.
# True — безопасно для повторной регенерации из одного и того же сценария.
OVERWRITE = True

# Регулярка для реплики «Персонаж: текст».
# Имя персонажа: начинается с буквы (кириллица/латиница), дальше только буквы,
# пробелы, дефис и апостроф. До 40 символов — отсекает длинные строки вида
# «Location: Kitchen» и случайные совпадения.
CHARACTER_LINE_RE = re.compile(
    r"^([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s\-']{0,39}):\s*(.+)$"
)

# Строки, которые игнорируем целиком (ремарки, списки персонажей в блоке).
STAGE_PREFIXES = ("*(", "*{", "(", "[")


def sanitize_folder_name(name):
    """Убирает символы, недопустимые в имени папки/файла."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return cleaned or "Unknown"


def find_master_script():
    """
    Ищет .txt-файл сценария в корне BASE_DIR (не внутри папок актёров).
    Если найден один — используется автоматически.
    Если несколько — спрашиваем пользователя, какой.
    """
    candidates = sorted(
        f for f in os.listdir(BASE_DIR)
        if f.lower().endswith(".txt")
        and os.path.isfile(os.path.join(BASE_DIR, f))
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return os.path.join(BASE_DIR, candidates[0])

    print("Найдено несколько .txt-файлов сценариев:")
    for i, f in enumerate(candidates, 1):
        print(f"  {i}. {f}")
    try:
        choice = int(input("Выберите номер: ").strip())
    except (ValueError, KeyboardInterrupt, EOFError):
        return None
    if 1 <= choice <= len(candidates):
        return os.path.join(BASE_DIR, candidates[choice - 1])
    return None


def parse_script(script_path):
    """
    Читает сценарий и возвращает {персонаж: [реплика1, реплика2, ...]}.

    Игнорирует:
    - пустые строки
    - строки, начинающиеся с *( *{ ( [  (ремарки, списки персонажей в блоке)
    - строки без двоеточия или с «неправдоподобным» именем (скобки, цифры и т.д.)
    """
    char_lines = {}

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

            char_lines.setdefault(character, []).append(dialogue)

    return char_lines


def list_existing_actor_dirs():
    """
    Возвращает словарь {имя_папки_в_нижнем_регистре: реальное_имя_папки}
    для всех существующих папок актёров в BASE_DIR.

    Нижний регистр нужен, чтобы находить папки даже при небольших расхождениях
    в написании между сценарием и именем папки (например, «Blueberry» vs «blueberry»).
    """
    dirs = {}
    for entry in os.listdir(BASE_DIR):
        full = os.path.join(BASE_DIR, entry)
        if not os.path.isdir(full):
            continue
        if entry == "cut" or entry.startswith(".") or entry == "__pycache__":
            continue
        dirs[entry.lower()] = entry
    return dirs


def write_actor_files(char_lines):
    """
    Кладёт <Character>.txt в уже существующую папку актёра <BASE_DIR>/<Actor>/.
    Новые папки НЕ создаём: если папки актёра нет, просто предупреждаем —
    возможно, у актёра нет аудио и он не участвует в этой сценке.
    """
    existing = list_existing_actor_dirs()

    total_lines = 0
    written = 0
    missing_folders = []

    for character, lines in sorted(char_lines.items()):
        safe_name = sanitize_folder_name(character)
        real_dir_name = existing.get(safe_name.lower())

        if real_dir_name is None:
            missing_folders.append((character, len(lines)))
            continue

        actor_dir = os.path.join(BASE_DIR, real_dir_name)
        # Имя .txt совпадает с реальным именем папки — так main.py
        # и так найдёт его через find_script_for_audio().
        txt_path = os.path.join(actor_dir, f"{real_dir_name}.txt")

        if os.path.exists(txt_path) and not OVERWRITE:
            print(f"  [~] {real_dir_name}/{real_dir_name}.txt уже существует, пропускаем ({len(lines)} строк).")
            continue

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        print(f"  [v] {real_dir_name}/{real_dir_name}.txt — {len(lines)} строк(и)")
        total_lines += len(lines)
        written += 1

    if missing_folders:
        print(f"\n  ⚠️  Для {len(missing_folders)} персонаж(ей) не найдено папки — .txt не создан:")
        for name, count in missing_folders:
            print(f"     {name} ({count} строк) — создайте папку «{name}/» с аудио, если он участвует в сценке.")

    return total_lines, written


def main():
    print(f"🔍 Поиск сценария в: {BASE_DIR}")
    script_path = find_master_script()
    if not script_path:
        print("[!] Не найдено .txt-файла сценария в корне.")
        print(f"    Положите его в {BASE_DIR} и запустите снова.")
        return

    print(f"🎬 Сценарий: {os.path.basename(script_path)}\n")

    char_lines = parse_script(script_path)
    if not char_lines:
        print("[!] В сценарии не распознано ни одной реплики персонажа.")
        print("    Проверьте формат строк: «Персонаж: реплика».")
        return

    total_lines, written = write_actor_files(char_lines)
    print(
        f"\n📊 Итого: {total_lines} реплик(и) записано в {written} "
        f"папк(и) из {len(char_lines)} найденных в сценарии."
    )


if __name__ == "__main__":
    main()
    print("\n✅ ГОТОВО")
