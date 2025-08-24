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
track_data = {}         # mapping track_number (str) -> title
MAX_TRACK = 0           # максимально ожидаемый номер трека (int)
user_states = {}

# === Функции ===
def initialize_google_sheets():
    """Инициализация подключения к Google Таблицам через переменную окружения"""
    global worksheet
    try:
        creds_json_str = os.environ.get('GOOGLE_CREDS_JSON')
        if not creds_json_str:
            print("❌ GOOGLE_CREDS_JSON не задан")
            worksheet = None
            return False

        creds_dict = json.loads(creds_json_str)
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

def load_track_data():
    """Загрузка данных о треках из CSV и вычисление MAX_TRACK"""
    global track_data, MAX_TRACK
    track_data = {}
    MAX_TRACK = 0
    try:
        if not os.path.exists('track_list.csv'):
            print("⚠️ track_list.csv не найден — попробую определить треки по папке audio")
            # Попытаться определить количество файлов в audio
            if os.path.isdir(AUDIO_FOLDER):
                files = sorted(glob.glob(os.path.join(AUDIO_FOLDER, '*.mp3')))
                for f in files:
                    # попытаемся распарсить номер из имени файла вида 001.mp3 или 1.mp3
                    basename = os.path.basename(f)
                    name, _ = os.path.splitext(basename)
                    try:
                        num = int(name)
                        track_data[str(num)] = basename
                    except Exception:
                        continue
                MAX_TRACK = max((int(k) for k in track_data.keys()), default=0)
                print(f"✅ Автодетект: найдено {len(track_data)} файлов в {AUDIO_FOLDER}")
                return True if track_data else False
            return False

        with open('track_list.csv', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tn = row.get('track_number')
                title = row.get('title', '')
                if tn:
                    tn_stripped = tn.strip()
                    # сохраняем ключ как строку
                    track_data[tn_stripped] = title
            if track_data:
                try:
                    MAX_TRACK = max(int(k) for k in track_data.keys())
                except Exception:
                    # если ключи не числа — просто длина
                    MAX_TRACK = len(track_data)
        print(f"✅ Загружено {len(track_data)} треков (MAX_TRACK={MAX_TRACK})")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки треков: {e}")
        track_data = {}
        MAX_TRACK = 0
        return False

def save_to_google_sheets(user_data, ratings):
    """Сохранение результатов в Google Таблицу"""
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
    """Резервное сохранение в CSV"""
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

# === Обработчики бота ===
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_states[chat_id] = {
        'user_id': chat_id,
        'username': message.from_user.username,
        'ratings': {},
        'current_track': 1
    }

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎵 Начать тест", callback_data="start_test"))
    bot.send_message(chat_id, "Добро пожаловать в музыкальный тест! Нажмите кнопку ниже чтобы начать.", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def start_test(call):
    chat_id = call.message.chat.id
    try:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("Мужской", callback_data="gender_M"))
    kb.row(types.InlineKeyboardButton("Женский", callback_data="gender_F"))
    bot.send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    user_states[chat_id]['gender'] = c.data.split('_', 1)[1]

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    ask_age(chat_id)

def ask_age(chat_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    ages = ["до 24", "25-34", "35-44", "45-54", "55+"]
    for age in ages:
        kb.add(types.InlineKeyboardButton(age, callback_data=f"age_{age}"))
    bot.send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    user_states[chat_id]['age'] = c.data.split('_', 1)[1]

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    bot.send_message(chat_id, "🎵 Начинаем музыкальный тест!\n\nОцените каждый трек по шкале от 1 до 5 звезд")
    send_track(chat_id)

def send_track(chat_id):
    """Отправляет очередной трек. Корректно обрабатывает отсутствие треков/файлов."""
    if chat_id not in user_states:
        return

    track_num = user_states[chat_id]['current_track']

    # Если не загружены треки (MAX_TRACK == 0) — сообщаем пользователю и не завершаем тест "по-умолчанию"
    if MAX_TRACK == 0:
        msg = ("⚠️ В настоящий момент треки не загружены на сервере.\n"
               "Пожалуйста, сообщите администратору или попробуйте позже.")
        bot.send_message(chat_id, msg)
        print(f"[DEBUG] Пользователь {chat_id}: попытка начать тест при MAX_TRACK=0")
        return

    # Если номер трека превышает MAX_TRACK — тест окончен
    if track_num > MAX_TRACK:
        user_data = user_states[chat_id]
        google_success = save_to_google_sheets(user_data, user_data['ratings'])
        csv_success = save_to_csv_backup(user_data, user_data['ratings'])

        if google_success:
            bot.send_message(chat_id, "🎉 Тест завершен! Результаты сохранены в Google Таблицу.")
        elif csv_success:
            bot.send_message(chat_id, "✅ Тест завершен! Результаты сохранены в файл (локальный бэкап).")
        else:
            bot.send_message(chat_id, "⚠️ Тест завершен! Но возникла ошибка при сохранении.")
        # можно очистить состояние пользователя, если нужно:
        try:
            del user_states[chat_id]
        except Exception:
            pass
        return

    # Формируем путь к аудиофайлу (ожидается формат 001.mp3 / 002.mp3 и т.д.)
    file_path = os.path.join(AUDIO_FOLDER, f"{track_num:03d}.mp3")

    # Если файла нет — логируем и завершаем тест (чтобы не отправлять пустоту пользователю)
    if not os.path.exists(file_path):
        # Логируем причину
        print(f"❌ Отсутствует файл для трека {track_num}: ожидается {file_path}")
        bot.send_message(chat_id, f"⚠️ Трек #{track_num} временно недоступен. Тест будет завершён, результаты сохраняются.")
        # сохраняем то, что есть
        user_data = user_states[chat_id]
        google_success = save_to_google_sheets(user_data, user_data['ratings'])
        csv_success = save_to_csv_backup(user_data, user_data['ratings'])
        if google_success:
            bot.send_message(chat_id, "🎉 Частично сохранённые результаты отправлены в Google Таблицу.")
        elif csv_success:
            bot.send_message(chat_id, "✅ Частично сохранённые результаты сохранены в файл.")
        else:
            bot.send_message(chat_id, "⚠️ Ошибка при сохранении результатов.")
        try:
            del user_states[chat_id]
        except Exception:
            pass
        return

    # Отправляем сам аудиофайл
    try:
        with open(file_path, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file, caption=f"Трек #{track_num}")
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка загрузки трека: {e}")
        print(f"❌ Ошибка при отправке файла {file_path} пользователю {chat_id}: {e}")
        return

    # Отправляем inline клавиатуру с оценкой
    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(f"{i}★", callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените трек:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    try:
        rating = int(c.data.split('_', 1)[1])
    except Exception:
        rating = None

    track_num = user_states[chat_id]['current_track']
    if rating is not None:
        user_states[chat_id]['ratings'][str(track_num)] = rating

    user_states[chat_id]['current_track'] += 1

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    send_track(chat_id)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    bot.send_message(message.chat.id, "Для начала теста нажмите /start")

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
