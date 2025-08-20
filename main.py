import telebot
from telebot import types
import openpyxl
import os

# === Токен бота ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
bot = telebot.TeleBot(TOKEN)

# === ID администратора (твой) ===
ADMIN_ID = 866964827

# === Папка с треками ===
TRACKS_DIR = "tracks"
TRACK_LIST = sorted([f for f in os.listdir(TRACKS_DIR) if f.endswith(".mp3")])

# === Хранилище данных пользователей ===
user_metadata = {}       # {chat_id: {"gender": "..", "age": ".."}}
user_progress = {}       # {chat_id: индекс трека}
user_rated_tracks = {}   # {chat_id: set(track_id)}

# === Файл для сохранения результатов ===
RESULT_FILE = "results.xlsx"

# Создаём Excel, если его нет
if not os.path.exists(RESULT_FILE):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["ChatID", "Gender", "Age", "TrackID", "Rating"])
    wb.save(RESULT_FILE)


# === Сохранение ответа ===
def save_result(chat_id, gender, age, track_id, rating):
    wb = openpyxl.load_workbook(RESULT_FILE)
    ws = wb.active
    ws.append([chat_id, gender, age, track_id, rating])
    wb.save(RESULT_FILE)


# === Приветствие ===
@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id
    remove_kb = types.ReplyKeyboardRemove()

    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)
    bot.send_message(
        chat_id,
        "Ты услышишь несколько коротких треков. Оцени каждый по шкале от 1 до 5:\n\n"
        "Но сначала давай познакомимся 🙂"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    user_metadata[chat_id] = None


# === Кнопка «Начать» ===
@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def handle_start_button(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    ask_gender(chat_id)


def ask_gender(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("👨 Мужчина", "👩 Женщина")
    bot.send_message(chat_id, "Укажи свой пол:", reply_markup=kb)


@bot.message_handler(func=lambda message: message.text in ["👨 Мужчина", "👩 Женщина"])
def handle_gender(message):
    chat_id = message.chat.id
    gender = "M" if "Мужчина" in message.text else "F"
    user_metadata[chat_id] = {"gender": gender}
    ask_age(chat_id)


def ask_age(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("18-24", "25-34", "35-44", "45+")
    bot.send_message(chat_id, "Выбери свой возраст:", reply_markup=kb)


@bot.message_handler(func=lambda message: message.text in ["18-24", "25-34", "35-44", "45+"])
def handle_age(message):
    chat_id = message.chat.id
    user_metadata[chat_id]["age"] = message.text
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    bot.send_message(chat_id, "✅ Отлично! Начнём тест.", reply_markup=types.ReplyKeyboardRemove())
    send_track(chat_id)


# === Отправка трека ===
def send_track(chat_id):
    index = user_progress[chat_id]
    if index >= len(TRACK_LIST):
        bot.send_message(chat_id, "🎉 Спасибо! Ты прошёл тест.")
        return

    track_file = TRACK_LIST[index]
    track_path = os.path.join(TRACKS_DIR, track_file)

    with open(track_path, "rb") as f:
        bot.send_audio(chat_id, f, title=f"Трек {index+1}")

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("1. Не нравится", callback_data=f"rate_{index}_1"),
        types.InlineKeyboardButton("2. Раньше нравилась, но надоела", callback_data=f"rate_{index}_2")
    )
    kb.add(
        types.InlineKeyboardButton("3. Нейтрально", callback_data=f"rate_{index}_3"),
        types.InlineKeyboardButton("4. Нравится", callback_data=f"rate_{index}_4")
    )
    kb.add(
        types.InlineKeyboardButton("5. Любимая песня", callback_data=f"rate_{index}_5")
    )

    bot.
