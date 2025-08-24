import os
import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telebot import types
from flask import Flask, request
from datetime import datetime
import json
import time

# === НАСТРОЙКИ ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_CHAT_ID = "866964827"
AUDIO_FOLDER = "tracks"
SPREADSHEET_NAME = "music_testing"
WORKSHEET_NAME = "track_list"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === GOOGLE SHEETS ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
worksheet = None

def initialize_google_sheets():
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
            print("❌ Нет ключа для Google API")
            return False

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        print("✅ Успешно подключено к Google Таблице!")
        return True
    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

# === ХРАНИЛИЩЕ ===
user_last_message = {}
user_rating_guide = {}
user_rating_time = {}
user_states = {}

# === РАСШИФРОВКА ОЦЕНОК ===
RATING_GUIDE_MESSAGE = """
🎵 **Шкала оценок:**

1️⃣ ★ - Совсем не нравится
2️⃣ ★★ - Скорее не нравится  
3️⃣ ★★★ - Нейтрально
4️⃣ ★★★★ - Нравится
5️⃣ ★★★★★ - Очень нравится

Выберите оценку для текущего трека:
"""

# === СОХРАНЕНИЕ В GOOGLE SHEETS ===
def save_to_google_sheets(user_data, ratings):
    if not worksheet:
        print("❌ Google Таблица не доступна")
        return False
    try:
        all_data = worksheet.get_all_values()
        if not all_data:
            next_col = 1
        else:
            next_col = len(all_data[0]) + 1

        user_info = [
            user_data['user_id'],
            f"@{user_data['username']}" if user_data.get('username') else user_data.get('first_name', ''),
            user_data.get('last_name', ''),
            user_data['gender'],
            user_data['age'],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]
        for i in range(1, 31):
            user_info.append(ratings.get(str(i), ''))

        for row_idx, value in enumerate(user_info, start=1):
            worksheet.update_cell(row_idx, next_col, value)

        print(f"✅ Данные сохранены в колонку {next_col}")
        return True
    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

