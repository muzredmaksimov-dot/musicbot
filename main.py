import os
import telebot
import time
import csv
from telebot import types
from flask import Flask, request
from datetime import datetime
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import base64

# === НАСТРОЙКИ ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_CHAT_ID = "866964827"
AUDIO_FOLDER = "tracks"
SPREADSHEET_NAME = "music_testing"
WORKSHEET_NAME = "track_list"
CSV_FILE = "backup_results.csv"

# GitHub репозиторий для хранения CSV (ваш репо)
GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # обязательно в Render Secrets

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === GOOGLE SHEETS (оставлено, но не обязательно) ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
worksheet = None

def initialize_google_sheets():
    global worksheet
    try:
        creds_json_str = os.environ.get('GOOGLE_CREDS_JSON')

        if creds_json_str:
            creds_dict = json.loads(creds_json_str)
        elif os.path.exists('creds.json'):
            with open('creds.json', 'r', encoding='utf-8') as f:
                creds_dict = json.load(f)
        else:
            print("❌ Нет ключа для Google API")
            return False

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        print("✅ Подключено к Google Таблице!")
        return True
    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

def save_to_google_sheets(user_data, ratings):
    if not worksheet:
        print("❌ Google Таблица недоступна")
        return False
    try:
        all_data = worksheet.get_all_values()
        next_col = len(all_data[0]) + 1 if all_data else 1

        user_info = [
            user_data['user_id'],
            f"@{user_data['username']}" if user_data.get('username') else user_data.get('first_name',''),
            user_data.get('last_name',''),
            user_data['gender'],
            user_data['age'],
        ]

        for i in range(1,31):
            user_info.append(ratings.get(str(i), ''))

        for row_idx, value in enumerate(user_info, start=1):
            worksheet.update_cell(row_idx, next_col, value)

        print(f"✅ Данные сохранены в колонку {next_col}")
        return True
    except Exception as e:
        print(f"❌ Ошибка записи в Google Таблицу: {e}")
        return False


