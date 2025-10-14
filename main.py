#!/usr/bin/env python3
# coding: utf-8

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
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_CHAT_ID = 866964827  # числовой id администратора
AUDIO_FOLDER = "tracks"
CSV_FILE = "backup_results.csv"

# GitHub репозиторий для хранения CSV и subscribers.txt
GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # настроить в Render secrets

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === НАЗВАНИЯ ДОП. ФАЙЛОВ ===
SUBSCRIBERS_FILE = "subscribers.txt"

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: GitHub interaction ===

def download_file_from_github(repo, path_in_repo, token, local_path, timeout=15):
    """
    Скачивает файл path_in_repo из repo в local_path. Возвращает True/False.
    """
    if not token:
        return False
    try:
        url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            j = r.json()
            content_b64 = j.get("content", "")
            if content_b64:
                content_bytes = base64.b64decode(content_b64)
                with open(local_path, "wb") as f:
                    f.write(content_bytes)
                print(f"✅ Downloaded {path_in_repo} from GitHub to {local_path}")
                return True
            else:
                print("GitHub: файл найден, но контент пуст.")
                return False
        else:
            print(f"GitHub download returned {r.status_code}: {r.text}")
            return False
    except Exception as e:
        print("Ошибка при скачивании файла с GitHub:", e)
        return False

def overwrite_github_file(repo, path_in_repo, token, new_text, commit_message=None):
    """
    Перезаписывает файл path_in_repo в repo новым текстом new_text.
    Если файла нет — создаёт.
    Возвращает True/False.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        r_get = requests.get(url, headers=headers, timeout=15)
    except Exception as e:
        print("Ошибка GitHub GET:", e)
        return False

    content_b64 = base64.b64encode(new_text.encode("utf-8")).decode("utf-8")
    payload = {
        "message": commit_message or f"Reset/Update {path_in_repo} by bot @ {datetime.utcnow().isoformat()}",
        "content": content_b64,
    }

    if r_get.status_code == 200:
        try:
            sha = r_get.json().get("sha")
            payload["sha"] = sha
            r_put = requests.put(url, headers=headers, json=payload, timeout=15)
            if r_put.status_code in (200, 201):
                print(f"✅ GitHub: файл {path_in_repo} перезаписан")
                return True
            else:
                print("❌ GitHub PUT error:", r_put.status_code, r_put.text)
                return False
        except Exception as e:
            print("Ошибка при перезаписи файла на GitHub:", e)
            return False
    elif r_get.status_code == 404:
        # создаём файл
        try:
            r_put = requests.put(url, headers=headers, json=payload, timeout=15)
            if r_put.status_code in (200, 201):
                print(f"✅ GitHub: файл {path_in_repo} создан")
                return True
            else:
                print("❌ GitHub create error:", r_put.status_code, r_put.text)
                return False
        except Exception as e:
            print("Ошибка при создании файла в GitHub:", e)
            return False
    else:
        print(f"GitHub GET unexpected: {r_get.status_code} {r_get.text}")
        return False

def append_line_to_github(repo, path_in_repo, token, line_to_append, header_if_missing=None):
    """
    Добавляет одну строку в файл CSV в GitHub repo/path.
    Если файла нет — создаёт файл с header_if_missing + line.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    r_get = requests.get(url, headers=headers, timeout=15)
    if r_get.status_code == 200:
        try:
            j = r_get.json()
            content_b64 = j.get("content", "")
            sha = j.get("sha")
            remote_text = base64.b64decode(content_b64).decode("utf-8")
            if not remote_text.endswith("\n") and remote_text.strip() != "":
                remote_text = remote_text + "\n"
            new_text = remote_text + line_to_append.rstrip("\n") + "\n"
            b64 = base64.b64encode(new_text.encode("utf-8")).decode("utf-8")
            payload = {"message": f"Append row from bot @ {datetime.utcnow().isoformat()}", "content": b64, "sha": sha}
            r_put = requests.put(url, headers=headers, json=payload, timeout=15)
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
        try:
            if header_if_missing:
                content_text = header_if_missing.rstrip("\n") + "\n" + line_to_append.rstrip("\n") + "\n"
            else:
                content_text = line_to_append.rstrip("\n") + "\n"
            b64 = base64.b64encode(content_text.encode("utf-8")).decode("utf-8")
            payload = {"message": f"Create CSV and append row from bot @ {datetime.utcnow().isoformat()}", "content": b64}
            r_put = requests.put(url, headers=headers, json=payload, timeout=15)
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

