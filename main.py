import telebot
import csv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from telebot import types
from datetime import datetime
from flask import Flask, request
import json
import glob

# === Настройки ===
TOKEN = '8109304672:AAHkOQ8kzQLmHupii78YCd-1Q4HtDKWuuNk'
AUDIO_FOLDER = 'audio'
SPREADSHEET_NAME = 'music_testing'
WORKSHEET_NAME = 'track_list'

# === Инициализация ===
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === Google Sheets авторизация ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

worksheet = None
track_data = {}         # mapping track_number (str) -> title (from CSV)
MAX_TRACK = 0           # максимально ожидаемый номер трека (int)
user_states = {}

# === Функции ===
def initialize_google_sheets():
    """Инициализация подключения к Google Таблицам.
    Поддерживает env GOOGLE_CREDS_JSON, GOOGLE_CREDS_B64, или локальный creds.json.
    """
    global worksheet
    try:
        creds_json_str = os.environ.get('GOOGLE_CREDS_JSON')
        creds_b64 = os.environ.get('GOOGLE_CREDS_B64')

        if creds_json_str:
            creds_dict = json.loads(creds_json_str)
        elif creds_b64:
            import base64
            creds_dict = json.loads(base64.b64decode(creds_b64).decode('utf-8'))
        elif os.path.exists('creds.json'):
            with open('creds.json', 'r', encoding='utf-8') as f:
                creds_dict = json.load(f)
        else:
            print("❌ Нет ключа для Google API: задайте GOOGLE_CREDS_JSON или GOOGLE_CREDS_B64, или положите creds.json")
            worksheet = None
            return False

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        print("✅ Успешно подключено к Google Таблице!")
        return True

    except Exception as e:
        worksheet = None
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

