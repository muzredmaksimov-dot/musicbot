import os
import asyncio
import logging
import csv
import base64
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# === НАСТРОЙКИ ===
TOKEN = "8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk"
ADMIN_CHAT_ID = "866964827"
AUDIO_FOLDER = "tracks"
CSV_FILE = "backup_results.csv"
SUBSCRIBERS_FILE = "subscribers.txt"

# GitHub репозиторий для хранения CSV и subscribers.txt
GITHUB_REPO = "muzredmaksimov-dot/testmuzicbot_results"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # обязательно задать в Render Secrets

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Буфер для CSV (запись пачками)
csv_buffer = []
BUFFER_SIZE = 10

# Кэши (загружаются при старте)
subscribers_cache = set()
csv_header = []

# Семафор: максимум 50 одновременных операций
semaphore = asyncio.Semaphore(50)

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Подсказка по оценкам
RATING_GUIDE_MESSAGE = """
1️⃣ — Не нравится  
2️⃣ — Раньше нравилась, но надоела  
3️⃣ — Нейтрально  
4️⃣ — Нравится  
5️⃣ — Любимая песня
"""

# Утилиты
async def github_read_file(repo, path_in_repo, token):
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {"Authorization": f'token {token}"'} if token else {}  # Исправлено
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = base64.b64decode(data["content"]).decode("utf-8")
                    return content
    except Exception as e:
        logger.error(f"GitHub READ error ({path_in_repo}): {e}")
        return ""

async def github_write_file(repo, path_in_repo, token, content_text, commit_message):
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {
        "Authorization": f'token {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": commit_message,
        "content": base64.b64encode(content_text.encode("utf-8")).decode("utf-8")
    }
    try:
        async with aiohttp.ClientSession() as session:
            # Проверка существования файла (получаем sha)
            async with session.get(url, headers=headers) as get_resp:
                if get_resp.status == 200:
                    payload["sha"] = (await get_resp.json())["sha"]
            # Запись
            async with session.put(url, headers=headers, json=payload) as put_resp:
                return put_resp.status in (200, 201)
    except Exception as e:
        logger.error(f"GitHub WRITE error ({path_in_repo}): {e}")
        return False

async def flush_csv_buffer():
    """Запись буфера в локальный CSV и на GitHub"""
    if not csv_buffer:
        return
    try:
        # Локальная запись
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(csv_buffer)
        # GitHub-запись (пачкой)
        csv_content = "\n".join([","join(map(str, row)) for row in csv_buffer])
        await github_write_file(
            GITHUB_REPO, CSV_FILE, GITHUB_TOKEN,
            csv_content + "\n", f"Update {CSV_FILE}"
        )
        csv_buffer.clear()
    except Exception as e:
        logger.error(f"CSV flush error: {e}")


async def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return msg
    except Exception as e:
        logger.error(f!Send message error ({chat_id}): {e}")

# Старт и подписчики
@dp.message(Command("start"))
async def start(message: types.Message):
    chat_id = message.chat.id
    user = message.from_user

    # Добавляем в подписчики (если нет в кэше)
    if str(chat_id) not in subscribers_cache:
        subscribers_cache.add(str(chat_id))
        new_text = "\n".join(sorted(subscribers_cache))
        await github_write_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN, new_text, "Add subscriber")


    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать тест", callback_data="start_test")]
    ])
    await send_message(
        chat_id,
        f"Привет, {user.first_name}! 🎵\n\n"
        "Вы прослушаете 30 музыкальных фрагментов и оцените каждый по шкале от 1 до 5.\n\n"
        "🎁 После теста среди всех участников — розыгрыш подарков!\n\n"
        "_Нажимая «Начать тест», вы даёте согласие на обработку персональных данных._",
        reply_markup=kb, parse_mode="Markdown"
    )

@dp.callback_query(F.data == "start_test")
async def start_test(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user = callback.from_user
    # Инициализация состояния
    user_states[chat_id] = {
        "user_data": {
            "user_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "gender": "",
            "age": ""
        },
        "ratings": {},  # { "1": 5, "2": 3, ... }
        "current_track": 1
    }
    await callback.answer()
    await ask_gender(chat_id)

# Анкета
async def ask_gender(chat_id):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужской", callback_data="gender_M")],
        [InlineKeyboardButton(text="Женский", callback_data="gender_F")]
    ])
    await send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@dp.callback_query(F.data.startswith("gender_"))
