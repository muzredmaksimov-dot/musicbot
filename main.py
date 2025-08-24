import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from telebot import types
from datetime import datetime
from flask import Flask, request
import json
import glob

# === Настройки ===
TOKEN = '8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk'
AUDIO_FOLDER = 'audio'
SPREADSHEET_NAME = 'music_testing'
WORKSHEET_NAME = 'track_list'

# === Инициализация ===
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === Google Sheets авторизация ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

worksheet = None
track_data = {}         # mapping track_number (str) -> title (from CSV)
MAX_TRACK = 0           # максимально ожидаемый номер трека (int)

# --- состояния (старая логика отправки) ---
user_progress     = {}   # какой трек у кого сейчас (int)
user_ratings      = {}   # dict: chat_id -> {track_num_str: rating}
user_metadata     = {}   # dict: chat_id -> {'username':..., 'gender':..., 'age':...}
last_audios       = {}   # message_id последнего аудио

# === Функции Google Sheets & CSV (взятые из актуального кода) ===
def initialize_google_sheets():
    """Инициализация подключения к Google Таблицам.
    Поддерживает env GOOGLE_CREDS_JSON, GOOGLE_CREDS_B64, или локальный creds.json.
    """
    global worksheet
    try:
        creds_json_str = os.environ.get('GOOGLE_CREDS_JSON')
        creds_b64 = os.environ.get('GOOGLE_CREDS_B64')

        if creds_json_str:
            creds_dict = json.loads(creds_json_str)
        elif creds_b64:
            import base64
            creds_dict = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
        elif os.path.exists('creds.json'):
            with open('creds.json', 'r', encoding='utf-8') as f:
                creds_dict = json.load(f)
        else:
            print("❌ Нет ключа для Google API: задайте GOOGLE_CREDS_JSON или GOOGLE_CREDS_B64, или положите creds.json")
            worksheet = None
            return False

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        print("✅ Успешно подключено к Google Таблице!")
        return True

    except Exception as e:
        worksheet = None
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

def save_to_google_sheets(user_data, ratings):
    """Сохранение результатов в Google Таблицу (как в актуальном коде)."""
    if not worksheet:
        print("❌ Google Таблица не доступна — пропускаем запись в Google")
        return False

    try:
        all_data = worksheet.get_all_values()
        next_col = len(all_data[0]) + 1 if all_data and all_data[0] else 1

        user_info = [
            user_data['user_id'],
            f"@{user_data.get('username', '')}",
            user_data.get('gender', ''),
            user_data.get('age', ''),
            datetime.now().isoformat()
        ]

        for i in range(1, MAX_TRACK + 1):
            user_info.append(ratings.get(str(i), ''))

        for row_idx, value in enumerate(user_info, start=1):
            worksheet.update_cell(row_idx, next_col, value)

        print(f"✅ Данные сохранены в колонку {next_col} Google Sheets")
        return True

    except Exception as e:
        print(f"❌ Ошибка сохранения в Google Таблицу: {e}")
        return False

