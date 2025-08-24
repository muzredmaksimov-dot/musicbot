import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from telebot import types
from datetime import datetime
from flask import Flask, request
import json

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
track_data = {}
user_states = {}

# === Функции ===
def initialize_google_sheets():
    """Инициализация подключения к Google Таблицам через переменную окружения"""
    global worksheet
    try:
        creds_json_str = os.environ.get('GOOGLE_CREDS_JSON')
        if not creds_json_str:
            print("❌ GOOGLE_CREDS_JSON не задан")
            return False

        creds_dict = json.loads(creds_json_str)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        print("✅ Успешно подключено к Google Таблице!")
        return True

    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

def load_track_data():
    """Загрузка данных о треках из CSV"""
    global track_data
    try:
        with open('track_list.csv', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            track_data = {row['track_number']: row['title'] for row in reader}
        print(f"✅ Загружено {len(track_data)} треков")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки треков: {e}")
        return False

def save_to_google_sheets(user_data, ratings):
    """Сохранение результатов в Google Таблицу"""
    if not worksheet:
        print("❌ Google Таблица не доступна")
        return False
    
    try:
        all_data = worksheet.get_all_values()
        next_col = len(all_data[0]) + 1 if all_data and all_data[0] else 1

        user_info = [
            user_data['user_id'],
            f"@{user_data.get('username', '')}",
            user_data['gender'],
            user_data['age'],
            datetime.now().isoformat()
        ]

        for i in range(1, len(track_data) + 1):
            user_info.append(ratings.get(str(i), ''))

        for row_idx, value in enumerate(user_info, start=1):
            worksheet.update_cell(row_idx, next_col, value)

        print(f"✅ Данные сохранены в колонку {next_col}")
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
                for i in range(1, len(track_data) + 1):
                    headers.append(f'track_{i}')
                writer.writerow(headers)

            row_data = [
                user_data['user_id'],
                user_data.get('username', ''),
                user_data['gender'],
                user_data['age'],
                datetime.now().isoformat()
            ]

            for i in range(1, len(track_data) + 1):
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

    user_states[chat_id]['gender'] = c.data.split('_')[1]

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

    user_states[chat_id]['age'] = c.data.split('_')[1]

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    bot.send_message(chat_id, "🎵 Начинаем музыкальный тест!\n\nОцените каждый трек по шкале от 1 до 5 звезд")
    send_track(chat_id)

def send_track(chat_id):
    track_num = user_states[chat_id]['current_track']
    file_path = os.path.join(AUDIO_FOLDER, f"{track_num:03d}.mp3")

    if not os.path.exists(file_path):
        user_data = user_states[chat_id]
        google_success = save_to_google_sheets(user_data, user_data['ratings'])
        csv_success = save_to_csv_backup(user_data, user_data['ratings'])

        if google_success:
            bot.send_message(chat_id, "🎉 Тест завершен! Результаты сохранены в Google Таблицу.")
        elif csv_success:
            bot.send_message(chat_id, "✅ Тест завершен! Результаты сохранены в файл.")
        else:
            bot.send_message(chat_id, "⚠️ Тест завершен! Но возникла ошибка при сохранении.")
        return

    try:
        with open(file_path, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file, caption=f"Трек #{track_num}")
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка загрузки трека: {e}")
        return

    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(f"{i}★", callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените трек:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    rating = int(c.data.split('_')[1])
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    track_num = user_states[chat_id]['current_track']
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
    initialize_google_sheets()
    load_track_data()

    if 'RENDER' in os.environ:
        print("🌐 Запуск на Render (вебхук)")
        port = int(os.environ.get('PORT', 10000))
        app.run(host='0.0.0.0', port=port)
    else:
        print("💻 Локальный запуск (polling)")
        bot.remove_webhook()
        bot.polling(none_stop=True)
