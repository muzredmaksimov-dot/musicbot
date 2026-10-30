import os
import re
import telebot
import time
import csv
from telebot import types
from flask import Flask, request
import requests
import base64
import threading

# === НАСТРОЙКИ ===
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is required")
ADMIN_CHAT_ID = "866964827"
AUDIO_FOLDER = "tracks"
CSV_FILE = "backup_results.csv"
SUBSCRIBERS_FILE = "subscribers.txt"

# GitHub репозиторий для хранения CSV и subscribers.txt
GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === ХРАНИЛИЩЕ ===
user_last_message = {}
user_rating_guide = {}
user_states = {}
buffer_lock = threading.Lock()
result_buffer = []  # временный буфер строк CSV

# === ПОДСКАЗКА ПО ОЦЕНКАМ ===
RATING_GUIDE_MESSAGE = """
1️⃣ - Не нравится  
2️⃣ - Раньше нравилась, но надоела  
3️⃣ - Нейтрально  
4️⃣ - Нравится  
5️⃣ - Любимая песня
"""

# === УТИЛИТЫ ===
def github_read_file(repo, path_in_repo, token):
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
    existing = github_read_file(repo, path_in_repo, token)
    if not existing:
        new_text = (header_if_missing + "\n" if header_if_missing else "") + line + "\n"
    else:
        if not existing.endswith("\n"):
            existing += "\n"
        new_text = existing + line + "\n"
    return github_write_file(repo, path_in_repo, token, new_text, f"Update {path_in_repo}")

# === СООБЩЕНИЯ ===
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        user_last_message.setdefault(chat_id, []).append(msg.message_id)
        return msg
    except Exception as e:
        print("Ошибка отправки:", e)

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
        print("Ошибка очистки:", e)

def send_rating_guide(chat_id):
    if chat_id in user_rating_guide:
        try:
            bot.delete_message(chat_id, user_rating_guide[chat_id])
        except:
            pass
    msg = send_message(chat_id, RATING_GUIDE_MESSAGE)
    if msg:
        user_rating_guide[chat_id] = msg.message_id

