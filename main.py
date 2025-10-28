import os
import telebot
import time
import csv
from telebot import types
from flask import Flask, request
from datetime import datetime
import json
import requests
import base64

# === НАСТРОЙКИ ===
TOKEN = "ВАШ_ТОКЕН"
ADMIN_CHAT_ID = "866964827"
AUDIO_FOLDER = "tracks"
CSV_FILE = "backup_results.csv"
SUBSCRIBERS_FILE = "subscribers.txt"

# GitHub репозиторий для хранения CSV и subscribers.txt
GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # обязательно задать в Render Secrets

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === ХРАНИЛИЩЕ ===
user_last_message = {}
user_rating_guide = {}
user_rating_time = {}
user_states = {}

# === ПОДСКАЗКА ПО ОЦЕНКАМ ===
RATING_GUIDE_MESSAGE = """
1️⃣  - Не нравится  
2️⃣  - Раньше нравилась, но надоела  
3️⃣  - Нейтрально  
4️⃣  - Нравится  
5️⃣  - Любимая песня
"""

# === УТИЛИТЫ ===
def github_read_file(repo, path_in_repo, token):
    """Чтение текстового файла с GitHub"""
    try:
        url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            content_b64 = r.json().get("content", "")
            return base64.b64decode(content_b64).decode("utf-8")
        return ""
    except Exception as e:
        print("Ошибка чтения с GitHub:", e)
        return ""

def github_write_file(repo, path_in_repo, token, content_text, commit_message):
    """Запись (перезапись) файла в GitHub"""
    try:
        url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        r_get = requests.get(url, headers=headers)
        b64 = base64.b64encode(content_text.encode("utf-8")).decode("utf-8")
        payload = {"message": commit_message, "content": b64}
        if r_get.status_code == 200:
            payload["sha"] = r_get.json().get("sha")
        r_put = requests.put(url, headers=headers, json=payload)
        return r_put.status_code in (200, 201)
    except Exception as e:
        print("Ошибка записи на GitHub:", e)
        return False

def github_append_line(repo, path_in_repo, token, line, header_if_missing=None):
    """Добавление строки в текстовый файл на GitHub"""
    existing = github_read_file(repo, path_in_repo, token)
    if not existing:
        if header_if_missing:
            new_text = header_if_missing + "\n" + line + "\n"
        else:
            new_text = line + "\n"
    else:
        if not existing.endswith("\n"):
            existing += "\n"
        new_text = existing + line + "\n"
    return github_write_file(repo, path_in_repo, token, new_text, f"Update {path_in_repo}")

# === ОТПРАВКА ===
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        user_last_message.setdefault(chat_id, []).append(msg.message_id)
        return msg
    except Exception as e:
        print("Ошибка отправки сообщения:", e)

def cleanup_chat(chat_id, keep_rating_guide=False):
    try:
        messages_to_keep = [user_rating_guide.get(chat_id)] if keep_rating_guide else []
        for msg_id in user_last_message.get(chat_id, []):
            if msg_id not in messages_to_keep and msg_id:
                try:
                    bot.delete_message(chat_id, msg_id)
                except:
                    pass
        user_last_message[chat_id] = messages_to_keep
    except Exception as e:
        print("Ошибка очистки чата:", e)

def send_rating_guide(chat_id):
    if chat_id in user_rating_guide:
        try: bot.delete_message(chat_id, user_rating_guide[chat_id])
        except: pass
    msg = send_message(chat_id, RATING_GUIDE_MESSAGE)
    user_rating_guide[chat_id] = msg.message_id

