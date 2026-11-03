
import os
import time
import csv
import io
import base64
import threading
import requests
import telebot

from telebot import types
from flask import Flask, request


# ==================================================
# НАСТРОЙКИ
# ==================================================

TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise RuntimeError("TOKEN environment variable is required")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

ADMIN_CHAT_ID = "866964827"

AUDIO_FOLDER = "tracks"
CSV_FILE = "backup_results.csv"
SUBSCRIBERS_FILE = "subscribers.txt"

GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"

GITHUB_API = "https://api.github.com"

CSV_HEADERS = [
    "user_id",
    "username",
    "first_name",
    "last_name",
    "gender",
    "age",
    "phone"
] + [f"track_{i}" for i in range(1, 31)]


# ==================================================
# ЗАПУСК БОТА
# ==================================================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)


# ==================================================
# ХРАНИЛИЩЕ
# ==================================================

user_last_message = {}
user_rating_guide = {}
user_states = {}

buffer_lock = threading.Lock()
result_buffer = []


# ==================================================
# ПОДСКАЗКА ПО ОЦЕНКАМ
# ==================================================

RATING_GUIDE_MESSAGE = """
1️⃣ - Не нравится
2️⃣ - Раньше нравилась, но надоела
3️⃣ - Нейтрально
4️⃣ - Нравится
5️⃣ - Любимая песня
"""


# ==================================================
# GITHUB: ОБЩИЕ ФУНКЦИИ
# ==================================================

def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    return headers


def github_read_file(repo, path_in_repo, token=None):
    if not token:
        print("GitHub: отсутствует GITHUB_TOKEN.")
        return ""

    url = f"{GITHUB_API}/repos/{repo}/contents/{path_in_repo}"

    headers = github_headers()

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if response.status_code == 200:
            content_b64 = response.json().get("content", "")
            return base64.b64decode(content_b64).decode("utf-8")

        if response.status_code == 404:
            return ""

        print(
            "Ошибка чтения GitHub:",
            response.status_code,
            response.text
        )

        return ""

    except Exception as e:
        print("Ошибка github_read_file:", repr(e))
        return ""


