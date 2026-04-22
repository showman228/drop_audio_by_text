import os
import re
import subprocess
import whisper
from thefuzz import fuzz

# --- КОНФИГУРАЦИЯ ---
model = whisper.load_model("base")  # small, medium, large

# Настройки звука (в секундах)
MICRO_GAP = 0.05        # Зазор перед началом слова (чтобы не щелкало)
PAD_END = 0.2           # Зазор после конца слова (для естественного затухания)
SIMILARITY_THRESHOLD = 60  # Насколько слова должны быть похожи (0-100)
SEARCH_WINDOW = 20      # Сколько слов вперёд искать начало/конец фразы (окно поиска)
RETRY_WINDOW_MULTIPLIER = 5  # Во сколько раз расширить окно при повторной попытке
ANCHOR_DEPTH = 3        # Сколько крайних слов (в начале/конце фразы) пробовать как якорь

# Директория, где лежит скрипт
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def cut_audio(input_file, start, end, output_file):
    """Нарезка аудио без потери качества через ffmpeg"""
    duration = end - start
    if duration <= 0:
        return
    command = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", input_file,
        "-c", "copy",
        output_file
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clean_word(word):
    """Очистка слова от мусора для точного сравнения"""
    if not word:
        return ""
    return word.strip().lower().translate(str.maketrans('', '', '.,!?—-:;()"\''))


def is_similar(word1, word2):
    """Нечеткое сравнение слов (обработка опечаток и падежей)"""
    return fuzz.ratio(clean_word(word1), clean_word(word2)) >= SIMILARITY_THRESHOLD


def get_time_hint(all_audio_words, current_word_idx):
    """
    Возвращает примерный момент в аудио (в секундах),
    где сейчас находится поиск — чтобы понять, где именно возникла проблема.
    """
    if current_word_idx < len(all_audio_words):
        t = all_audio_words[current_word_idx]["start"]
    elif all_audio_words:
        t = all_audio_words[-1]["end"]
    else:
        t = 0.0
    return t


def find_phrase_start(all_audio_words, start_idx, first_target):
    """
    Ищет первое слово фразы в окне SEARCH_WINDOW слов от start_idx.
    Если не нашли — возвращает (None, start_idx + SEARCH_WINDOW),
    чтобы следующая фраза продолжила с конца окна, а не застряла на месте.
    """
    window_end = min(start_idx + SEARCH_WINDOW, len(all_audio_words))
    for idx in range(start_idx, window_end):
        if is_similar(all_audio_words[idx]["word"], first_target):
            phrase_start_time = max(0, all_audio_words[idx]["start"] - MICRO_GAP)
            return phrase_start_time, idx
    return None, window_end


def find_phrase_end(all_audio_words, start_idx, last_target, phrase_len):
    """
    Ищет последнее слово фразы в окне от start_idx.
    Окно = max(SEARCH_WINDOW, длина фразы + 5) — чтобы не обрезать длинные фразы.
    Если не нашли — возвращает (None, start_idx + 1).
    """
    window = max(SEARCH_WINDOW, phrase_len + 5)
    window_end = min(start_idx + window, len(all_audio_words))
    for idx in range(start_idx, window_end):
        if is_similar(all_audio_words[idx]["word"], last_target):
            phrase_end_time = all_audio_words[idx]["end"] + PAD_END
            return phrase_end_time, idx
    return None, start_idx + 1


def find_phrase_start_robust(all_audio_words, start_idx, phrase_words):
    """
    Ищет начало фразы с несколькими стратегиями повторных попыток.

    1) Обычный поиск первого слова в окне SEARCH_WINDOW.
    2) Если не нашли — расширяем окно в RETRY_WINDOW_MULTIPLIER раз.
    3) Если всё ещё не нашли — пробуем 2-е, 3-е слово фразы как якорь
       (Whisper иногда пропускает первое слово или распознаёт его как мусор).
       Время начала оценивается отступом назад на N слов от найденного якоря.

    Возвращает (start_time, start_idx, strategy_note) или (None, next_idx, None).
    """
    first_target = clean_word(phrase_words[0])

    # --- Стратегия 1: обычное окно ---
    t, idx = find_phrase_start(all_audio_words, start_idx, first_target)
    if t is not None:
        return t, idx, None

    # --- Стратегия 2: расширенное окно ---
    ext_end = min(start_idx + SEARCH_WINDOW * RETRY_WINDOW_MULTIPLIER, len(all_audio_words))
    for i in range(start_idx, ext_end):
        if is_similar(all_audio_words[i]["word"], first_target):
            return max(0, all_audio_words[i]["start"] - MICRO_GAP), i, "расширенное окно"

    # --- Стратегия 3: якорь по 2-му, 3-му слову ---
    for offset in range(1, min(ANCHOR_DEPTH, len(phrase_words))):
        anchor_target = clean_word(phrase_words[offset])
        if not anchor_target:
            continue
        for i in range(start_idx, ext_end):
            if is_similar(all_audio_words[i]["word"], anchor_target):
                est_idx = max(0, i - offset)
                est_start = all_audio_words[est_idx]["start"]
                return max(0, est_start - MICRO_GAP), est_idx, f"по {offset + 1}-му слову"

    return None, ext_end, None