# === SUBSCRIBERS (подписчики на уведомления) ===

def load_subscribers():
    """
    Возвращает set(int) chat_id'ов. Попытка сначала загрузить локальный файл,
    иначе — пытаемся скачать из GitHub (если настроен токен).
    """
    subs = set()
    try:
        # если локального файла нет — попытаться скачать с GitHub
        if not os.path.exists(SUBSCRIBERS_FILE) and GITHUB_TOKEN:
            try:
                download_file_from_github(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, SUBSCRIBERS_FILE)
            except Exception:
                pass

        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        try:
                            subs.add(int(s))
                        except:
                            pass
    except Exception as e:
        print("Ошибка чтения subscribers:", e)
    return subs

def add_subscriber(chat_id):
    """
    Добавляет chat_id в локальный файл и синхронизирует на GitHub (перезапись).
    """
    try:
        chat_id = int(chat_id)
    except:
        return False

    try:
        subs = load_subscribers()
        if chat_id in subs:
            return True

        subs.add(chat_id)
        try:
            with open(SUBSCRIBERS_FILE, "w", encoding="utf-8", newline="") as f:
                for cid in sorted(subs):
                    f.write(str(cid) + "\n")
        except Exception as e:
            print("Ошибка записи локального subscribers.txt:", e)
            return False

        if GITHUB_TOKEN:
            try:
                with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                ok = overwrite_github_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, content,
                                          commit_message=f"Update subscribers by bot @ {datetime.utcnow().isoformat()}")
                if not ok:
                    print("⚠️ Не удалось обновить subscribers.txt на GitHub (оставлен локально).")
                return True
            except Exception as e:
                print("Ошибка при попытке синхронизировать subscribers на GitHub:", e)
                return True
        else:
            return True

    except Exception as e:
        print("Ошибка add_subscriber:", e)
        return False

def remove_subscriber(chat_id):
    """
    Удаляет chat_id из локального файла и синхронизирует на GitHub.
    """
    try:
        chat_id = int(chat_id)
    except:
        return False

    try:
        subs = load_subscribers()
        if chat_id not in subs:
            return True

        subs.remove(chat_id)
        try:
            with open(SUBSCRIBERS_FILE, "w", encoding="utf-8", newline="") as f:
                for cid in sorted(subs):
                    f.write(str(cid) + "\n")
        except Exception as e:
            print("Ошибка записи локального subscribers.txt при удалении:", e)
            return False

        if GITHUB_TOKEN:
            try:
                with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                ok = overwrite_github_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, content,
                                          commit_message=f"Update subscribers (remove) by bot @ {datetime.utcnow().isoformat()}")
                if not ok:
                    print("⚠️ Не удалось обновить subscribers.txt на GitHub после удаления (локально изменён).")
                return True
            except Exception as e:
                print("Ошибка при синхронизации удаления subscribers на GitHub:", e)
                return True
        else:
            return True

    except Exception as e:
        print("Ошибка remove_subscriber:", e)
        return False

# === ХРАНИЛИЩЕ ===
user_last_message = {}   # chat_id -> [message_id,...]
user_rating_guide = {}   # chat_id -> message_id
user_rating_time = {}    # chat_id -> timestamp
user_states = {}         # chat_id -> {user_data, ratings, current_track}

