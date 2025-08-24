import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from telebot import types

# === Настройки ===
TOKEN = 'ТОКЕН_БОТА'
AUDIO_FOLDER = 'audio'
SPREADSHEET_NAME = 'music_testing'
WORKSHEET_NAME = 'track_list'
LOCAL_RESULTS = 'results.csv'

# === Google Sheets авторизация ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).worksheet(WORKSHEET_NAME)

# === Загрузка CSV-файла с треками ===
with open('track_list.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    track_data = {row['track_number']: row['title'] for row in reader}

# === Бот ===
bot = telebot.TeleBot(TOKEN)

# === Словари состояния ===
user_progress     = {}   # какой трек у кого сейчас
user_rated_tracks = {}   # что уже оценено
user_metadata     = {}   # пол/возраст
user_column       = {}   # столбец для каждого пользователя
last_audios       = {}   # message_id последнего аудио

# === Локальный CSV для прогресса ===
if not os.path.exists(LOCAL_RESULTS):
    with open(LOCAL_RESULTS, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["chat_id", "track", "score", "gender", "age"])

def save_progress_csv(chat_id, track, score):
    gender = user_metadata.get(chat_id, {}).get("gender", "")
    age = user_metadata.get(chat_id, {}).get("age", "")
    with open(LOCAL_RESULTS, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([chat_id, track, score, gender, age])

# === Вспомогалки ===
def insert_values_into_column(sheet, col, values):
    for i, v in enumerate(values, start=1):
        sheet.update_cell(i, col, v)

# === Опрос перед тестом ===
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    welcome_text = (
        "Ты услышишь несколько коротких треков. Оцени каждый по шкале от 1 до 5:\n\n"
        "Но сначала давай познакомимся 🙂"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))

    bot.send_message(chat_id, welcome_text, reply_markup=kb)
    user_metadata[chat_id] = None

@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)

    user_metadata[chat_id] = {}
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

# === Гендер и возраст ===
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
    bot.delete_message(chat_id, c.message.message_id)
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
    bot.delete_message(chat_id, c.message.message_id)

    # выделяем столбец
    headers = sheet.row_values(1)
    col = len(headers) + 1
    user_column[chat_id] = col

    insert_values_into_column(sheet, col, [
        user_metadata[chat_id]['gender'],
        user_metadata[chat_id]['age']
    ])

    user_progress[chat_id] = 1
    bot.send_message(chat_id, "Оцени трек от 1 до 5:\n\n1 — Не нравится\n2 — Раньше нравилась, но надоела\n3 — Нейтрально\n4 — Нравится\n5 — Любимая песня")
    send_next_track(chat_id)

# === Отправка и оценка треков ===
def send_next_track(chat_id):
    n = user_progress.get(chat_id,1)
    path = os.path.join(AUDIO_FOLDER,f"{n:03}.mp3")
    if not os.path.exists(path):
        bot.send_message(chat_id, "🎉 Тест завершён! Результаты будут перенесены в Google Sheets.")

        # Переносим локальные результаты в таблицу
        try:
            with open(LOCAL_RESULTS, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = [r for r in reader if str(r["chat_id"]) == str(chat_id)]
                col = user_column.get(chat_id)
                if col:
                    for r in rows:
                        sheet.update_cell(int(r["track"])+2, col, r["score"])
        except Exception as e:
            bot.send_message(chat_id, f"⚠️ Ошибка при переносе в Google Sheets: {e}")
        return

    with open(path,'rb') as f:
        m = bot.send_audio(chat_id,f,caption=f"Трек №{n}")
        last_audios[chat_id] = m.message_id

    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1,6):
        kb.add(types.InlineKeyboardButton(str(i),callback_data=f"rate_{i}"))
    bot.send_message(chat_id,"Оцените:",reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rate(c):
    chat_id = c.message.chat.id
    n = user_progress.get(chat_id,1)
    if n in user_rated_tracks[chat_id]:
        bot.answer_callback_query(c.id,"Уже оценено",show_alert=True)
        return

    score = c.data.split('_',1)[1]
    save_progress_csv(chat_id, n, score)   # сохраняем сразу в CSV

    user_rated_tracks[chat_id].add(n)
    try: bot.delete_message(chat_id, last_audios[chat_id])
    except: pass
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass

    user_progress[chat_id] = n+1
    send_next_track(chat_id)

# === Скачивание результатов ===
@bot.message_handler(commands=["results"])
def send_results(message):
    chat_id = message.chat.id
    if str(chat_id) != "ТВОЙ_CHAT_ID_АДМИНА":
        bot.send_message(chat_id, "⛔ Доступ запрещён")
        return

    if os.path.exists(LOCAL_RESULTS):
        with open(LOCAL_RESULTS, "rb") as f:
            bot.send_document(chat_id, f)
    else:
        bot.send_message(chat_id, "Файл с результатами ещё не создан.")

# === Фоллбек ===
@bot.message_handler(func=lambda m: True)
def fallback(m):
    bot.send_message(m.chat.id,"Нажмите /start")

bot.polling()
