import os
import time
import csv
import base64
import requests
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# === НАСТРОЙКИ ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_CHAT_ID = " 866964827"
GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # Render Secret

AUDIO_BASE = "tracks"
USERS_FILE = "users_done.csv"
TOTAL_PLAYLISTS = 3  # количество плейлистов

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_states = {}
user_last_message = {}
user_rating_guide = {}
user_rating_time = {}

# === ПОДСКАЗКА ===
RATING_GUIDE_MESSAGE = """
1️⃣  - Не нравится  
2️⃣  - Когда-то нравилась, но надоела  
3️⃣  - Нейтрально  
4️⃣  - Нравится  
5️⃣  - Любимая песня
"""

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    user_last_message.setdefault(chat_id, []).append(msg.message_id)
    return msg

def cleanup_chat(chat_id, keep_rating_guide=False):
    if chat_id not in user_last_message:
        return
    keep = [user_rating_guide.get(chat_id)] if keep_rating_guide else []
    for mid in user_last_message[chat_id]:
        if mid not in keep:
            try:
                bot.delete_message(chat_id, mid)
            except:
                pass
    user_last_message[chat_id] = keep

def send_rating_guide(chat_id):
    if chat_id in user_rating_guide:
        try: bot.delete_message(chat_id, user_rating_guide[chat_id])
        except: pass
    msg = send_message(chat_id, RATING_GUIDE_MESSAGE, parse_mode='Markdown')
    user_rating_guide[chat_id] = msg.message_id

# === CSV + GITHUB ===
def append_line_to_github(repo, path_in_repo, token, line_to_append, header_if_missing=None):
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"token {token}"}

    r_get = requests.get(url, headers=headers)
    if r_get.status_code == 200:
        j = r_get.json()
        content = base64.b64decode(j.get("content", "")).decode("utf-8")
        sha = j.get("sha")
        if not content.endswith("\n") and content.strip() != "":
            content += "\n"
        new_content = content + line_to_append.rstrip("\n") + "\n"
        b64 = base64.b64encode(new_content.encode()).decode()
        payload = {"message": f"Append CSV update {datetime.utcnow()}", "content": b64, "sha": sha}
        r_put = requests.put(url, headers=headers, json=payload)
        return r_put.status_code in (200, 201)
    elif r_get.status_code == 404:
        text = ""
        if header_if_missing:
            text += header_if_missing.rstrip("\n") + "\n"
        text += line_to_append.rstrip("\n") + "\n"
        b64 = base64.b64encode(text.encode()).decode()
        payload = {"message": f"Create CSV {datetime.utcnow()}", "content": b64}
        r_put = requests.put(url, headers=headers, json=payload)
        return r_put.status_code in (200, 201)
    return False

