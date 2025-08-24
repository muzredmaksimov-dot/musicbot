import telebot
from telebot import types
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

# === Настройки ===
TOKEN = "ТВОЙ_ТОКЕН"
AUDIO_FOLDER = "audio"
SPREADSHEET_NAME = "music_testing"
WORKSHEET_NAME = "track_list"
PROGRESS_FILE = "progress.csv"

# === Google Sheets авторизация ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).worksheet(WORKSHEET_NAME)

# === Подготовка CSV для прогресса ===
if not os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["chat_id", "track_number", "score"])

# === Загружаем список треков ===
with open("track_list.csv", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    track_data = {row["track_number"]: row["title"] for row in reader}

# === Бот ===
bot = telebot.TeleBot(TOKEN)

# === Словари состояния ===
user_progress = {}     # какой трек у кого сейчас
user_rated_tracks = {} # что уже оценено
user_metadata = {}     # пол/возраст
last_audios = {}       # id последнего аудио

# === Вспомогалки ===
def save_progress_csv(chat_id, track_number, score):
    """Сохраняем каждую оценку в CSV"""
    with open(PROGRESS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([chat_id, track_number, score])

def upload_results_to_google():
    """После завершения теста переносим CSV в Google Sheets"""
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)

    if not data:
        return

    headers = ["chat_id", "track_number", "score"]
    sheet.clear()
    sheet.append_row(headers)
    for row in data:
        sheet.append_row([row["chat_id"], row["track_number"], row["score"]])

# === /results команда ===
@bot.message_handler(commands=["results"])
def send_results(m):
    chat_id = m.chat.id
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "rb") as f:
            bot.send_document(chat_id, f)
    else:
        bot.send_message(chat_id, "Результаты пока пусты.")

# === Опрос перед тестом ===
@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    welcome_text = (
        "Ты услышишь несколько коротких треков. "
        "Оцени каждый по шкале от 1 до 5.\n\n"
        "Но сначала давай познакомимся 🙂"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))
    bot.send_message(chat_id, welcome_text, reply_markup=kb)
    user_metadata[chat_id] = None

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def handle_start_button(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)

    user_metadata[chat_id] = {}
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_M"),
        types.InlineKeyboardButton("Женский", callback_data="gender_F"),
    )
    bot.send_message(chat_id, "Укажи свой пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id] = {"gender": c.data.split("_", 1)[1]}
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass
    ask_age(chat_id)

def ask_age(chat_id):
    opts = ["до 24", "25-34", "35-44", "45-54", "55+"]
    kb = types.InlineKeyboardMarkup(row_width=3)
    for o in opts:
        kb.add(types.InlineKeyboardButton(o, callback_data=f"age_{o}"))
    bot.send_message(chat_id, "Укажи свой возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]["age"] = c.data.split("_", 1)[1]
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    user_progress[chat_id] = 1
    bot.send_message(
        chat_id,
        "Оцени трек от 1 до 5:\n\n"
        "1 — Не нравится\n"
        "2 — Раньше нравилась, но надоела\n"
        "3 — Нейтрально\n"
        "4 — Нравится\n"
        "5 — Любимая песня",
    )
    send_next_track(chat_id)

# === Отправка треков ===
def send_next_track(chat_id):
    n = user_progress.get(chat_id, 1)
    path = os.path.join(AUDIO_FOLDER, f"{n:03}.mp3")
    if not os.path.exists(path):
        bot.send_message(chat_id, "🎉 Тест завершён! Сохраняю результаты...")
        upload_results_to_google()
        return

    with open(path, "rb") as f:
        m = bot.send_audio(chat_id, f, caption=f"Трек №{n}")
        last_audios[chat_id] = m.message_id

    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rate(c):
    chat_id = c.message.chat.id
    n = user_progress.get(chat_id, 1)

    if n in user_rated_tracks[chat_id]:
        bot.answer_callback_query(c.id, "Уже оценено", show_alert=True)
        return

    score = c.data.split("_", 1)[1]
    save_progress_csv(chat_id, n, score)
    user_rated_tracks[chat_id].add(n)

    if chat_id in last_audios:
        try:
            bot.delete_message(chat_id, last_audios[chat_id])
        except Exception:
            pass

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    user_progress[chat_id] = n + 1
    send_next_track(chat_id)

# === Фолбэк ===
@bot.message_handler(func=lambda m: True)
def fallback(m):
    bot.send_message(m.chat.id, "Нажмите /start")

# === Старт ===
bot.polling()
