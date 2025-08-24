import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from telebot import types

# === Настройки ===
TOKEN = '8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk'
AUDIO_FOLDER = 'audio'
SPREADSHEET_NAME = 'music_testing'
WORKSHEET_NAME = 'track_list'

# === Google Sheets авторизация ===
scope = ["https://spreadsheets.google.com/feeds", 
         "https://www.googleapis.com/auth/drive",
         "https://www.googleapis.com/auth/spreadsheets"]
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).worksheet(WORKSHEET_NAME)

# === Загрузка CSV-файла с треками ===
with open('track_list.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    track_data = {row['track_number']: row['title'] for row in reader}

# === Бот ===
bot = telebot.TeleBot(TOKEN)

# === Словари состояния ===
user_progress = {}        # какой трек у кого сейчас
user_rated_tracks = {}    # что уже оценено
user_metadata = {}        # пол/возраст
user_column = {}          # столбец для каждого пользователя
last_audios = {}          # message_id последнего аудио

# === Вспомогательные функции ===
def prepare_spreadsheet():
    """Подготавливает структуру таблицы если она пустая"""
    # Добавляем заголовки если их нет
    headers = sheet.row_values(1)
    if not headers:
        sheet.update('A1', ['Track Number', 'Track Title'])
    
    # Заполняем номера и названия треков если их нет
    all_values = sheet.get_all_values()
    if len(all_values) < 3:  # Если только заголовки или пусто
        for num, title in track_data.items():
            row = int(num) + 2  # +2 потому что первая строка - заголовки, вторая - демография
            sheet.update_cell(row, 1, num)
            sheet.update_cell(row, 2, title)

def get_next_available_column():
    """Находит следующий свободный столбец"""
    headers = sheet.row_values(1)
    return len(headers) + 1 if headers else 3

def setup_user_column(chat_id, username):
    """Настраивает столбец для пользователя"""
    col = get_next_available_column()
    user_column[chat_id] = col
    
    # Записываем заголовок столбца (username или user_id)
    header_text = f"@{username}" if username else f"user_{chat_id}"
    sheet.update_cell(1, col, header_text)
    
    # Записываем демографические данные
    sheet.update_cell(2, col, f"{user_metadata[chat_id]['gender']}, {user_metadata[chat_id]['age']}")
    
    return col

# === Опрос перед тестом ===
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    welcome_handler(message)

@bot.message_handler(func=lambda message: message.chat.id not in user_metadata)
def welcome_handler(message):
    chat_id = message.chat.id

    # Убираем клавиатуру, если была
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, "👋 Добро пожаловать в музыкальный тест!", reply_markup=remove_kb)

    # Сообщение с описанием и кнопкой
    welcome_text = (
        "Ты услышишь несколько коротких треков. Оцени каждый по шкале от 1 до 5:\n\n"
        "Но сначала давай познакомимся 🙂"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Начать", callback_data="start_test"))

    bot.send_message(chat_id, welcome_text, reply_markup=kb)
    user_metadata[chat_id] = {}  # Инициализируем как словарь

# Обработка нажатия кнопки "Начать"
@bot.callback_query_handler(func=lambda call: call.data == 'start_test')
def handle_start_button(call):
    chat_id = call.message.chat.id

    # Удаляем кнопку (оставляя сообщение)
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)

    # Подготавливаем таблицу
    prepare_spreadsheet()
    
    # Запускаем сценарий
    user_metadata[chat_id] = {}
    user_progress[chat_id] = 1  # Начинаем с первого трека
    user_rated_tracks[chat_id] = set()
    ask_gender(chat_id)

