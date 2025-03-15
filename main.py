# Импортируем нужные библиотеки
import aiohttp
import asyncio
from telebot.async_telebot import AsyncTeleBot
import json
import os
import random
import string
from telebot import types
import logging
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import time
from datetime import datetime
from together import Together
from dotenv import load_dotenv
from functools import partial
import base64
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Настраиваем логи
logging.basicConfig(level=logging.INFO)
logging.info("Bot started")
load_dotenv() # Загружает переменные из .env

# Глобальные переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
TOGETHER_API_KEY =  os.getenv("TOGETHER_API_KEY")
DATA_FILE = "dnd_data.json"
TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"
BACKUP_FOLDER_FILE = "backup_folder_id.txt"
DATA_CHANGED = False
CAMPAIGN_BY_CODE = {}
user_states = {}
together_client = Together(api_key=TOGETHER_API_KEY)

if not BOT_TOKEN or not ADMIN_PASSWORD:
    raise ValueError("BOT_TOKEN или ADMIN_PASSWORD не заданы в .env!")

# Инициализируем бота
bot = AsyncTeleBot(BOT_TOKEN)
DATA = {"users": {}, "campaigns": {}, "admins": {}, "characters": {}}
BACKUP_FOLDER_ID = None
PORTRAIT_FOLDER_ID = None


# Функции для Google Drive

async def async_backup_to_drive():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, backup_to_drive)

async def async_backup_portrait_to_drive(portrait_path, owner_id, char_name):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(backup_portrait_to_drive, portrait_path, owner_id, char_name))

def load_backup_folder_id():
    if os.path.exists(BACKUP_FOLDER_FILE):
        with open(BACKUP_FOLDER_FILE, "r") as f:
            return f.read().strip()
    return None

def save_backup_folder_id(folder_id):
    with open(BACKUP_FOLDER_FILE, "w") as f:
        f.write(folder_id)

def load_portrait_folder_id():
    portrait_folder_file = "portrait_folder_id.txt"
    if os.path.exists(portrait_folder_file):
        with open(portrait_folder_file, "r") as f:
            return f.read().strip()
    return None

def save_portrait_folder_id(folder_id):
    portrait_folder_file = "portrait_folder_id.txt"
    with open(portrait_folder_file, "w") as f:
        f.write(folder_id)

def authenticate_drive():
    gauth = GoogleAuth()
    gauth.LoadCredentialsFile("mycreds.txt")
    if gauth.credentials is None:
        gauth.CommandLineAuth()
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()
    gauth.SaveCredentialsFile("mycreds.txt")
    return GoogleDrive(gauth)

def backup_to_drive():
    if not os.path.exists(DATA_FILE):
        logging.info("Файл данных не найден, резервное копирование пропущено!")
        return
    drive = authenticate_drive()
    global BACKUP_FOLDER_ID
    BACKUP_FOLDER_ID = load_backup_folder_id()
    if BACKUP_FOLDER_ID is None:
        folder_metadata = {
            "title": "DnD Bot Backups",
            "mimeType": "application/vnd.google-apps.folder"
        }
        folder = drive.CreateFile(folder_metadata)
        folder.Upload()
        BACKUP_FOLDER_ID = folder["id"]
        save_backup_folder_id(BACKUP_FOLDER_ID)
        logging.info(f"Создана новая папка на Google Drive с ID: {BACKUP_FOLDER_ID}")
    else:
        logging.info(f"Используем существующую папку с ID: {BACKUP_FOLDER_ID}")
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    backup_file_name = f"dnd_data_{timestamp}.json"
    file_metadata = {
        "title": backup_file_name,
        "parents": [{"id": BACKUP_FOLDER_ID}]
    }
    file = drive.CreateFile(file_metadata)
    file.SetContentFile(DATA_FILE)
    file.Upload()
    logging.info(f"Резервная копия {backup_file_name} загружена на Google Drive!")
    try:
        file_list = drive.ListFile({'q': f"'{BACKUP_FOLDER_ID}' in parents"}).GetList()
        current_time = time.time()
        for file in file_list:
            # Проверяем, что это файл (не папка) и это JSON-бэкап данных
            if file['mimeType'] != "application/vnd.google-apps.folder" and file['title'].startswith("dnd_data_") and file['title'].endswith(".json"):
                file_time_str = file['title'].replace("dnd_data_", "").replace(".json", "")
                try:
                    file_time = datetime.strptime(file_time_str, "%Y-%m-%d_%H-%M-%S")
                    file_age = current_time - file_time.timestamp()
                    if file_age > 24 * 3600:  # Удаляем только файлы старше 24 часов
                        file.Delete()
                        logging.info(f"Удалён старый бэкап: {file['title']}")
                except ValueError:
                    logging.info(f"Пропущен файл с некорректным именем: {file['title']}")
            else:
                logging.info(f"Пропущен файл или папка: {file['title']}")
    except Exception as e:
        logging.info(f"Ошибка при очистке бэкапов: {str(e)}")

def backup_portrait_to_drive(portrait_path, owner_id, char_name):
    drive = authenticate_drive()
    global BACKUP_FOLDER_ID, PORTRAIT_FOLDER_ID

    # Проверяем или создаём основную папку "DnD Bot Backups"
    BACKUP_FOLDER_ID = load_backup_folder_id()
    if BACKUP_FOLDER_ID is None:
        folder_metadata = {
            "title": "DnD Bot Backups",
            "mimeType": "application/vnd.google-apps.folder"
        }
        folder = drive.CreateFile(folder_metadata)
        folder.Upload()
        BACKUP_FOLDER_ID = folder["id"]
        save_backup_folder_id(BACKUP_FOLDER_ID)
        logging.info(f"Создана новая папка DnD Bot Backups с ID: {BACKUP_FOLDER_ID}")
    else:
        logging.info(f"Используем существующую папку DnD Bot Backups с ID: {BACKUP_FOLDER_ID}")

    # Проверяем или создаём подпапку "Portraits"
    PORTRAIT_FOLDER_ID = load_portrait_folder_id()
    if PORTRAIT_FOLDER_ID is None:
        folder_metadata = {
            "title": "Portraits",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [{"id": BACKUP_FOLDER_ID}]
        }
        folder = drive.CreateFile(folder_metadata)
        folder.Upload()
        PORTRAIT_FOLDER_ID = folder["id"]
        save_portrait_folder_id(PORTRAIT_FOLDER_ID)
        logging.info(f"Создана новая папка Portraits с ID: {PORTRAIT_FOLDER_ID}")
    else:
        logging.info(f"Используем существующую папку Portraits с ID: {PORTRAIT_FOLDER_ID}")

    # Загружаем портрет
    portrait_file_name = f"{owner_id}_{char_name}.png"
    file_metadata = {
        "title": portrait_file_name,
        "parents": [{"id": PORTRAIT_FOLDER_ID}]
    }
    file = drive.CreateFile(file_metadata)
    file.SetContentFile(portrait_path)
    file.Upload()
    logging.info(f"Портрет {portrait_file_name} загружён на Google Drive!")

def load_data():
    global DATA, DATA_CHANGED, CAMPAIGN_BY_CODE
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as file:
            DATA = json.load(file)
    if "admins" not in DATA:
        DATA["admins"] = {}
    if "characters" not in DATA:
        DATA["characters"] = {}
    # Добавляем инициализацию квестов для всех персонажей
    for char_id in DATA["characters"]:
        if "quests" not in DATA["characters"][char_id]:
            DATA["characters"][char_id]["quests"] = {"active": {}, "completed": {}}
    CAMPAIGN_BY_CODE = {c["code"]: short_name for short_name, c in DATA["campaigns"].items()}
    DATA_CHANGED = False

async def save_data(force=False):
    global DATA_CHANGED
    if not DATA_CHANGED and not force:
        return
    with open(DATA_FILE, "w") as file:
        json.dump(DATA, file, indent=2)
    asyncio.create_task(async_backup_to_drive())  # Запускаем бэкап в фоне
    DATA_CHANGED = False

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# Асинхронные утилитные функции
async def generate_text(prompt, chat_id, is_dm=False, is_title=False):
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    system_prompt = (
        "Ты помощник, который создаёт название сессии из трех слов (максимум 30 символов) на русском языке на основе заметок. Название должно быть кратким, логичным, отражать ключевые события в том порядке, в котором они указаны, и не содержать выдуманных деталей. Используй только информацию из заметок, сохраняя их последовательность."
        if is_title else
        ("Ты помощник, который пересказывает события от лица героя на русском языке. Сохраняй строгий порядок событий, как они указаны в заметках, без изменений последовательности, добавления выдуманных деталей или пропуска событий. Текст должен быть кратким, но включать все ключевые моменты из заметок, с естественными склонениями и связностью."
         if not is_dm else
         "Ты помощник, который составляет краткую хронику событий кампании на русском языке в третьем лице. У тебя есть заметки от разных игроков, подписанные их именами (формат: 'Имя: заметка'). Твоя задача: объединить эти заметки в связную историю, сохраняя строгий порядок появления заметок в списке. Если заметки пересекаются или противоречат, выбирай наиболее логичное объяснение и соединяй их естественными переходами (например, 'тем временем', 'в то же время', 'после этого'). Не добавляй выдуманные детали, не пропускай события и используй только данные из заметок. Текст должен быть кратким, но полным, с естественными склонениями и ясной последовательностью.")
    )
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        "max_tokens": 20 if is_title else 500000,
        "temperature": 0.4,
        "top_p": 0.9,
        "stream": False
    }
    try:
        await bot.send_chat_action(chat_id, 'typing')
        async with bot.session.post(TOGETHER_API_URL, headers=headers, json=payload) as response:
            if response.status != 200:
                return f"Ошибка API: {response.status}. Заметки: {prompt}"
            data = await response.json()
            return data["choices"][0]["message"]["content"].strip()
    except aiohttp.ClientConnectorError as e:
        logging.error(f"Ошибка подключения к API: {str(e)}")
        return f"Ошибка подключения к API: {str(e)}. Проверьте интернет-соединение."
    except asyncio.TimeoutError:
        return "Ошибка: Превышено время ожидания ответа от API."
    except Exception as e:
        return f"Ошибка: {str(e)}. Заметки: {prompt}"

async def generate_image_prompt(backstory, chat_id):
    system_prompt = (
        "Ты помощник, который создаёт промпт на английском языке для генерации портрета персонажа. Максимум реализма и деталей, а также улучшенные текстуры"
        "На основе переданной внешности создай краткий, но детализированный промпт (максимум 100 слов), "
        "описывающий внешность и ключевые черты персонажа. Переведи предысторию на английский точно, "
        "не добавляй выдуманных деталей, используй только информацию из текста."
    )
    prompt = f"Создай промпт для портрета на основе этой внешности: {backstory}"
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        "max_tokens": 200,  # Ограничиваем длину промпта
        "temperature": 0.3,  # Низкая температура для точности
        "top_p": 0.9,
        "stream": False
    }
    try:
        await bot.send_chat_action(chat_id, 'typing')
        async with bot.session.post(TOGETHER_API_URL, headers=headers, json=payload) as response:
            if response.status != 200:
                return f"Ошибка создания промпта: {response.status}"
            data = await response.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Ошибка создания промпта: {str(e)}")
        return f"Ошибка: {str(e)}"

async def generate_character_portrait(backstory, chat_id):  # Изменили аргумент с short_backstory на backstory
    # Создаём промпт на основе полной предыстории
    image_prompt = await generate_image_prompt(backstory, chat_id)
    if "Ошибка" in image_prompt:
        return None, f"Ошибка создания промпта: {image_prompt}"

    # Формируем полный промпт для генерации изображения
    prompt = f"A detailed portrait of a character: {image_prompt}"
    try:
        await bot.send_chat_action(chat_id, 'upload_photo')
        response = together_client.images.generate(
            prompt=prompt,
            model="black-forest-labs/FLUX.1-schnell-Free",
            width=1024,
            height=768,
            steps=4,
            n=1,
            response_format="b64_json"
        )
        # Извлекаем base64-данные изображения
        b64_image = response.data[0].b64_json
        return b64_image, None
    except Exception as e:
        logging.error(f"Ошибка генерации изображения: {str(e)}")
        return None, f"Ошибка генерации: {str(e)}"

async def send_menu(chat_id, text, buttons=None, back_to="main_menu", buttons_per_row=2):
    markup = types.InlineKeyboardMarkup()
    if buttons:
        for i in range(0, len(buttons), buttons_per_row):
            row_buttons = buttons[i:i + buttons_per_row]
            markup.add(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in row_buttons])
    # Добавляем кнопку "Назад" только если back_to не пустой
    if back_to:
        markup.add(types.InlineKeyboardButton("⬅️ Назад в главное меню", callback_data=back_to))
    await bot.send_message(chat_id, text, reply_markup=markup)

async def check_access(chat_id, user_id, allow_dm_only=False, admin=False):
    if admin:
        if not await check_admin(chat_id, user_id):
            return False
    elif not await check_user(chat_id, user_id, allow_dm_only):
        return False
    return True

async def check_user(chat_id, user_id, allow_dm_only=False):
    if user_id not in DATA["users"]:
        buttons = [("🔑 Зарегистрироваться", "register")]
        await send_menu(chat_id, "❌ Ты не зарегистрирован!", buttons, buttons_per_row=2)
        return False
    if allow_dm_only and DATA["users"][user_id]["role"] != "dm":
        buttons = [("⬅️ Назад", "main_menu")]
        await send_menu(chat_id, "🚫 Только мастер может это сделать!", buttons, buttons_per_row=1)
        return False
    return True