def github_write_file(
    repo,
    path_in_repo,
    token,
    content_text,
    commit_message
):
    if not token:
        print("GitHub: отсутствует GITHUB_TOKEN.")
        return False

    url = f"{GITHUB_API}/repos/{repo}/contents/{path_in_repo}"

    headers = github_headers()

    try:
        # Получаем SHA существующего файла
        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if response.status_code == 200:
            sha = response.json().get("sha")

        elif response.status_code == 404:
            sha = None

        else:
            print(
                "GitHub GET error:",
                response.status_code,
                response.text
            )
            return False

        payload = {
            "message": commit_message,
            "content": base64.b64encode(
                content_text.encode("utf-8")
            ).decode("utf-8")
        }

        if sha:
            payload["sha"] = sha

        # Записываем файл
        result = requests.put(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        if result.status_code in (200, 201):
            print(f"GitHub: файл {path_in_repo} сохранён.")
            return True

        print(
            "GitHub PUT error:",
            result.status_code,
            result.text
        )

        return False

    except Exception as e:
        print("Ошибка github_write_file:", repr(e))
        return False


def github_append_line(
    repo,
    path_in_repo,
    token,
    line,
    header_if_missing=None
):
    existing = github_read_file(repo, path_in_repo, token)

    if not existing:
        new_text = (
            (header_if_missing + "\n") if header_if_missing else ""
        ) + line + "\n"

    else:
        if not existing.endswith("\n"):
            existing += "\n"

        new_text = existing + line + "\n"

    return github_write_file(
        repo,
        path_in_repo,
        token,
        new_text,
        f"Update {path_in_repo}"
    )


# ==================================================
# СОХРАНЕНИЕ РЕЗУЛЬТАТОВ ТЕСТА
# ==================================================

def push_buffer_to_github():

    with buffer_lock:

        if not result_buffer:
            print("FLUSH: буфер пуст.")
            return True, 0, "Новых результатов нет."

        if not GITHUB_TOKEN:
            error = "Не задан GITHUB_TOKEN."
            print(error)
            return False, 0, error

        url = (
            f"{GITHUB_API}/repos/"
            f"{GITHUB_REPO}/contents/{CSV_FILE}"
        )

        headers = github_headers()

        try:
            # 1. Получаем актуальный CSV с GitHub

            response = requests.get(
                url,
                headers=headers,
                timeout=20
            )

            if response.status_code == 200:

                file_data = response.json()

                sha = file_data.get("sha")

                content_b64 = file_data.get("content", "")

                if not content_b64:
                    error = "GitHub вернул пустое содержимое CSV."
                    print(error)
                    return False, 0, error

                existing_text = base64.b64decode(
                    content_b64
                ).decode("utf-8")

            elif response.status_code == 404:

                sha = None
                existing_text = ""

            else:

                error = (
                    f"Ошибка чтения GitHub: "
                    f"{response.status_code} {response.text}"
                )

                print(error)

                return False, 0, error

            # 2. Формируем новые строки CSV

            output = io.StringIO(newline="")

            writer = csv.writer(output)

            if not existing_text.strip():
                writer.writerow(CSV_HEADERS)

            rows_to_save = list(result_buffer)

            writer.writerows(rows_to_save)

            new_rows = output.getvalue()

            # 3. Объединяем старые и новые данные

            if existing_text.strip():

                if not existing_text.endswith("\n"):
                    existing_text += "\n"

                new_text = existing_text + new_rows

            else:

                new_text = new_rows

            # 4. Подготавливаем запись в GitHub

            payload = {
                "message": "Append new test results",
                "content": base64.b64encode(
                    new_text.encode("utf-8")
                ).decode("utf-8")
            }

            if sha:
                payload["sha"] = sha

            # 5. Отправляем обновлённый CSV

            saved_response = requests.put(
                url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if saved_response.status_code not in (200, 201):

                error = (
                    f"Ошибка записи GitHub: "
                    f"{saved_response.status_code} "
                    f"{saved_response.text}"
                )

                print(error)

                return False, 0, error

            # 6. GitHub подтвердил запись.
            # Обновляем локальную копию.

            try:
                with open(
                    CSV_FILE,
                    "w",
                    encoding="utf-8",
                    newline=""
                ) as f:
                    f.write(new_text)

            except Exception as e:
                print(
                    "Не удалось обновить локальный CSV:",
                    repr(e)
                )

            # 7. Очищаем буфер только после успешной записи

            saved_count = len(rows_to_save)

            result_buffer.clear()

            print(
                f"FLUSH: успешно сохранено строк: {saved_count}"
            )

            return True, saved_count, "Сохранение выполнено."

        except Exception as e:

            error = f"Ошибка сохранения: {repr(e)}"

            print(error)

            return False, 0, error


# ==================================================
# СООБЩЕНИЯ
# ==================================================

def send_message(
    chat_id,
    text,
    reply_markup=None,
    parse_mode=None
):
    try:
        msg = bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )

        user_last_message.setdefault(
            chat_id,
            []
        ).append(msg.message_id)

        return msg

    except Exception as e:
        print("Ошибка отправки:", repr(e))
        return None


def cleanup_chat(chat_id, keep_rating_guide=False):

    try:
        messages_to_keep = (
            [user_rating_guide.get(chat_id)]
            if keep_rating_guide
            else []
        )

        for msg_id in user_last_message.get(chat_id, []):

            if msg_id not in messages_to_keep and msg_id:

                try:
                    bot.delete_message(chat_id, msg_id)

                except Exception:
                    pass

        user_last_message[chat_id] = messages_to_keep

    except Exception as e:
        print("Ошибка очистки:", repr(e))


def send_rating_guide(chat_id):

    if chat_id in user_rating_guide:

        try:
            bot.delete_message(
                chat_id,
                user_rating_guide[chat_id]
            )

        except Exception:
            pass

    msg = send_message(
        chat_id,
        RATING_GUIDE_MESSAGE
    )

    if msg:
        user_rating_guide[chat_id] = msg.message_id


# ==================================================
# СТАРТ
# ==================================================

@bot.message_handler(commands=["start"])
def start(message):

    chat_id = message.chat.id
    user = message.from_user

    try:

        subscribers_text = github_read_file(
            GITHUB_REPO,
            SUBSCRIBERS_FILE,
            GITHUB_TOKEN
        )

        subscribers = set(
            s.strip()
            for s in subscribers_text.split("\n")
            if s.strip()
        )

        if str(chat_id) not in subscribers:

            subscribers.add(str(chat_id))

            github_write_file(
                GITHUB_REPO,
                SUBSCRIBERS_FILE,
                GITHUB_TOKEN,
                "\n".join(sorted(subscribers)),
                "Add new subscriber"
            )

    except Exception as e:
        print("Ошибка subscribers:", repr(e))

    cleanup_chat(chat_id)

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "🚀 Начать тест",
            callback_data="start_test"
        )
    )

    send_message(
        chat_id,
        f"Привет, {user.first_name}! 🎵\n\n"
        "Вы прослушаете 30 музыкальных фрагментов "
        "и оцените каждый по шкале от 1 до 5.\n\n"
        "🎁 После теста среди всех участников — "
        "розыгрыш беспроводных наушников!\n\n"
        "_Нажимая «Начать тест», вы даёте согласие "
        "на обработку персональных данных._",
        reply_markup=kb,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "start_test"
)
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
        bot.delete_message(
            chat_id,
            c.message.message_id
        )

    except Exception:
        pass

    bot.answer_callback_query(c.id)

    ask_gender(chat_id)


