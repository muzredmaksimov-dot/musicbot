import telebot
from telebot import types
import openpyxl
import os
import threading
from flask import Flask

# === Настройки ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
bot = telebot.TeleBot(TOKEN)

FILE_NAME = "results.xlsx"

# Проверяем, есть ли файл, если нет — создаём
if not os.path.exists(FILE_NAME):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Результаты"
    ws.append(["ChatID", "Пол", "Возраст", "Оценка"])
    wb.save(FILE_NAME)

# Хранилище для прогресса
user_metadata = {}
user_progress = {}
user_rated_tracks = {}

# === Приветствие ===
@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        "👋 Добро пожаловать в музыкальный тест!\n\n"
        "Ты услышишь несколько коротких треков. "
        "Оцени каждый по шкале от 1 до 5:\n\n"
        "1. Не нравится\n"
        "2. Раньше нравилась, но надоела\n"
        "3. Нейтрально\n"
        "4. Нравится\n"
        "5. Любимая песня\n\n"
        "Но сначала давай познакомимся 🙂"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    user_metadata[chat_id] = None

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def handle_start_button(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    user_metadata[chat_id] = {}
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

# === Пол ===
def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_M"),
        types.InlineKeyboardButton("Женский", callback_data="gender_F"),
    )
    bot.send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gender_"))
def handle_gender(call):
    chat_id = call.message.chat.id
    gender = "М" if call.data == "gender_M" else "Ж"
    user_metadata[chat_id]["gender"] = gender
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    ask_age(chat_id)

# === Возраст ===
def ask_age(chat_id):
    bot.send_message(chat_id, "Введите ваш возраст цифрами:")

@bot.message_handler(func=lambda message: message.chat.id in user_metadata and "gender" in user_metadata[message.chat.id] and "age" not in user_metadata[message.chat.id])
def handle_age(message):
    chat_id = message.chat.id
    if not message.text.isdigit():
        bot.send_message(chat_id, "Пожалуйста, введите возраст цифрами 🙂")
        return
    age = int(message.text)
    user_metadata[chat_id]["age"] = age
    bot.send_message(chat_id, "Спасибо! Теперь начнем тест 🎧")
    ask_rating(chat_id)

# === Оценка ===
def ask_rating(chat_id):
    kb = types.InlineKeyboardMarkup()
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените этот трек:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def handle_rating(call):
    chat_id = call.message.chat.id
    rating = int(call.data.split("_")[1])

    gender = user_metadata[chat_id].get("gender", "")
    age = user_metadata[chat_id].get("age", "")

    wb = openpyxl.load_workbook(FILE_NAME)
    ws = wb.active
    ws.append([chat_id, gender, age, rating])
    wb.save(FILE_NAME)

    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    bot.send_message(chat_id, f"Ваша оценка: {rating}")

    ask_rating(chat_id)  # пока зациклено, можно потом ограничить

# === Flask сервер для Render ===
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.polling(none_stop=True, interval=0)
