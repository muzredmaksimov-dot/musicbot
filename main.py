import telebot
import os
import datetime
from flask import Flask, request
from openpyxl import Workbook, load_workbook

TOKEN = os.getenv("BOT_TOKEN")  # твой токен из переменных окружения
bot = telebot.TeleBot(TOKEN)

WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"

app = Flask(__name__)

# ======= Плейлист =======
TRACKS = [f"{str(i).zfill(3)}.mp3" for i in range(1, 31)]

# ======= Excel подключение =======
RESULT_FILE = "results.xlsx"

if not os.path.exists(RESULT_FILE):
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["user_id", "track", "rating", "timestamp"])
    wb.save(RESULT_FILE)


def save_result(user_id, track_id, rating):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wb = load_workbook(RESULT_FILE)
    ws = wb.active
    ws.append([user_id, track_id, rating, timestamp])
    wb.save(RESULT_FILE)


# ======= Хранилище прогресса =======
user_progress = {}       # chat_id -> текущий индекс
user_rated_tracks = {}   # chat_id -> множество оценённых треков


# ======= Отправка трека =======
def send_track(chat_id, track_index):
    if track_index < len(TRACKS):
        filename = TRACKS[track_index]
        with open(f"tracks/{filename}", "rb") as f:
            markup = telebot.types.InlineKeyboardMarkup()
            buttons = [
                telebot.types.InlineKeyboardButton(str(i), callback_data=f"rate_{track_index}_{i}")
                for i in range(1, 6)
            ]
            markup.row(*buttons)
            bot.send_message(chat_id, f"🎶 Трек {track_index+1} из {len(TRACKS)}")
            bot.send_audio(chat_id, f, title=filename, reply_markup=markup)
    else:
        bot.send_message(chat_id, "🎉 Спасибо! Ты оценил все треки.")


# ======= Старт =======
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user_progress[chat_id] = 0
    user_rated_tracks[chat_id] = set()

    bot.send_message(chat_id, "Привет! 👋 Давай начнём тест.\n\n"
                              "Вот шкала оценок:\n"
                              "1️⃣ — совсем не нравится\n"
                              "2️⃣ — скорее не нравится\n"
                              "3️⃣ — нейтрально\n"
                              "4️⃣ — нравится\n"
                              "5️⃣ — очень нравится ❤️")

    send_track(chat_id, 0)


# ======= Обработка оценки =======
@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    _, track_id, rating = c.data.split("_")
    track_id = int(track_id)
    rating = int(rating)

    save_result(chat_id, TRACKS[track_id], rating)
    user_rated_tracks[chat_id].add(track_id)
    user_progress[chat_id] += 1

    # удаляем сообщение с кнопками
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    # отправляем следующий трек
    send_track(chat_id, user_progress[chat_id])


# ======= Flask webhook =======
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200


@app.route("/", methods=["GET", "HEAD"])
def index():
    return "Bot is running!", 200


if name == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=10000)