# ==================================================
# АНКЕТА
# ==================================================

def ask_gender(chat_id):

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "Мужской",
            callback_data="gender_M"
        ),
        types.InlineKeyboardButton(
            "Женский",
            callback_data="gender_F"
        )
    )

    send_message(
        chat_id,
        "Укажите ваш пол:",
        reply_markup=kb
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("gender_")
)
def handle_gender(c):

    chat_id = c.message.chat.id

    if chat_id not in user_states:
        bot.answer_callback_query(
            c.id,
            "Сначала нажмите /start."
        )
        return

    gender = (
        "Мужской"
        if c.data.endswith("M")
        else "Женский"
    )

    user_states[chat_id]["user_data"]["gender"] = gender

    try:
        bot.delete_message(
            chat_id,
            c.message.message_id
        )

    except Exception:
        pass

    bot.answer_callback_query(c.id)

    ask_age(chat_id)


def ask_age(chat_id):

    kb = types.InlineKeyboardMarkup(row_width=2)

    for option in [
        "до 24",
        "25-34",
        "35-44",
        "45-54",
        "55+"
    ]:

        kb.add(
            types.InlineKeyboardButton(
                option,
                callback_data=f"age_{option}"
            )
        )

    send_message(
        chat_id,
        "Укажите ваш возраст:",
        reply_markup=kb
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("age_")
)
def handle_age(c):

    chat_id = c.message.chat.id

    if chat_id not in user_states:
        bot.answer_callback_query(
            c.id,
            "Сначала нажмите /start."
        )
        return

    user_states[chat_id]["user_data"]["age"] = (
        c.data.split("_", 1)[1]
    )

    try:
        bot.delete_message(
            chat_id,
            c.message.message_id
        )

    except Exception:
        pass

    bot.answer_callback_query(c.id)

    ask_phone(chat_id)


# ==================================================
# ТЕЛЕФОН ДЛЯ РОЗЫГРЫША
# ==================================================

def ask_phone(chat_id):

    user_states[chat_id]["awaiting_phone"] = True

    kb = types.InlineKeyboardMarkup()

    kb.add(
        types.InlineKeyboardButton(
            "Пропустить",
            callback_data="skip_phone"
        )
    )

    send_message(
        chat_id,
        "🎁 Участвуйте в розыгрыше призов!\n\n"
        "Оставьте номер телефона, чтобы мы могли "
        "связаться с вами в случае победы.\n\n"
        "Номер будет использоваться только для связи "
        "по итогам розыгрыша. Вы можете пропустить этот шаг.",
        reply_markup=kb
    )


def begin_music_test(chat_id):

    user_states[chat_id]["awaiting_phone"] = False

    username = (
        user_states[chat_id]["user_data"].get("username")
        or user_states[chat_id]["user_data"]["first_name"]
    )

    send_message(
        chat_id,
        f"Спасибо, {username}! 🎶\n\n"
        "Теперь начнем тест. Удачи! 🎁"
    )

    time.sleep(1)

    send_rating_guide(chat_id)

    send_track(chat_id)


