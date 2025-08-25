import telebot
from telebot import types
import os
import csv
from flask import Flask, send_file, request

# 🔑 Данные твоего бота
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_ID = 866964827  # Твой Telegram ID

bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)

# 📂 Константа для CSV
CSV_FILE = "backup_results.csv"

# 🎵 Треки (001–030)
tracks = [f"{i:03}.mp3" for i in range(1, 31)]

# 📊 Прогресс пользователей
user_progress = {}

# 📌 Сохраняем ответ в CSV
def save_answer_to_csv(user_data, track, rating):
    file_exists = os.path.exists(CSV_FILE)

    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            headers = ['User ID', 'Username', 'First Name', 'Gender', 'Age', 'Track', 'Rating']
            writer.writerow(headers)

        row = [
            user_data.get('user_id', ''),
            f"@{user_data['username']}" if user_data.get('username') else '',
            user_data.get('first_name', ''),
            user_data.get('gender', ''),
            user_data.get('age', ''),
            track,
            rating
        ]
        writer.writerow(row)

# 🚀 Старт
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    user_progress[user_id] = {
        "current_track": 0,
        "data": {
            "user_id": user_id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "gender": "M",      # 👈 пока фиксируем пол
            "age": "45-54"      # 👈 и возраст
        }
    }

    bot.send_message(
        user_id,
        "Добро пожаловать! 🎶\n\n"
        "Вы будете слушать фрагменты треков и оценивать их от 1 до 5.\n\n"
        "Оценки:\n"
        "1 – ужасно ❌\n"
        "2 – плохо 👎\n"
        "3 – нейтрально 😐\n"
        "4 – хорошо 👍\n"
        "5 – супер 🔥\n\n"
        "Поехали!"
    )
    send_next_track(user_id)

# ▶️ Отправка следующего трека
def send_next_track(user_id):
    progress = user_progress[user_id]
    track_index = progress['current_track']

    if track_index >= len(tracks):
        bot.send_message(user_id, "✅ Спасибо! Вы прослушали все треки.")
        return

    track_file = tracks[track_index]
    progress['current_track'] += 1

    # Отправляем трек
    with open(track_file, "rb") as audio:
        bot.send_audio(user_id, audio, caption=f"Трек {track_file}")

    # Кнопки для оценки
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("1", "2", "3", "4", "5")
    bot.send_message(user_id, "Ваша оценка:", reply_markup=markup)

# ⭐ Обработка оценки
@bot.message_handler(func=lambda message: message.text in ['1', '2', '3', '4', '5'])
def handle_rating(message):
    user_id = message.from_user.id
    rating = int(message.text)

    if user_id not in user_progress:
        return

    track_number = tracks[user_progress[user_id]['current_track'] - 1]
    user_data = user_progress[user_id]['data']

    # 💾 Сохраняем в CSV
    save_answer_to_csv(user_data, track_number, rating)

    # Следующий трек
    send_next_track(user_id)

# 📂 Отправка CSV по /results
@bot.message_handler(commands=['results'])
def send_results(message):
    if message.from_user.id == ADMIN_ID:
        if os.path.exists(CSV_FILE):
            bot.send_document(message.chat.id, open(CSV_FILE, "rb"))
        else:
            bot.send_message(message.chat.id, "❌ Файл пока не создан.")
    else:
        bot.send_message(message.chat.id, "⛔ У вас нет доступа к результатам.")

# Flask webhook
@server.route('/' + TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url='https://musicbot-knqj.onrender.com/' + TOKEN)
    return "!", 200

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