def find_phrase_end_robust(all_audio_words, start_idx, phrase_words):
    """
    Ищет конец фразы с несколькими стратегиями повторных попыток.

    1) Обычный поиск последнего слова в стандартном окне.
    2) Расширенное окно в RETRY_WINDOW_MULTIPLIER раз.
    3) Якорь по 2-му/3-му с конца слову фразы (на случай, если Whisper
       не распознал самое последнее слово или «съел» его).
       Время конца оценивается отступом вперёд на N слов от якоря.

    Возвращает (end_time, end_idx, strategy_note) или (None, next_idx, None).
    """
    phrase_len = len(phrase_words)
    last_target = clean_word(phrase_words[-1])

    # --- Стратегия 1: стандартное окно ---
    t, idx = find_phrase_end(all_audio_words, start_idx, last_target, phrase_len)
    if t is not None:
        return t, idx, None

    # --- Стратегия 2: расширенное окно ---
    base_window = max(SEARCH_WINDOW, phrase_len + 5)
    ext_end = min(start_idx + base_window * RETRY_WINDOW_MULTIPLIER, len(all_audio_words))
    for i in range(start_idx, ext_end):
        if is_similar(all_audio_words[i]["word"], last_target):
            return all_audio_words[i]["end"] + PAD_END, i, "расширенное окно"

    # --- Стратегия 3: якорь по 2-му, 3-му слову с конца ---
    for offset in range(1, min(ANCHOR_DEPTH, phrase_len)):
        anchor_target = clean_word(phrase_words[-1 - offset])
        if not anchor_target:
            continue
        for i in range(start_idx, ext_end):
            if is_similar(all_audio_words[i]["word"], anchor_target):
                est_idx = min(len(all_audio_words) - 1, i + offset)
                est_end = all_audio_words[est_idx]["end"]
                return est_end + PAD_END, est_idx, f"по {offset + 1}-му с конца"

    return None, start_idx + 1, None


def process_audio(audio_path, text_path, output_dir, base_name):
    """Основная логика сопоставления текста и звука"""
    print(f"\n--- 🎬 Обработка: {os.path.basename(audio_path)} ---")

    with open(text_path, "r", encoding="utf-8") as f:
        target_phrases = []
        for line in f:
            if line.strip():
                line = line.strip()
                line = re.sub(r'[—–‒―⁃]', '-', line)
                target_phrases.append(line)

    # Получаем пословные временные метки от Whisper
    # fp16=False предотвращает предупреждения на процессорах без GPU
    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        fp16=False,  # на Apple Silicon fp16 через MPS нестабилен
        language="en",  # явно — убирает детекцию языка
        beam_size=5,
        best_of=5,
        temperature=0.0,  # нейронка чистая → детерминизм лучше
        condition_on_previous_text=False,  # критично для длинных записей
        no_speech_threshold=0.3,  # нейронка не делает пауз-шумов → можно снизить
        compression_ratio_threshold=2.4,
        initial_prompt="The following is a clearly spoken voice acting performance."
    )

    # Собираем все распознанные слова в один список
    all_audio_words = []
    for segment in result["segments"]:
        for w in segment["words"]:
            all_audio_words.append({
                "word": clean_word(w["word"]),
                "start": w["start"],
                "end": w["end"]
            })

    if not all_audio_words:
        print("  [!] Whisper не распознал ни одного слова в аудио. Пропускаем файл.")
        return

    # Конец аудио — берём позицию последнего распознанного слова + PAD_END.
    # Используется как правая граница fallback-нарезки при ошибках поиска фразы.
    audio_end_time = all_audio_words[-1]["end"] + PAD_END

    current_word_idx = 0
    os.makedirs(output_dir, exist_ok=True)

    failed_phrases = []

    for i, phrase in enumerate(target_phrases):
        phrase_words = phrase.split()
        if not phrase_words:
            continue

        first_target = clean_word(phrase_words[0])
        last_target = clean_word(phrase_words[-1])

        # --- 1. Ищем начало фразы (со стратегиями повторных попыток) ---
        phrase_start_time, start_idx_in_audio, start_note = find_phrase_start_robust(
            all_audio_words, current_word_idx, phrase_words
        )

        if phrase_start_time is None:
            # Не нашли начало — сохраняем fallback-нарезку от текущей позиции
            # до конца аудио, чтобы пропавший фрагмент можно было разобрать вручную.
            time_hint = get_time_hint(all_audio_words, current_word_idx)
            current_word_idx = start_idx_in_audio  # start_idx_in_audio = window_end

            output_name = f"{base_name}_{i + 1:03}.mp3"
            output_path = os.path.join(output_dir, output_name)
            cut_audio(audio_path, time_hint, audio_end_time, output_path)

            msg = (
                f"  [x] Фраза {i + 1:03}: не найдено первое слово «{first_target}» "
                f"(~{time_hint:.1f}с) → fallback {output_name} "
                f"({time_hint:.1f}с → {audio_end_time:.1f}с) — «{phrase[:50]}»"
            )
            print(msg)
            failed_phrases.append(msg)
            continue

        # --- 2. Ищем конец фразы (со стратегиями повторных попыток) ---
        phrase_end_time, end_idx_in_audio, end_note = find_phrase_end_robust(
            all_audio_words, start_idx_in_audio, phrase_words
        )

        if phrase_end_time is None:
            # Конец фразы не нашли — fallback от найденного начала до конца аудио.
            time_hint = all_audio_words[start_idx_in_audio]["start"]
            current_word_idx = end_idx_in_audio  # end_idx_in_audio = start_idx + 1

            output_name = f"{base_name}_{i + 1:03}.mp3"
            output_path = os.path.join(output_dir, output_name)
            fallback_start = max(0, time_hint - MICRO_GAP)
            cut_audio(audio_path, fallback_start, audio_end_time, output_path)

            msg = (
                f"  [!] Фраза {i + 1:03}: начало найдено (~{time_hint:.1f}с), "
                f"но не найдено последнее слово «{last_target}» → fallback {output_name} "
                f"({fallback_start:.1f}с → {audio_end_time:.1f}с) — «{phrase[:50]}»"
            )
            print(msg)
            failed_phrases.append(msg)
            continue

        # --- 3. Всё нашли — нарезаем ---
        output_name = f"{base_name}_{i + 1:03}.mp3"
        output_path = os.path.join(output_dir, output_name)

        retry_notes = [n for n in (start_note, end_note) if n]
        retry_hint = f" [повтор: {', '.join(retry_notes)}]" if retry_notes else ""
        print(
            f"  [v] Фраза {i + 1:03}: {output_name} "
            f"({phrase_start_time:.1f}с → {phrase_end_time:.1f}с){retry_hint}"
        )
        cut_audio(audio_path, phrase_start_time, phrase_end_time, output_path)

        # Сдвигаем позицию за конец найденной фразы
        current_word_idx = end_idx_in_audio + 1

    # --- Итоговый отчёт ---
    total = len(target_phrases)
    failed = len(failed_phrases)
    success = total - failed

    print(f"\n  📊 Итог: {success}/{total} фраз нарезано успешно.")
    if failed_phrases:
        print(f"  ⚠️  Не удалось обработать {failed} фраз(ы):")
        for msg in failed_phrases:
            print(f"    {msg.strip()}")


