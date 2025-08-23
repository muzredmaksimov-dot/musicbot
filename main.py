import os
import telebot
from telebot import types
from flask import Flask, request
import openpyxl

# === ТОКЕН БОТА ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === ХРАНИЛИЩЕ ДАННЫХ ===
user_metadata = {}        # chat_id -> {gender, age}
user_progress = {}        # chat_id -> текущий трек
user_rated_tracks = {}    # chat_id -> set(оценённых треков)

RESULTS_FILE = "results.xlsx"

# === СПИСОК ТРЕКОВ ===
track_files = [f"tracks/{str(i).zfill(3)}.mp3" for i in range(1, 31)]  # 001–030

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

# === ПРИВЕТСТВИЕ ===
@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    bot.send_message(
        chat_id,
        "Ты услышишь несколько коротких треков. Оцени каждый по шкале от 1 до 5:\n\n"
        "Но сначала давай познакомимся 🙂",
        reply_markup=kb
    )

# === КНОПКА НАЧАТЬ ===
@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    user_metadata[chat_id] = {}
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

# === ВЫБОР ПОЛА ===
def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужчина", callback_data="gender_Мужчина"),
        types.InlineKeyboardButton("Женщина", callback_data="gender_Женщина")
    )
    bot.send_message(chat_id, "Укажи свой пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['gender'] = c.data.split('_', 1)[1]
    bot.delete_message(chat_id, c.message.message_id)
    ask_age(chat_id)

# === ВЫБОР ВОЗРАСТА ===
def ask_age(chat_id):
    opts = ["до 24","25-34","35-44","45-54","55+"]
    kb = types.InlineKeyboardMarkup(row_width=3)
    for o in opts:
        kb.add(types.InlineKeyboardButton(o, callback_data=f"age_{o}"))
    bot.send_message(chat_id, "Укажи свой возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['age'] = c.data.split('_', 1)[1]
    bot.delete_message(chat_id, c.message.message_id)
    bot.send_message(chat_id, "Спасибо! 🎶 Сейчас начнём тест.")
    send_track(chat_id, user_progress[chat_id])

# === ОТПРАВКА ТРЕКА ===
def send_track(chat_id, track_id):
    if track_id >= len(track_files):
        bot.send_message(chat_id, "🎉 Тест завершён! Спасибо за участие.")
        return

    track_file = track_files[track_id]
    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(str(i), callback_data=f"rate_{track_id}_{i}"))

    if os.path.exists(track_file):
        with open(track_file, 'rb') as f:
            bot.send_audio(chat_id, f, reply_markup=kb)
    else:
        bot.send_message(chat_id, f"⚠️ Файл {track_file} не найден.")
        user_progress[chat_id] += 1
        send_track(chat_id, user_progress[chat_id])

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    _, track_id, rating = c.data.split('_')
    track_id = int(track_id)
    rating = int(rating)

    save_result(chat_id, track_id, rating)
    user_rated_tracks[chat_id].add(track_id)
    user_progress[chat_id] += 1

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    bot.edit_message_reply_markup(chat_id, c.message.message_id, reply_markup=None)
    bot.send_message(chat_id, f"✅ Оценка {rating} сохранена.")
    send_track(chat_id, user_progress[chat_id])

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

# === ЗАПУСК БОТА ===
if name == "__main__":
    init_excel()
    port = int(os.environ.get("PORT", 5000))
    bot.remove_webhook()
    bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/{TOKEN}")
    app.run(host="0.0.0.0", port=port)