# === CSV функции ===
def save_to_csv_backup(user_data, ratings):
    """
    Сохраняет итоговую строку (в одну строку все треки).
    """
    try:
        file_exists = os.path.exists(CSV_FILE)
        with open(CSV_FILE,'a',newline='',encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                headers = ['user_id','username','first_name','last_name','gender','age']
                for i in range(1,31):
                    headers.append(f'track_{i}')
                writer.writerow(headers)
            row_data = [
                user_data['user_id'],
                user_data.get('username',''),
                user_data.get('first_name',''),
                user_data.get('last_name',''),
                user_data['gender'],
                user_data['age'],
            ]
            for i in range(1,31):
                row_data.append(ratings.get(str(i),''))
            writer.writerow(row_data)
        print("✅ Данные сохранены в CSV (локально)")
        return True
    except Exception as e:
        print(f"❌ Ошибка CSV: {e}")
        return False

def get_last_nonempty_line(local_csv_path):
    """
    Возвращает последнюю непустую строку из локального CSV в виде текста (без добавочного \n)
    """
    try:
        if not os.path.exists(local_csv_path):
            return None
        last = None
        with open(local_csv_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.rstrip("\n\r")
                if s.strip() != "":
                    last = s
        return last
    except Exception as e:
        print("Ошибка чтения локального CSV:", e)
        return None

# === GitHub append helper ===
def append_line_to_github(repo, path_in_repo, token, line_to_append, header_if_missing=None):
    """
    Добавляет одну строку в файл CSV в GitHub repo/path.
    Если файла нет — создаёт файл с header_if_missing (строка, без \n) + line.
    Работает через GitHub Contents API (PUT). Возвращает True/False.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    # Получаем существующий файл, чтобы взять sha и content
    r_get = requests.get(url, headers=headers)
    if r_get.status_code == 200:
        try:
            j = r_get.json()
            content_b64 = j.get("content", "")
            sha = j.get("sha")
            remote_text = base64.b64decode(content_b64).decode("utf-8")
            # Добавляем строку, корректируем перевод строки
            if not remote_text.endswith("\n") and remote_text.strip() != "":
                remote_text = remote_text + "\n"
            new_text = remote_text + line_to_append.rstrip("\n") + "\n"
            b64 = base64.b64encode(new_text.encode("utf-8")).decode("utf-8")
            payload = {"message": f"Append row from bot @ {datetime.utcnow().isoformat()}", "content": b64, "sha": sha}
            r_put = requests.put(url, headers=headers, json=payload)
            if r_put.status_code in (200, 201):
                print("✅ appended row to GitHub CSV (updated existing file)")
                return True
            else:
                print("❌ GitHub PUT error:", r_put.status_code, r_put.text)
                return False
        except Exception as e:
            print("Ошибка обработки содержимого файла с GitHub:", e)
            return False
    elif r_get.status_code == 404:
        # Файла нет — создаём: header_if_missing (если есть) + line
        try:
            if header_if_missing:
                content_text = header_if_missing.rstrip("\n") + "\n" + line_to_append.rstrip("\n") + "\n"
            else:
                # без заголовков — просто строка
                content_text = line_to_append.rstrip("\n") + "\n"
            b64 = base64.b64encode(content_text.encode("utf-8")).decode("utf-8")
            payload = {"message": f"Create CSV and append row from bot @ {datetime.utcnow().isoformat()}", "content": b64}
            r_put = requests.put(url, headers=headers, json=payload)
            if r_put.status_code in (200, 201):
                print("✅ created CSV and pushed to GitHub")
                return True
            else:
                print("❌ GitHub create error:", r_put.status_code, r_put.text)
                return False
        except Exception as e:
            print("Ошибка создания файла в GitHub:", e)
            return False
    else:
        print(f"GitHub GET error: {r_get.status_code} {r_get.text}")
        return False

# === ХРАНИЛИЩЕ ===
user_last_message = {}
user_rating_guide = {}
user_rating_time = {}
user_states = {}

# === РАСШИФРОВКА ОЦЕНОК ===
RATING_GUIDE_MESSAGE = """

1️⃣  - Не нравится
2️⃣  - Раньшн нравилась, но надоела  
3️⃣  - Нейтрально
4️⃣  - Нравится
5️⃣  - Любимая песня

"""

# === СЛУЖЕБНЫЕ ФУНКЦИИ ===
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        user_last_message.setdefault(chat_id, []).append(msg.message_id)
        return msg
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")

def cleanup_chat(chat_id, keep_rating_guide=False):
    if chat_id in user_last_message:
        try:
            rating_guide_id = user_rating_guide.get(chat_id)
            messages_to_keep = [rating_guide_id] if keep_rating_guide and rating_guide_id else []
            for msg_id in user_last_message[chat_id]:
                if msg_id not in messages_to_keep:
                    try: bot.delete_message(chat_id,msg_id)
                    except: pass
            user_last_message[chat_id] = messages_to_keep
        except Exception as e:
            print(f"Ошибка очистки чата: {e}")

def send_rating_guide(chat_id):
    if chat_id in user_rating_guide:
        try: bot.delete_message(chat_id, user_rating_guide[chat_id])
        except: pass
    msg = send_message(chat_id, RATING_GUIDE_MESSAGE, parse_mode='Markdown')
    if msg: user_rating_guide[chat_id] = msg.message_id

# === КОМАНДА START ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user = message.from_user
    cleanup_chat(chat_id, keep_rating_guide=True)
    user_states[chat_id] = {
        'user_data': {
            'user_id': chat_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'gender':'',
            'age':''
        },
        'ratings':{},
        'current_track':1
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
    welcome_text = (
        f"Привет, {user.first_name}! 🎵\n\n"
        "Вы прослушаете 30 музыкальных треков и оцените каждый по шкале от 1 до 5.\n\n"
        "🎁 После теста среди всех участников будет розыгрыш подарков!\n\n"
         "*нажимая «Начать тест» вы даете согласие на обработку персональных данных"
        )
    send_message(chat_id, welcome_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data=="start_test")
def handle_start_button(call):
    chat_id = call.message.chat.id
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    cleanup_chat(chat_id)
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_Мужской"),
        types.InlineKeyboardButton("Женский", callback_data="gender_Женский")
    )
    send_message(chat_id,"Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    gender = c.data.split("_",1)[1]
    user_states[chat_id]['user_data']['gender'] = gender
    try: bot.delete_message(chat_id,c.message.message_id)
    except: pass
    cleanup_chat(chat_id)
    ask_age(chat_id)

def ask_age(chat_id):
    opts = ["до 24","25-34","35-44","45-54","55+"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(o, callback_data=f"age_{o}") for o in opts]
    kb.add(*buttons)
    send_message(chat_id,"Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    age = c.data.split("_",1)[1]
    user_states[chat_id]['user_data']['age'] = age
    try: bot.delete_message(chat_id,c.message.message_id)
    except: pass
    username_display = f"@{user_states[chat_id]['user_data']['username']}" if user_states[chat_id]['user_data']['username'] else user_states[chat_id]['user_data']['first_name']
    send_message(chat_id,f"Спасибо, {username_display}! 🎶\n\nТеперь начнем тест. Удачи! 🎁")
    send_rating_guide(chat_id)
    send_track(chat_id)

# === ОТПРАВКА ТРЕКОВ ===
def send_track(chat_id):
    cleanup_chat(chat_id, keep_rating_guide=True)
    track_num = user_states[chat_id]['current_track']
    if track_num>30: finish_test(chat_id); return
    track_filename = f"{track_num:03d}.mp3"
    track_path = os.path.join(AUDIO_FOLDER, track_filename)
    send_message(chat_id,f"🎵 Трек {track_num}/30")
    if os.path.exists(track_path):
        try:
            with open(track_path,'rb') as audio_file:
                audio_msg = bot.send_audio(chat_id,audio_file,title=f"Трек {track_num:03d}")
                user_last_message.setdefault(chat_id,[]).append(audio_msg.message_id)
                kb = types.InlineKeyboardMarkup(row_width=5)
                buttons = [types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}") for i in range(1,6)]
                kb.add(*buttons)
                rating_msg = bot.send_message(chat_id,"Оцените трек:",reply_markup=kb)
                user_last_message[chat_id].append(rating_msg.message_id)
        except Exception as e:
            send_message(chat_id,f"❌ Ошибка: {e}")
            user_states[chat_id]['current_track']+=1
            send_track(chat_id)
    else:
        send_message(chat_id,f"⚠️ Трек {track_num:03d} не найден.")
        user_states[chat_id]['current_track']+=1
        send_track(chat_id)

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    rating = int(c.data.split("_")[1])
    track_num = user_states[chat_id]['current_track']
    current_time = time.time()
    if current_time - user_rating_time.get(chat_id,0) < 2:
        bot.answer_callback_query(c.id,"Пожалуйста, прослушайте трек")
        return
    user_rating_time[chat_id]=current_time
    user_states[chat_id]['ratings'][str(track_num)] = rating
    try: bot.delete_message(chat_id,c.message.message_id)
    except: pass
    user_states[chat_id]['current_track']+=1
    cleanup_chat(chat_id, keep_rating_guide=True)
    send_track(chat_id)

def finish_test(chat_id):
    user_data = user_states[chat_id]['user_data']
    ratings = user_states[chat_id]['ratings']

    # 1) локально сохраняем
    csv_success = save_to_csv_backup(user_data, ratings)

    # 2) на GitHub append последней строки (если токен настроен)
    if GITHUB_TOKEN and csv_success:
        last_line = get_last_nonempty_line(CSV_FILE)
        if last_line:
            # Если remote отсутствует, добавим заголовок из локального файла (первая строка)
            header_line = None
            try:
                with open(CSV_FILE, "r", encoding="utf-8") as f:
                    first = f.readline().rstrip("\n")
                    header_line = first if first and "," in first else None
            except:
                header_line = None

            appended = append_line_to_github(GITHUB_REPO, CSV_FILE, GITHUB_TOKEN, last_line, header_if_missing=header_line)
            if not appended:
                print("Не удалось append в GitHub.")
        else:
            print("Не найдено последней строки локального CSV для добавления.")
    else:
        if not csv_success:
            print("CSV локально не сохранён — пропускаем append в GitHub.")
        if not GITHUB_TOKEN:
            print("GITHUB_TOKEN не настроен — пропуск append в GitHub.")

    # 3) старая попытка сохранить в Google Sheets (если доступно)
    google_success = save_to_google_sheets(user_data, ratings)

    username_display = f"@{user_data['username']}" if user_data['username'] else user_data['first_name']
    if google_success:
        send_message(chat_id,f"🎉 {username_display}, тест завершён!.\n\nСледите за новостями в @RadioMlR_Efir для розыгрыша подарков! 🎁")
    elif csv_success:
        send_message(chat_id,f"🎉 {username_display}, тест завершён!.\n\nСледите за новостями в @RadioMlR_Efir для розыгрыша подарков! 🎁")
    else:
        send_message(chat_id,"⚠️ Тест завершен! Ошибка при сохранении.")


# === FLASK WEBHOOK ===
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
if __name__=="__main__":
    initialize_google_sheets()
    print("🚀 Бот запущен!")
    if 'RENDER' in os.environ:
        port = int(os.environ.get('PORT',10000))
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"https://musicbot-knqj.onrender.com/webhook/{TOKEN}")
        except Exception as e: print(f"❌ Вебхук: {e}")
        app.run(host='0.0.0.0', port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