@bot.message_handler(
    func=lambda message: (
        message.chat.id in user_states
        and user_states[message.chat.id].get(
            "awaiting_phone",
            False
        )
    ),
    content_types=["text"]
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


@bot.callback_query_handler(
    func=lambda c: c.data == "skip_phone"
)
def skip_phone(c):

    chat_id = c.message.chat.id

    if chat_id not in user_states:

        bot.answer_callback_query(
            c.id,
            "Начните заново командой /start."
        )

        return

    user_states[chat_id]["user_data"]["phone"] = ""

    user_states[chat_id]["awaiting_phone"] = False

    try:
        bot.delete_message(
            chat_id,
            c.message.message_id
        )

    except Exception:
        pass

    bot.answer_callback_query(c.id)

    begin_music_test(chat_id)


# ==================================================
# ТРЕКИ
# ==================================================

def send_track(chat_id):

    cleanup_chat(
        chat_id,
        keep_rating_guide=True
    )

    track_num = user_states[chat_id]["current_track"]

    if track_num > 30:

        finish_test(chat_id)

        return

    path = os.path.join(
        AUDIO_FOLDER,
        f"{track_num:03d}.mp3"
    )

    send_message(
        chat_id,
        f"🎵 Трек {track_num}/30"
    )

    if os.path.exists(path):

        try:

            with open(path, "rb") as f:

                audio = bot.send_audio(
                    chat_id,
                    f,
                    title=f"Трек {track_num:03d}"
                )

                user_last_message.setdefault(
                    chat_id,
                    []
                ).append(audio.message_id)

            kb = types.InlineKeyboardMarkup(row_width=5)

            kb.add(
                *[
                    types.InlineKeyboardButton(
                        str(i),
                        callback_data=f"rate_{i}"
                    )
                    for i in range(1, 6)
                ]
            )

            msg = send_message(
                chat_id,
                "Оцените трек:",
                reply_markup=kb
            )

            if msg:
                user_last_message[chat_id].append(
                    msg.message_id
                )

        except Exception as e:

            print("Ошибка отправки трека:", repr(e))

            send_message(
                chat_id,
                "⚠️ Не удалось отправить аудио. "
                "Попробуйте позже."
            )

    else:

        print(f"Файл трека не найден: {path}")

        user_states[chat_id]["current_track"] += 1

        send_track(chat_id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("rate_")
)
def rate(c):

    chat_id = c.message.chat.id

    if chat_id not in user_states:

        bot.answer_callback_query(
            c.id,
            "Тест не найден. Нажмите /start."
        )

        return

    r = int(c.data.split("_")[1])

    if r not in range(1, 6):
        bot.answer_callback_query(c.id)
        return

    t = user_states[chat_id]["current_track"]

    if t > 30:
        bot.answer_callback_query(c.id)
        return

    user_states[chat_id]["ratings"][str(t)] = r

    user_states[chat_id]["current_track"] += 1

    try:
        bot.delete_message(
            chat_id,
            c.message.message_id
        )

    except Exception:
        pass

    bot.answer_callback_query(c.id)

    send_track(chat_id)


# ==================================================
# ФИНАЛ ТЕСТА
# ==================================================

def finish_test(chat_id):

    if chat_id not in user_states:
        return

    user = user_states[chat_id]["user_data"]

    ratings = user_states[chat_id]["ratings"]

    row = [
        user["user_id"],
        user.get("username", ""),
        user.get("first_name", ""),
        user.get("last_name", ""),
        user["gender"],
        user["age"],
        user.get("phone", "")
    ] + [
        ratings.get(str(i), "")
        for i in range(1, 31)
    ]

    with buffer_lock:
        result_buffer.append(row)

    bot.send_message(
        ADMIN_CHAT_ID,
        f"✅ Пользователь "
        f"{user.get('username') or user['first_name']} "
        f"завершил тест."
    )

    send_message(
        chat_id,
        f"🎉 @{user.get('username') or user['first_name']}, "
        "тест завершён!\n\n"
        "Следите за новостями в @RadioMIR_Efir 🎁"
    )

    # Удаляем состояние завершённого теста
    user_states.pop(chat_id, None)


# ==================================================
# СБРОС РЕЗУЛЬТАТОВ
# ==================================================

@bot.message_handler(commands=["reset_all"])
def reset_all(message):

    if str(message.chat.id) != ADMIN_CHAT_ID:

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    args = message.text.split()

    announce = (
        len(args) > 1
        and args[1].lower() in ("announce", "1", "send")
    )

    # Формируем пустой CSV с заголовками

    empty_csv = io.StringIO(newline="")

    writer = csv.writer(empty_csv)

    writer.writerow(CSV_HEADERS)

    empty_csv_text = empty_csv.getvalue()

    # Очищаем GitHub и буфер под блокировкой

    with buffer_lock:

        saved = github_write_file(
            GITHUB_REPO,
            CSV_FILE,
            GITHUB_TOKEN,
            empty_csv_text,
            "Reset CSV"
        )

        if not saved:

            bot.send_message(
                ADMIN_CHAT_ID,
                "⚠️ Не удалось очистить CSV на GitHub. "
                "Локальные данные и буфер не изменены."
            )

            return

        result_buffer.clear()

        try:

            with open(
                CSV_FILE,
                "w",
                encoding="utf-8",
                newline=""
            ) as f:

                f.write(empty_csv_text)

        except Exception as e:

            print("Ошибка локального сброса CSV:", repr(e))

    if announce:

        subs_text = github_read_file(
            GITHUB_REPO,
            SUBSCRIBERS_FILE,
            GITHUB_TOKEN
        )

        subs = [
            s.strip()
            for s in subs_text.split("\n")
            if s.strip()
        ]

        sent = 0

        for s in subs:

            try:

                kb = types.InlineKeyboardMarkup()

                kb.add(
                    types.InlineKeyboardButton(
                        "🚀 Начать тест",
                        callback_data="start_test"
                    )
                )

                bot.send_message(
                    int(s),
                    "🎧 Новый музыкальный тест уже готов!\n\n"
                    "Пройди и оцени 30 треков — "
                    "твое мнение важно для радио МИР 🎶",
                    reply_markup=kb
                )

                sent += 1

                time.sleep(0.1)

            except Exception:
                pass

        bot.send_message(
            ADMIN_CHAT_ID,
            f"✅ Рассылка выполнена ({sent} пользователей)."
        )

    else:

        bot.send_message(
            ADMIN_CHAT_ID,
            "✅ Все данные очищены. Буфер также очищен."
        )


# ==================================================
# КОМАНДА /FLUSH
# ==================================================

@bot.message_handler(commands=["flush"])
def flush_command(message):

    if str(message.chat.id) != ADMIN_CHAT_ID:

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    success, count, info = push_buffer_to_github()

    if success and count > 0:

        bot.send_message(
            ADMIN_CHAT_ID,
            f"💾 Успешно сохранено результатов: {count}."
        )

    elif success:

        bot.send_message(
            ADMIN_CHAT_ID,
            f"ℹ️ {info}"
        )

    else:

        bot.send_message(
            ADMIN_CHAT_ID,
            "⚠️ Не удалось сохранить CSV.\n\n"
            f"Причина: {info}\n\n"
            "Данные остались в оперативном буфере."
        )


# ==================================================
# АВТОМАТИЧЕСКОЕ СОХРАНЕНИЕ
# ==================================================

def auto_flush():

    while True:

        time.sleep(120)

        success, count, info = push_buffer_to_github()

        if not success:

            print(
                "AUTO FLUSH ERROR:",
                info
            )


threading.Thread(
    target=auto_flush,
    daemon=True
).start()


# ==================================================
# КОМАНДА /RESULTS
# ==================================================

@bot.message_handler(commands=["results"])
def send_results(message):

    chat_id = message.chat.id

    if str(chat_id) != ADMIN_CHAT_ID:

        bot.send_message(
            chat_id,
            "⛔ У вас нет доступа к этой команде."
        )

        return

    # Сначала скачиваем актуальный CSV с GitHub

    if GITHUB_TOKEN:

        try:

            url = (
                f"{GITHUB_API}/repos/"
                f"{GITHUB_REPO}/contents/{CSV_FILE}"
            )

            response = requests.get(
                url,
                headers=github_headers(),
                timeout=20
            )

            if response.status_code == 200:

                content_b64 = response.json().get("content", "")

                content_bytes = base64.b64decode(
                    content_b64
                )

                try:

                    with io.BytesIO(content_bytes) as file:

                        file.name = CSV_FILE

                        bot.send_document(
                            chat_id,
                            file,
                            caption="backup_results.csv (from GitHub)"
                        )

                    return

                except Exception as e:

                    print(
                        "Ошибка отправки CSV из GitHub:",
                        repr(e)
                    )

            else:

                print(
                    "GitHub /results error:",
                    response.status_code,
                    response.text
                )

        except Exception as e:

            print(
                "Ошибка загрузки CSV с GitHub:",
                repr(e)
            )

    # Если GitHub недоступен — пробуем локальный файл

    try:

        if os.path.exists(CSV_FILE):

            with open(CSV_FILE, "rb") as f:

                bot.send_document(
                    chat_id,
                    f,
                    caption="backup_results.csv (local)"
                )

        else:

            bot.send_message(
                chat_id,
                "❌ Файл backup_results.csv пока не создан."
            )

    except Exception as e:

        bot.send_message(
            chat_id,
            f"⚠️ Ошибка при отправке файла: {e}"
        )


# ==================================================
# WEBHOOK И FLASK
# ==================================================

@app.route(
    f"/webhook/{TOKEN}",
    methods=["POST"]
)
def webhook():

    if request.headers.get("content-type", "").startswith(
        "application/json"
    ):

        try:

            update = telebot.types.Update.de_json(
                request.get_data().decode("utf-8")
            )

            bot.process_new_updates([update])

            return ""

        except Exception as e:

            print("Ошибка обработки webhook:", repr(e))

            return "Internal Server Error", 500

    return "Bad Request", 400


@app.route("/")
def index():
    return "Music Test Bot running!"


@app.route("/health")
def health():
    return "OK"


# ==================================================
# ЗАПУСК
# ==================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )

