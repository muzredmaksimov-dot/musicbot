import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from telebot import types
from datetime import datetime

# === Настройки ===
TOKEN = '8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk'
AUDIO_FOLDER = 'audio'
SPREADSHEET_NAME = 'music_testing'
WORKSHEET_NAME = 'track_list'

# === Google Sheets авторизация ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Проверяем наличие файла creds.json
if not os.path.exists('creds.json'):
    print("Ошибка: Файл creds.json не найден!")
else:
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
        client = gspread.authorize(creds)
        
        # Открываем таблицу
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
            print("Успешно подключено к Google Таблице!")
        except gspread.SpreadsheetNotFound:
            print(f"Таблица '{SPREADSHEET_NAME}' не найдена!")
        except gspread.WorksheetNotFound:
            print(f"Лист '{WORKSHEET_NAME}' не найден!")
            
    except Exception as e:
        print(f"Ошибка авторизации: {e}")

# === Загрузка CSV-файла с треками ===
try:
    with open('track_list.csv', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        track_data = {row['track_number']: row['title'] for row in reader}
    print(f"Загружено {len(track_data)} треков")
except FileNotFoundError:
    track_data = {}
    print("Предупреждение: track_list.csv не найден")
except Exception as e:
    track_data = {}
    print(f"Ошибка загрузки track_list.csv: {e}")

# === Бот ===
bot = telebot.TeleBot(TOKEN)

# === Словари состояния ===
user_states = {}

def save_to_google_sheets(user_data, ratings):
    """Сохраняет результаты в Google Таблицу"""
    try:
        # Получаем все данные из таблицы
        all_data = worksheet.get_all_values()
        
        # Находим следующий свободный столбец
        if not all_data:
            next_col = 1
        else:
            next_col = len(all_data[0]) + 1
        
        # Подготавливаем данные для записи
        user_info = [
            user_data['user_id'],
            f"@{user_data['username']}" if user_data.get('username') else '',
            user_data['gender'],
            user_data['age'],
            user_data['timestamp']
        ]
        
        # Добавляем оценки для каждого трека
        for i in range(1, len(track_data) + 1):
            user_info.append(ratings.get(str(i), ''))
        
        # Записываем данные
        for row_idx, value in enumerate(user_info, start=1):
            worksheet.update_cell(row_idx, next_col, value)
        
        print(f"Данные сохранены в колонку {next_col}")
        return True
        
    except Exception as e:
        print(f"Ошибка сохранения в Google Таблицу: {e}")
        return False

def prepare_spreadsheet():
    """Подготавливает структуру таблицы"""
    try:
        # Создаем заголовки если таблица пустая
        if not worksheet.get_all_values():
            headers = ['User ID', 'Username', 'Gender', 'Age', 'Timestamp']
            for i in range(1, len(track_data) + 1):
                headers.append(f'Track {i}')
            worksheet.update('A1', [headers])
            
            # Заполняем номера и названия треков
            for num, title in track_data.items():
                row = int(num) + 1  # +1 потому что первая строка - заголовки
                worksheet.update_cell(row, 1, f"Track {num}")
                worksheet.update_cell(row, 2, title)
                
        print("Таблица подготовлена")
        
    except Exception as e:
        print(f"Ошибка подготовки таблицы: {e}")

# === Обработчики бота ===
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_states[chat_id] = {
        'user_id': chat_id,
        'username': message.from_user.username,
        'first_name': message.from_user.first_name,
        'last_name': message.from_user.last_name,
        'ratings': {},
        'current_track': 1,
        'start_time': datetime.now()
    }
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎵 Начать тест", callback_data="start_test"))
    bot.send_message(chat_id, "Добро пожаловать в музыкальный тест! Нажмите кнопку ниже чтобы начать.", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def start_test(call):
    chat_id = call.message.chat.id
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("Мужской", callback_data="gender_M"))
    kb.row(types.InlineKeyboardButton("Женский", callback_data="gender_F"))
    bot.send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    user_states[chat_id]['gender'] = c.data.split('_')[1]
    bot.delete_message(chat_id, c.message.message_id)
    ask_age(chat_id)

def ask_age(chat_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    ages = ["до 24", "25-34", "35-44", "45-54", "55+"]
    for age in ages:
        kb.add(types.InlineKeyboardButton(age, callback_data=f"age_{age}"))
    bot.send_message(chat_id, "Укажите ваш возраст:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("age_"))
def handle_age(c):
    chat_id = c.message.chat.id
    user_states[chat_id]['age'] = c.data.split('_')[1]
    bot.delete_message(chat_id, c.message.message_id)
    
    # Подготавливаем таблицу
    prepare_spreadsheet()
    
    bot.send_message(chat_id, "🎵 Начинаем музыкальный тест!\n\nОцените каждый трек по шкале от 1 до 5 звезд")
    send_track(chat_id)

def send_track(chat_id):
    track_num = user_states[chat_id]['current_track']
    file_path = os.path.join(AUDIO_FOLDER, f"{track_num:03d}.mp3")
    
    if not os.path.exists(file_path):
        # Тест завершен
        user_data = user_states[chat_id]
        user_data['timestamp'] = datetime.now().isoformat()
        user_data['end_time'] = datetime.now()
        
        # Сохраняем в Google Таблицу
        success = save_to_google_sheets(user_data, user_data['ratings'])
        
        if success:
            bot.send_message(chat_id, "🎉 Тест завершен! Результаты сохранены в Google Таблицу.")
        else:
            bot.send_message(chat_id, "✅ Тест завершен! Но возникла ошибка при сохранении.")
        
        return

    try:
        with open(file_path, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file, caption=f"Трек #{track_num}")
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка загрузки трека: {e}")
        return

    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(f"{i}★", callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените трек:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    rating = int(c.data.split('_')[1])
    track_num = user_states[chat_id]['current_track']
    
    user_states[chat_id]['ratings'][str(track_num)] = rating
    user_states[chat_id]['current_track'] += 1
    
    bot.delete_message(chat_id, c.message.message_id)
    send_track(chat_id)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    bot.send_message(message.chat.id, "Для начала теста нажмите /start")

if __name__ == "__main__":
    print("Бот запущен и готов к работе!")
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Ошибка запуска бота: {e}")