# === РАСШИФРОВКА ОЦЕНОК ===
RATING_GUIDE_MESSAGE = """
1️⃣  - Не нравится
2️⃣  - Раньше нравилась, но надоела
3️⃣  - Нейтрально
4️⃣  - Нравится
5️⃣  - Любимая песня

Выберите оценку для текущего трека:
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
    """
    Удаляет из чата сообщения, которые бот отправлял и которые мы отслеживаем,
    кроме (опционально) сообщения с расшифровкой оценок.
    """
    if chat_id in user_last_message:
        try:
            rating_guide_id = user_rating_guide.get(chat_id)
            messages_to_keep = [rating_guide_id] if keep_rating_guide and rating_guide_id else []
            for msg_id in list(user_last_message[chat_id]):
                if msg_id not in messages_to_keep:
                    try:
                        bot.delete_message(chat_id,msg_id)
                    except Exception:
                        pass
            user_last_message[chat_id] = messages_to_keep
        except Exception as e:
            print(f"Ошибка очистки чата: {e}")

def send_rating_guide(chat_id):
    # удаляем старую расшифровку
    if chat_id in user_rating_guide:
        try:
            bot.delete_message(chat_id, user_rating_guide[chat_id])
        except Exception:
            pass
    msg = send_message(chat_id, RATING_GUIDE_MESSAGE, parse_mode='Markdown')
    if msg:
        user_rating_guide[chat_id] = msg.message_id

# === КОМАНДА START ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user = message.from_user
    cleanup_chat(chat_id, keep_rating_guide=True)
    user_states[chat_id] = {
        'user_data': {
            'user_id': chat_id,
            'username': user.username or '',
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
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
        "Вы прослушаете 30 музыкальных фрагментов, оцените каждый по шкале от 1 до 5.\n\n"
        "🎁 После теста среди всех участников будет розыгрыш подарков!\n\n"
        "_нажимая «Начать тест» вы даёте согласие на обработку персональных данных_"
    )
    send_message(chat_id, welcome_text, reply_markup=kb, parse_mode='Markdown')

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
        types.InlineKeyboardButton("Мужской", callback_data="gender_M"),
        types.InlineKeyboardButton("Женский", callback_data="gender_F")
    )
    send_message(chat_id,"Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    gender = c.data.split("_",1)[1]
    user_states.setdefault(chat_id, {})  # на всякий случай
    user_states[chat_id].setdefault('user_data', {})
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
    user_states.setdefault(chat_id, {})  # safety
    user_states[chat_id].setdefault('user_data', {})
    user_states[chat_id]['user_data']['age'] = age
    try: bot.delete_message(chat_id,c.message.message_id)
    except: pass
    username_display = (
        f"@{user_states[chat_id]['user_data'].get('username')}"
        if user_states[chat_id]['user_data'].get('username') else user_states[chat_id]['user_data'].get('first_name','')
    )
    send_message(chat_id,f"Спасибо, {username_display}! 🎶\n\nТеперь начнем тест. Удачи! 🎁")
    time.sleep(1)
    send_rating_guide(chat_id)
    send_track(chat_id)

# === ОТПРАВКА ТРЕКОВ ===
def send_track(chat_id):
    cleanup_chat(chat_id, keep_rating_guide=True)
    state = user_states.get(chat_id)
    if not state:
        # Если нет состояния - попросим нажать /start
        send_message(chat_id, "Пожалуйста, запустите тест командой /start")
        return
    track_num = state.get('current_track',1)
    if track_num > 30:
        finish_test(chat_id)
        return
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
            # пропускаем трек при ошибке
            user_states[chat_id]['current_track'] = track_num + 1
            send_track(chat_id)
    else:
        send_message(chat_id,f"⚠️ Трек {track_num:03d} не найден.")
        user_states[chat_id]['current_track'] = track_num + 1
        send_track(chat_id)

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    try:
        rating = int(c.data.split("_")[1])
    except:
        bot.answer_callback_query(c.id, "Неверная оценка")
        return
    track_num = user_states.get(chat_id,{}).get('current_track',1)
    current_time = time.time()
    if current_time - user_rating_time.get(chat_id,0) < 2:
        bot.answer_callback_query(c.id,"Пожалуйста, прослушайте трек")
        return
    user_rating_time[chat_id]=current_time
    user_states.setdefault(chat_id,{}).setdefault('ratings',{})[str(track_num)] = rating
    try:
        bot.delete_message(chat_id,c.message.message_id)
    except:
        pass
    # переход к следующему треку
    user_states[chat_id]['current_track'] = track_num + 1
    cleanup_chat(chat_id, keep_rating_guide=True)
    send_track(chat_id)

def finish_test(chat_id):
    # Удаляем справку с оценками (если есть)
    try:
        rg_id = user_rating_guide.get(chat_id)
        if rg_id:
            bot.delete_message(chat_id, rg_id)
    except Exception:
        pass
    # Удаляем запись в словарях (не удаляем профиль пользователя)
    user_data = user_states.get(chat_id,{}).get('user_data',{})
    ratings = user_states.get(chat_id,{}).get('ratings',{})

    # 1) локально сохраняем
    csv_success = save_to_csv_backup(user_data, ratings)

    # 2) на GitHub append (если токен настроен)
    if GITHUB_TOKEN and csv_success:
        last_line = get_last_nonempty_line(CSV_FILE)
        if last_line:
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

    # Окончательное сообщение + кнопка «Оценить еще 30 треков»
    username_display = f"@{user_data.get('username')}" if user_data.get('username') else user_data.get('first_name','')
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎧 Оценить еще 30 треков", callback_data="restart_test"))
    send_message(chat_id,f"🎉 {username_display}, тест завершён!.\n\nСледите за новостями в @RadioMlR_Efir для розыгрыша подарков! 🎁", reply_markup=kb)

    # Сброс прогресса (оставляем профиль) — если пользователь нажмёт кнопку, начнём заново
    user_states[chat_id]['ratings'] = {}
    user_states[chat_id]['current_track'] = 9999  # блокируем пока не нажмёт кнопку

@bot.callback_query_handler(func=lambda call: call.data == "restart_test")
def handle_restart_test(call):
    chat_id = call.message.chat.id
    # Если профиль отсутствует — просим /start
    if chat_id not in user_states or 'user_data' not in user_states[chat_id]:
        send_message(chat_id, "Пожалуйста, запустите тест командой /start")
        return
    # Сбрасываем и начинаем тест заново, не спрашивая пол/возраст (они сохранены)
    user_states[chat_id]['ratings'] = {}
    user_states[chat_id]['current_track'] = 1
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    send_rating_guide(chat_id)
    send_track(chat_id)

# === КОМАНДА /results (только для админа) ===
@bot.message_handler(commands=['results'])
def send_results(message):
    chat_id = message.chat.id
    if int(chat_id) != int(ADMIN_CHAT_ID):
        bot.send_message(chat_id, "⛔ У вас нет доступа к этой команде.")
        return

    # 1) Попробуем скачать актуальную версию с GitHub
    if GITHUB_TOKEN:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{CSV_FILE}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
            r = requests.get(url, headers=headers, timeout=15)
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

# === КОМАНДА администратора: полный сброс состояний и очистка CSV (и GitHub) ===

@bot.message_handler(commands=['reset_all'])
def handle_reset_all(message):
    chat_id = message.chat.id
    # доступ только для администратора
    if int(chat_id) != int(ADMIN_CHAT_ID):
        bot.send_message(chat_id, "⛔ У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    announce = False
    if len(args) > 1 and args[1].lower() in ("announce", "send", "1"):
        announce = True

    bot.send_message(chat_id, "Запускаю полный сброс: очищаю чаты и CSV.")

    # Список всех чатов, где есть записи
    chats_from_last = list(user_last_message.keys())
    chats_from_states = list(user_states.keys())
    chats_from_guides = list(user_rating_guide.keys())
    all_chats = list(set(chats_from_last) | set(chats_from_states) | set(chats_from_guides))

    deleted_messages = 0
    for u_chat in all_chats:
        # удаляем все сохранённые сообщения
        msg_ids = user_last_message.get(u_chat, [])[:]
        for m_id in msg_ids:
            try:
                bot.delete_message(u_chat, m_id)
                deleted_messages += 1
            except Exception:
                pass

        # удаляем отдельно запись с расшифровкой (если осталась)
        rg_id = user_rating_guide.get(u_chat)
        if rg_id:
            try:
                bot.delete_message(u_chat, rg_id)
                deleted_messages += 1
            except Exception:
                pass

        # опциональная рассылка приветствия с кнопкой (для подписчиков и/или всех чатов)
        if announce:
            try:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
                welcome_text = (
                    "Привет! 🎵\n\n"
                    "Вы прослушаете 30 музыкальных фрагментов и оцените каждый по шкале от 1 до 5.\n\n"
                    "🎁 После теста среди всех участников будет розыгрыш подарков!\n\n"
                    "_нажимая «Начать тест» вы даёте согласие на обработку персональных данных_"
                )
                sent = bot.send_message(u_chat, welcome_text, reply_markup=kb, parse_mode='Markdown')
                user_last_message.setdefault(u_chat, []).append(sent.message_id)
            except Exception:
                # если не удалось доставить (пользователь заблокировал бота и т.п.) — игнорируем
                pass

        time.sleep(0.12)  # чтобы не швырять лимиты

    # Очистка внутренних словарей (сброс прогресса)
    user_last_message.clear()
    user_rating_guide.clear()
    user_rating_time.clear()
    user_states.clear()

    # --- Очистка локального CSV: перезаписываем только заголовок ---
    try:
        headers = ['user_id','username','first_name','last_name','gender','age']
        for i in range(1,31):
            headers.append(f'track_{i}')
        header_line = ",".join(headers) + "\n"

        with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
            f.write(header_line)

        csv_cleared = True
        print("✅ Локальный CSV перезаписан заголовком.")
    except Exception as e:
        csv_cleared = False
        print("❌ Не удалось перезаписать локальный CSV:", e)

    # --- Очистка файла на GitHub (перезаписать тем же заголовком) ---
    github_cleared = False
    if GITHUB_TOKEN:
        try:
            github_cleared = overwrite_github_file(
                GITHUB_REPO,
                CSV_FILE,
                GITHUB_TOKEN,
                header_line,
                commit_message=f"Reset CSV by admin @ {datetime.utcnow().isoformat()}"
            )
        except Exception as e:
            github_cleared = False
            print("❌ Ошибка при перезаписи GitHub CSV:", e)
    else:
        print("⚠️ GITHUB_TOKEN не настроен — пропускаем очистку на GitHub.")

    # --- (опционально) уведомление подписчиков ---
    if announce:
        subs = load_subscribers()
        for sid in subs:
            try:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🚀 Начать тест", callback_data="start_test"))
                bot.send_message(sid, "Новый тест загружен! Нажмите кнопку, чтобы начать.", reply_markup=kb)
                time.sleep(0.12)
            except Exception:
                pass

    # Отправляем результат админу
    summary = (
        f"Сброс выполнен.\n"
        f"Обработано чатов: {len(all_chats)}. Удалено сообщений (прибл.): {deleted_messages}.\n"
        f"Локальный CSV очищен: {'✅' if csv_cleared else '❌'}.\n"
        f"GitHub CSV очищен: {'✅' if github_cleared else '❌ или не настроен'}.\n"
        f"announce={announce}"
    )
    bot.send_message(chat_id, summary)

# === КОМАНДЫ управления подпиской ===
@bot.message_handler(commands=['subscribe'])
def cmd_subscribe(message):
    cid = message.chat.id
    ok = add_subscriber(cid)
    if ok:
        bot.send_message(cid, "Вы подписаны на уведомления о новых тестах.")
    else:
        bot.send_message(cid, "Не удалось подписаться. Попробуйте позже.")

@bot.message_handler(commands=['unsubscribe'])
def cmd_unsubscribe(message):
    cid = message.chat.id
    ok = remove_subscriber(cid)
    if ok:
        bot.send_message(cid, "Вы отписаны от уведомлений.")
    else:
        bot.send_message(cid, "Не удалось отписаться. Попробуйте позже.")

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

# === ЗАПУСК ===
if __name__=="__main__":
    # При старте попытаемся загрузить subscribers.txt из GitHub (если есть)
    if GITHUB_TOKEN:
        try:
            download_file_from_github(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, SUBSCRIBERS_FILE)
        except Exception as e:
            print("Не удалось загрузить subscribers.txt при старте:", e)

    print("🚀 Бот запущен!")
    # Запуск под Render: webhook
    if 'RENDER' in os.environ:
        port = int(os.environ.get('PORT',10000))
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME','musicbot-knqj.onrender.com')}/webhook/{TOKEN}")
        except Exception as e:
            print(f"❌ Вебхук: {e}")
        app.run(host='0.0.0.0', port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
