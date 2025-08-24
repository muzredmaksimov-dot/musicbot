import telebot
from telebot import types
import os
import pandas as pd
from flask import Flask, request

# === Настройки ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_ID = 866964827
bot = telebot.TeleBot(TOKEN)

# Flask для Render
app = Flask(__name__)

# === Excel файл для результатов ===
RESULTS_FILE = "results.xlsx"

if not os.path.exists(RESULTS_FILE):
    df = pd.DataFrame(columns=["user_id", "track", "rating"])
    df.to_excel(RESULTS_FILE, index=False)

# === Треки ===
TRACKS = [f"{str(i).zfill(3)}.mp3" for i in range(1, 31)]
user_progress = {}

# === Команда старт ===
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    user_progress[user_id] = 0

    bot.send_message(
        user_id,
        "Привет! 👋\n"
        "Сейчас будем слушать треки.\n"
        "Оцени каждый по шкале от 1 до 5:\n\n"
        "1 — очень плохо \n"
        "2 — плохо \n"
        "3 — нормально \n"
        "4 — хорошо \n"
        "5 — супер! \n\n"
        "Поехали!"
    )
    send_next_track(user_id)

# === Отправка следующего трека ===
def send_next_track(user_id):
    progress = user_progress.get(user_id, 0)

    if progress >= len(TRACKS):
        bot.send_message(user_id, "Тест завершён ✅ Спасибо за участие!")
        return

    track_file = TRACKS[progress]
    if os.path.exists(track_file):
        with open(track_file, "rb") as f:
            msg = bot.send_audio(user_id, f, title=track_file)

        # Кнопки для оценки
        markup = types.InlineKeyboardMarkup()
        buttons = [
            types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}")
            for i in range(1, 6)
        ]
        markup.add(*buttons)

        bot.send_message(user_id, "Твоя оценка?", reply_markup=markup)

        # Сохраняем id сообщения с треком, чтобы потом удалить
        user_progress[user_id] = progress
        bot.user_data = getattr(bot, "user_data", {})
        bot.user_data[user_id] = msg.message_id
    else:
        bot.send_message(user_id, f"Файл {track_file} не найден.")
        user_progress[user_id] += 1
        send_next_track(user_id)

# === Обработка оценки ===
@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def callback_rate(call):
    user_id = call.message.chat.id
    rating = int(call.data.split("_")[1])
    progress = user_progress.get(user_id, 0)
    track = TRACKS[progress]

    # Сохраняем в Excel
    df = pd.read_excel(RESULTS_FILE)
    new_row = pd.DataFrame([[user_id, track, rating]], columns=df.columns)
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel(RESULTS_FILE, index=False)

    # Удаляем сообщение с треком и кнопками
    try:
        bot.delete_message(user_id, bot.user_data[user_id])
        bot.delete_message(user_id, call.message.message_id)
    except:
        pass

    # Следующий трек
    user_progress[user_id] += 1
    send_next_track(user_id)

# === Отправка файла results.xlsx админу ===
@bot.message_handler(commands=["results"])
def send_results(message):
    if message.chat.id == ADMIN_ID:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, "rb") as f:
                bot.send_document(message.chat.id, f)
        else:
            bot.send_message(message.chat.id, "Файл результатов пока отсутствует.")
    else:
        bot.send_message(message.chat.id, "У вас нет доступа к этой команде.")

# === Flask webhook ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.stream.read().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!"

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/{TOKEN}")
    app.run(host="0.0.0.0", port=10000)