def save_to_csv(user_data, ratings, playlist_num):
    csv_name = f"backup_results_playlist{playlist_num}.csv"
    exists = os.path.exists(csv_name)
    with open(csv_name, "a", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not exists:
            headers = ['user_id','username','first_name','last_name','gender','age'] + [f"track_{i}" for i in range(1,31)]
            writer.writerow(headers)
        row = [
            user_data['user_id'],
            user_data.get('username',''),
            user_data.get('first_name',''),
            user_data.get('last_name',''),
            user_data['gender'],
            user_data['age']
        ] + [ratings.get(str(i),'') for i in range(1,31)]
        writer.writerow(row)
    print(f"✅ Результаты сохранены локально ({csv_name})")
    return csv_name

# === ХРАНЕНИЕ ПРОГРЕССА ===
def get_user_playlist(user_id):
    if not os.path.exists(USERS_FILE):
        return 0
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            uid, pl = line.strip().split(",")
            if uid == str(user_id):
                return int(pl)
    return 0

def update_user_playlist(user_id, playlist):
    lines, updated = [], False
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        for line in lines:
            uid, pl = line.strip().split(",")
            if uid == str(user_id):
                f.write(f"{user_id},{playlist}\n")
                updated = True
            else:
                f.write(line)
        if not updated:
            f.write(f"{user_id},{playlist}\n")

# === СТАРТ ===
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user = message.from_user
    cleanup_chat(chat_id)
    user_states[chat_id] = {
        'user_data': {
            'user_id': chat_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'gender': '',
            'age': ''
        },
        'ratings': {},
        'current_track': 1
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
    text = (
        f"Привет, {user.first_name}! 🎵\n\n"
        "Вы прослушаете 30 музыкальных фрагментов и оцените каждый по шкале от 1 до 5.\n\n"
        "🎁 После теста среди участников — розыгрыш подарков!\n\n"
        "*Нажимая «Начать тест», вы даёте согласие на обработку персональных данных*"
    )
    send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "start_test")
def start_test(c):
    chat_id = c.message.chat.id
    bot.delete_message(chat_id, c.message.message_id)
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Мужской", callback_data="gender_M"), types.InlineKeyboardButton("Женский", callback_data="gender_F"))
    send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_states[chat_id]['user_data']['gender'] = "Мужской" if c.data.endswith("M") else "Женский"
    bot.delete_message(chat_id, c.message.message_id)
    ask_age(chat_id)

def ask_age(chat_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for a in ["до 24","25-34","35-44","45-54","55+"]:
        kb.add(types.InlineKeyboardButton(a, callback_data=f"age_{a}"))
    send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    age = c.data.split("_",1)[1]
    user_states[chat_id]['user_data']['age'] = age
    bot.delete_message(chat_id, c.message.message_id)
    username = user_states[chat_id]['user_data'].get('username') or user_states[chat_id]['user_data']['first_name']
    send_message(chat_id, f"Спасибо, {username}! 🎶\n\nТеперь начнём тест. Удачи! 🎁")
    time.sleep(3)
    send_rating_guide(chat_id)
    start_playlist(chat_id)

def start_playlist(chat_id):
    current_pl = get_user_playlist(chat_id)
    if current_pl >= TOTAL_PLAYLISTS:
        send_message(chat_id, "🎧 Вы уже прошли все плейлисты! Спасибо ❤️")
        return
    next_pl = current_pl + 1
    update_user_playlist(chat_id, next_pl)
    user_states[chat_id]['playlist'] = next_pl
    send_message(chat_id, f"📀 Ваш плейлист №{next_pl}. Поехали!")
    send_track(chat_id)

# === ТРЕКИ ===
def send_track(chat_id):
    state = user_states[chat_id]
    pl = state['playlist']
    num = state['current_track']
    if num > 30:
        finish_test(chat_id)
        return
    track_path = os.path.join(AUDIO_BASE, f"playlist{pl}", f"{num:03d}.mp3")
    if not os.path.exists(track_path):
        send_message(chat_id, f"⚠️ Трек {num:03d} не найден.")
        state['current_track'] += 1
        send_track(chat_id)
        return
    cleanup_chat(chat_id, keep_rating_guide=True)
    send_message(chat_id, f"🎵 Трек {num}/30")
    with open(track_path, "rb") as a:
        bot.send_audio(chat_id, a, title=f"Трек {num:03d}")
    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1,6):
        kb.add(types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}"))
    msg = bot.send_message(chat_id, "Оцените трек:", reply_markup=kb)
    user_last_message.setdefault(chat_id, []).append(msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def rate(c):
    chat_id = c.message.chat.id
    rating = int(c.data.split("_")[1])
    user_states[chat_id]['ratings'][str(user_states[chat_id]['current_track'])] = rating
    bot.delete_message(chat_id, c.message.message_id)
    user_states[chat_id]['current_track'] += 1
    send_track(chat_id)

# === ФИНАЛ ===
def finish_test(chat_id):
    data = user_states[chat_id]['user_data']
    ratings = user_states[chat_id]['ratings']
    playlist_num = user_states[chat_id]['playlist']

    csv_path = save_to_csv(data, ratings, playlist_num)
    header = None
    with open(csv_path, "r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n")
        last = None
        for line in f:
            if line.strip():
                last = line.strip()
    if GITHUB_TOKEN and last:
        append_line_to_github(GITHUB_REPO, csv_path, GITHUB_TOKEN, last, header_if_missing=header)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎧 Оценить ещё 30 треков", callback_data="start_test"))
    send_message(chat_id, "🎉 Тест завершён! Спасибо за участие!\n\nХочешь пройти следующий плейлист?", reply_markup=kb)

# === /results и /clear ===
@bot.message_handler(commands=['results'])
def results(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID):
        send_message(message.chat.id, "⛔ Нет доступа.")
        return
    for pl in range(1, TOTAL_PLAYLISTS + 1):
        path = f"backup_results_playlist{pl}.csv"
        if os.path.exists(path):
            with open(path, "rb") as f:
                bot.send_document(message.chat.id, f, caption=f"Плейлист {pl}")
        else:
            send_message(message.chat.id, f"⚠️ Нет данных для плейлиста {pl}")

@bot.message_handler(commands=['clear'])
def clear(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID):
        send_message(message.chat.id, "⛔ Нет доступа.")
        return
    for pl in range(1, TOTAL_PLAYLISTS + 1):
        name = f"backup_results_playlist{pl}.csv"
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{name}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            sha = r.json().get("sha")
            requests.delete(url, headers=headers, json={"message": "Clear data", "sha": sha})
    send_message(message.chat.id, "🧹 Все результаты на GitHub очищены.")

# === FLASK WEBHOOK ===
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
        return ""
    return "Bad request", 400

@app.route("/")
def index():
    return "Music Test Bot running!"

# === ЗАПУСК ===
if __name__ == "__main__":
    print("🚀 Бот запущен!")
    if "RENDER" in os.environ:
        port = int(os.environ.get("PORT", 10000))
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/webhook/{TOKEN}")
        app.run(host="0.0.0.0", port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