def save_to_csv_backup(user_data, ratings):
    """Резервное сохранение в CSV (как в актуальном коде)."""
    try:
        file_exists = os.path.exists('backup_results.csv')
        with open('backup_results.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            if not file_exists:
                headers = ['user_id', 'username', 'gender', 'age', 'timestamp']
                for i in range(1, MAX_TRACK + 1):
                    headers.append(f'track_{i}')
                writer.writerow(headers)

            row_data = [
                user_data['user_id'],
                user_data.get('username', ''),
                user_data.get('gender', ''),
                user_data.get('age', ''),
                datetime.now().isoformat()
            ]

            for i in range(1, MAX_TRACK + 1):
                row_data.append(ratings.get(str(i), ''))

            writer.writerow(row_data)

        print("✅ Данные сохранены в CSV бэкап")
        return True

    except Exception as e:
        print(f"❌ Ошибка сохранения в CSV: {e}")
        return False

# === Утилиты треков ===
def list_audio_files():
    if not os.path.isdir(AUDIO_FOLDER):
        print(f"⚠️ Папка audio не найдена: {AUDIO_FOLDER}")
        return []
    files = glob.glob(os.path.join(AUDIO_FOLDER, '**', '*.mp3'), recursive=True)
    files_sorted = sorted(files)
    print(f"🔎 Найдено {len(files_sorted)} mp3 в '{AUDIO_FOLDER}':")
    for p in files_sorted:
        print("   ", os.path.relpath(p))
    return files_sorted

def load_track_data():
    """Загрузим CSV метаданные (если есть) и вычислим MAX_TRACK по файлам/CSV."""
    global track_data, MAX_TRACK
    track_data = {}
    MAX_TRACK = 0
    try:
        # листаем файлы для диагностики
        list_audio_files()

        if os.path.exists('track_list.csv'):
            with open('track_list.csv', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tn = row.get('track_number')
                    title = row.get('title', '')
                    if tn:
                        tn_stripped = tn.strip()
                        track_data[tn_stripped] = title
            if track_data:
                try:
                    MAX_TRACK = max(int(k) for k in track_data.keys())
                except Exception:
                    MAX_TRACK = len(track_data)

        else:
            # если CSV нет — попробуем определить MAX_TRACK по файлам в папке audio
            files = list_audio_files()
            for f in files:
                bn = os.path.basename(f)
                name, _ = os.path.splitext(bn)
                # ищем первые цифры в имени
                digits = ''.join(ch for ch in name.split()[0] if ch.isdigit())
                if digits:
                    try:
                        num = int(digits)
                        track_data[str(num)] = bn
                    except Exception:
                        continue
            if track_data:
                MAX_TRACK = max(int(k) for k in track_data.keys())

        print(f"✅ Загружено {len(track_data)} треков (MAX_TRACK={MAX_TRACK})")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки треков: {e}")
        track_data = {}
        MAX_TRACK = 0
        return False

# === Интерфейс / flow — взято из старого кода (отправка треков) ===
@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id
    user_metadata[chat_id] = {'username': message.from_user.username}
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    welcome_text = (
        "Ты услышишь несколько коротких треков. Оцени каждый по шкале от 1 до 5:\n\n"
        "Но сначала давай познакомимся 🙂"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    bot.send_message(chat_id, welcome_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    try:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    # инициализируем состояния
    user_metadata[chat_id].setdefault('gender', None)
    user_metadata[chat_id].setdefault('age', None)
    user_progress[chat_id] = 1
    user_ratings[chat_id] = {}
    last_audios[chat_id] = None

    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_M"),
        types.InlineKeyboardButton("Женский", callback_data="gender_F")
    )
    bot.send_message(chat_id, "Укажи свой пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['gender'] = c.data.split('_',1)[1]
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass
    ask_age(chat_id)

def ask_age(chat_id):
    opts = ["до 24","25-34","35-44","45-54","55+"]
    kb = types.InlineKeyboardMarkup(row_width=3)
    for o in opts:
        kb.add(types.InlineKeyboardButton(o, callback_data=f"age_{o}"))
    bot.send_message(chat_id, "Укажи свой возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['age'] = c.data.split('_',1)[1]
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    # старт теста (сообщение и отправка первого трека)
    bot.send_message(chat_id, "Оцени трек от 1 до 5:\n\n1 — Не нравится\n2 — Раньше нравилась, но надоела\n3 — Нейтрально\n4 — Нравится\n5 — Любимая ппесня")
    send_next_track(chat_id)

def send_next_track(chat_id):
    """Отправка аудио в формате старого рабочего кода (001.mp3, 002.mp3...)."""
    n = user_progress.get(chat_id, 1)
    path = os.path.join(AUDIO_FOLDER, f"{n:03d}.mp3")
    print(f"[send_next_track] chat={chat_id} пытаемся отправить {path}")
    if not os.path.exists(path):
        # нет следующего файла -> считаем тест завершённым
        bot.send_message(chat_id, "🎉 Тест завершен! Сохраняю результаты...")
        # готовим данные и сохраняем через актуальные функции
        user_data = {
            'user_id': chat_id,
            'username': user_metadata.get(chat_id, {}).get('username', ''),
            'gender': user_metadata.get(chat_id, {}).get('gender', ''),
            'age': user_metadata.get(chat_id, {}).get('age', '')
        }
        ratings = user_ratings.get(chat_id, {})
        google_success = save_to_google_sheets(user_data, ratings)
        csv_success = save_to_csv_backup(user_data, ratings)
        if google_success:
            bot.send_message(chat_id, "✅ Результаты сохранены в Google Таблицу.")
        elif csv_success:
            bot.send_message(chat_id, "✅ Результаты сохранены в локальный файл.")
        else:
            bot.send_message(chat_id, "⚠️ Ошибка при сохранении результатов.")
        # очистка состояний
        try:
            del user_progress[chat_id]
            del user_ratings[chat_id]
            del user_metadata[chat_id]
            del last_audios[chat_id]
        except Exception:
            pass
        return

    # отправляем аудио
    try:
        with open(path, 'rb') as f:
            m = bot.send_audio(chat_id, f, caption=f"Трек №{n}")
            last_audios[chat_id] = m.message_id
    except Exception as e:
        print(f"[send_next_track] Ошибка отправки {path}: {e}")
        bot.send_message(chat_id, f"Ошибка при отправке трека #{n}: {e}")
        return

    # клавиатура 1..5
    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1,6):
        kb.add(types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rate(c):
    chat_id = c.message.chat.id
    # защита
    if chat_id not in user_progress:
        bot.answer_callback_query(c.id, "Тест не запущен. Нажмите /start или Начать.", show_alert=True)
        return

    n = user_progress.get(chat_id, 1)
    # если оценка уже есть — предупреждаем
    if str(n) in user_ratings.get(chat_id, {}):
        bot.answer_callback_query(c.id, "Уже оценено", show_alert=True)
        return

    score = c.data.split('_',1)[1]

    # сохраняем оценку в память
    user_ratings.setdefault(chat_id, {})[str(n)] = score

    # удаляем сообщения с аудио/кнопками (попытки, в try)
    try:
        if last_audios.get(chat_id):
            bot.delete_message(chat_id, last_audios[chat_id])
    except Exception:
        pass
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    # идем дальше
    user_progress[chat_id] = n + 1
    send_next_track(chat_id)

@bot.message_handler(func=lambda m: True)
def fallback(m):
    bot.send_message(m.chat.id,"Нажмите /start или отправьте любое сообщение, чтобы начать")

# === Вебхук обработчики ===
@app.route('/webhook/' + TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400

@app.route('/')
def index():
    return 'Music Test Bot is running!'

@app.route('/health')
def health():
    return 'OK'

# === Запуск ===
if __name__ == "__main__":
    print("🚀 Инициализация бота...")
    gs_ok = initialize_google_sheets()
    csv_ok = load_track_data()
    print(f"[INIT] GoogleSheets ok={gs_ok}, Tracks loaded ok={csv_ok}, MAX_TRACK={MAX_TRACK}")

    if 'RENDER' in os.environ:
        print("🌐 Запуск на Render (вебхук)")
        port = int(os.environ.get('PORT', 10000))
        app.run(host='0.0.0.0', port=port)
    else:
        print("💻 Локальный запуск (polling)")
        bot.remove_webhook()
        bot.polling(none_stop=True)