# === СТАРТ ===
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user = message.from_user

    # Добавляем в список подписчиков (и на GitHub)
    try:
        subscribers_text = github_read_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN)
        subscribers = set(s.strip() for s in subscribers_text.split("\n") if s.strip())
        if str(chat_id) not in subscribers:
            subscribers.add(str(chat_id))
            new_text = "\n".join(sorted(subscribers))
            github_write_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, new_text, "Add new subscriber")
    except Exception as e:
        print("Ошибка добавления в subscribers:", e)

    cleanup_chat(chat_id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
    send_message(chat_id, f"Привет, {user.first_name}! 🎵\n\n"
                          "Вы прослушаете 30 музыкальных фрагментов и оцените каждый по шкале от 1 до 5.\n\n"
                          "🎁 После теста среди всех участников — розыгрыш Беспроводных наушников!\n\n"
                          "_Нажимая «Начать тест», вы даёте согласие на обработку персональных данных._",
                 reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def start_test(call):
    chat_id = call.message.chat.id
    user = call.from_user
    user_states[chat_id] = {
        "user_data": {
            "user_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "gender": "",
            "age": ""
        },
        "ratings": {},
        "current_track": 1
    }
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    ask_gender(chat_id)

# === АНКЕТА ===
def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Мужской", callback_data="gender_M"),
           types.InlineKeyboardButton("Женский", callback_data="gender_F"))
    send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    gender = "Мужской" if c.data.endswith("M") else "Женский"
    user_states[chat_id]["user_data"]["gender"] = gender
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass
    ask_age(chat_id)

def ask_age(chat_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for o in ["до 24", "25-34", "35-44", "45-54", "55+"]:
        kb.add(types.InlineKeyboardButton(o, callback_data=f"age_{o}"))
    send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_states[chat_id]["user_data"]["age"] = c.data.split("_", 1)[1]
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass
    username = user_states[chat_id]["user_data"].get("username") or user_states[chat_id]["user_data"]["first_name"]
    send_message(chat_id, f"Спасибо, @{username}! 🎶\n\nТеперь начнем тест. Удачи! 🎁")
    time.sleep(1)
    send_rating_guide(chat_id)
    send_track(chat_id)

# === ОТПРАВКА ТРЕКОВ ===
def send_track(chat_id):
    cleanup_chat(chat_id, keep_rating_guide=True)
    track_num = user_states[chat_id]["current_track"]
    if track_num > 30:
        finish_test(chat_id)
        return
    track_filename = f"{track_num:03d}.mp3"
    path = os.path.join(AUDIO_FOLDER, track_filename)
    send_message(chat_id, f"🎵 Трек {track_num}/30")
    if os.path.exists(path):
        with open(path, "rb") as a:
            bot.send_audio(chat_id, a, title=f"Трек {track_num:03d}")
        kb = types.InlineKeyboardMarkup(row_width=5)
        kb.add(*[types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)])
        send_message(chat_id, "Оцените трек:", reply_markup=kb)
    else:
        user_states[chat_id]["current_track"] += 1
        send_track(chat_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def rate(c):
    chat_id = c.message.chat.id
    r = int(c.data.split("_")[1])
    t = user_states[chat_id]["current_track"]
    user_states[chat_id]["ratings"][str(t)] = r
    user_states[chat_id]["current_track"] += 1
    try: bot.delete_message(chat_id, c.message.message_id)
    except: pass
    send_track(chat_id)

# === ФИНАЛ ===
def finish_test(chat_id):
    user = user_states[chat_id]["user_data"]
    ratings = user_states[chat_id]["ratings"]

    # сохраняем CSV локально
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            headers = ["user_id", "username", "first_name", "last_name", "gender", "age"] + [f"track_{i}" for i in range(1, 31)]
            w.writerow(headers)
        row = [user["user_id"], user.get("username", ""), user.get("first_name", ""), user.get("last_name", ""), user["gender"], user["age"]] + [ratings.get(str(i), "") for i in range(1, 31)]
        w.writerow(row)

    # добавляем на GitHub
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) >= 2:
        github_append_line(GITHUB_REPO, CSV_FILE, GITHUB_TOKEN, lines[-1].strip(), header_if_missing=lines[0].strip())

    send_message(chat_id, f"🎉 @{user.get('username') or user['first_name']}, тест завершён!\n\nСледите за новостями в @RadioMlR_Efir 🎁")

# === СБРОС ===
@bot.message_handler(commands=["reset_all"])
def reset_all(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "⛔ Нет доступа.")
        return

    args = message.text.split()
    announce = len(args) > 1 and args[1].lower() in ("announce", "1", "send")

    # очистка CSV
    headers = ["user_id","username","first_name","last_name","gender","age"]+[f"track_{i}" for i in range(1,31)]
    open(CSV_FILE, "w", encoding="utf-8").write(",".join(headers) + "\n")
    github_write_file(GITHUB_REPO, CSV_FILE, GITHUB_TOKEN, ",".join(headers) + "\n", "Reset CSV")

    # рассылка новым тестом
    if announce:
        subs_text = github_read_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN)
        subs = [s.strip() for s in subs_text.split("\n") if s.strip()]
        sent_count = 0
        for s in subs:
            try:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
                bot.send_message(int(s), "🎧 Новый музыкальный тест уже готов!\n\n"
                                         "Пройди и оцени 30 треков — твое мнение важно для радио МИР! 🎶",
                                 reply_markup=kb)
                sent_count += 1
                time.sleep(0.1)
            except Exception:
                pass
        bot.send_message(ADMIN_CHAT_ID, f"✅ Рассылка выполнена ({sent_count} пользователей).")
    else:
        bot.send_message(ADMIN_CHAT_ID, "✅ Все данные очищены (без рассылки).")

# === ЗАПУСК ===
@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type')=='application/json':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    return 'Bad Request',400

@app.route('/')
def index(): return 'Music Test Bot running!'
@app.route('/health')
def health(): return 'OK'

if __name__=="__main__":
    print("🚀 Бот запущен")
    if "RENDER" in os.environ:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/webhook/{TOKEN}")
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