# Запрос пола
def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_M"),
        types.InlineKeyboardButton("Женский", callback_data="gender_F")
    )
    bot.send_message(chat_id, "Укажи свой пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['gender'] = c.data.split('_',1)[1]
    bot.delete_message(chat_id, c.message.message_id)
    ask_age(chat_id)

def ask_age(chat_id):
    opts = ["до 24", "25-34", "35-44", "45-54", "55+"]
    kb = types.InlineKeyboardMarkup(row_width=3)
    for o in opts:
        kb.add(types.InlineKeyboardButton(o, callback_data=f"age_{o}"))
    bot.send_message(chat_id, "Укажи свой возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_metadata[chat_id]['age'] = c.data.split('_',1)[1]
    bot.delete_message(chat_id, c.message.message_id)

    # Настраиваем столбец для пользователя
    username = c.from_user.username
    col = setup_user_column(chat_id, username)

    # Запускаем тест
    bot.send_message(chat_id, "🎵 Начинаем музыкальный тест!\n\nОцени каждый трек по шкале от 1 до 5:\n\n1 ★ - Совсем не нравится\n2 ★★ - Скорее не нравится\n3 ★★★ - Нейтрально\n4 ★★★★ - Нравится\n5 ★★★★★ - Очень нравится")
    send_next_track(chat_id)

# === Отправка и оценка треков ===
def send_next_track(chat_id):
    n = user_progress.get(chat_id, 1)
    path = os.path.join(AUDIO_FOLDER, f"{n:03}.mp3")
    
    if not os.path.exists(path):
        # Тест завершен
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Начать сначала", callback_data="restart"))
        bot.send_message(chat_id, "🎉 Тест завершён! Спасибо за участие!\n\nРезультаты сохранены. Следите за новостями для розыгрыша подарков!", reply_markup=kb)
        return

    # Отправляем аудио
    try:
        with open(path, 'rb') as f:
            m = bot.send_audio(chat_id, f, caption=f"Трек №{n}")
            last_audios[chat_id] = m.message_id
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка при отправке трека: {e}")
        return

    # Кнопки для оценки
    kb = types.InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 6):
        buttons.append(types.InlineKeyboardButton(str(i), callback_data=f"rate_{i}"))
    kb.add(*buttons)
    bot.send_message(chat_id, "Оцените этот трек:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rate(c):
    chat_id = c.message.chat.id
    n = user_progress.get(chat_id, 1)
    
    if n in user_rated_tracks[chat_id]:
        bot.answer_callback_query(c.id, "Этот трек уже оценен", show_alert=True)
        return

    score = c.data.split('_', 1)[1]
    col = user_column.get(chat_id)
    
    if not col:
        bot.answer_callback_query(c.id, "Ошибка: не найден столбец для сохранения", show_alert=True)
        return

    # Сохраняем оценку в Google Таблицу (строка = номер трека + 2)
    try:
        sheet.update_cell(n + 2, col, score)
    except Exception as e:
        bot.answer_callback_query(c.id, f"Ошибка сохранения: {e}", show_alert=True)
        return

    user_rated_tracks[chat_id].add(n)
    
    # Удаляем сообщение с аудио и кнопками
    try:
        bot.delete_message(chat_id, last_audios[chat_id])
    except:
        pass
    try:
        bot.delete_message(chat_id, c.message.message_id)
    except:
        pass

    # Переходим к следующему треку
    user_progress[chat_id] = n + 1
    send_next_track(chat_id)

@bot.callback_query_handler(func=lambda c: c.data == "restart")
def handle_restart(c):
    chat_id = c.message.chat.id
    bot.delete_message(chat_id, c.message.message_id)
    
    # Очищаем состояние пользователя
    if chat_id in user_metadata:
        del user_metadata[chat_id]
    if chat_id in user_progress:
        del user_progress[chat_id]
    if chat_id in user_rated_tracks:
        del user_rated_tracks[chat_id]
    if chat_id in user_column:
        del user_column[chat_id]
    
    # Запускаем заново
    welcome_handler(c.message)

@bot.message_handler(func=lambda m: True)
def fallback(m):
    bot.send_message(m.chat.id, "Для начала теста нажмите /start")

if __name__ == "__main__":
    print("Бот запущен и готов к работе!")
    bot.polling(none_stop=True)