# === СТАРТ ===
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user = message.from_user

    try:
        subscribers_text = github_read_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN)
        subscribers = set(s.strip() for s in subscribers_text.split("\n") if s.strip())
        if str(chat_id) not in subscribers:
            subscribers.add(str(chat_id))
            github_write_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, "\n".join(sorted(subscribers)), "Add new subscriber")
    except Exception as e:
        print("Ошибка subscribers:", e)

    cleanup_chat(chat_id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
    send_message(chat_id, f"Привет, {user.first_name}! 🎵\n\n"
                          "Вы прослушаете 30 музыкальных фрагментов и оцените каждый по шкале от 1 до 5.\n\n"
                          "🎁 После теста среди всех участников — розыгрыш беспроводных нушников!\n\n"
                          "_Нажимая «Начать тест», вы даёте согласие на обработку персональных данных._",
                 reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "start_test")
def start_test(c):
    chat_id = c.message.chat.id
    user = c.from_user
    user_states[chat_id] = {
        "user_data": {
            "user_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "gender": "",
            "age": "",
            "phone": ""
        },
        "ratings": {},
        "current_track": 1,
        "awaiting_phone": False
    }
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    bot.answer_callback_query(c.id)
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
    if chat_id not in user_states:
        bot.answer_callback_query(c.id, "Сначала нажмите /start.")
        return
    gender = "Мужской" if c.data.endswith("M") else "Женский"
    user_states[chat_id]["user_data"]["gender"] = gender
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    bot.answer_callback_query(c.id)
    ask_age(chat_id)

def ask_age(chat_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for o in ["до 24", "25-34", "35-44", "45-54", "55+"]:
        kb.add(types.InlineKeyboardButton(o, callback_data=f"age_{o}"))
    send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.answer_callback_query(c.id, "Сначала нажмите /start.")
        return
    user_states[chat_id]["user_data"]["age"] = c.data.split("_", 1)[1]
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    bot.answer_callback_query(c.id)
    ask_phone(chat_id)

# === ТЕЛЕФОН ДЛЯ РОЗЫГРЫША ===
def ask_phone(chat_id):
    user_states[chat_id]["awaiting_phone"] = True
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_phone"))
    send_message(
        chat_id,
        "🎁 Участвуйте в розыгрыше призов!\n\n"
        "Оставьте номер телефона, чтобы мы могли связаться с вами в случае победы.\n\n"
        "Введите номер в международном формате, например:\n"
        "+375291234567\n\n"
        "Номер будет использоваться только для связи по итогам розыгрыша. "
        "Вы можете пропустить этот шаг.",
        reply_markup=kb
    )

def begin_music_test(chat_id):
    user_states[chat_id]["awaiting_phone"] = False
    username = user_states[chat_id]["user_data"].get("username") or user_states[chat_id]["user_data"]["first_name"]
    send_message(chat_id, f"Спасибо, {username}! 🎶\n\nТеперь начнем тест. Удачи! 🎁")
    time.sleep(1)
    send_rating_guide(chat_id)
    send_track(chat_id)

@bot.message_handler(
    func=lambda message: (
        message.chat.id in user_states
        and user_states[message.chat.id].get(«awaiting_phone», False)
    ),
    content_types=[«text»]
)
def handle_phone(message):
    chat_id = message.chat.id
    phone = message.text.strip()
    if not phone:
    send_message(
        chat_id,
        "Введите номер телефона или нажмите «Пропустить»."
    )
    return

user_states[chat_id]["user_data"]["phone"] = phone
begin_music_test(chat_id)

@bot.callback_query_handler(func=lambda c: c.data == "skip_phone")
def skip_phone(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.answer_callback_query(c.id, "Начните заново командой /start.")
        return
    user_states[chat_id]["user_data"]["phone"] = ""
    user_states[chat_id]["awaiting_phone"] = False
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    bot.answer_callback_query(c.id)
    begin_music_test(chat_id)

# === ТРЕКИ ===
def send_track(chat_id):
    cleanup_chat(chat_id, keep_rating_guide=True)
    track_num = user_states[chat_id]["current_track"]
    if track_num > 30:
        finish_test(chat_id)
        return
    path = os.path.join(AUDIO_FOLDER, f"{track_num:03d}.mp3")
    send_message(chat_id, f"🎵 Трек {track_num}/30")
    if os.path.exists(path):
        with open(path, "rb") as f:
            audio = bot.send_audio(chat_id, f, title=f"Трек {track_num:03d}")
            user_last_message.setdefault(chat_id, []).append(audio.message_id)
        kb = types.InlineKeyboardMarkup(row_width=5)
        kb.add(*[types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1, 6)])
        msg = send_message(chat_id, "Оцените трек:", reply_markup=kb)
        if msg:
            user_last_message[chat_id].append(msg.message_id)
    else:
        user_states[chat_id]["current_track"] += 1
        send_track(chat_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def rate(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.answer_callback_query(c.id, "Тест не найден. Нажмите /start.")
        return
    r = int(c.data.split("_")[1])
    t = user_states[chat_id]["current_track"]
    user_states[chat_id]["ratings"][str(t)] = r
    user_states[chat_id]["current_track"] += 1
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass
    bot.answer_callback_query(c.id)
    send_track(chat_id)

# === ФИНАЛ ===
def finish_test(chat_id):
    user = user_states[chat_id]["user_data"]
    ratings = user_states[chat_id]["ratings"]
    row = [user["user_id"], user.get("username", ""), user.get("first_name", ""), user.get("last_name", ""),
           user["gender"], user["age"], user.get("phone", "")] + [ratings.get(str(i), "") for i in range(1, 31)]

    with buffer_lock:
        result_buffer.append(row)

    bot.send_message(ADMIN_CHAT_ID, f"✅ Пользователь {user.get('username') or user['first_name']} завершил тест.")
    send_message(chat_id, f"🎉 @{user.get('username') or user['first_name']}, тест завершён!\n\nСледите за новостями в @RadioMIR_Efir 🎁")

# === СБРОС ===
@bot.message_handler(commands=["reset_all"])
def reset_all(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "⛔ Нет доступа.")
        return
    args = message.text.split()
    announce = len(args) > 1 and args[1].lower() in ("announce", "1", "send")

    headers = ["user_id", "username", "first_name", "last_name", "gender", "age", "phone"] + [f"track_{i}" for i in range(1, 31)]
    open(CSV_FILE, "w", encoding="utf-8").write(",".join(headers) + "\n")
    github_write_file(GITHUB_REPO, CSV_FILE, GITHUB_TOKEN, ",".join(headers) + "\n", "Reset CSV")

    if announce:
        subs_text = github_read_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN)
        subs = [s.strip() for s in subs_text.split("\n") if s.strip()]
        sent = 0
        for s in subs:
            try:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
                bot.send_message(int(s), "🎧 Новый музыкальный тест уже готов!\n\n"
                                         "Пройди и оцени 30 треков — твое мнение важно для радио МИР 🎶",
                                 reply_markup=kb)
                sent += 1
                time.sleep(0.1)
            except:
                pass
        bot.send_message(ADMIN_CHAT_ID, f"✅ Рассылка выполнена ({sent} пользователей).")
    else:
        bot.send_message(ADMIN_CHAT_ID, "✅ Все данные очищены (без рассылки).")

# === СБРОС И FLUSH ===
def push_buffer_to_github():
    with buffer_lock:
        if not result_buffer:
            return
        file_exists = os.path.exists(CSV_FILE)
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not file_exists:
                headers = ["user_id", "username", "first_name", "last_name", "gender", "age", "phone"] + [f"track_{i}" for i in range(1, 31)]
                w.writerow(headers)
            for row in result_buffer:
                w.writerow(row)
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        github_write_file(GITHUB_REPO, CSV_FILE, GITHUB_TOKEN, "".join(lines), "Buffer flush to GitHub")
        result_buffer.clear()

@bot.message_handler(commands=["flush"])
def flush_command(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "⛔ Нет доступа.")
        return
    push_buffer_to_github()
    bot.send_message(ADMIN_CHAT_ID, "💾 Буфер успешно отправлен на GitHub.")

def auto_flush():
    while True:
        time.sleep(120)
        push_buffer_to_github()

threading.Thread(target=auto_flush, daemon=True).start()

 # === КОМАНДА /results (только для админа) ===
@bot.message_handler(commands=['results'])
def send_results(message):
    chat_id = message.chat.id
    if str(chat_id) != str(ADMIN_CHAT_ID):
        bot.send_message(chat_id, "⛔ У вас нет доступа к этой команде.")
        return

    # 1) Попробуем скачать актуальную версию с GitHub
    if GITHUB_TOKEN:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{CSV_FILE}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                j = r.json()
                content_b64 = j.get("content", "")
                content_bytes = base64.b64decode(content_b64)
                tmp_path = "/tmp/backup_results.csv"
                try:
                    with open(tmp_path, "wb") as f:
                        f.write(content_bytes)
                    with open(tmp_path, "rb") as f:
                        bot.send_document(chat_id, f, caption="backup_results.csv (from GitHub)")
                    return
                except Exception as e:
                    print("Ошибка записи/отправки временного файла из GitHub:", e)
            else:
                print("GitHub /results fetch returned:", r.status_code, r.text)
        except Exception as e:
            print("Ошибка при попытке загрузить CSV с GitHub:", e)

    # 2) fallback — отдадим локальную копию (если есть)
    try:
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'rb') as f:
                bot.send_document(chat_id, f, caption="backup_results.csv (local)")
        else:
            bot.send_message(chat_id, "❌ Файл backup_results.csv пока не создан.")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка при отправке файла: {e}")

# === ЗАПУСК ===
@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400

@app.route('/')
def index(): return 'Music Test Bot running!'
@app.route('/health')
def health(): return 'OK'

if __name__ == "__main__":
    app.run( host="0.0.0.0", port=int(os.environ.get("PORT", 8080)) )