async def check_admin(chat_id, user_id):
    if user_id not in DATA["admins"] or not DATA["admins"][user_id]:
        buttons = [("⬅️ Назад", "main_menu")]
        await send_menu(chat_id, "🚫 Доступ только для админов! Используй /admin", buttons, buttons_per_row=1)
        return False
    return True

# Обработчики

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_char_details|"))
async def show_admin_char_details(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    print(f"Callback received: {call.data}")  # Должно появиться в консоли
    if not await check_access(chat_id, user_id, admin=True):
        print(f"Access denied for user {user_id}")
        await send_menu(chat_id, "🚫 У тебя нет доступа к этой функции!")
        return
    parts = call.data.split("|")
    if len(parts) != 3:
        print(f"Invalid callback format: {call.data}")
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    target_uid, char_id = parts[1], parts[2]
    print(f"Target UID: {target_uid}, Char ID: {char_id}")
    if char_id not in DATA["characters"] or DATA["characters"][char_id]["owner"] != target_uid:
        print(f"Character {char_id} not found or doesn't belong to {target_uid}")
        await send_menu(chat_id, "❌ Персонаж не найден!", back_to=f"admin_user_details|{target_uid}")
        return
    char = DATA["characters"][char_id]
    text = (
        f"🧙‍♂️ Персонаж: {char['name']}\n"
        f"ID: {char_id}\n"
        f"Кампании: {', '.join(DATA['campaigns'][c]['full_name'] for c in char.get('campaigns', [])) or 'нет'}"
    )
    buttons = [
        ("📜 Полная предыстория", f"admin_show_full_backstory|{char_id}"),
        ("📖 Краткая предыстория", f"admin_show_short_backstory|{char_id}"),
        ("👤 Внешность", f"admin_show_appearance|{char_id}"),
        ("🖼 Портрет", f"admin_show_portrait|{char_id}"),
        ("🗑 Удалить персонажа", f"admin_delete_char_prompt|{target_uid}|{char_id}")
    ]
    await send_menu(chat_id, text, buttons, back_to=f"admin_user_details|{target_uid}", buttons_per_row=2)

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    user_id = str(message.from_user.id)
    if user_id in DATA["users"]:
        buttons = [("🔑 Войти", "login")]
        text = "👤 Ты зарегистрирован! Войди:"
    else:
        buttons = [("🎲 Как мастер", "register_dm"), ("⚔️ Как игрок", "register_player")]
        text = "👋 Добро пожаловать! Зарегистрируйся:"
    await send_menu(message.chat.id, text, buttons, buttons_per_row=2)

@bot.message_handler(commands=['admin'])
async def admin_login(message):
    user_id = str(message.from_user.id)
    user_states[user_id] = {"state": "waiting_for_admin_password"}
    await send_menu(message.chat.id, "🔒 Введи пароль админа:")

# Предполагается, что импорты и глобальные переменные (BOT_TOKEN, DATA, ADMIN_PASSWORD и т.д.) уже определены выше

# Обработчик ввода пароля админа для входа
@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_admin_password")
async def handle_admin_password_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    if message.text.strip() == ADMIN_PASSWORD:
        DATA["admins"][user_id] = True
        DATA_CHANGED = True
        await save_data()
        del user_states[user_id]
        await show_admin_panel(message.chat.id, user_id)
    else:
        del user_states[user_id]
        await send_menu(message.chat.id, "❌ Неверный пароль админа!")

# Команда выхода из админ-панели
@bot.message_handler(commands=['exitadmin'])
async def admin_logout(message):
    user_id = str(message.from_user.id)
    if user_id in DATA["admins"] and DATA["admins"][user_id]:
        global DATA_CHANGED
        DATA["admins"][user_id] = False
        DATA_CHANGED = True
        await save_data()
        await send_menu(message.chat.id, "👋 Ты вышел из админ-панели!")
    else:
        await send_menu(message.chat.id, "❌ Ты не в админ-панели!")

# Показ админ-панели
async def show_admin_panel(chat_id, user_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    buttons = [
        ("👤 Пользователи", "admin_users"),
        ("🏰 Кампании", "admin_campaigns"),
        ("🚪 Выйти", "admin_exit")
    ]
    text = "⚙️ Админ-панель\nДобро пожаловать! Выбери действие:"
    await send_menu(chat_id, text, buttons, buttons_per_row=3)

# Обработчик основных команд админ-панели
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
async def handle_admin_commands(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id, admin=True):
        return
    parts = call.data.split("|")
    command = parts[0].replace("admin_", "")
    if command == "users":
        await show_users_panel(call.message.chat.id, user_id)
    elif command == "campaigns":
        await show_campaigns_panel(call.message.chat.id, user_id)
    elif command == "exit":
        global DATA_CHANGED
        DATA["admins"][user_id] = False
        DATA_CHANGED = True
        await save_data()
        await send_menu(call.message.chat.id, "👋 Ты вышел из админ-панели!")
    elif command == "panel":
        await show_admin_panel(call.message.chat.id, user_id)
    elif command == "user_details" and len(parts) > 1:
        await show_user_details(call.message.chat.id, user_id, parts[1])
    elif command == "reset_password" and len(parts) > 1:
        await reset_password_prompt(call.message.chat.id, user_id, parts[1])
    elif command == "delete_user" and len(parts) > 1:
        await delete_user(call.message.chat.id, user_id, parts[1])
    elif command == "campaign_details" and len(parts) > 1:
        await show_campaign_details(call.message.chat.id, user_id, parts[1])
    elif command == "delete_campaign" and len(parts) > 1:
        await delete_campaign(call.message.chat.id, user_id, parts[1])
    elif command == "char_details" and len(parts) > 2:  # Добавлен обработчик для меню персонажа
        await show_admin_char_details(call.message.chat.id, user_id, parts[1], parts[2])
    elif command == "show_full_backstory" and len(parts) > 1:
        await admin_show_full_backstory(call)
    elif command == "show_short_backstory" and len(parts) > 1:
        await admin_show_short_backstory(call)
    elif command == "show_appearance" and len(parts) > 1:
        await admin_show_appearance(call)
    elif command == "show_portrait" and len(parts) > 1:
        await admin_show_portrait(call)
    elif command == "delete_char_prompt" and len(parts) > 2:
        await admin_delete_char_prompt(call)
    elif command == "delete_char_password" and len(parts) > 2:
        await admin_delete_char_password(call)
    elif command == "delete_char" and len(parts) > 2:
        await admin_delete_char(call)

# Панель пользователей
async def show_users_panel(chat_id, user_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    text = "👤 Список пользователей\n"
    buttons = []
    for uid, user in DATA["users"].items():
        characters = [c["name"] for c in DATA["characters"].values() if c["owner"] == uid]
        text += f"- ID: {uid} | Имя: {user['name']} | Роль: {'мастер' if user['role'] == 'dm' else 'игрок'} | Персонажи: {', '.join(characters) or 'нет'}\n"
        buttons.append((f"👤 {user['name']}", f"admin_user_details|{uid}"))
    await send_menu(chat_id, text, buttons, back_to="admin_panel", buttons_per_row=2)

# Детали пользователя
async def show_user_details(chat_id, user_id, target_uid):
    if not await check_access(chat_id, user_id, admin=True):
        return
    user = DATA["users"].get(target_uid, {})
    if not user:
        await send_menu(chat_id, "❌ Пользователь не найден!", back_to="admin_users")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == target_uid]
    campaigns = [c["full_name"] for c in DATA["campaigns"].values() if any(char_id in c["players"] for char_id, _ in characters)]
    text = (
        f"👤 Детали пользователя\n"
        f"ID: {target_uid}\n"
        f"Имя: {user['name']}\n"
        f"Роль: {'мастер' if user['role'] == 'dm' else 'игрок'}\n"
        f"Пароль: {user['password']}\n"
        f"Персонажи: {len(characters) or 'нет'}\n"
        f"Кампании: {', '.join(campaigns) or 'нет'}"
    )
    buttons = [
        (f"🧙‍♂️ {name}", f"admin_char_details|{target_uid}|{cid}") for cid, name in characters
    ] + [
        ("🔑 Сбросить пароль", f"admin_reset_password|{target_uid}"),
        ("🗑 Удалить пользователя", f"admin_delete_user|{target_uid}")
    ]
    print(f"Buttons for user {target_uid}: {buttons}")  # Отладка
    await send_menu(chat_id, text, buttons, back_to="admin_users", buttons_per_row=2)

# Добавлено: меню персонажа
async def show_admin_char_details(chat_id, user_id, target_uid, char_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    char = DATA["characters"].get(char_id, {})
    if not char or char["owner"] != target_uid:
        await send_menu(chat_id, "❌ Персонаж не найден!", back_to=f"admin_user_details|{target_uid}")
        return
    text = (
        f"🧙‍♂️ Персонаж: {char['name']}\n"
        f"ID: {char_id}\n"
        f"Кампании: {', '.join(DATA['campaigns'][c]['full_name'] for c in char.get('campaigns', [])) or 'нет'}"
    )
    buttons = [
        ("📜 Полная предыстория", f"admin_show_full_backstory|{char_id}"),
        ("📖 Краткая предыстория", f"admin_show_short_backstory|{char_id}"),
        ("👤 Внешность", f"admin_show_appearance|{char_id}"),
        ("🖼 Портрет", f"admin_show_portrait|{char_id}"),
        ("🗑 Удалить персонажа", f"admin_delete_char_prompt|{target_uid}|{char_id}")
    ]
    await send_menu(chat_id, text, buttons, back_to=f"admin_user_details|{target_uid}", buttons_per_row=2)

# Показ полной предыстории
async def admin_show_full_backstory(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or not await check_access(chat_id, user_id, admin=True):
        await send_menu(chat_id, "❌ Ошибка!")
        return
    char_id = parts[1]
    char = DATA["characters"].get(char_id, {})
    text = f"📜 Полная предыстория {char.get('name', '???')}:\n{char.get('backstory', 'Предыстория отсутствует')}"
    await send_menu(chat_id, text, back_to=f"admin_char_details|{char['owner']}|{char_id}")

# Показ краткой предыстории
async def admin_show_short_backstory(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or not await check_access(chat_id, user_id, admin=True):
        await send_menu(chat_id, "❌ Ошибка!")
        return
    char_id = parts[1]
    char = DATA["characters"].get(char_id, {})
    text = f"📖 Краткая предыстория {char.get('name', '???')}:\n{char.get('short_backstory', 'Предыстория отсутствует')}"
    await send_menu(chat_id, text, back_to=f"admin_char_details|{char['owner']}|{char_id}")

# Показ внешности
async def admin_show_appearance(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or not await check_access(chat_id, user_id, admin=True):
        await send_menu(chat_id, "❌ Ошибка!")
        return
    char_id = parts[1]
    char = DATA["characters"].get(char_id, {})
    text = f"👤 Внешность {char.get('name', '???')}:\n{char.get('appearance', 'Не указана')}"
    await send_menu(chat_id, text, back_to=f"admin_char_details|{char['owner']}|{char_id}")

# Показ портрета
async def admin_show_portrait(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or not await check_access(chat_id, user_id, admin=True):
        await send_menu(chat_id, "❌ Ошибка!")
        return
    char_id = parts[1]
    char = DATA["characters"].get(char_id, {})
    if "portrait" in char:
        with open(char["portrait"], "rb") as f:
            await bot.send_photo(chat_id, photo=f, caption=f"🖼 Портрет {char['name']}")
        await send_menu(chat_id, "✅ Портрет отправлен!", back_to=f"admin_char_details|{char['owner']}|{char_id}")
    else:
        await send_menu(chat_id, f"❌ У {char.get('name', '???')} нет портрета!", back_to=f"admin_char_details|{char['owner']}|{char_id}")

# Запрос подтверждения удаления персонажа
async def admin_delete_char_prompt(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id, admin=True):
        return
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    target_uid, char_id = parts[1], parts[2]
    char = DATA["characters"].get(char_id, {})
    if not char or char["owner"] != target_uid:
        await send_menu(chat_id, "❌ Персонаж не найден!", back_to=f"admin_user_details|{target_uid}")
        return
    buttons = [
        ("✅ Да", f"admin_delete_char_password|{target_uid}|{char_id}"),
        ("❌ Нет", f"admin_char_details|{target_uid}|{char_id}")
    ]
    text = (
        f"🗑 Вы точно хотите удалить персонажа {char['name']}?\n"
        f"⚠️ Все данные персонажа будут удалены без возможности восстановления!"
    )
    await send_menu(chat_id, text, buttons, buttons_per_row=2)

# Запрос пароля для удаления персонажа
async def admin_delete_char_password(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id, admin=True):
        return
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    target_uid, char_id = parts[1], parts[2]
    char = DATA["characters"].get(char_id, {})
    if not char or char["owner"] != target_uid:
        await send_menu(chat_id, "❌ Персонаж не найден!", back_to=f"admin_user_details|{target_uid}")
        return
    user_states[user_id] = {"state": "confirm_admin_char_deletion", "data": {"target_uid": target_uid, "char_id": char_id}}
    text = (
        f"🔒 Введи пароль админа для подтверждения удаления персонажа {char['name']}:\n"
        f"⚠️ Это действие необратимо!"
    )
    await send_menu(chat_id, text, back_to=f"admin_char_details|{target_uid}|{char_id}")

# Подтверждение удаления персонажа с паролем
@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "confirm_admin_char_deletion")
async def confirm_admin_char_deletion(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    if not await check_access(chat_id, user_id, admin=True):
        del user_states[user_id]
        return
    target_uid = user_states[user_id]["data"]["target_uid"]
    char_id = user_states[user_id]["data"]["char_id"]
    char = DATA["characters"].get(char_id, {})
    if not char or char["owner"] != target_uid:
        await send_menu(chat_id, "❌ Персонаж не найден!", back_to=f"admin_user_details|{target_uid}")
        del user_states[user_id]
        return
    if message.text.strip() != ADMIN_PASSWORD:
        await send_menu(chat_id, "❌ Неверный пароль админа! Удаление отменено.", back_to=f"admin_char_details|{target_uid}|{char_id}")
        del user_states[user_id]
        return
    char_name = char["name"]
    for campaign in DATA["campaigns"].values():
        if char_id in campaign["players"]:
            campaign["players"].remove(char_id)
    if "portrait" in char and os.path.exists(char["portrait"]):
        os.remove(char["portrait"])
    del DATA["characters"][char_id]
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, f"🗑 Персонаж {char_name} удалён навсегда!", back_to=f"admin_user_details|{target_uid}")
    del user_states[user_id]

# Удаление персонажа (без пароля, устаревшая версия)
async def admin_delete_char(call):
    global DATA_CHANGED
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id, admin=True):
        return
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    target_uid, char_id = parts[1], parts[2]
    char = DATA["characters"].get(char_id, {})
    if not char or char["owner"] != target_uid:
        await send_menu(chat_id, "❌ Персонаж не найден!", back_to=f"admin_user_details|{target_uid}")
        return
    char_name = char["name"]
    for campaign in DATA["campaigns"].values():
        if char_id in campaign["players"]:
            campaign["players"].remove(char_id)
    del DATA["characters"][char_id]
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, f"🗑 Персонаж {char_name} удалён!", back_to=f"admin_user_details|{target_uid}")

# Запрос сброса пароля
async def reset_password_prompt(chat_id, user_id, target_uid):
    if not await check_access(chat_id, user_id, admin=True):
        return
    user_states[user_id] = {"state": "waiting_for_reset_password", "data": {"target_uid": target_uid}}
    await send_menu(chat_id,
                    f"🔑 Введи новый пароль для {DATA['users'][target_uid]['name']}:",
                    back_to=f"admin_user_details|{target_uid}")

# Обработка ввода нового пароля
@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_reset_password")
async def reset_password_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    if not await check_access(message.chat.id, user_id, admin=True):
        del user_states[user_id]
        return
    target_uid = user_states[user_id]["data"]["target_uid"]
    new_password = message.text.strip()
    if not new_password:
        await send_menu(message.chat.id, "❌ Пароль не может быть пустым!", back_to=f"admin_user_details|{target_uid}")
        del user_states[user_id]
        return
    DATA["users"][target_uid]["password"] = new_password
    DATA_CHANGED = True
    await send_menu(message.chat.id, f"✅ Пароль для {DATA['users'][target_uid]['name']} сброшен на {new_password}!", back_to=f"admin_user_details|{target_uid}")
    del user_states[user_id]

# Удаление пользователя
async def delete_user(chat_id, user_id, target_uid):
    global DATA_CHANGED
    if not await check_access(chat_id, user_id, admin=True):
        return
    if target_uid not in DATA["users"]:
        await send_menu(chat_id, "❌ Пользователь не найден!", back_to="admin_users")
        return
    user_name = DATA["users"][target_uid]["name"]
    for campaign in DATA["campaigns"].values():
        for char_id in list(campaign["players"]):
            if DATA["characters"][char_id]["owner"] == target_uid:
                campaign["players"].remove(char_id)
    for char_id in list(DATA["characters"].keys()):
        if DATA["characters"][char_id]["owner"] == target_uid:
            del DATA["characters"][char_id]
    del DATA["users"][target_uid]
    if target_uid in DATA["admins"]:
        del DATA["admins"][target_uid]
    DATA_CHANGED = True
    await send_menu(chat_id, f"🗑 Пользователь {user_name} удалён!", back_to="admin_users")

# Панель кампаний
async def show_campaigns_panel(chat_id, user_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    text = "🏰 Список кампаний\n"
    buttons = []
    for short_name, camp in DATA["campaigns"].items():
        players = [DATA["characters"][pid]["name"] for pid in camp["players"]]
        text += f"- {short_name} | Полное: {camp['full_name']}\n  Создатель: {DATA['users'][camp['creator']]['name']} | Участники: {', '.join(players) or 'нет'}\n"
        buttons.append((f"🏰 {short_name}", f"admin_campaign_details|{short_name}"))
    await send_menu(chat_id, text, buttons, back_to="admin_panel", buttons_per_row=2)

# Детали кампании
async def show_campaign_details(chat_id, user_id, short_name):
    if not await check_access(chat_id, user_id, admin=True):
        return
    camp = DATA["campaigns"].get(short_name, {})
    if not camp:
        await send_menu(chat_id, "❌ Кампания не найдена!", back_to="admin_campaigns")
        return
    players = [f"{DATA['characters'][pid]['name']} (владелец: {DATA['users'][DATA['characters'][pid]['owner']]['name']})" for pid in camp["players"]]
    sessions = camp["sessions"]
    text = (
        f"🏰 Детали кампании\n"
        f"Краткое название: {short_name}\n"
        f"Полное название: {camp['full_name']}\n"
        f"Создатель: {DATA['users'][camp['creator']]['name']} (ID: {camp['creator']})\n"
        f"Код: {camp['code']}\n"
        f"Участники:\n" + "\n".join(f"- {p}" for p in players) or "нет" + "\n"
        f"Сессий: {len(sessions)}\n"
        f"Активная сессия: {'да' if any(s['active'] for s in sessions.values()) else 'нет'}"
    )
    buttons = [("🗑 Удалить", f"admin_delete_campaign|{short_name}")]
    await send_menu(chat_id, text, buttons, back_to="admin_campaigns", buttons_per_row=1)

# Удаление кампании
async def delete_campaign(chat_id, user_id, short_name):
    global DATA_CHANGED, CAMPAIGN_BY_CODE
    if not await check_access(chat_id, user_id, admin=True):
        return
    if short_name not in DATA["campaigns"]:
        await send_menu(chat_id, "❌ Кампания не найдена!", back_to="admin_campaigns")
        return
    code = DATA["campaigns"][short_name]["code"]
    full_name = DATA["campaigns"][short_name]["full_name"]
    for char_id in DATA["campaigns"][short_name]["players"]:
        DATA["characters"][char_id]["campaigns"].remove(short_name)
    del DATA["campaigns"][short_name]
    del CAMPAIGN_BY_CODE[code]
    DATA_CHANGED = True
    await send_menu(chat_id, f"🗑 Кампания {full_name} удалена!", back_to="admin_campaigns")

@bot.callback_query_handler(func=lambda call: call.data in ["register_dm", "register_player"])
async def handle_register_choice(call):
    user_id = str(call.from_user.id)
    if user_id in DATA["users"]:
        buttons = [("🔑 Войти", "login")]
        await send_menu(call.message.chat.id, "👤 Ты уже зарегистрирован!", buttons)
        return
    role = "dm" if call.data == "register_dm" else "player"
    user_states[user_id] = {"state": "waiting_for_registration", "data": {"role": role}}
    await send_menu(call.message.chat.id,
                    "📝 Введи имя и пароль в формате: Имя Пароль\nПример: Иван pass123")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_registration")
async def register_user_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    role = user_states[user_id]["data"]["role"]
    try:
        name, password = message.text.split(" ", 1)
        if not (name and password):
            raise ValueError
        DATA["users"][user_id] = {
            "role": role,
            "name": name,
            "password": password
        }
        DATA_CHANGED = True
        await save_data()
        buttons = [("🔑 Войти", "login")]
        await send_menu(message.chat.id, f"✅ Ты зарегистрирован как {'мастер' if role == 'dm' else 'игрок'}, {name}!\nТеперь войди.", buttons)
    except ValueError:
        await send_menu(message.chat.id, "❌ Неверный формат! Введи: Имя Пароль")
    finally:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "login")
async def ask_login(call):
    user_id = str(call.from_user.id)
    if user_id not in DATA["users"]:
        buttons = [("📝 Зарегистрироваться", "register")]  # Изменено с "start" на "register"
        await send_menu(call.message.chat.id, "❌ Ты не зарегистрирован! Начни заново:", buttons)
        return
    user_states[user_id] = {"state": "waiting_for_login_password"}
    await send_menu(call.message.chat.id, "🔒 Введи пароль для входа:")

@bot.callback_query_handler(func=lambda call: call.data == "register")
async def handle_register(call):
    user_id = str(call.from_user.id)
    if user_id in DATA["users"]:
        buttons = [("🔑 Войти", "login")]
        await send_menu(call.message.chat.id, "👤 Ты уже зарегистрирован!", buttons)
        return
    buttons = [("🎲 Как мастер", "register_dm"), ("⚔️ Как игрок", "register_player")]
    text = "👋 Добро пожаловать! Зарегистрируйся:"
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=2)

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_login_password")
async def login_user_input(message):
    user_id = str(message.from_user.id)
    if user_id not in DATA["users"]:
        await send_menu(message.chat.id, "❌ Ты не зарегистрирован! Начни заново: /start")
        del user_states[user_id]
        return
    if DATA["users"][user_id]["password"] != message.text.strip():
        buttons = [("🔄 Снова", "login")]
        await send_menu(message.chat.id, "❌ Неверный пароль!", buttons)
        del user_states[user_id]
        return
    del user_states[user_id]
    await show_main_menu(message.chat.id, user_id)

@bot.message_handler(commands=['newcharacter'])
async def ask_new_character(message):
    user_id = str(message.from_user.id)
    if not await check_access(message.chat.id, user_id):
        return
    user_states[user_id] = {"state": "waiting_for_character_name"}
    await send_menu(message.chat.id, "🧙‍♂️ Введи имя своего персонажа:")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_character_name")
async def create_character_name_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    name = message.text.strip()
    if not name:
        await send_menu(message.chat.id, "❌ Имя не может быть пустым!")
        del user_states[user_id]
        return
    character_id = f"char_{len(DATA['characters']) + 1}"
    # Инициализируем персонажа с пустой предысторией и списком частей
    DATA["characters"][character_id] = {
        "name": name,
        "owner": user_id,
        "campaigns": [],
        "backstory": "",  # Полная предыстория будет тут
        "backstory_parts": [],  # Список частей для сборки
        "short_backstory": ""  # Сокращённая версия будет тут
    }
    DATA_CHANGED = True
    await save_data()
    user_states[user_id] = {"state": "adding_backstory_parts", "data": {"character_id": character_id, "name": name}}
    buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
    await send_menu(message.chat.id, f"🧙‍♂️ Персонаж {name} (ID: {character_id}) создан!\nДобавляй предысторию частями:", buttons)

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "adding_backstory_parts")
async def add_backstory_part_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    character_id = user_states[user_id]["data"]["character_id"]
    name = user_states[user_id]["data"]["name"]
    part = message.text.strip()

    if not part:
        buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
        await send_menu(message.chat.id, "❌ Часть не может быть пустой! Продолжай добавлять предысторию:", buttons)
        return

    # Добавляем часть в список, даже если она пришла отдельным сообщением
    if "backstory_parts" not in DATA["characters"][character_id]:
        DATA["characters"][character_id]["backstory_parts"] = []
    DATA["characters"][character_id]["backstory_parts"].append(part)
    DATA_CHANGED = True

    # Предлагаем продолжить или завершить
    buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
    await send_menu(
        message.chat.id,
        f"✅ Часть предыстории добавлена для {name}!\n"
        f"Текущие части: {len(DATA['characters'][character_id]['backstory_parts'])}\n"
        f"Продолжай добавлять или заверши:",
        buttons
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_backstory|"))
async def add_backstory(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    # Инициализируем пустой список для частей предыстории
    DATA["characters"][character_id]["backstory_parts"] = []
    user_states[user_id] = {
        "state": "adding_backstory_parts",
        "data": {"character_id": character_id, "name": DATA["characters"][character_id]["name"]}
    }
    buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
    await send_menu(
        chat_id,
        f"Добавляй предысторию для {DATA['characters'][character_id]['name']} по частям:",
        buttons
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_backstory|"))
async def edit_backstory(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    # Инициализируем пустой список для новых частей предыстории
    DATA["characters"][character_id]["backstory_parts"] = []
    user_states[user_id] = {
        "state": "editing_backstory_parts",
        "data": {"character_id": character_id, "name": DATA["characters"][character_id]["name"]}
    }
    buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
    await send_menu(
        chat_id,
        f"Перепиши предысторию для {DATA['characters'][character_id]['name']} по частям (старая будет заменена):",
        buttons
    )

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") in ["adding_backstory_parts", "editing_backstory_parts"])
async def add_backstory_part_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    name = user_states[user_id]["data"]["name"]
    part = message.text.strip()

    if not part:
        buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
        await send_menu(chat_id, "❌ Часть не может быть пустой! Продолжай добавлять предысторию:", buttons)
        return

    # Добавляем часть в список
    if "backstory_parts" not in DATA["characters"][character_id]:
        DATA["characters"][character_id]["backstory_parts"] = []
    DATA["characters"][character_id]["backstory_parts"].append(part)
    DATA_CHANGED = True

    buttons = [("🏁 Завершить предысторию", f"finish_backstory|{character_id}")]
    await send_menu(
        chat_id,
        f"✅ Часть предыстории добавлена для {name}!\n"
        f"Текущие части: {len(DATA['characters'][character_id]['backstory_parts'])}\n"
        f"Продолжай добавлять или заверши:",
        buttons
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_backstory|"))
async def finish_backstory(call):
    global DATA_CHANGED
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    # Собираем полную предысторию из частей
    backstory_parts = DATA["characters"][character_id].get("backstory_parts", [])
    if not backstory_parts:
        DATA["characters"][character_id]["backstory"] = "Предыстория отсутствует"
        DATA["characters"][character_id]["short_backstory"] = "Предыстория отсутствует"
    else:
        full_backstory = " ".join(backstory_parts)
        DATA["characters"][character_id]["backstory"] = full_backstory
        prompt = f"Сократи этот текст до 5 предложений, сохраняя ключевые события и смысл, без выдумок:\n{full_backstory}"
        short_backstory = await generate_text(prompt, chat_id)
        if "Ошибка" in short_backstory:
            await send_menu(chat_id, f"❌ Не удалось сократить предысторию: {short_backstory}")
            return
        DATA["characters"][character_id]["short_backstory"] = short_backstory

    # Очищаем временные части
    if "backstory_parts" in DATA["characters"][character_id]:
        del DATA["characters"][character_id]["backstory_parts"]
    DATA_CHANGED = True
    await save_data()

    # Проверяем, откуда был вызов: создание или редактирование
    if user_states[user_id].get("state") == "adding_backstory_parts":
        # Переход к добавлению внешности при создании персонажа
        user_states[user_id] = {
            "state": "adding_appearance",
            "data": {"character_id": character_id, "name": DATA["characters"][character_id]["name"]}
        }
        buttons = [("🏁 Завершить без внешности", f"finish_appearance|{character_id}")]
        await send_menu(
            chat_id,
            f"✅ Предыстория для {DATA['characters'][character_id]['name']} сохранена!\n"
            f"Теперь опиши внешность персонажа (например, 'Высокий мужчина с чёрными волосами и зелёными глазами'):",
            buttons
        )
    else:
        # Возврат к профилю при редактировании
        await send_menu(
            chat_id,
            f"✅ Предыстория для {DATA['characters'][character_id]['name']} обновлена!",
            back_to=f"show_character|{character_id}"
        )
        if user_id in user_states:
            del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_backstory|"))
async def finish_backstory(call):
    global DATA_CHANGED
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    # Собираем предысторию
    backstory_parts = DATA["characters"][character_id].get("backstory_parts", [])
    if not backstory_parts:
        DATA["characters"][character_id]["backstory"] = "Предыстория отсутствует"
        DATA["characters"][character_id]["short_backstory"] = "Предыстория отсутствует"
    else:
        full_backstory = " ".join(backstory_parts)
        DATA["characters"][character_id]["backstory"] = full_backstory
        prompt = f"Сократи этот текст до 5 предложений, сохраняя ключевые события и смысл, без выдумок:\n{full_backstory}"
        short_backstory = await generate_text(prompt, chat_id)
        if "Ошибка" in short_backstory:
            await send_menu(chat_id, f"❌ Не удалось сократить предысторию: {short_backstory}")
            return
        DATA["characters"][character_id]["short_backstory"] = short_backstory

    # Очищаем временные части
    if "backstory_parts" in DATA["characters"][character_id]:
        del DATA["characters"][character_id]["backstory_parts"]
    DATA_CHANGED = True
    await save_data()

    # Переключаем состояние на добавление внешности
    user_states[user_id] = {
        "state": "adding_appearance",
        "data": {"character_id": character_id, "name": DATA["characters"][character_id]["name"]}
    }
    buttons = [("🏁 Завершить без внешности", f"finish_appearance|{character_id}")]
    await send_menu(
        chat_id,
        f"✅ Предыстория для {DATA['characters'][character_id]['name']} сохранена!\n"
        f"Теперь опиши внешность персонажа (например, 'Высокий мужчина с чёрными волосами и зелёными глазами'):",
        buttons
    )

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "adding_appearance")
async def add_appearance_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    name = user_states[user_id]["data"]["name"]
    appearance = message.text.strip()

    if not appearance:
        buttons = [("🏁 Завершить без внешности", f"finish_appearance|{character_id}")]
        await send_menu(chat_id, "❌ Описание внешности не может быть пустым! Попробуй снова:", buttons)
        return

    DATA["characters"][character_id]["appearance"] = appearance
    DATA_CHANGED = True
    await save_data()

    buttons = [
        ("📜 Предыстория", f"show_character|{character_id}"),
        ("🖼 Сгенерировать портрет", f"generate_portrait|{character_id}"),
        ("🤝 Вступить в новую", "join_campaign")
    ]
    await send_menu(
        chat_id,
        f"✅ Внешность для {name} сохранена:\n{appearance}\n"
        f"Персонаж создан с ID: {character_id}!",
        buttons,
        buttons_per_row=2
    )
    if user_id in user_states:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_appearance|"))
async def finish_appearance(call):
    global DATA_CHANGED
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    buttons = [
        ("📜 Предыстория", f"show_character|{character_id}"),
        ("🖼 Сгенерировать портрет", f"generate_portrait|{character_id}"),
        ("🤝 Вступить в новую", "join_campaign")
    ]
    await send_menu(
        chat_id,
        f"✅ Персонаж {DATA['characters'][character_id]['name']} создан с ID: {character_id}!\n"
        f"Внешность не указана — можно добавить позже.",
        buttons,
        buttons_per_row=2
    )
    if user_id in user_states:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_character|"))
async def show_character(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    char = DATA["characters"][character_id]
    text = (
        f"🧙‍♂️ Персонаж: {char['name']}\n"
        f"ID: {character_id}\n"
        f"Предыстория (сокращённая): {char['short_backstory']}\n"
        f"Внешность: {char.get('appearance', 'Не указана')}\n"
        f"Кампании:\n" + "\n".join(f"- {DATA['campaigns'][c]['full_name']}" for c in char.get('campaigns', [])) or "нет"
    )
    buttons = [(f"🏰 {DATA['campaigns'][c]['short_name']}", f"history|{c}") for c in char.get("campaigns", [])]

    # Проверяем наличие портрета
    if "portrait" in char:
        with open(char["portrait"], "rb") as f:
            await bot.send_photo(chat_id, photo=f, caption=f"Портрет {char['name']}")
        # Проверяем наличие предыстории
        if char.get("backstory", "Предыстория отсутствует") == "Предыстория отсутствует":
            buttons.extend([
                ("✏️ Добавить предысторию", f"add_backstory|{character_id}"),
                ("✏️ Изменить внешность", f"edit_appearance|{character_id}"),
                ("✏️ Редактировать имя", f"edit_char_name|{character_id}"),  # Новая кнопка
                ("🤝 Вступить в новую", "join_campaign")
            ])
        else:
            buttons.extend([
                ("📖 Полная предыстория", f"show_full_backstory|{character_id}"),
                ("✏️ Изменить предысторию", f"edit_backstory|{character_id}"),
                ("✏️ Изменить внешность", f"edit_appearance|{character_id}"),
                ("✏️ Редактировать имя", f"edit_char_name|{character_id}"),  # Новая кнопка
                ("🤝 Вступить в новую", "join_campaign")
            ])
    else:
        # Если портрета нет
        if char.get("backstory", "Предыстория отсутствует") == "Предыстория отсутствует":
            buttons.extend([
                ("✏️ Добавить предысторию", f"add_backstory|{character_id}"),
                ("✏️ Добавить внешность", f"edit_appearance|{character_id}"),
                ("🖼 Сгенерировать портрет", f"generate_portrait|{character_id}"),
                ("✏️ Редактировать имя", f"edit_char_name|{character_id}"),  # Новая кнопка
                ("🤝 Вступить в новую", "join_campaign")
            ])
        else:
            buttons.extend([
                ("📖 Полная предыстория", f"show_full_backstory|{character_id}"),
                ("✏️ Изменить предысторию", f"edit_backstory|{character_id}"),
                ("✏️ Добавить внешность", f"edit_appearance|{character_id}"),
                ("🖼 Сгенерировать портрет", f"generate_portrait|{character_id}"),
                ("✏️ Редактировать имя", f"edit_char_name|{character_id}"),  # Новая кнопка
                ("🤝 Вступить в новую", "join_campaign")
            ])

    await send_menu(chat_id, text, buttons, buttons_per_row=2)





@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_appearance|"))
async def edit_appearance(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    user_states[user_id] = {
        "state": "editing_appearance",
        "data": {"character_id": character_id, "name": DATA["characters"][character_id]["name"]}
    }
    buttons = [("🏁 Завершить без внешности", f"finish_appearance|{character_id}")]
    await send_menu(
        chat_id,
        f"Опиши внешность персонажа {DATA['characters'][character_id]['name']} (например, 'Высокий мужчина с чёрными волосами и зелёными глазами'):",
        buttons
    )

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "editing_appearance")
async def process_appearance_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    name = user_states[user_id]["data"]["name"]
    appearance = message.text.strip()

    if not appearance:
        buttons = [("🏁 Завершить без внешности", f"finish_appearance|{character_id}")]
        await send_menu(chat_id, "❌ Описание внешности не может быть пустым! Попробуй снова:", buttons)
        return

    DATA["characters"][character_id]["appearance"] = appearance
    DATA_CHANGED = True
    await save_data()

    await send_menu(
        chat_id,
        f"✅ Внешность для {name} обновлена:\n{appearance}",
        back_to=f"show_character|{character_id}"
    )
    if user_id in user_states:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_full_backstory|"))
async def show_full_backstory(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    char = DATA["characters"][character_id]
    full_backstory = char.get("backstory", "Предыстория отсутствует")
    if full_backstory == "Предыстория отсутствует":
        await send_menu(chat_id, "📜 Полная предыстория отсутствует.", back_to=f"show_character|{character_id}")
        return

    # Разбиваем текст на части по 4096 символов
    MAX_MESSAGE_LENGTH = 4000
    backstory_parts = [full_backstory[i:i + MAX_MESSAGE_LENGTH] for i in range(0, len(full_backstory), MAX_MESSAGE_LENGTH)]

    # Отправляем каждую часть
    for i, part in enumerate(backstory_parts, 1):
        # Для первой части добавляем заголовок, для остальных — просто текст
        if i == 1:
            message_text = f"📜 Полная предыстория {char['name']}:\n{part}"
        else:
            message_text = part

        # Если это последняя часть, добавляем кнопку "Назад"
        if i == len(backstory_parts):
            buttons = [("⬅️ Назад", f"show_character|{character_id}")]
            await bot.send_message(chat_id, message_text, reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("⬅️ Назад", callback_data=f"show_character|{character_id}")
            ))
        else:
            await bot.send_message(chat_id, message_text)

    # Показываем, что бот печатает, чтобы избежать ощущения задержки
    await bot.send_chat_action(chat_id, "typing")

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_full_backstory|"))
async def show_full_backstory(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Это не твой персонаж!")
        return
    char = DATA["characters"][character_id]
    text = (
        f"🧙‍♂️ Персонаж: {char['name']}\n"
        f"ID: {character_id}\n"
        f"Полная предыстория:\n{char['backstory']}"
    )  
    await send_menu(call.message.chat.id, text)

@bot.callback_query_handler(func=lambda call: call.data.startswith("generate_portrait|"))
async def generate_portrait(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    char = DATA["characters"][character_id]
    appearance = char.get("appearance", "Описание внешности отсутствует")
    if appearance == "Описание внешности отсутствует":
        await send_menu(
            chat_id,
            "❌ У персонажа нет описания внешности! Добавь его сначала.",
            back_to=f"show_character|{character_id}"
        )
        return

    # Генерация изображения на основе внешности
    b64_image, error = await generate_character_portrait(appearance, chat_id)
    if error:
        await send_menu(chat_id, f"❌ Не удалось сгенерировать портрет: {error}")
        return

    # Сохраняем временное изображение в состоянии
    user_states[user_id] = {
        "state": "portrait_generated",
        "data": {"character_id": character_id, "b64_image": b64_image}
    }

    # Отправляем портрет
    import base64
    image_data = base64.b64decode(b64_image)
    await bot.send_photo(chat_id, photo=image_data, caption=f"Портрет {char['name']} на основе внешности")

    buttons = [
        ("💾 Сохранить портрет", f"save_portrait|{character_id}"),
        ("🔄 Перегенерировать", f"regenerate_portrait|{character_id}"),
        ("⬅️ Назад в меню персонажа", f"show_character|{character_id}")
    ]
    await send_menu(chat_id, "✅ Портрет сгенерирован! Что дальше?", buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_portrait|"))
async def handle_save_portrait(call):
    global DATA_CHANGED
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or user_id not in user_states or user_states[user_id].get("state") != "portrait_generated":
        await send_menu(chat_id, "❌ Ошибка или сессия истекла!", back_to="main_menu")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    # Извлекаем данные из состояния
    b64_image = user_states[user_id]["data"]["b64_image"]
    char = DATA["characters"][character_id]
    owner_id = char["owner"]
    char_name = char["name"]

    # Создаём папку portraits/{owner_id}, если её нет
    import os
    portrait_dir = f"portraits/{owner_id}"
    os.makedirs(portrait_dir, exist_ok=True)

    # Сохраняем изображение локально
    import base64
    image_data = base64.b64decode(b64_image)
    portrait_path = f"{portrait_dir}/{char_name}.png"
    with open(portrait_path, "wb") as f:
        f.write(image_data)

    # Сохраняем путь к портрету в данных персонажа
    DATA["characters"][character_id]["portrait"] = portrait_path
    DATA_CHANGED = True
    await save_data()

    # Выполняем резервное копирование на Google Drive
    try:
        backup_portrait_to_drive(portrait_path, owner_id, char_name)
        backup_message = "и успешно загружен на Google Drive"
    except Exception as e:
        logging.error(f"Ошибка бэкапа портрета на Google Drive: {str(e)}")
        backup_message = f", но произошла ошибка бэкапа на Google Drive: {str(e)}"

    # Очищаем состояние
    if user_id in user_states:
        del user_states[user_id]

    # Возвращаемся в меню персонажа
    buttons = [("⬅️ Назад в меню персонажа", f"show_character|{character_id}")]
    await send_menu(call.message.chat.id, f"✅ Портрет {char_name} сохранён и загружен на Google Drive!", buttons, buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("regenerate_portrait|"))
async def handle_regenerate_portrait(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or user_id not in user_states or user_states[user_id].get("state") != "portrait_generated":
        await send_menu(chat_id, "❌ Ошибка или сессия истекла!", back_to="main_menu")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    char = DATA["characters"][character_id]
    appearance = char.get("appearance", "Описание внешности отсутствует")
    if appearance == "Описание внешности отсутствует":
        await send_menu(
            chat_id,
            "❌ У персонажа нет описания внешности! Добавь его сначала.",
            back_to=f"show_character|{character_id}"
        )
        return

    # Генерируем новый портрет на основе внешности
    b64_image, error = await generate_character_portrait(appearance, chat_id)
    if error:
        await send_menu(chat_id, f"❌ {error}", back_to=f"show_character|{character_id}")
        return

    # Декодируем и отправляем новый портрет
    import base64
    image_data = base64.b64decode(b64_image)
    await bot.send_photo(chat_id, photo=image_data, caption=f"Портрет {char['name']} на основе внешности")

    # Обновляем временный портрет в состоянии
    user_states[user_id]["data"]["b64_image"] = b64_image

    # Предлагаем сохранить или перегенерировать снова
    buttons = [
        ("💾 Сохранить портрет", f"save_portrait|{character_id}"),
        ("🔄 Перегенерировать", f"regenerate_portrait|{character_id}"),
        ("⬅️ Назад в меню персонажа", f"show_character|{character_id}")
    ]
    await send_menu(chat_id, "✅ Новый портрет сгенерирован! Что дальше?", buttons, buttons_per_row=2)

async def show_main_menu(chat_id, user_id):
    role, name = DATA["users"][user_id]["role"], DATA["users"][user_id]["name"]
    buttons = []
    if role == "dm":
        campaigns = [(c["short_name"], c["full_name"]) for c in DATA["campaigns"].values() if c["creator"] == user_id]
        text = (
            f"Привет, {name}! Ты вошёл как мастер.\n"
            f"Твои кампании: {', '.join(n for _, n in campaigns) or 'нет кампаний'}\n"
            f"Выбери действие:"
        )
        for short_name, _ in campaigns:
            buttons.append((f"🏰 {short_name}", f"manage_campaign|{short_name}"))
        buttons.extend([
            ("➕ Новая кампания", "new_campaign"),
            ("⚔️ Как игрок", "join_campaign"),
            ("🧙‍♂️ Новый персонаж", "new_character"),
            ("✏️ Редактировать профиль", "edit_profile")  # Новая кнопка
        ])
        await send_menu(chat_id, text, buttons, buttons_per_row=2)
    else:
        characters = [(cid, c["name"], c["campaigns"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id]
        characters_list = "\n".join(f"- {char_name}: {', '.join(DATA['campaigns'][c]['full_name'] for c in campaigns) or 'без кампаний'}" for cid, char_name, campaigns in characters) if characters else "Нет персонажей."
        text = (
            f"Привет, {name}! Ты вошёл как игрок.\n"
            f"Твои персонажи:\n{characters_list}\n"
            f"Выбери действие:"
        )
        buttons = [(f"📜 {char_name}", f"show_character|{cid}") for cid, char_name, _ in characters]
        buttons.extend([
            ("🤝 Вступить в кампанию", "join_campaign"),
            ("🧙‍♂️ Новый персонаж", "new_character"),
            ("✏️ Редактировать профиль", "edit_profile")  # Новая кнопка
        ])
        await send_menu(chat_id, text, buttons, buttons_per_row=2)


@bot.callback_query_handler(func=lambda call: call.data == "new_character")
async def handle_new_character(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id):
        return
    user_states[user_id] = {"state": "waiting_for_character_name"}
    await send_menu(call.message.chat.id, "🧙‍♂️ Введи имя своего персонажа:")

@bot.callback_query_handler(func=lambda call: call.data == "new_campaign")
async def ask_new_campaign(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id, allow_dm_only=True):
        return
    user_states[user_id] = {"state": "waiting_for_campaign_name"}
    await send_menu(call.message.chat.id,
                    "📝 Введи краткое (до 16 символов) и полное название кампании через пробел:\nПример: Тест Очень Длинное Название Кампании")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_campaign_name")
async def create_campaign_input(message):
    global DATA_CHANGED, CAMPAIGN_BY_CODE
    user_id = str(message.from_user.id)
    if not await check_access(message.chat.id, user_id):
        del user_states[user_id]
        return
    try:
        short_name, *full_name_parts = message.text.split()
        full_name = " ".join(full_name_parts)
        if not (short_name and full_name and len(short_name) <= 16 and short_name not in DATA["campaigns"]):
            raise ValueError
        code = generate_code()
        DATA["campaigns"][short_name] = {
            "creator": user_id,
            "code": code,
            "players": [],
            "sessions": {},
            "short_name": short_name,
            "full_name": full_name
        }
        CAMPAIGN_BY_CODE[code] = short_name
        DATA_CHANGED = True
        await save_data()
        buttons = [(f"🏰 {short_name}", f"manage_campaign|{short_name}")]
        await send_menu(message.chat.id, f"✅ Кампания {full_name} создана!\nКод: {code}", buttons)
    except ValueError:
        await send_menu(message.chat.id, "❌ Введи краткое (до 16 символов) и полное название через пробел, краткое должно быть уникальным!\nПример: Тест Очень Длинное Название")
    finally:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "join_campaign")
async def ask_join_campaign(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id):
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id]
    if not characters:
        await send_menu(call.message.chat.id, "❌ У тебя нет персонажей! Создай одного с помощью /newcharacter")
        return
    user_states[user_id] = {"state": "waiting_for_campaign_code"}
    await send_menu(call.message.chat.id, "🔑 Введи код кампании:")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_campaign_code")
async def join_campaign_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    if not await check_access(message.chat.id, user_id):
        del user_states[user_id]
        return
    code = message.text.strip()
    short_name = CAMPAIGN_BY_CODE.get(code)
    if not short_name:
        await send_menu(message.chat.id, "❌ Неверный код!")
        del user_states[user_id]
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id]
    buttons = [(name, f"join_with_char|{short_name}|{cid}") for cid, name in characters]
    user_states[user_id] = {"state": "waiting_for_character_selection", "data": {"short_name": short_name}}
    await send_menu(message.chat.id, "🧙‍♂️ Выбери персонажа для вступления в кампанию:", buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("join_with_char|"))
async def join_with_character(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, character_id = parts[1], parts[2]
    if user_id not in user_states or user_states[user_id].get("state") != "waiting_for_character_selection":
        await send_menu(call.message.chat.id, "❌ Сессия истекла, попробуй снова!")
        return
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Это не твой персонаж!")
        return
    DATA["campaigns"][short_name]["players"].append(character_id)
    DATA["characters"][character_id]["campaigns"].append(short_name)
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    buttons = [
        ("📜 История", f"history|{short_name}"),
        ("🚪 Выйти", "leave_campaign")
    ]
    await send_menu(call.message.chat.id, f"✅ Персонаж {DATA['characters'][character_id]['name']} присоединился к {DATA['campaigns'][short_name]['full_name']}!", buttons, buttons_per_row=2)
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "leave_campaign")
async def leave_campaign(call):
    global DATA_CHANGED
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id):
        return
    characters = [cid for cid, c in DATA["characters"].items() if c["owner"] == user_id]
    campaign = next((n for n, c in DATA["campaigns"].items() if any(char_id in c["players"] for char_id in characters)), None)
    if not campaign:
        await send_menu(call.message.chat.id, "🏰 У тебя нет персонажей в кампаниях!")
        return
    char_in_campaign = next(char_id for char_id in characters if char_id in DATA["campaigns"][campaign]["players"])
    DATA["campaigns"][campaign]["players"].remove(char_in_campaign)
    DATA["characters"][char_in_campaign]["campaigns"].remove(campaign)
    DATA_CHANGED = True
    await show_main_menu(call.message.chat.id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("manage_campaign|"))
async def manage_campaign(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ты не создатель этой кампании!")
        return
    full_name = DATA["campaigns"][short_name]["full_name"]
    buttons = [
        ("▶️ Начать сессию", f"start_session|{short_name}"),
        ("⏹ Завершить сессию", f"end_session|{short_name}"),
        ("🗑 Удалить сессию", f"delete_session|{short_name}"),
        ("📜 История", f"dm_history|{short_name}"),
        ("🎥 Последние сессии", f"last_sessions_dm|{short_name}"),
        ("🔑 Показать код", f"show_code|{short_name}"),
        ("🏰 Удалить кампанию", f"delete_campaign_prompt|{short_name}")
    ]
    text = f"🏰 Кампания: {full_name}\nЧто хочешь сделать?"
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=3)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_campaign_prompt|"))
async def delete_campaign_prompt(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Ты не создатель этой кампании!")
        return
    full_name = DATA["campaigns"][short_name]["full_name"]
    buttons = [
        ("✅ Да", f"delete_campaign_password|{short_name}"),
        ("❌ Нет", f"manage_campaign|{short_name}")
    ]
    text = (
        f"🏰 Вы точно хотите удалить кампанию {full_name}?\n"
        f"⚠️ Все данные кампании будут удалены без возможности восстановления!"
    )
    await send_menu(chat_id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_campaign_password|"))
async def delete_campaign_password(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Ты не создатель этой кампании!")
        return
    user_states[user_id] = {"state": "confirm_campaign_deletion", "data": {"short_name": short_name}}
    text = (
        f"🔒 Введи свой пароль для подтверждения удаления кампании {DATA['campaigns'][short_name]['full_name']}:\n"
        f"⚠️ Это действие необратимо!"
    )
    await send_menu(chat_id, text, back_to=f"manage_campaign|{short_name}")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "confirm_campaign_deletion")
async def confirm_campaign_deletion(message):
    global DATA_CHANGED, CAMPAIGN_BY_CODE
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    short_name = user_states[user_id]["data"]["short_name"]
    if short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Ты не создатель этой кампании!", back_to="main_menu")
        del user_states[user_id]
        return
    if message.text.strip() != DATA["users"][user_id]["password"]:
        await send_menu(chat_id, "❌ Неверный пароль! Удаление отменено.", back_to=f"manage_campaign|{short_name}")
        del user_states[user_id]
        return
    code = DATA["campaigns"][short_name]["code"]
    full_name = DATA["campaigns"][short_name]["full_name"]
    for char_id in DATA["campaigns"][short_name]["players"]:
        DATA["characters"][char_id]["campaigns"].remove(short_name)
    del DATA["campaigns"][short_name]
    del CAMPAIGN_BY_CODE[code]
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, f"🗑 Кампания {full_name} удалена навсегда!", back_to="main_menu")
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_char_prompt|"))
async def delete_char_prompt(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or not await check_access(chat_id, user_id):
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    char_id = parts[1]
    char = DATA["characters"].get(char_id, {})
    if char["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return
    buttons = [
        ("✅ Да", f"delete_char_password|{char_id}"),
        ("❌ Нет", f"show_character|{char_id}")
    ]
    text = (
        f"🗑 Вы точно хотите удалить персонажа {char['name']}?\n"
        f"⚠️ Все данные персонажа будут удалены без возможности восстановления!"
    )
    await send_menu(chat_id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_char_password|"))
async def delete_char_password(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2 or not await check_access(chat_id, user_id):
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    char_id = parts[1]
    char = DATA["characters"].get(char_id, {})
    if char["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return
    user_states[user_id] = {"state": "confirm_char_deletion", "data": {"char_id": char_id}}
    text = (
        f"🔒 Введи свой пароль для подтверждения удаления персонажа {char['name']}:\n"
        f"⚠️ Это действие необратимо!"
    )
    await send_menu(chat_id, text, back_to=f"show_character|{char_id}")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "confirm_char_deletion")
async def confirm_char_deletion(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    char_id = user_states[user_id]["data"]["char_id"]
    char = DATA["characters"].get(char_id, {})
    if char["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!", back_to="main_menu")
        del user_states[user_id]
        return
    if message.text.strip() != DATA["users"][user_id]["password"]:
        await send_menu(chat_id, "❌ Неверный пароль! Удаление отменено.", back_to=f"show_character|{char_id}")
        del user_states[user_id]
        return
    char_name = char["name"]
    for campaign in DATA["campaigns"].values():
        if char_id in campaign["players"]:
            campaign["players"].remove(char_id)
    if "portrait" in char and os.path.exists(char["portrait"]):
        os.remove(char["portrait"])  # Удаляем файл портрета, если он есть
    del DATA["characters"][char_id]
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, f"🗑 Персонаж {char_name} удалён навсегда!", back_to="main_menu")
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_code|"))
async def show_code(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ты не создатель этой кампании!")
        return
    buttons = [("⬅️ Назад в управление кампаниями", f"manage_campaign|{short_name}")]
    text = f"🔑 Код кампании {DATA['campaigns'][short_name]['full_name']}: {DATA['campaigns'][short_name]['code']}"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("start_session|"))
async def start_session(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Только создатель может начать сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if any(s["active"] for s in sessions.values()):
        buttons = [("⏹ Завершить сессию", f"end_session|{short_name}")]
        await send_menu(call.message.chat.id, "⏳ Уже есть активная сессия!", buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)
        return
    session_num = len(sessions) + 1
    session_name = f"Сессия {session_num}"
    sessions[session_name] = {"active": True, "notes": {}, "player_histories": {}}
    global DATA_CHANGED
    DATA_CHANGED = True
    full_name = DATA["campaigns"][short_name]["full_name"]
    buttons = [("⏹ Завершить сессию", f"end_session|{short_name}")]
    await send_menu(call.message.chat.id, f"▶️ Сессия {session_name} в {full_name} началась!", buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)
    for char_id in DATA["campaigns"][short_name]["players"]:
        player_id = DATA["characters"][char_id]["owner"]
        buttons = [("📝 Добавить заметки", f"start_adding_notes|{short_name}|{session_num}")]
        await send_menu(player_id, f"▶️ Сессия {session_name} в кампании {full_name} началась!\nДобавляй заметки за {DATA['characters'][char_id]['name']}:", buttons, buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("end_session|"))
async def end_session(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Только создатель может завершить сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    if not active_session:
        await send_menu(chat_id, "⏳ Нет активной сессии!", back_to=f"manage_campaign|{short_name}")
        return
    all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[active_session]["notes"].get(char_id, [])]
    if not all_notes:
        buttons = [("✅ Да", f"delete_empty_session|{short_name}|{active_session}"), ("❌ Нет", f"manage_campaign|{short_name}")]
        await send_menu(chat_id, f"📭 Сессия {active_session} пустая. Удалить её?", buttons, buttons_per_row=2)
        return
    session_num = active_session.split("(", 1)[1][:-1] if "(" in active_session else active_session.split()[1]
    new_title = await generate_text(f"Создай название из двух-трёх слов на основе заметок: {'; '.join(all_notes)}", chat_id, is_title=True)
    new_session_name = f"{new_title} ({session_num})"
    # Генерация общей истории мастера
    history = await generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{' '.join(all_notes)}", chat_id, is_dm=True)
    await asyncio.sleep(1)  # Задержка перед следующим запросом
    # Генерация историй для игроков
    player_histories = {}
    for char_id in sessions[active_session]["notes"]:
        if sessions[active_session]["notes"][char_id]:
            player_history = await generate_text(
                f"Перескажи эти события от лица {DATA['characters'][char_id]['name']} кратко, без спойлеров и выдумок:\n{'; '.join(sessions[active_session]['notes'][char_id])}",
                chat_id
            )
            player_histories[char_id] = player_history
            await asyncio.sleep(1)  # Задержка между запросами
    # Обновляем данные сессии
    sessions[new_session_name] = sessions.pop(active_session)
    sessions[new_session_name]["active"] = False
    sessions[new_session_name]["history"] = history
    sessions[new_session_name]["player_histories"] = player_histories
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    # Уведомление мастера
    buttons = [
        ("▶️ Новая сессия", f"start_session|{short_name}"),
        ("🗑 Удалить сессию", f"delete_session|{short_name}"),
        ("🔄 Перегенерировать историю", f"regenerate_dm_history|{short_name}|{session_num}"), 
	("🔄 Перегенерировать название", f"regenerate_title|{short_name}|{session_num}")
    ]
    text = (
        f"⏹ Сессия завершена\n"
        f"Названа {new_session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
        f"Общая хроника:\n{history}"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)
    # Уведомление игроков
    for char_id in DATA["campaigns"][short_name]["players"]:
        player_id = DATA["characters"][char_id]["owner"]
        if player_id != user_id and char_id in player_histories:  # Не отправляем мастеру
            player_text = (
                f"⏹ Сессия {new_session_name} завершена в {DATA['campaigns'][short_name]['full_name']}!\n"
                f"Твоя история для {DATA['characters'][char_id]['name']}:\n"
                f"{player_histories[char_id]}\n"
                f"Сохранить или перегенерировать?"
            )
            player_buttons = [
                ("✅ Сохранить", f"save_player_history|{short_name}|{session_num}|{char_id}"),
                ("🔄 Перегенерировать", f"regenerate_player_history|{short_name}|{session_num}|{char_id}")
            ]
            try:
                await send_menu(int(player_id), player_text, player_buttons, back_to=f"history|{short_name}", buttons_per_row=2)
            except Exception as e:
                print(f"Не удалось отправить сообщение игроку {player_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("regenerate_dm_history|"))
async def regenerate_dm_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id  # Исправлено с chat.ConcurrentHashMapid
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Только создатель может перегенерировать историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or "notes" not in sessions[session_name]:
        await send_menu(chat_id, "📭 Нет заметок для перегенерации!", back_to=f"manage_campaign|{short_name}")
        return
    all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])]
    if not all_notes:
        await send_menu(chat_id, "📭 Нет заметок для этой сессии!", back_to=f"manage_campaign|{short_name}")
        return
    history = await generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{' '.join(all_notes)}", chat_id, is_dm=True)
    if "Ошибка" in history:
        await send_menu(chat_id, f"❌ {history}", back_to=f"manage_campaign|{short_name}")
        return
    sessions[session_name]["history"] = history
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    buttons = [
        ("▶️ Новая сессия", f"start_session|{short_name}"),
        ("🗑 Удалить сессию", f"delete_session|{short_name}"),
        ("🔄 Перегенерировать снова", f"regenerate_dm_history|{short_name}|{session_num}")
    ]
    text = (
        f"🔄 История перегенерирована\n"
        f"Для {session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
        f"{history}"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_dm|"))
async def session_history_dm(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "📭 Такой сессии нет!", back_to=f"last_sessions_dm|{short_name}")
        return
    buttons = [("📝 Заметки", f"session_notes_dm|{short_name}|{session_num}")]
    if "history" in sessions[session_name]:
        history = sessions[session_name]["history"]
    elif "notes" in sessions[session_name] and not sessions[session_name]["active"]:
        all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])]  # Исправлено active_session на session_name
        if not all_notes:
            await send_menu(call.message.chat.id, f"📭 В {session_name} нет заметок!", buttons, back_to=f"last_sessions_dm|{short_name}")
            return
        history = f"Заметки (не сохранено):\n{' '.join(all_notes)}"
        buttons.append(("💾 Сохранить историю", f"save_history|{short_name}|{session_num}"))
    else:
        await send_menu(call.message.chat.id, f"📭 В {session_name} нет данных!", buttons, back_to=f"last_sessions_dm|{short_name}")
        return
    text = (
        f"📜 История\n"
        f"{session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
        f"{history}"
    )
    await send_menu(call.message.chat.id, text, buttons, back_to=f"last_sessions_dm|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("session_notes_dm|"))
async def session_notes_dm(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "📭 Такой сессии нет!", back_to=f"last_sessions_dm|{short_name}")
        return
    if "notes" in sessions[session_name]:
        all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])]  # Исправлено active_session на session_name
        if not all_notes:
            await send_menu(call.message.chat.id, f"📭 В {session_name} нет заметок!", back_to=f"last_sessions_dm|{short_name}")
            return
        text = (
            f"📝 Заметки\n"
            f"{session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
            + "\n".join(f"- {note}" for note in all_notes)
        )
    elif "history" in sessions[session_name]:
        text = (
            f"📜 Заметки удалены\n"
            f"Сохранённая история {session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
            f"{sessions[session_name]['history']}"
        )
    else:
        text = f"📭 В {session_name} нет ни заметок, ни истории!"
    await send_menu(call.message.chat.id, text, back_to=f"last_sessions_dm|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("regenerate_title|"))
async def regenerate_title(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Только создатель может перегенерировать название!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or sessions[session_name]["active"]:
        await send_menu(chat_id, "❌ Сессия не завершена или не существует!", back_to=f"manage_campaign|{short_name}")
        return
    if "notes" in sessions[session_name]:
        all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])]
        new_title = await generate_text(f"Создай название из двух-трёх слов на основе заметок: {'; '.join(all_notes)}", chat_id, is_title=True)
    elif "history" in sessions[session_name]:
        new_title = await generate_text(f"Создай название из двух-трёх слов на основе текста: {sessions[session_name]['history']}", chat_id, is_title=True)
    else:
        await send_menu(chat_id, "📭 Нет данных для перегенерации названия!", back_to=f"manage_campaign|{short_name}")
        return
    old_session_name = session_name
    new_session_name = f"{new_title} ({session_num})"
    sessions[new_session_name] = sessions.pop(old_session_name)
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    buttons = [
        ("✅ Сохранить историю", f"save_history|{short_name}|{session_num}"),
        ("🔄 Переписать историю", f"rewrite_history|{short_name}|{session_num}"),
        ("🔄 Новое название", f"regenerate_title|{short_name}|{session_num}")
    ]
    text = (
        f"⏹ Название изменено\n"
        f"Сессия {old_session_name} в {DATA['campaigns'][short_name]['full_name']} теперь называется {new_session_name}:\n"
        f"{sessions[new_session_name]['history'] if 'history' in sessions[new_session_name] else 'Заметки ещё не пересказаны'}\n"
        f"Сохранить историю или изменить название снова?"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_history|"))
async def save_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Только создатель может сохранить историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(chat_id, "❌ Сессия не найдена!", back_to=f"manage_campaign|{short_name}")
        return
    if "history" in sessions[session_name]:
        history = sessions[session_name]["history"]
        text = f"📜 История для {session_name} уже сохранена:\n{history}"
        await send_menu(chat_id, text, back_to=f"manage_campaign|{short_name}")
        return
    # Используем историю из состояния
    if user_id not in user_states or user_states[user_id]["state"] != "reviewing_history":
        await send_menu(chat_id, "❌ Нет истории для сохранения!", back_to=f"manage_campaign|{short_name}")
        return
    history = user_states[user_id]["data"]["history"]
    sessions[session_name]["history"] = history
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    del user_states[user_id]
    buttons = [
        ("▶️ Новая сессия", f"start_session|{short_name}"),
        ("🗑 Удалить сессию", f"delete_session|{short_name}")
    ]
    text = f"✅ История сессии {session_name} сохранена:\n{history}"
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rewrite_history|"))
async def rewrite_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "🚫 Только создатель может переписать историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or "notes" not in sessions[session_name]:
        await send_menu(chat_id, "❌ Заметки для переписывания не найдены!", back_to=f"manage_campaign|{short_name}")
        return
    all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])]
    history = await generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{'; '.join(all_notes)}", chat_id, is_dm=True)
    user_states[user_id] = {"state": "reviewing_history", "data": {"short_name": short_name, "session_name": session_name, "history": history}}
    buttons = [
        ("✅ Сохранить историю", f"save_history|{short_name}|{session_num}"),
        ("🔄 Переписать историю", f"rewrite_history|{short_name}|{session_num}"), 
	("🔄 Перегенерировать название", f"regenerate_title|{short_name}|{session_num}")
    ]
    text = (
        f"⏹ Новый пересказ\n"
        f"Сессия {session_name}:\n"
        f"{history}\n"
        f"Сохранить эту историю?"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
async def handle_back_to_main_menu(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id):
        return
    await show_main_menu(chat_id, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_empty_session|"))
async def delete_empty_session(call):
    user_id, short_name, session_name = str(call.from_user.id), *call.data.split("|")[1:]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Только создатель может удалить сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if session_name in sessions and sessions[session_name]["active"]:
        del sessions[session_name]
        global DATA_CHANGED
        DATA_CHANGED = True
        buttons = [("▶️ Новая сессия", f"start_session|{short_name}")]
        await send_menu(call.message.chat.id, f"🗑 Пустая сессия {session_name} удалена!", buttons, back_to=f"manage_campaign|{short_name}")
    else:
        await send_menu(call.message.chat.id, "📭 Сессия уже удалена или завершена!", back_to=f"manage_campaign|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_session|"))
async def delete_session(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Только создатель может удалить сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if not sessions:
        await send_menu(call.message.chat.id, "📭 В кампании нет сессий!", back_to=f"manage_campaign|{short_name}")
        return
    last_session = list(sessions)[-1]
    if sessions[last_session]["active"]:
        await send_menu(call.message.chat.id, "🚫 Нельзя удалить активную сессию!", back_to=f"manage_campaign|{short_name}")
        return
    del sessions[last_session]
    global DATA_CHANGED
    DATA_CHANGED = True
    buttons = [("▶️ Новая сессия", f"start_session|{short_name}")]
    await send_menu(call.message.chat.id, f"🗑 Сессия {last_session} удалена!", buttons, back_to=f"manage_campaign|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("start_adding_notes|"))
async def start_adding_notes(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    if not active_session:
        await send_menu(call.message.chat.id, "📭 Нет активной сессии!", back_to=f"history|{short_name}")
        if user_id in user_states:
            del user_states[user_id]
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "❌ У тебя нет персонажей в этой кампании!", back_to=f"history|{short_name}")
        return
    buttons = [(name, f"add_note_with_char|{short_name}|{session_num}|{cid}") for cid, name in characters]
    text = f"🧙‍♂️ Выбери персонажа для добавления заметок в {active_session}:"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_note_with_char|"))
async def add_note_with_char(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(call.message.chat.id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    if not active_session:
        await send_menu(call.message.chat.id, "⏳ Сессия истекла!", back_to=f"history|{short_name}")
        if user_id in user_states:
            del user_states[user_id]
        return
    user_states[user_id] = {
        "state": "adding_note",
        "short_name": short_name,
        "session_name": active_session,
        "character_id": character_id
    }
    await bot.send_message(call.message.chat.id, f"📝 Введи заметку для {DATA['characters'][character_id]['name']} в {active_session}:")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_notes")
async def add_note_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    if not await check_access(message.chat.id, user_id):
        del user_states[user_id]
        return
    short_name = user_states[user_id]["data"]["short_name"]
    session_name = user_states[user_id]["data"]["session_name"]
    character_id = user_states[user_id]["data"]["character_id"]
    note = message.text.strip()
    buttons = [("🏁 Завершить заметки", f"finish_adding_notes|{short_name}")]
    if not note:
        await send_menu(message.chat.id, "❌ Укажи заметку! Продолжай:", buttons)
    else:
        sessions = DATA["campaigns"][short_name]["sessions"]
        sessions[session_name]["notes"].setdefault(character_id, []).append(note)
        DATA_CHANGED = True
        await send_menu(message.chat.id, f"✅ Заметка добавлена в {session_name} для {DATA['characters'][character_id]['name']}! Продолжай:", buttons)

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)]["state"] == "adding_note")
async def process_note(message):
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    state = user_states[user_id]
    short_name = state["short_name"]
    session_name = state["session_name"]
    character_id = state["character_id"]
    note = message.text.strip()
    sessions = DATA["campaigns"][short_name]["sessions"]
    if session_name not in sessions or not sessions[session_name]["active"]:
        await send_menu(chat_id, "⏳ Сессия истекла!", back_to=f"history|{short_name}")
        del user_states[user_id]
        return
    if "notes" not in sessions[session_name]:
        sessions[session_name]["notes"] = {}
    if character_id not in sessions[session_name]["notes"]:
        sessions[session_name]["notes"][character_id] = []
    sessions[session_name]["notes"][character_id].append(note)
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    session_num = session_name.split("(", 1)[1][:-1] if "(" in session_name else session_name.split()[1]
    buttons = [("➕ Добавить ещё", f"add_note_with_char|{short_name}|{session_num}|{character_id}")]
    await send_menu(chat_id, f"✅ Заметка сохранена для {DATA['characters'][character_id]['name']} в {session_name}!", buttons, back_to=f"history|{short_name}")
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_player_history|"))
async def save_player_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or character_id not in sessions[session_name]["player_histories"]:
        await send_menu(chat_id, "📭 История не найдена!", back_to=f"history|{short_name}")
        return
    # История уже сгенерирована и сохранена в end_session, просто подтверждаем
    history = sessions[session_name]["player_histories"][character_id]
    buttons = [("📜 История кампании", f"history|{short_name}")]
    text = (
        f"✅ История сохранена\n"
        f"Для {DATA['characters'][character_id]['name']} в {session_name}:\n"
        f"{history}"
    )
    await send_menu(chat_id, text, buttons, back_to=f"history|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("regenerate_player_history|"))
async def regenerate_player_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or character_id not in sessions[session_name]["notes"]:
        await send_menu(chat_id, "📭 Нет заметок для перегенерации!", back_to=f"history|{short_name}")
        return
    notes = sessions[session_name]["notes"][character_id]
    history = await generate_text(
        f"Перескажи эти события от лица {DATA['characters'][character_id]['name']} кратко, без спойлеров и выдумок:\n{'; '.join(notes)}",
        chat_id
    )
    if "Ошибка" in history:
        await send_menu(chat_id, f"❌ {history}", back_to=f"history|{short_name}")
        return
    sessions[session_name]["player_histories"][character_id] = history
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()
    buttons = [
        ("✅ Сохранить", f"save_player_history|{short_name}|{session_num}|{character_id}"),
        ("🔄 Перегенерировать", f"regenerate_player_history|{short_name}|{session_num}|{character_id}")
    ]
    text = (
        f"🔄 История перегенерирована\n"
        f"Для {DATA['characters'][character_id]['name']} в {session_name}:\n"
        f"{history}"
    )
    await send_menu(chat_id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("history|"))
async def player_history(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "🚫 Ошибка доступа!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "❌ У тебя нет персонажей в этой кампании!")
        return
    buttons = [
        ("📜 Полная история", f"full_history_player|{short_name}"),
        ("🎥 Последние сессии", f"last_sessions_player|{short_name}"),
        ("📜 Квесты", f"select_character_quests|{short_name}")  # Новая кнопка для перехода к квестам
    ]
    text = f"📜 История кампании\n{DATA['campaigns'][short_name]['full_name']}\nЧто посмотреть для твоих персонажей?"
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("quests_menu|"))
async def quests_menu(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    buttons = [
        ("📋 Активные квесты", f"active_quests|{character_id}"),
        ("✅ Завершённые квесты", f"completed_quests|{character_id}"),
        ("➕ Новый квест", f"new_quest|{character_id}")
    ]
    text = f"📜 Квесты персонажа {DATA['characters'][character_id]['name']}"
    await send_menu(chat_id, text, buttons, back_to=f"show_character|{character_id}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("active_quests|"))
async def active_quests(call):
    logging.info(f"active_quests called with data: {call.data}")
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    quests = DATA["characters"][character_id]["quests"]["active"]
    if not quests:
        await send_menu(chat_id, "📭 У тебя нет активных квестов!", back_to=f"quests_menu|{character_id}")
        return

    buttons = [(q_data["name"], f"quest_details|{character_id}|{qid}") for qid, q_data in quests.items()]
    text = f"📋 Активные квесты {DATA['characters'][character_id]['name']}:"
    await send_menu(chat_id, text, buttons, back_to=f"quests_menu|{character_id}", buttons_per_row=1)


@bot.callback_query_handler(func=lambda call: call.data.startswith("new_quest|"))
async def new_quest(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    user_states[user_id] = {"state": "waiting_for_quest_name", "data": {"character_id": character_id}}
    await send_menu(chat_id, "📜 Введи название нового квеста:", back_to=f"quests_menu|{character_id}")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_quest_name")
async def process_quest_name(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    quest_name = message.text.strip()
    if not quest_name:
        await send_menu(chat_id, "❌ Название не может быть пустым!", back_to=f"quests_menu|{character_id}")
        return

    quest_id = f"quest_{len(DATA['characters'][character_id]['quests']['active']) + len(DATA['characters'][character_id]['quests']['completed']) + 1}"
    DATA["characters"][character_id]["quests"]["active"][quest_id] = {
        "name": quest_name,
        "tasks": [],
        "note": ""
    }
    DATA_CHANGED = True
    await save_data()

    user_states[user_id] = {"state": "waiting_for_quest_note", "data": {"character_id": character_id, "quest_id": quest_id}}
    buttons = [("➡️ Пропустить", f"skip_quest_note|{character_id}|{quest_id}")]
    await send_menu(chat_id, f"✅ Квест '{quest_name}' создан!\nДобавь заметку (или пропусти):", buttons)

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_quest_note")
async def process_quest_note(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    quest_id = user_states[user_id]["data"]["quest_id"]
    note = message.text.strip()

    DATA["characters"][character_id]["quests"]["active"][quest_id]["note"] = note
    DATA_CHANGED = True
    await save_data()

    del user_states[user_id]
    await add_first_task(chat_id, user_id, character_id, quest_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("skip_quest_note|"))
async def skip_quest_note(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    del user_states[user_id]
    await add_first_task(chat_id, user_id, character_id, quest_id)

async def add_first_task(chat_id, user_id, character_id, quest_id):
    user_states[user_id] = {"state": "waiting_for_task_text", "data": {"character_id": character_id, "quest_id": quest_id}}
    await send_menu(chat_id, f"📋 Введи текст первого задания для '{DATA['characters'][character_id]['quests']['active'][quest_id]['name']}':", back_to=f"quest_details|{character_id}|{quest_id}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_task|"))
async def add_task(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    user_states[user_id] = {"state": "waiting_for_task_text", "data": {"character_id": character_id, "quest_id": quest_id}}
    await send_menu(chat_id, "📋 Введи текст нового задания:", back_to=f"quest_details|{character_id}|{quest_id}")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_task_text")
async def process_task_text(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    quest_id = user_states[user_id]["data"]["quest_id"]
    task_text = message.text.strip()

    if not task_text:
        await send_menu(chat_id, "❌ Задание не может быть пустым!", back_to=f"quest_details|{character_id}|{quest_id}")
        return

    DATA["characters"][character_id]["quests"]["active"][quest_id]["tasks"].append({
        "text": task_text,
        "completed": False,
        "note": ""
    })
    DATA_CHANGED = True
    await save_data()

    del user_states[user_id]
    await send_menu(chat_id, f"✅ Задание '{task_text}' добавлено!", back_to=f"quest_details|{character_id}|{quest_id}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("complete_task|"))
async def complete_task(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id, task_idx = parts[1], parts[2], int(parts[3])
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    quest = DATA["characters"][character_id]["quests"]["active"][quest_id]
    if task_idx >= len(quest["tasks"]):
        await send_menu(chat_id, "❌ Задание не найдено!", back_to=f"quest_details|{character_id}|{quest_id}")
        return

    task = quest["tasks"][task_idx]
    if task["completed"]:
        await send_menu(chat_id, "❌ Это задание уже завершено!", back_to=f"quest_details|{character_id}|{quest_id}")
        return

    task["completed"] = True
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()

    user_states[user_id] = {"state": "waiting_for_task_note", "data": {"character_id": character_id, "quest_id": quest_id, "task_idx": task_idx}}
    buttons = [("➡️ Пропустить", f"skip_task_note|{character_id}|{quest_id}|{task_idx}")]
    await send_menu(chat_id, f"✅ Задание '{task['text']}' завершено!\nДобавь заметку (или пропусти):", buttons)

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_task_note")
async def process_task_note(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    quest_id = user_states[user_id]["data"]["quest_id"]
    task_idx = user_states[user_id]["data"]["task_idx"]
    note = message.text.strip()

    DATA["characters"][character_id]["quests"]["active"][quest_id]["tasks"][task_idx]["note"] = note
    DATA_CHANGED = True
    await save_data()

    del user_states[user_id]
    await send_menu(chat_id, "✅ Заметка добавлена!", back_to=f"quest_details|{character_id}|{quest_id}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("skip_task_note|"))
async def skip_task_note(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id, task_idx = parts[1], parts[2], int(parts[3])
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    del user_states[user_id]
    await send_menu(chat_id, "✅ Завершено без заметки!", back_to=f"quest_details|{character_id}|{quest_id}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("complete_quest|"))
async def complete_quest(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    quest = DATA["characters"][character_id]["quests"]["active"].get(quest_id)
    if not quest:
        await send_menu(chat_id, "❌ Квест не найден!", back_to=f"active_quests|{character_id}")
        return

    # Проверяем, все ли задания завершены
    if not all(task["completed"] for task in quest["tasks"]):
        await send_menu(chat_id, "❌ Заверши все задания перед завершением квеста!", back_to=f"quest_details|{character_id}|{quest_id}")
        return

    # Формируем промпт для пересказа от лица героя
    prompt = (
        f"Перескажи события квеста '{quest['name']}' от лица персонажа {DATA['characters'][character_id]['name']}.\n"
        f"Вот детали квеста:\n"
        f"Заметка к квесту: {quest['note'] or 'Нет заметки'}\n"
        f"Задания:\n" + "\n".join(
            f"- {task['text']} (Заметка: {task['note'] or 'Нет заметки'})" for task in quest["tasks"]
        )
    )

    # Генерируем историю через вашу функцию
    history = await generate_text(prompt, chat_id, is_dm=False, is_title=False)
    if "Ошибка" in history:
        history = "История не сгенерирована из-за ошибки API."

    # Добавляем историю в данные квеста
    quest["history"] = history

    # Перемещаем квест в завершённые
    DATA["characters"][character_id]["quests"]["completed"][quest_id] = quest
    del DATA["characters"][character_id]["quests"]["active"][quest_id]
    global DATA_CHANGED
    DATA_CHANGED = True
    await save_data()

    # Отправляем сообщение с историей
    text = f"✅ Квест '{quest['name']}' завершён!\n\n**История:**\n{history}"
    await send_menu(chat_id, text, back_to=f"quests_menu|{character_id}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("quest_details|"))
async def quest_details(call):
    logging.info(f"quest_details called with data: {call.data}")
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    quest = DATA["characters"][character_id]["quests"]["active"].get(quest_id)
    if not quest:
        await send_menu(chat_id, "❌ Квест не найден!", back_to=f"active_quests|{character_id}")
        return

    text = f"**{quest['name']}**\n"
    if quest["note"]:
        text += f"Заметка: {quest['note']}\n"
    text += "\nЗадания:\n" + "\n".join(
        f"- [{'✅' if task['completed'] else '⏳'}] {task['text']}" + (f" ({task['note']})" if task['note'] else "")
        for task in quest["tasks"]
    )
    buttons = [
        ("➕ Добавить задание", f"add_task|{character_id}|{quest_id}"),
        ("🏁 Завершить квест", f"complete_quest|{character_id}|{quest_id}")
    ]
    for i, task in enumerate(quest["tasks"]):
        if not task["completed"]:
            buttons.append((f"✅ Завершить '{task['text']}'", f"complete_task|{character_id}|{quest_id}|{i}"))
    await send_menu(chat_id, text, back_to=f"active_quests|{character_id}", buttons=buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("completed_quest_details|"))
async def completed_quest_details(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id, quest_id = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    quest = DATA["characters"][character_id]["quests"]["completed"].get(quest_id)
    if not quest:
        await send_menu(chat_id, "❌ Квест не найден!", back_to=f"completed_quests|{character_id}")
        return

    text = f"**{quest['name']}**\n"
    if quest["note"]:
        text += f"Заметка: {quest['note']}\n"
    text += "\nЗадания:\n" + "\n".join(
        f"- {task['text']}" + (f"\n  Заметка: {task['note']}" if task['note'] else "")
        for task in quest["tasks"]
    )
    if "history" in quest:
        text += f"\n\n**История:**\n{quest['history']}"
    await send_menu(chat_id, text, back_to=f"completed_quests|{character_id}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("completed_quests|"))
async def completed_quests(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if not await check_access(chat_id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return

    quests = DATA["characters"][character_id]["quests"]["completed"]
    if not quests:
        await send_menu(chat_id, "📭 У тебя нет завершённых квестов!", back_to=f"quests_menu|{character_id}")
        return

    buttons = [(q_data["name"], f"completed_quest_details|{character_id}|{qid}") for qid, q_data in quests.items()]
    text = f"✅ Завершённые квесты {DATA['characters'][character_id]['name']}:"
    await send_menu(chat_id, text, buttons, back_to=f"quests_menu|{character_id}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_character_quests|"))
async def select_character_quests(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(chat_id, "🚫 Ошибка доступа!")
        return

    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(chat_id, "❌ У тебя нет персонажей в этой кампании!", back_to=f"history|{short_name}")
        return

    buttons = [(name, f"quests_menu|{cid}") for cid, name in characters]
    text = f"📜 Выбери персонажа для просмотра квестов в кампании {DATA['campaigns'][short_name]['full_name']}:"
    await send_menu(chat_id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("last_sessions_player|"))
async def last_sessions_player(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "🚫 Ошибка доступа!")
        return
    characters = [cid for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "❌ У тебя нет персонажей в этой кампании!")
        return
    sessions = list(DATA["campaigns"][short_name]["sessions"])
    last_three = sessions[-3:] if len(sessions) >= 3 else sessions
    if not last_three:
        await send_menu(call.message.chat.id, "📭 В кампании нет сессий!", back_to=f"history|{short_name}")
        return
    buttons = [(f"🎬 {session}", f"session_history_player|{short_name}|{session.split('(')[-1].strip(')')}") for session in reversed(last_three)]
    text = f"🎥 Последние сессии\n{DATA['campaigns'][short_name]['full_name']}:"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)




@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_player|"))
async def session_history_player(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "📭 Такой сессии нет!", back_to=f"last_sessions_player|{short_name}")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "❌ У тебя нет персонажей в этой кампании!")
        return
    buttons = [(name, f"view_char_session|{short_name}|{session_num}|{cid}") for cid, name in characters]
    text = f"📜 Выбор персонажа\nПросмотр истории в {session_name}:"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"last_sessions_player|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_char_session|"))
async def view_character_session(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(call.message.chat.id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "📭 Такой сессии нет!", back_to=f"last_sessions_player|{short_name}")
        return
    buttons = [("📝 Заметки", f"session_notes_player|{short_name}|{session_num}|{character_id}")]
    if "player_histories" in sessions[session_name] and character_id in sessions[session_name]["player_histories"]:
        history = sessions[session_name]["player_histories"][character_id]
    elif "notes" in sessions[session_name] and sessions[session_name]["notes"].get(character_id, []):
        # Генерируем историю заново, если её нет
        notes = sessions[session_name]["notes"][character_id]
        history = await generate_text(
            f"Перескажи эти события от лица {DATA['characters'][character_id]['name']} кратко, без спойлеров и выдумок:\n{'; '.join(notes)}",
            call.message.chat.id
        )
        if "Ошибка" not in history:
            if "player_histories" not in sessions[session_name]:
                sessions[session_name]["player_histories"] = {}
            sessions[session_name]["player_histories"][character_id] = history
            global DATA_CHANGED
            DATA_CHANGED = True
            await save_data()
        else:
            history = f"Ошибка при генерации: {history}"
    else:
        await send_menu(call.message.chat.id, f"📭 У {DATA['characters'][character_id]['name']} нет данных в {session_name}!", buttons, back_to=f"last_sessions_player|{short_name}")
        return
    text = (
        f"📜 История персонажа\n"
        f"{DATA['characters'][character_id]['name']} в {session_name} ({DATA['campaigns'][short_name]['full_name']}):\n"
        f"{history}"
    )
    await send_menu(call.message.chat.id, text, buttons, back_to=f"last_sessions_player|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("session_notes_player|"))
async def session_notes_player(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(call.message.chat.id, user_id) or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "📭 Такой сессии нет!", back_to=f"last_sessions_player|{short_name}")
        return
    if "notes" in sessions[session_name] and sessions[session_name]["notes"].get(character_id, []):
        notes = sessions[session_name]["notes"].get(character_id, [])
        text = (
            f"📝 Заметки персонажа\n"
            f"{DATA['characters'][character_id]['name']} в {session_name} ({DATA['campaigns'][short_name]['full_name']}):\n"
            + "\n".join(f"- {note}" for note in notes)
        )
    elif "history" in sessions[session_name]:
        history = sessions[session_name]["history"]
        text = (
            f"📜 Заметки удалены\n"
            f"Общая история {session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
            f"{history}"
        )
    else:
        text = f"📭 У {DATA['characters'][character_id]['name']} нет заметок или истории в {session_name}!"
    await send_menu(call.message.chat.id, text, back_to=f"last_sessions_player|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("full_history_player|"))
async def full_history_player(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "🚫 Ошибка доступа!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "❌ У тебя нет персонажей в этой кампании!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    full_history = []
    for session_name, session_data in sessions.items():
        for cid, char_name in characters:
            if "player_histories" in session_data and cid in session_data["player_histories"]:
                full_history.append(f"{session_name} ({char_name}):\n{session_data['player_histories'][cid]}\n")
            elif "notes" in session_data and cid in session_data["notes"] and not session_data["active"]:
                notes = session_data["notes"][cid]
                full_history.append(f"{session_name} ({char_name}, не сохранено):\nЗаметки: {'; '.join(notes)}\n")
    if not full_history:
        await send_menu(call.message.chat.id, "📭 У твоих персонажей нет сохранённой истории!", back_to=f"history|{short_name}")
        return
    text = (
        f"📜 Полная история\n"
        f"Твоих персонажей в {DATA['campaigns'][short_name]['full_name']}:\n\n"
        + "\n".join(full_history)
    )
    await send_menu(call.message.chat.id, text, back_to=f"history|{short_name}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("last_sessions_dm|"))
async def last_sessions_dm(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ты не создатель этой кампании!")
        return
    sessions = list(DATA["campaigns"][short_name]["sessions"])
    last_three = sessions[-3:] if len(sessions) >= 3 else sessions
    if not last_three:
        await send_menu(call.message.chat.id, "📭 В кампании нет сессий!", back_to=f"manage_campaign|{short_name}")
        return
    buttons = [(f"🎬 {session}", f"session_history_dm|{short_name}|{session.split('(')[-1].strip(')')}") for session in reversed(last_three)]
    text = f"🎥 Последние сессии\n{DATA['campaigns'][short_name]['full_name']}:"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_dm|"))
async def session_history_dm(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "📭 Такой сессии нет!", back_to=f"last_sessions_dm|{short_name}")
        return
    buttons = [("📝 Заметки", f"session_notes_dm|{short_name}|{session_num}")]
    if "history" in sessions[session_name]:
        history = sessions[session_name]["history"]
    elif "notes" in sessions[session_name] and not sessions[session_name]["active"]:
        all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[active_session]["notes"].get(char_id, [])]
        if not all_notes:
            await send_menu(call.message.chat.id, f"📭 В {session_name} нет заметок!", buttons, back_to=f"last_sessions_dm|{short_name}")
            return
        history = f"Заметки (не сохранено):\n{' '.join(all_notes)}"
        buttons.append(("💾 Сохранить историю", f"save_history|{short_name}|{session_num}"))
    else:
        await send_menu(call.message.chat.id, f"📭 В {session_name} нет данных!", buttons, back_to=f"last_sessions_dm|{short_name}")
        return
    text = (
        f"📜 История\n"
        f"{session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
        f"{history}"
    )
    await send_menu(call.message.chat.id, text, buttons, back_to=f"last_sessions_dm|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dm_history|"))
async def dm_history(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "❌ Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "🚫 Ты не создатель этой кампании!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    full_history = []
    for session_name, session_data in sessions.items():
        if "history" in session_data:
            full_history.append(f"{session_name}:\n{session_data['history']}\n")
        elif "notes" in session_data and not session_data["active"]:
            all_notes = [f"{DATA['characters'][char_id]['name']}: {note}" for char_id in DATA["campaigns"][short_name]["players"] for note in session_data["notes"].get(char_id, [])]  # Исправлено на session_data
            if all_notes:
                full_history.append(f"{session_name} (не сохранено):\nЗаметки: {'; '.join(all_notes)}\n")
    if not full_history:
        await send_menu(call.message.chat.id, "📭 В этой кампании нет сохранённой истории!", back_to=f"manage_campaign|{short_name}")
        return
    text = (
        f"📜 Полная история\n"
        f"{DATA['campaigns'][short_name]['full_name']}:\n\n"
        + "\n".join(full_history)
    )
    await send_menu(call.message.chat.id, text, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data == "edit_name")
async def ask_new_name(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id):
        return
    user_states[user_id] = {"state": "waiting_for_new_name"}
    await send_menu(chat_id, "📝 Введи новое имя:", back_to="main_menu")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_new_name")
async def process_new_name(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    new_name = message.text.strip()
    if not new_name:
        await send_menu(chat_id, "❌ Имя не может быть пустым!", back_to="main_menu")
        return
    DATA["users"][user_id]["name"] = new_name
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, f"✅ Имя изменено на {new_name}!", back_to="main_menu")
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "edit_password")
async def ask_new_password(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id):
        return
    user_states[user_id] = {"state": "waiting_for_new_password"}
    await send_menu(chat_id, "🔑 Введи новый пароль:", back_to="main_menu")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_new_password")
async def process_new_password(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    new_password = message.text.strip()
    if not new_password:
        await send_menu(chat_id, "❌ Пароль не может быть пустым!", back_to="main_menu")
        return
    DATA["users"][user_id]["password"] = new_password
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, "✅ Пароль успешно изменён!", back_to="main_menu")
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_char_name|"))
async def ask_new_char_name(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "❌ Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "🚫 Это не твой персонаж!")
        return
    user_states[user_id] = {"state": "waiting_for_new_char_name", "data": {"character_id": character_id}}
    await send_menu(chat_id, "📝 Введи новое имя персонажа:", back_to=f"show_character|{character_id}")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_new_char_name")
async def process_new_char_name(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    chat_id = message.chat.id
    character_id = user_states[user_id]["data"]["character_id"]
    new_name = message.text.strip()
    if not new_name:
        await send_menu(chat_id, "❌ Имя не может быть пустым!", back_to=f"show_character|{character_id}")
        return
    DATA["characters"][character_id]["name"] = new_name
    DATA_CHANGED = True
    await save_data()
    await send_menu(chat_id, f"✅ Имя персонажа изменено на {new_name}!", back_to=f"show_character|{character_id}")
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "edit_profile")
async def handle_edit_profile(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    if not await check_access(chat_id, user_id):
        return
    buttons = [
        ("✏️ Изменить имя", "edit_name"),
        ("🔑 Изменить пароль", "edit_password"),
    ]
    text = "Что ты хочешь изменить в своём профиле?"
    await send_menu(chat_id, text, buttons, back_to="main_menu", buttons_per_row=2)

async def periodic_save():
    while True:
        await asyncio.sleep(300)
        await save_data()
        logging.info("Данные автоматически сохранены")

async def main():
    logging.info("Loading data...")
    load_data()
    logging.info("Starting bot...")
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=60)) as session:
        bot.session = session
        asyncio.create_task(periodic_save())
        await bot.polling(non_stop=True, interval=1, timeout=20)

if __name__ == "__main__":
    asyncio.run(main())