def load_track_data():
    """Загрузка данных о треках из CSV и вычисление MAX_TRACK"""
    global track_data, MAX_TRACK
    track_data = {}
    MAX_TRACK = 0
    try:
        if not os.path.exists('track_list.csv'):
            print("⚠️ track_list.csv не найден — попробую определить треки по папке audio")
            if os.path.isdir(AUDIO_FOLDER):
                files = sorted(glob.glob(os.path.join(AUDIO_FOLDER, '*.mp3')))
                for f in files:
                    basename = os.path.basename(f)
                    name, _ = os.path.splitext(basename)
                    # пробуем взять номер из имени (первые цифры)
                    digits = ''.join(ch for ch in name.split()[0] if ch.isdigit())
                    if digits:
                        try:
                            num = int(digits)
                            track_data[str(num)] = basename
                        except Exception:
                            continue
                MAX_TRACK = max((int(k) for k in track_data.keys()), default=0)
                print(f"✅ Автодетект: найдено {len(track_data)} файлов в {AUDIO_FOLDER}")
                return True if track_data else False
            return False

        with open('track_list.csv', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tn = row.get('track_number')
                title = row.get('title', '')
                if tn:
                    tn_stripped = tn.strip()
                    track_data[tn_stripped] = title
            if track_data:
                try:
                    MAX_TRACK = max(int(k) for k in track_data.keys())
                except Exception:
                    MAX_TRACK = len(track_data)
        print(f"✅ Загружено {len(track_data)} треков (MAX_TRACK={MAX_TRACK})")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки треков: {e}")
        track_data = {}
        MAX_TRACK = 0
        return False

def find_audio_file(track_num):
    """Попытка найти файл для трека track_num.
    Возвращает путь к файлу или None.
    Логика:
      - exact formats: 001.mp3, 01.mp3, 1.mp3
      - patterns: '001 - *', '1 - *'
      - check track_data value if it looks like filename
      - glob '*{track_num}*.mp3' as last resort
    """
    # проверяем разные форматы имени
    candidates = [
        os.path.join(AUDIO_FOLDER, f"{track_num:03d}.mp3"),
        os.path.join(AUDIO_FOLDER, f"{track_num:02d}.mp3"),
        os.path.join(AUDIO_FOLDER, f"{track_num}.mp3"),
    ]

    # если в CSV в title явно указано имя файла (редкий случай) — попробуем
    title = track_data.get(str(track_num))
    if title:
        # если title выглядит как файл (оканчивается на .mp3) — попробуем
        if title.lower().endswith('.mp3'):
            candidates.append(os.path.join(AUDIO_FOLDER, title))
        # если title содержит номер и/или название — возможно файл "001 - Title.mp3"
        candidates.append(os.path.join(AUDIO_FOLDER, f"{track_num:03d} - {title}.mp3"))
        candidates.append(os.path.join(AUDIO_FOLDER, f"{track_num} - {title}.mp3"))

    # добавляем шаблоны glob для случаев "001 Title.mp3" и т.д.
    for c in candidates:
        if os.path.exists(c):
            return c

    # glob patterns (более общие)
    patterns = []
    patterns.append(os.path.join(AUDIO_FOLDER, f"{track_num:03d}*.mp3"))
    patterns.append(os.path.join(AUDIO_FOLDER, f"{track_num:02d}*.mp3"))
    patterns.append(os.path.join(AUDIO_FOLDER, f"{track_num}*.mp3"))
    patterns.append(os.path.join(AUDIO_FOLDER, f"*{track_num}*.mp3"))

    for pat in patterns:
        found = glob.glob(pat)
        if found:
            # возвращаем первый подходящий
            return found[0]

    return None

def save_to_google_sheets(user_data, ratings):
    """Сохранение результатов в Google Таблицу"""
    if not worksheet:
        print("❌ Google Таблица не доступна — пропускаем запись в Google")
        return False

    try:
        all_data = worksheet.get_all_values()
        next_col = len(all_data[0]) + 1 if all_data and all_data[0] else 1

        user_info = [
            user_data['user_id'],
            f"@{user_data.get('username', '')}",
            user_data.get('gender', ''),
            user_data.get('age', ''),
            datetime.now().isoformat()
        ]

        for i in range(1, MAX_TRACK + 1):
            user_info.append(ratings.get(str(i), ''))

        for row_idx, value in enumerate(user_info, start=1):
            worksheet.update_cell(row_idx, next_col, value)

        print(f"✅ Данные сохранены в колонку {next_col} Google Sheets")
        return True

    except Exception as e:
        print(f"❌ Ошибка сохранения в Google Таблицу: {e}")
        return False

def save_to_csv_backup(user_data, ratings):
    """Резервное сохранение в CSV"""
    try:
        file_exists = os.path.exists('backup_results.csv')
        with open('backup_results.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            if not file_exists:
                headers = ['user_id', 'username', 'gender', 'age', 'timestamp']
                for i in range(1, MAX_TRACK + 1):
                    headers.append(f'track_{i}')
                writer.writerow(headers)

            row_data = [
                user_data['user_id'],
                user_data.get('username', ''),
                user_data.get('gender', ''),
                user_data.get('age', ''),
                datetime.now().isoformat()
            ]

            for i in range(1, MAX_TRACK + 1):
                row_data.append(ratings.get(str(i), ''))

            writer.writerow(row_data)

        print("✅ Данные сохранены в CSV бэкап")
        return True

    except Exception as e:
        print(f"❌ Ошибка сохранения в CSV: {e}")
        return False

# === Обработчики бота ===
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_states[chat_id] = {
        'user_id': chat_id,
        'username': message.from_user.username,
        'ratings': {},
        'current_track': 1,
        'skipped': []  # номера пропущенных из-за отсутствия файлов
    }

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎵 Начать тест", callback_data="start_test"))
    bot.send_message(chat_id, "Добро пожаловать в музыкальный тест! Нажмите кнопку ниже чтобы начать.", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def start_test(call):
    chat_id = call.message.chat.id
    try:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    ask_gender(chat_id)

def ask_gender(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("Мужской", callback_data="gender_M"))
    kb.row(types.InlineKeyboardButton("Женский", callback_data="gender_F"))
    bot.send_message(chat_id, "Укажите ваш пол:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def handle_gender(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    user_states[chat_id]['gender'] = c.data.split('_', 1)[1]

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

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
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    user_states[chat_id]['age'] = c.data.split('_', 1)[1]

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    bot.send_message(chat_id, "🎵 Начинаем музыкальный тест!\n\nОцените каждый трек по шкале от 1 до 5 звезд")
    send_track(chat_id)

def send_track(chat_id):
    """Отправляет очередной трек. Пропускает отсутствующие файлы, пытаясь найти следующий."""
    if chat_id not in user_states:
        return

    # Защита — если треки не загружены
    if MAX_TRACK == 0:
        bot.send_message(chat_id, "⚠️ Треки не загружены на сервер. Пожалуйста, попробуйте позже.")
        print(f"[DEBUG] Пользователь {chat_id}: MAX_TRACK=0")
        return

    # начинаем с текущего номера и ищем ближайший доступный файл
    start = user_states[chat_id]['current_track']
    track_to_send = None
    skipped = []
    for num in range(start, MAX_TRACK + 1):
        found = find_audio_file(num)
        if found:
            track_to_send = (num, found)
            break
        else:
            skipped.append(num)

    if track_to_send is None:
        # ничего не найдено до конца — завершаем тест и сохраняем
        user_data = user_states[chat_id]
        google_success = save_to_google_sheets(user_data, user_data['ratings'])
        csv_success = save_to_csv_backup(user_data, user_data['ratings'])
        if google_success:
            bot.send_message(chat_id, "🎉 Тест завершен! Результаты сохранены в Google Таблицу.")
        elif csv_success:
            bot.send_message(chat_id, "✅ Тест завершен! Результаты сохранены в файл (локальный бэкап).")
        else:
            bot.send_message(chat_id, "⚠️ Тест завершен! Но возникла ошибка при сохранении.")
        try:
            del user_states[chat_id]
        except Exception:
            pass
        return

    # Если были пропуски — сохраним их в состояние и уведомим кратко
    if skipped:
        user_states[chat_id].setdefault('skipped', [])
        user_states[chat_id]['skipped'].extend(skipped)
        # короткое уведомление пользователю о пропуске первого трека(ов)
        bot.send_message(chat_id, f"⚠️ Трек(и) {', '.join(str(x) for x in skipped)} недоступен(ы) и будут пропущены.")

    track_num, file_path = track_to_send
    # обновляем текущий трек на найденный
    user_states[chat_id]['current_track'] = track_num

    # Отправляем сам аудиофайл
    try:
        with open(file_path, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file, caption=f"Трек #{track_num}")
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка загрузки трека: {e}")
        print(f"❌ Ошибка при отправке файла {file_path} пользователю {chat_id}: {e}")
        return

    # Отправляем inline клавиатуру с оценкой
    kb = types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        kb.add(types.InlineKeyboardButton(f"{i}★", callback_data=f"rate_{i}"))
    bot.send_message(chat_id, "Оцените трек:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def handle_rating(c):
    chat_id = c.message.chat.id
    if chat_id not in user_states:
        bot.send_message(chat_id, "⚠️ Пожалуйста, начните тест заново командой /start")
        return

    try:
        rating = int(c.data.split('_', 1)[1])
    except Exception:
        rating = None

    track_num = user_states[chat_id]['current_track']
    if rating is not None:
        user_states[chat_id]['ratings'][str(track_num)] = rating

    # двигаемся к следующему номеру (на следующем вызове send_track будет найдён следующий доступный файл)
    user_states[chat_id]['current_track'] = track_num + 1

    try:
        bot.delete_message(chat_id, c.message.message_id)
    except Exception:
        pass

    send_track(chat_id)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    bot.send_message(message.chat.id, "Для начала теста нажмите /start")

# === Вебхук обработчики ===
@app.route('/webhook/' + TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400

@app.route('/')
def index():
    return 'Music Test Bot is running!'

@app.route('/health')
def health():
    return 'OK'

# === Запуск ===
if __name__ == "__main__":
    print("🚀 Инициализация бота...")
    gs_ok = initialize_google_sheets()
    csv_ok = load_track_data()
    print(f"[INIT] GoogleSheets ok={gs_ok}, Tracks loaded ok={csv_ok}, MAX_TRACK={MAX_TRACK}")

    if 'RENDER' in os.environ:
        print("🌐 Запуск на Render (вебхук)")
        port = int(os.environ.get('PORT', 10000))
        app.run(host='0.0.0.0', port=port)
    else:
        print("💻 Локальный запуск (polling)")
        bot.remove_webhook()
        bot.polling(none_stop=True)
