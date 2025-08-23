import os
import telebot
import sqlite3
import time
from telebot import types
from flask import Flask, request
from datetime import datetime

# === НАСТРОЙКИ ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_CHAT_ID = "866964827"  # ID администратора: Андрей (@andrei_jose01)
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (chat_id INTEGER PRIMARY KEY, 
                  username TEXT, 
                  first_name TEXT, 
                  last_name TEXT, 
                  gender TEXT, 
                  age TEXT, 
                  registration_date TEXT,
                  completed INTEGER DEFAULT 0)''')
    
    # Таблица оценок
    c.execute('''CREATE TABLE IF NOT EXISTS ratings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  track_number INTEGER,
                  rating INTEGER,
                  timestamp TEXT,
                  FOREIGN KEY(chat_id) REFERENCES users(chat_id))''')
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

def save_user(chat_id, username, first_name, last_name, gender, age):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    if c.fetchone() is None:
        c.execute("INSERT INTO users (chat_id, username, first_name, last_name, gender, age, registration_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (chat_id, username, first_name, last_name, gender, age, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    else:
        c.execute("UPDATE users SET username=?, first_name=?, last_name=?, gender=?, age=? WHERE chat_id=?",
                  (username, first_name, last_name, gender, age, chat_id))
    
    conn.commit()
    conn.close()

def save_rating(chat_id, track_number, rating):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM ratings WHERE chat_id = ? AND track_number = ?", (chat_id, track_number))
    if c.fetchone() is None:
        c.execute("INSERT INTO ratings (chat_id, track_number, rating, timestamp) VALUES (?, ?, ?, ?)",
                  (chat_id, track_number, rating, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        c.execute("SELECT COUNT(*) FROM ratings WHERE chat_id = ?", (chat_id,))
        rated_count = c.fetchone()[0]
        
        if rated_count >= 30:
            c.execute("UPDATE users SET completed = 1 WHERE chat_id = ?", (chat_id,))
            try:
                c.execute("SELECT username, first_name FROM users WHERE chat_id = ?", (chat_id,))
                user_info = c.fetchone()
                username = user_info[0] or user_info[1] or "Неизвестный"
                bot.send_message(ADMIN_CHAT_ID, f"🎉 Пользователь {username} завершил тест!")
            except:
                pass
    
    conn.commit()
    conn.close()

def get_user_progress(chat_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM ratings WHERE chat_id = ?", (chat_id,))
    progress = c.fetchone()[0]
    
    conn.close()
    return progress

def has_user_completed(chat_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT completed FROM users WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    
    conn.close()
    return result and result[0] == 1

# === СПИСОК ТРЕКОВ ===
track_numbers = [f"{str(i).zfill(3)}" for i in range(1, 31)]

# === ОБРАБОТКА КОМАНД ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user = message.from_user
    
    save_user(chat_id, user.username, user.first_name, user.last_name, "", "")
    
    if has_user_completed(chat_id):
        bot.send_message(chat_id, "🎉 Вы уже завершили тест! Спасибо за участие.")
        return
    
    progress = get_user_progress(chat_id)
    
    if progress > 0:
        bot.send_message(chat_id, f"Продолжим тест! 🎵 (Прогресс: {progress}/30)")
        send_track(chat_id, progress)
    else:
        remove_kb = types.ReplyKeyboardRemove()
        bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
        
        welcome_text = (
            f"Привет, {user.first_name}! 🎵\n\n"
            "Вы прослушаете 30 музыкальных треков и оцените каждый по шкале от 1 до 5:\n\n"
            "1 ★ - Совсем не нравится\n"
            "2 ★★ - Не нравится\n" 
            "3 ★★★ - Нейтрально\n"
            "4 ★★★★ - Нравится\n"
            "5 ★★★★★ - Очень нравится\n\n"
            "Тест проводится вслепую - вы не будете знать названия треков.\n\n"
            "🎁 После теста среди всех участников будет розыгрыш подарков!"
        )
        
        bot.send_message(chat_id, welcome_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    
    ask_gender(chat_id)

# === ВЫБОР ПОЛА И ВОЗРАСТА ===
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
    gender = c.data.split('_', 1)[1]
    
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("UPDATE users SET gender = ? WHERE chat_id = ?", (gender, chat_id))
    conn.commit()
    conn.close()
    
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    
    ask_age(chat_id)

def ask_age(chat_id):
    opts = ["до 24", "25-34", "35-44", "45-54", "55+"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(o, callback_data=f"age_{o}") for o in opts]
    kb.add(*buttons)
    bot.send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    age = c.data.split('_', 1)[1]
    
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("UPDATE users SET age = ? WHERE chat_id = ?", (age, chat_id))
    conn.commit()
    conn.close()
    
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT username, first_name FROM users WHERE chat_id = ?", (chat_id,))
    user_info = cur.fetchone()
    conn.close()
    
    username_display = f"@{user_info[0]}" if user_info[0] else user_info[1]
    
    bot.send_message(
        chat_id, 
        f"Спасибо, {username_display}! 🎶\n\n"
        "Теперь начнем слепой тест. Удачи в розыгрыше! 🎁"
    )
    
    send_track(chat_id, 0)

# === ОТПРАВКА ТРЕКА ===
def send_track(chat_id, track_index):
    if track_index >= len(track_numbers):
        conn = sqlite3.connect('database.db')
        cur = conn.cursor()
        cur.execute("SELECT username, first_name FROM users WHERE chat_id = ?", (chat_id,))
        user_info = cur.fetchone()
        conn.close()
        
        username_display = f"@{user_info[0]}" if user_info[0] else user_info[1]
        
        bot.send_message(
            chat_id, 
            f"🎉 {username_display}, тест завершён! Спасибо за участие!\n\n"
            "Результаты сохранены. Следите за новостями для розыгрыша подарков! 🎁"
        )
        return
    
    track_number = track_numbers[track_index]
    track_filename = f"{track_number}.mp3"
    track_path = os.path.join("tracks", track_filename)
    
    kb = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f"rate_{track_number}_{i}") for i in range(1, 6)]
    kb.add(*buttons)
    
    if os.path.exists(track_path):
        try:
            with open(track_path, 'rb') as audio_file:
                bot.send_message(chat_id, f"🎵 Трек {track_index + 1}/30")
                bot.send_audio(chat_id, audio_file, title=f"Трек {track_number}", reply_markup=kb)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка при отправке трека: {e}")
            send_track(chat_id, track_index + 1)
    else:
        bot.send_message(chat_id, f"⚠️ Трек {track_number} не найден.")
        send_track(chat_id, track_index + 1)

# === ОБРАБОТКА ОЦЕНКИ ===
user_rating_time = {}

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    data_parts = c.data.split('_')
    
    if len(data_parts) != 3:
        return
    
    track_number = data_parts[1]
    rating = int(data_parts[2])
    
    current_time = time.time()
    last_rating_time = user_rating_time.get(chat_id, 0)
    
    if current_time - last_rating_time < 5:
        bot.answer_callback_query(c.id, "Пожалуйста, прослушайте трек перед оценкой")
        return
    
    user_rating_time[chat_id] = current_time
    
    track_num = int(track_number)
    save_rating(chat_id, track_num, rating)
    
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    
    next_track_index = get_user_progress(chat_id)
    send_track(chat_id, next_track_index)

# === СЛУЖЕБНЫЕ КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА ===
@bot.message_handler(commands=['stats'])
def show_stats(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        return
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM users WHERE completed = 1")
    completed_users = c.fetchone()[0]
    
    c.execute("SELECT gender, COUNT(*) FROM users WHERE gender != '' GROUP BY gender")
    gender_stats = c.fetchall()
    
    c.execute("SELECT age, COUNT(*) FROM users WHERE age != '' GROUP BY age")
    age_stats = c.fetchall()
    
    conn.close()
    
    stats_text = f"""📊 Статистика теста:
    
👥 Пользователи:
• Всего: {total_users}
• Завершили тест: {completed_users}
• В процессе: {total_users - completed_users}

🚻 Распределение по полу:"""
    
    for gender, count in gender_stats:
        stats_text += f"\n• {gender}: {count}"
    
    stats_text += "\n\n🎂 Распределение по возрасту:"
    for age, count in age_stats:
        stats_text += f"\n• {age}: {count}"
    
    bot.send_message(ADMIN_CHAT_ID, stats_text)

@bot.message_handler(commands=['backup'])
def backup_database(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        return
    
    try:
        with open("database.db", "rb") as f:
            bot.send_document(ADMIN_CHAT_ID, f, caption="🔐 Резервная копия базы данных")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибка при создании бэкапа: {e}")

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
    return "Слепой музыкальный тест бот работает! 🎵", 200

# === ЗАПУСК ===
if __name__ == "__main__":
    init_db()
    
    try:
        bot.send_message(ADMIN_CHAT_ID, "✅ Бот запущен и готов к работе!")
    except:
        print("Не удалось отправить уведомление администратору.")
    
    port = int(os.environ.get("PORT", 5000))
    
    if not os.environ.get("DEBUG"):
        bot.remove_webhook()
        bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/{TOKEN}")
    
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("DEBUG"))