# === CSV РЕЗЕРВ ===
def save_to_csv_backup(user_data, ratings):
    try:
        file_exists = os.path.exists('backup_results.csv')
        with open('backup_results.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                headers = ['user_id', 'username', 'first_name', 'last_name', 'gender', 'age', 'timestamp']
                for i in range(1, 31):
                    headers.append(f'track_{i}')
                writer.writerow(headers)
            row_data = [
                user_data['user_id'],
                user_data.get('username', ''),
                user_data.get('first_name', ''),
                user_data.get('last_name', ''),
                user_data['gender'],
                user_data['age'],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ]
            for i in range(1, 31):
                row_data.append(ratings.get(str(i), ''))
            writer.writerow(row_data)
        print("✅ Данные сохранены в CSV файл")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения в CSV: {e}")
        return False

# === ФУНКЦИИ ОТПРАВКИ СООБЩЕНИЙ ===
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        user_last_message.setdefault(chat_id, []).append(msg.message_id)
        return msg
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")

def cleanup_chat(chat_id, keep_rating_guide=False):
    if chat_id in user_last_message:
        try:
            rating_guide_id = user_rating_guide.get(chat_id)
            messages_to_keep = []
            if keep_rating_guide and rating_guide_id:
                messages_to_keep.append(rating_guide_id)
            for msg_id in user_last_message[chat_id]:
                if msg_id not in messages_to_keep:
                    try: bot.delete_message(chat_id, msg_id)
                    except: pass
            user_last_message[chat_id] = messages_to_keep
        except Exception as e:
            print(f"Ошибка очистки чата: {e}")

def send_rating_guide(chat_id):
    if chat_id in user_rating_guide:
        try: bot.delete_message(chat_id, user_rating_guide[chat_id])
        except: pass
    msg = send_message(chat_id, RATING_GUIDE_MESSAGE, parse_mode='Markdown')
    if msg: user_rating_guide[chat_id] = msg.message_id

# === СТАРТ ТЕСТА ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user = message.from_user
    cleanup_chat(chat_id, keep_rating_guide=True)
    user_states[chat_id] = {
        'user_data': {
            'user_id': chat_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'gender': '',
            'age': ''
        },
        'ratings': {},
        'current_track': 1
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
    welcome_text = (
        f"Привет, {user.first_name}! 🎵\n\n"
        "Вы прослушаете 30 музыкальных треков и оцените каждый по шкале от 1 до 5.\n\n"
        "🎁 После теста среди всех участников будет розыгрыш подарков!"
    )
    send_message(chat_id, welcome_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    cleanup_chat(chat_id)
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_Мужской"),
        types.InlineKeyboardButton("Женский", callback_data="gender_Женский")
    )
    send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    gender = c.data.split('_', 1)[1]
    user_states[chat_id]['user_data']['gender'] = gender
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass
    cleanup_chat(chat_id)
    ask_age(chat_id)

def ask_age(chat_id):
    opts = ["до 24", "25-34", "35-44", "45-54", "55+"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(o, callback_data=f"age_{o}") for o in opts]
    kb.add(*buttons)
    send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    age = c.data.split('_', 1)[1]
    user_states[chat_id]['user_data']['age'] = age
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass
    cleanup_chat(chat_id)
    username_display = f"@{user_states[chat_id]['user_data']['username']}" if user_states[chat_id]['user_data']['username'] else user_states[chat_id]['user_data']['first_name']
    send_message(chat_id, f"Спасибо, {username_display}! 🎶\n\nТеперь начнем слепой тест. 🎁")
    send_rating_guide(chat_id)
    send_track(chat_id)

# === ОТПРАВКА ТРЕКА ===
def send_track(chat_id):
    cleanup_chat(chat_id, keep_rating_guide=True)
    track_num = user_states[chat_id]['current_track']
    if track_num > 30:
        finish_test(chat_id)
        return
    track_filename = f"{track_num:03d}.mp3"
    track_path = os.path.join(AUDIO_FOLDER, track_filename)
    send_message(chat_id, f"🎵 Трек {track_num}/30")
    if os.path.exists(track_path):
        with open(track_path, 'rb') as audio_file:
            audio_msg = bot.send_audio(chat_id, audio_file, title=f"Трек {track_num:03d}")
            user_last_message.setdefault(chat_id, []).append(audio_msg.message_id)
            kb = types.InlineKeyboardMarkup(row_width=5)
            kb.add(*[types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1,6)])
            rating_msg = bot.send_message(chat_id, "Оцените трек:", reply_markup=kb)
            user_last_message[chat_id].append(rating_msg.message_id)
    else:
        send_message(chat_id, f"⚠️ Трек {track_num:03d} не найден.")
        user_states[chat_id]['current_track'] += 1
        send_track(chat_id)

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    rating = int(c.data.split('_')[1])
    track_num = user_states[chat_id]['current_track']
    current_time = time.time()
    last_rating_time = user_rating_time.get(chat_id, 0)
    if current_time - last_rating_time < 2:
        bot.answer_callback_query(c.id, "Пожалуйста, прослушайте трек перед оценкой")
        return
    user_rating_time[chat_id] = current_time
    user_states[chat_id]['ratings'][str(track_num)] = rating
    # Сохраняем сразу в Google Sheets и CSV
    save_to_google_sheets(user_states[chat_id]['user_data'], user_states[chat_id]['ratings'])
    save_to_csv_backup(user_states[chat_id]['user_data'], user_states[chat_id]['ratings'])
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass
    user_states[chat_id]['current_track'] += 1
    cleanup_chat(chat_id, keep_rating_guide=True)
    send_track(chat_id)

# === ЗАВЕРШЕНИЕ ТЕСТА ===
def finish_test(chat_id):
    user_data = user_states[chat_id]['user_data']
    ratings = user_states[chat_id]['ratings']
    google_success = save_to_google_sheets(user_data, ratings)
    csv_success = save_to_csv_backup(user_data, ratings)
    username_display = f"@{user_data['username']}" if user_data['username'] else user_data['first_name']
    if google_success:
        send_message(chat_id, f"🎉 {username_display}, тест завершён! Результаты сохранены в Google Таблицу.\nСледите за новостями для розыгрыша подарков! 🎁")
    elif csv_success:
        send_message(chat_id, f"🎉 {username_display}, тест завершён! Результаты сохранены.\nСледите за новостями для розыгрыша подарков! 🎁")
    else:
        send_message(chat_id, "⚠️ Тест завершен! Но возникла ошибка при сохранении.")

# === ОТПРАВКА CSV АДМИНУ ===
@bot.message_handler(commands=['results'])
def send_results(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        return
    try:
        # Отправляем резервный CSV файл
        with open("backup_results.csv", "rb") as f:
            bot.send_document(ADMIN_CHAT_ID, f, caption="📊 Резервные результаты пользователей")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибка при отправке файла: {e}")

# === FLASK WEBHOOK ===
@app.route(f'/webhook/{TOKEN}', methods=['POST'])
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

# === ЗАПУСК ===
if __name__ == "__main__":
    initialize_google_sheets()
    print("🚀 Бот запущен и готов к работе!")
    if 'RENDER' in os.environ:
        port = int(os.environ.get('PORT', 10000))
        try:
            bot.remove_webhook()
            time.sleep(1)
            webhook_url = f"https://musicbot-knqj.onrender.com/webhook/{TOKEN}"
            bot.set_webhook(url=webhook_url)
            print(f"✅ Вебхук установлен: {webhook_url}")
        except Exception as e:
            print(f"❌ Ошибка установки вебхука: {e}")
        app.run(host='0.0.0.0', port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
