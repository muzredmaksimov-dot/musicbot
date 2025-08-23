import os
import telebot
from telebot import types
from flask import Flask, request
import openpyxl
from datetime import datetime

# === ТОКЕН БОТА ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === ХРАНИЛИЩЕ ДАННЫХ ===
user_metadata = {}        # chat_id -> {gender, age}
user_progress = {}        # chat_id -> текущий индекс трека (0-29)
user_rated_tracks = {}    # chat_id -> set(оценённых треков)

RESULTS_FILE = "results.xlsx"

# === СПИСОК ТРЕКОВ ===
track_files = [f"{str(i).zfill(3)}.mp3" for i in range(1, 31)]  # 001.mp3, 002.mp3... 030.mp3

# === ИНИЦИАЛИЗАЦИЯ EXCEL ===
def init_excel():
    if not os.path.exists(RESULTS_FILE):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["chat_id", "gender", "age", "track", "rating", "timestamp"])
        wb.save(RESULTS_FILE)

def save_result(chat_id, track_filename, rating):
    try:
        wb = openpyxl.load_workbook(RESULTS_FILE)
        ws = wb.active
        gender = user_metadata.get(chat_id, {}).get("gender", "unknown")
        age = user_metadata.get(chat_id, {}).get("age", "unknown")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append([chat_id, gender, age, track_filename, rating, timestamp])
        wb.save(RESULTS_FILE)
    except Exception as e:
        print(f"Ошибка сохранения в Excel: {e}")

# === ПРОВЕРКА РЕГИСТРАЦИИ ===
def is_user_registered(chat_id):
    return chat_id in user_metadata

# === ОБРАБОТКА КОМАНДЫ /START ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    
    if is_user_registered(chat_id):
        # Пользователь уже зарегистрирован - продолжаем тест
        current_track = user_progress.get(chat_id, 0)
        if current_track < len(track_files):
            bot.send_message(chat_id, "Продолжим тест! 🎵")
            send_track(chat_id, current_track)
        else:
            bot.send_message(chat_id, "🎉 Вы уже завершили тест! Спасибо за участие.")
        return

    # Новый пользователь
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    bot.send_message(
        chat_id,
        "Вы услышите 30 коротких треков. Оцените каждый по шкале от 1 до 5:\n\n"
        "1 - Совсем не нравится\n"
        "2 - Не нравится\n" 
        "3 - Нейтрально\n"
        "4 - Нравится\n"
        "5 - Очень нравится\n\n"
        "Но сначала давайте познакомимся 🙂",
        reply_markup=kb
    )

# === КНОПКА НАЧАТЬ ===
@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    
    user_metadata[chat_id] = {}
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

# === ВЫБОР ПОЛА ===
def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_Мужской"),
        types.InlineKeyboardButton("Женский", callback_data="gender_Женский")
    )
    bot.send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['gender'] = c.data.split('_', 1)[1]
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    ask_age(chat_id)

# === ВЫБОР ВОЗРАСТА ===
def ask_age(chat_id):
    opts = ["до 24", "25-34", "35-44", "45-54", "55+"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(o, callback_data=f"age_{o}") for o in opts]
    kb.add(*buttons)
    bot.send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['age'] = c.data.split('_', 1)[1]
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    bot.send_message(chat_id, "Спасибо! 🎶 Сейчас начнем тест.")
    send_track(chat_id, user_progress[chat_id])

# === ОТПРАВКА ТРЕКА ===
def send_track(chat_id, track_index):
    # Проверка завершения теста
    if track_index >= len(track_files):
        bot.send_message(chat_id, "🎉 Тест завершён! Спасибо за участие.")
        return
    
    track_filename = track_files[track_index]
    track_path = os.path.join("tracks", track_filename)
    
    # Создаем клавиатуру с оценками
    kb = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f"rate_{track_index}_{i}") for i in range(1, 6)]
    kb.add(*buttons)
    
    # Отправляем трек
    if os.path.exists(track_path):
        try:
            with open(track_path, 'rb') as audio_file:
                bot.send_message(chat_id, f"🎵 Трек {track_index + 1} из {len(track_files)}")
                bot.send_audio(chat_id, audio_file, title=f"Трек {track_index + 1}", reply_markup=kb)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка при отправке трека: {e}")
            # Пропускаем проблемный трек
            user_progress[chat_id] += 1
            send_track(chat_id, user_progress[chat_id])
    else:
        bot.send_message(chat_id, f"⚠️ Трек {track_filename} не найден.")
        # Пропускаем отсутствующий трек
        user_progress[chat_id] += 1
        send_track(chat_id, user_progress[chat_id])

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    data_parts = c.data.split('_')
    
    if len(data_parts) != 3:
        return
    
    track_index = int(data_parts[1])
    rating = int(data_parts[2])
    
    # Сохраняем результат с правильным именем файла
    save_result(chat_id, track_files[track_index], rating)
    user_rated_tracks[chat_id].add(track_index)
    
    # Увеличиваем прогресс
    user_progress[chat_id] += 1
    
    # Удаляем сообщение с кнопками
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    
    # Отправляем следующий трек
    send_track(chat_id, user_progress[chat_id])

# === FLASK WEBHOOK ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    return "Bad Request", 400

@app.route("/", methods=["GET"])
def index():
    return "Музыкальный тест бот работает! 🎵", 200

# === ЗАПУСК ===
if name == "__main__":
    init_excel()
    port = int(os.environ.get("PORT", 5000))
    
    # Настройка webhook только для продакшена
    if not os.environ.get("DEBUG"):
        bot.remove_webhook()
        bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/{TOKEN}")
    
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG"))
