import os
import telebot
from telebot import types
from flask import Flask, request
import openpyxl

# === ТВОЙ ТОКЕН ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === ХРАНИЛИЩЕ ДАННЫХ ===
user_metadata = {}        # chat_id -> {gender, age}
user_progress = {}        # chat_id -> текущий трек
user_rated_tracks = {}    # chat_id -> set(оценённых треков)

RESULTS_FILE = "results.xlsx"

# === ИНИЦИАЛИЗАЦИЯ EXCEL ===
def init_excel():
    if not os.path.exists(RESULTS_FILE):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["chat_id", "gender", "age", "track_id", "rating"])
        wb.save(RESULTS_FILE)

def save_result(chat_id, track_id, rating):
    wb = openpyxl.load_workbook(RESULTS_FILE)
    ws = wb.active
    gender = user_metadata.get(chat_id, {}).get("gender", "")
    age = user_metadata.get(chat_id, {}).get("age", "")
    ws.append([chat_id, gender, age, track_id, rating])
    wb.save(RESULTS_FILE)

# === ОПРОС ПЕРЕД ТЕСТОМ ===
@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id

    # Убираем клавиатуру, если была
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    # Сообщение с кнопкой
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    bot.send_message(
        chat_id,
        "Ты услышишь несколько коротких треков. Оцени каждый по шкале от 1 до 5:\n\n"
        "Но сначала давай познакомимся 🙂",
        reply_markup=kb
    )

# === ОБРАБОТКА КНОПКИ "НАЧАТЬ" ===
@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    user_metadata[chat_id] = {}
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

# === ВОПРОС ПРО ПОЛ ===
def ask_gender(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("Мужчина", "Женщина")
    bot.send_message(chat_id, "Укажи свой пол:", reply_markup=kb)

@bot.message_handler(func=lambda msg: msg.chat.id in user_metadata and "gender" not in user_metadata[msg.chat.id])
def handle_gender(message):
    chat_id = message.chat.id
    user_metadata[chat_id]["gender"] = message.text
    ask_age(chat_id)

# === ВОПРОС ПРО ВОЗРАСТ ===
def ask_age(chat_id):
    kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "Теперь укажи свой возраст:", reply_markup=kb)

@bot.message_handler(func=lambda msg: msg.chat.id in user_metadata and "gender" in user_metadata[msg.chat.id] and "age" not in user_metadata[msg.chat.id])
def handle_age(message):
    chat_id = message.chat.id
    if not message.text.isdigit():
        bot.send_message(chat_id, "Пожалуйста, введи число 🙂")
        return
    user_metadata[chat_id]["age"] = int(message.text)
    bot.send_message(chat_id, "Спасибо! 🎶 Сейчас начнём тест.")

    # тут можно запускать логику показа треков
    # send_track(chat_id, user_progress[chat_id])

# === ОБРАБОТКА ОЦЕНКИ ТРЕКА ===
@bot.message_handler(func=lambda msg: msg.text in ["1", "2", "3", "4", "5"])
def handle_rating(message):
    chat_id = message.chat.id
    rating = int(message.text)
    track_id = user_progress.get(chat_id, 0)

    if chat_id in user_metadata:
        save_result(chat_id, track_id, rating)
        user_rated_tracks[chat_id].add(track_id)
        user_progress[chat_id] += 1
        bot.send_message(chat_id, f"✅ Оценка {rating} сохранена.")

        # можно вызывать следующий трек
        # send_track(chat_id, user_progress[chat_id])

# === FLASK ДЛЯ WEBHOOK ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает на Render 🚀", 200

if name == "__main__":
    init_excel()
    port = int(os.environ.get("PORT", 5000))
    bot.remove_webhook()
    bot.set_webhook(url=f"https://ТВОЙ-РЕНДЕР-URL.onrender.com/{TOKEN}")
    app.run(host="0.0.0.0", port=port)