def find_script_for_audio(actor_dir, audio_basename):
    """
    Находит .txt-сценарий для данного аудио внутри папки актёра.

    1) Сначала ищем .txt с тем же именем, что и .mp3 (например, Alice.mp3 → Alice.txt).
    2) Если не нашли — используем единственный .txt в папке (частый случай,
       когда актёр называет файлы как угодно, но скрипт в папке один).
    3) Если .txt несколько и ни один не совпадает по имени — возвращаем None
       (неоднозначно, лучше пропустить, чем угадывать).
    """
    same_name = os.path.join(actor_dir, audio_basename + ".txt")
    if os.path.exists(same_name):
        return same_name

    txt_files = [f for f in os.listdir(actor_dir) if f.lower().endswith(".txt")]
    if len(txt_files) == 1:
        return os.path.join(actor_dir, txt_files[0])
    return None


def main():
    print(f"🔍 Сканирование папок актёров в: {BASE_DIR}")

    cut_root = os.path.join(BASE_DIR, "cut")

    # Берём только папки верхнего уровня как «актёров». cut/ и скрытые папки игнорируем.
    for entry in sorted(os.listdir(BASE_DIR)):
        actor_dir = os.path.join(BASE_DIR, entry)
        if not os.path.isdir(actor_dir):
            continue
        if entry == "cut" or entry.startswith(".") or entry == "__pycache__":
            continue
        if entry in ("characters_lines", "result_", "cut_"):
            continue

        actor_name = entry
        mp3_files = sorted(f for f in os.listdir(actor_dir) if f.lower().endswith(".mp3"))
        if not mp3_files:
            continue

        for audio_file in mp3_files:
            audio_path = os.path.join(actor_dir, audio_file)
            base_name = os.path.splitext(audio_file)[0]

            text_path = find_script_for_audio(actor_dir, base_name)
            if not text_path:
                print(f"\n[!] {actor_name}/{audio_file}: не найден парный .txt — пропускаем.")
                continue

            # Нарезки складываем в cut/<имя_актёра>/
            output_dir = os.path.join(cut_root, actor_name)
            process_audio(audio_path, text_path, output_dir, base_name)


if __name__ == "__main__":
    main()
    print("\n✅ ВСЕ ПАПКИ ОБРАБОТАНЫ")