async def handle_gender(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    gender = "Мужской" if callback.data.endswith("M") else "Женский"
    user_states[chat_id]["user_data"]["gender"] = gender
    await ask_age(chat_id)

async def ask_age(chat_id):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="до 24", callback_data="age_до 24")],
        [InlineKeyboardButton(text="25-34", callback_data="age_25-34")],
        [InlineKeyboardButton(text="35-44", callback_data="age_35-44")],
        [InlineKeyboardButton(text="45+", callback_data="age_45+")]
    ])
    await send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@dp.callback_query(F.data.startswith("age_"))
async def handle_age(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    age = callback.data.split("_", 1)[1]
    user_states[chat_id]["user_data"]["age"] = age
    username = user_states[chat_id]["user_data"].get("username") or user_states[chat_id]["user_data"]["first_name"]

    # Отправляем подсказку по оценкам
    await send_message(chat_id, RATING_GUIDE_MESSAGE, parse_mode="Markdown")
    await asyncio.sleep(1)
    await send_message(
        chat_id,
        f"Спасибо, @{username}! 🎶\n\nТеперь начнём тест. Удачи! 🎁"
    )
    await asyncio.sleep(1)
    await send_track(chat_id)

# Отправка треков и оценки
async def send_track(chat_id):
    track_num = user_states[chat_id]['current_track']
    if track_num > 30:
        await finish_test(chat_id)
        return

    track_filename = f"{track_num:03d}.mp3"
    track_path = os.path.join(AUDIO_FOLDER, track_filename)

    await send_message(chat_id, f"🎵 Трек {track_num}/30")

    if os.path.exists(track_path):
        try:
            with open(track_path, 'rb') as audio_file:
                audio_msg = await bot.send_audio(chat_id, audio_file, title=f"Трек {track_num:03d}")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=str(i), callback_data=f"rate_{i}") for i in range(1, 6)]
            ])
            rating_msg = await send_message(chat_id, "Оцените трек:", reply_markup=kb)
        except Exception as e:
            await send_message(chat_id, f!❌ Ошибка при отправке трека: {e}")
            user_states[chat_id]['current_track'] += 1
            await send_track(chat_id)
    else:
        await send_message(chat_id, f!⚠️ Трек {track_num:03d} не найден.")
        user_states[chat_id]['current_track'] += 1
        await send_track(chat_id)


@dp.callback_query(F.data.startswith("rate_"))
async def rate(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    r = int(callback.data.split("_")[1])
    t = user_states[chat_id]["current_track"]


    # Валидация оценки
    if 1 <= r <= 5:
        user_states[chat_id]["ratings"][str(t)] = r
        user_states[chat_id]["current_track"] += 1
        await callback.answer()
        await send_track(chat_id)
    else:
        await callback.answer("Некорректная оценка!", show_alert=True)


# Завершение теста
async def finish_test(chat_id):
    user = user_states[chat_id]["user_data"]
    ratings = user_states[chat_id]["ratings"]

    # Формируем строку для CSV: все 30 треков
    track_ratings = []
    for track_num in range(1, 31):
        track_key = str(track_num)
        track_rating = ratings.get(track_key, "")
        track_ratings.append(track_rating)

    row = [
        user["user_id"],
        user.get("username", ""),
        user.get("first_name", ""),
        user.get("last_name", ""),
        user["gender"],
        user["age"]
    ] + track_ratings

    # Добавляем в буфер
    csv_buffer.append(row)

    # Периодическая запись буфера
    if len(csv_buffer) >= BUFFER_SIZE:
        await flush_csv_buffer()

    await send_message(
        chat_id,
        f!🎉 @{user.get('username') or user['first_name']}, тест завершён!\n\n"
        "Следите за новостями в @RadioMIR_Efir 🎁"
    )

    # Очищаем состояние
    user_states.pop(chat_id, None)


# Команды администратора
@dp.message(Command("flush_buffer"))
async def flush_buffer_command(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ADMIN_CHAT_ID:
        await bot.send_message(chat_id, "⛔ Нет доступа.")
        return

    if not csv_buffer:
        await bot.send_message(chat_id, "📭 Буфер пуст. Нет данных для записи.")
        return

    try:
        # Принудительно записываем буфер
        await flush_csv_buffer()
        await bot.send_message(
            chat_id,
            f!✅ Буфер записан успешно!\n"
            f!Сохранено записей: {len(csv_buffer)}\n"
            f!Файл обновлён на GitHub."
        )
        logger.info(f"Администратор {chat_id} принудительно записал буфер ({len(csv_buffer)} записей)")
    except Exception as e:
        await bot.send_message(chat_id, f!❌ Ошибка при записи буфера: {e}")
        logger.error(f"Ошибка принудительной записи буфера: {e}")


@dp.message(Command("reset_all"))
async def reset_all(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ADMIN_CHAT_ID:
        await bot.send_message(chat_id, "⛔ Нет доступа.")
        return

    args = message.text.split()
    announce = len(args) > 1 and args[1].lower() in ("announce", "1", "send")

    # Принудительная запись буфера перед сбросом
    if csv_buffer:
        try:
            await flush_csv_buffer()
            logger.info(f!Записано {len(csv_buffer)} записей перед сбросом")
        except Exception as e:
            logger.error(f!Ошибка записи буфера перед сбросом: {e}")

    # Очистка буфера
    csv_buffer.clear()

    # Пересоздание CSV с заголовком
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "user_id", "username", "first_name", "last_name", "gender", "age"
        ] + [f"track_{i}" for i in range(1, 31)])

    # Обновление файла на GitHub
    header_row = ",".join([
        "user_id", "username", "first_name", "last_name", "gender", "age"
    ] + [f!track_{i}" for i in range(1, 31)]) + "\n"
    await github_write_file(
        GITHUB_REPO, CSV_FILE, GITHUB_TOKEN,
        header_row, "Reset CSV"
    )

    if announce:
        sent_count = 0
        for s in subscribers_cache:
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Начать тест", callback_data="start_test")]
                ])
                await bot.send_message(
                    int(s),
                    "🎧 Новый музыкальный тест уже готов!\n\n"
                    "Пройди и оцени 30 треков — твоё мнение важно для радио МИР 🎶",
                    reply_markup=kb
                )
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка отправки подписчику {s}: {e}")
        await bot.send_message(ADMIN_CHAT_ID, f!✅ Рассылка выполнена ({sent_count} пользователей).")
    else:
        await bot.send_message(ADMIN_CHAT_ID, "✅ Все данные очищены (без рассылки).")


@dp.message(Command("results"))
async def send_results(message: types.Message):
    chat_id = message.chat.id
    if chat_id != ADMIN_CHAT_ID:
        await bot.send_message(chat_id, "⛔ Нет доступа.")
        return

    try:
        with open(CSV_FILE, "rb") as f:
            await bot.send_document(chat_id, f, caption="📊 Текущие результаты теста")
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Ошибка при отправке файла: {e}")
        logger.error(f"Send results error: {e}")


# Глобальные переменные
user_states = {}  # Хранилище состояний (в памяти)

# Запуск бота
async def main():
    # Загрузка кэша при старте
    global subscribers_cache, csv_header

    # Читаем подписчиков из GitHub
    subscribers_text = await github_read_file(GITHUB_REPO, SUBSCRIBERS_FILE, GITHUB_TOKEN)
    if subscribers_text:
        subscribers_cache = set(s.strip() for s in subscribers_text.split("\n") if s.strip())
    else:
        subscribers_cache = set()

    # Читаем заголовки CSV (если файл существует локально)
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                csv_header = next(csv.reader(f))
        except:
            csv_header = []
    else:
        csv_header = [
            "user_id", "username", "first_name", "last_name", "gender", "age"
        ] + [f"track_{i}" for i in range(1, 31)]

    # Запуск polling
    await dp.start_polling(bot)

# Точка входа
if __name__ == "__main__":
    asyncio.run(main())


