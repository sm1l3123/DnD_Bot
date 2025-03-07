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
import base64
from io import BytesIO
from together import Together

logging.basicConfig(level=logging.INFO)
logging.info("Bot started")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY")
DATA_FILE = "dnd_data.json"
TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"
TOGETHER_IMAGE_API_URL = "https://api.together.xyz/v1/images/generations"
ADMIN_PASSWORD = "kikiriki1237"
BACKUP_FOLDER_FILE = "backup_folder_id.txt"
IMAGE_FOLDER = "character_images"
DATA_CHANGED = False
# Исправлены ссылки на CAMPAIGN_BY_CODE
CAMPAIGN_BY_CODE = {c["code"]: short_name for short_name, c in DATA["campaigns"].items()}
user_states = {}

bot = AsyncTeleBot(BOT_TOKEN)
together_client = Together(api_key=TOGETHER_API_KEY)
DATA = {"users": {}, "campaigns": {}, "admins": {}, "characters": {}}
BACKUP_FOLDER_ID = None

if not os.path.exists(IMAGE_FOLDER):
    os.makedirs(IMAGE_FOLDER)

def load_backup_folder_id():
    if os.path.exists(BACKUP_FOLDER_FILE):
        with open(BACKUP_FOLDER_FILE, "r") as f:
            return f.read().strip()
    return None

def save_backup_folder_id(folder_id):
    with open(BACKUP_FOLDER_FILE, "w") as f:
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
            file_time_str = file['title'].replace("dnd_data_", "").replace(".json", "")
            file_time = datetime.strptime(file_time_str, "%Y-%m-%d_%H-%M-%S")
            file_age = current_time - file_time.timestamp()
            if file_age > 24 * 3600:
                file.Delete()
                logging.info(f"Удалён старый бэкап: {file['title']}")
    except Exception as e:
        logging.info(f"Ошибка при очистке бэкапов: {str(e)}")

def backup_images_to_drive():
    drive = authenticate_drive()
    global BACKUP_FOLDER_ID
    BACKUP_FOLDER_ID = load_backup_folder_id()
    image_folder_id = None
    try:
        folder_list = drive.ListFile({'q': f"'{BACKUP_FOLDER_ID}' in parents Images in title"}).GetList()
        if folder_list:
            image_folder_id = folder_list[0]['id']
        else:
            folder_metadata = {
                "title": "Images",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [{"id": BACKUP_FOLDER_ID}]
            }
            folder = drive.CreateFile(folder_metadata)
            folder.Upload()
            image_folder_id = folder["id"]
            logging.info(f"Создана папка Images с ID: {image_folder_id}")
    except Exception as e:
        logging.error(f"Ошибка при поиске или создании папки Images: {str(e)}")
        return
    for image_file in os.listdir(IMAGE_FOLDER):
        file_path = os.path.join(IMAGE_FOLDER, image_file)
        file_metadata = {
            "title": image_file,
            "parents": [{"id": image_folder_id}]
        }
        file = drive.CreateFile(file_metadata)
        file.SetContentFile(file_path)
        file.Upload()
        logging.info(f"Изображение {image_file} загружено на Google Drive!")

def load_data():
    global DATA, DATA_CHANGED, CAMPAIGN_BY_CODE
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as file:
            DATA = json.load(file)
    if "admins" not in DATA:
        DATA["admins"] = {}
    if "characters" not in DATA:
        DATA["characters"] = {}
    CAMPAIGN_BY_CODE = {c["code"]: short_name for short_name, c in DATA["campaigns"].items()}
    DATA_CHANGED = False

def save_data(force=False):
    global DATA_CHANGED
    if not DATA_CHANGED and not force:
        return
    with open(DATA_FILE, "w") as file:
        json.dump(DATA, file, indent=2)
    backup_to_drive()
    DATA_CHANGED = False

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def generate_text(prompt, chat_id, is_dm=False, is_title=False, is_shortening=False):
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    system_prompt = (
        "Ты помощник, который создаёт название сессии из двух слов (максимум 20 символов с номером) на русском языке на основе заметок. Название должно быть кратким, логичным, отражать ключевые события в том порядке, в котором они указаны, и не содержать выдуманных деталей. Используй только информацию из заметок, сохраняя их последовательность."
        if is_title else
        ("Ты помощник, который сокращает текст предыстории на русском языке до 2-3 предложений, сохраняя ключевые детали и порядок событий, без выдумок."
         if is_shortening else
         ("Ты помощник, который пересказывает события от лица героя на русском языке. Сохраняй строгий порядок событий, как они указаны в заметках, без изменений последовательности, добавления выдуманных деталей или пропуска событий. Текст должен быть кратким, но включать все ключевые моменты из заметок, с естественными склонениями и связностью."
          if not is_dm else
          "Ты помощник, который составляет краткую хронику событий кампании на русском языке в третьем лице. У тебя есть заметки от разных игроков, подписанные их именами (формат: 'Имя: заметка'). Твоя задача: объединить эти заметки в связную историю, сохраняя строгий порядок появления заметок в списке. Если заметки пересекаются или противоречат, выбирай наиболее логичное объяснение и соединяй их естественными переходами (например, 'тем временем', 'в то же время', 'после этого'). Не добавляй выдуманные детали, не пропускай события и используй только данные из заметок. Текст должен быть кратким, но полным, с естественными склонениями и ясной последовательностью."))
    )
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        "max_tokens": 10 if is_title else (150 if is_shortening else 500000),
        "temperature": 0.4,
        "top_p": 0.9,
        "stream": False
    }
    try:
        await bot.send_chat_action(chat_id, 'typing')
        async with aiohttp.ClientSession() as session:
            async with session.post(TOGETHER_API_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    return f"Ошибка API: {response.status}. Заметки: {prompt}"
                data = await response.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Ошибка генерации текста: {str(e)}")
        return f"Ошибка: {str(e)}. Заметки: {prompt}"

async def translate_to_english(text):
    prompt = f"Переведи этот текст с русского на английский, сохраняя все детали и смысл:\n{text}"
    response = together_client.completions.create(
        model="deepseek-ai/DeepSeek-V3",
        prompt=prompt,
        max_tokens=512,
        temperature=0.7,
        top_p=0.7,
        top_k=50,
        repetition_penalty=1,
        stream=True
    )
    translated_text = ""
    for token in response:
        if hasattr(token, 'choices'):
            if token.choices[0].delta.content is not None:
                translated_text += token.choices[0].delta.content  # Add only if it's not None
    return translated_text.strip()

async def generate_image(prompt, chat_id):
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "model": "black-forest-labs/FLUX.1-schnell-Free",
        "width": 1024,
        "height": 768,
        "steps": 4,
        "n": 1,
        "response_format": "b64_json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            await bot.send_chat_action(chat_id, 'upload_photo')
            async with session.post(TOGETHER_IMAGE_API_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    return f"Ошибка генерации изображения: {response.status}"
                data = await response.json()
                b64_image = data["data"][0]["b64_json"]
                image_data = base64.b64decode(b64_image)
                return BytesIO(image_data)
    except Exception as e:
        logging.error(f"Ошибка генерации изображения: {str(e)}")
        return f"Ошибка генерации изображения: {str(e)}"

async def send_menu(chat_id, text, buttons=None, back_to="main_menu", buttons_per_row=2):
    markup = types.InlineKeyboardMarkup()
    if buttons:
        for i in range(0, len(buttons), buttons_per_row):
            row_buttons = buttons[i:i + buttons_per_row]
            markup.add(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in row_buttons])
    markup.add(types.InlineKeyboardButton("Назад", callback_data=back_to))
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
        buttons = [("Войти", "login"), ("Назад", "main_menu")]
        await send_menu(chat_id, "Ты не зарегистрирован!", buttons, buttons_per_row=2)
        return False
    if allow_dm_only and DATA["users"][user_id]["role"] != "dm":
        buttons = [("Назад", "main_menu")]
        await send_menu(chat_id, "Только мастер может это сделать!", buttons, buttons_per_row=1)
        return False
    return True

async def check_admin(chat_id, user_id):
    if user_id not in DATA["admins"] or not DATA["admins"][user_id]:
        buttons = [("Назад", "main_menu")]
        await send_menu(chat_id, "Доступ только для админов! Используй /admin", buttons, buttons_per_row=1)
        return False
    return True

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    user_id = str(message.from_user.id)
    if user_id in DATA["users"]:
        buttons = [("Войти", "login")]
        text = "Ты зарегистрирован! Войди:"
    else:
        buttons = [("Как мастер", "register_dm"), ("Как игрок", "register_player")]
        text = "Добро пожаловать! Зарегистрируйся:"
    await send_menu(message.chat.id, text, buttons, buttons_per_row=2)

@bot.message_handler(commands=['admin'])
async def admin_login(message):
    user_id = str(message.from_user.id)
    user_states[user_id] = {"state": "waiting_for_admin_password"}
    await send_menu(message.chat.id, "Введи пароль админа:")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_admin_password")
async def handle_admin_password_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    if message.text.strip() == ADMIN_PASSWORD:
        DATA["admins"][user_id] = True
        DATA_CHANGED = True
        save_data()
        del user_states[user_id]
        await show_admin_panel(message.chat.id, user_id)
    else:
        del user_states[user_id]
        await send_menu(message.chat.id, "Неверный пароль админа!")

@bot.message_handler(commands=['exitadmin'])
async def admin_logout(message):
    user_id = str(message.from_user.id)
    if user_id in DATA["admins"] and DATA["admins"][user_id]:
        global DATA_CHANGED
        DATA["admins"][user_id] = False
        DATA_CHANGED = True
        save_data()
        await send_menu(message.chat.id, "Ты вышел из админ-панели!")
    else:
        await send_menu(message.chat.id, "Ты не в админ-панели!")

async def show_admin_panel(chat_id, user_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    buttons = [
        ("Пользователи", "admin_users"),
        ("Кампании", "admin_campaigns"),
        ("Выйти", "admin_exit")
    ]
    text = "Админ-панель\nДобро пожаловать! Что хочешь сделать?"
    await send_menu(chat_id, text, buttons, buttons_per_row=3)

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
        save_data()
        await send_menu(call.message.chat.id, "Ты вышел из админ-панели!")
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

async def show_users_panel(chat_id, user_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    text = "Список пользователей\n"
    buttons = []
    for uid, user in DATA["users"].items():
        characters = [c["name"] for c in DATA["characters"].values() if c["owner"] == uid]
        text += f"- ID: {uid} | Имя: {user['name']} | Роль: {'мастер' if user['role'] == 'dm' else 'игрок'} | Персонажи: {', '.join(characters) or 'нет'}\n"
        buttons.append((f"{user['name']}", f"admin_user_details|{uid}"))
    await send_menu(chat_id, text, buttons, back_to="admin_panel", buttons_per_row=2)

async def show_user_details(chat_id, user_id, target_uid):
    if not await check_access(chat_id, user_id, admin=True):
        return
    user = DATA["users"].get(target_uid, {})
    if not user:
        await send_menu(chat_id, "Пользователь не найден!", back_to="admin_users")
        return
    characters = [(cid, c["name"], c.get("backstory", "Нет предыстории")) for cid, c in DATA["characters"].items() if c["owner"] == target_uid]
    campaigns = [c["full_name"] for c in DATA["campaigns"].values() if any(char_id in c["players"] for char_id, _, _ in characters)]
    text = (
        f"Детали пользователя\n"
        f"ID: {target_uid}\n"
        f"Имя: {user['name']}\n"
        f"Роль: {'мастер' if user['role'] == 'dm' else 'игрок'}\n"
        f"Пароль: {user['password']}\n"
        f"Персонажи:\n" + "\n".join(f"- {name} (ID: {cid})\n  Предыстория: {backstory}" for cid, name, backstory in characters) + "\n"
        f"Кампании: {', '.join(campaigns) or 'нет'}"
    )
    buttons = [
        ("Сбросить пароль", f"admin_reset_password|{target_uid}"),
        ("Удалить", f"admin_delete_user|{target_uid}")
    ]
    await send_menu(chat_id, text, buttons, back_to="admin_users", buttons_per_row=2)

async def reset_password_prompt(chat_id, user_id, target_uid):
    if not await check_access(chat_id, user_id, admin=True):
        return
    user_states[user_id] = {"state": "waiting_for_reset_password", "data": {"target_uid": target_uid}}
    await send_menu(chat_id, f"Введи новый пароль для {DATA['users'][target_uid]['name']}:", back_to=f"admin_user_details|{target_uid}")

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
        await send_menu(message.chat.id, "Пароль не может быть пустым!", back_to=f"admin_user_details|{target_uid}")
        del user_states[user_id]
        return
    DATA["users"][target_uid]["password"] = new_password
    DATA_CHANGED = True
    await send_menu(message.chat.id, f"Пароль для {DATA['users'][target_uid]['name']} сброшен на {new_password}!", back_to=f"admin_user_details|{target_uid}")
    del user_states[user_id]

async def delete_user(chat_id, user_id, target_uid):
    global DATA_CHANGED
    if not await check_access(chat_id, user_id, admin=True):
        return
    if target_uid not in DATA["users"]:
        await send_menu(chat_id, "Пользователь не найден!", back_to="admin_users")
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
    await send_menu(chat_id, f"Пользователь {user_name} удалён!", back_to="admin_users")

async def show_campaigns_panel(chat_id, user_id):
    if not await check_access(chat_id, user_id, admin=True):
        return
    text = "Список кампаний\n"
    buttons = []
    for short_name, camp in DATA["campaigns"].items():
        players = [DATA["characters"][pid]["name"] for pid in camp["players"]]
        text += f"- {short_name} | Полное: {camp['full_name']}\n  Создатель: {DATA['users'][camp['creator']]['name']} | Участники: {', '.join(players) or 'нет'}\n"
        buttons.append((f"{short_name}", f"admin_campaign_details|{short_name}"))
    await send_menu(chat_id, text, buttons, back_to="admin_panel", buttons_per_row=2)

async def show_campaign_details(chat_id, user_id, short_name):
    if not await check_access(chat_id, user_id, admin=True):
        return
    camp = DATA["campaigns"].get(short_name, {})
    if not camp:
        await send_menu(chat_id, "Кампания не найдена!", back_to="admin_campaigns")
        return
    players = [f"{DATA['characters'][pid]['name']} (владелец: {DATA['users'][DATA['characters'][pid]['owner']]['name']})" for pid in camp["players"]]
    sessions = camp["sessions"]
    text = (
        f"Детали кампании\n"
        f"Краткое название: {short_name}\n"
        f"Полное название: {camp['full_name']}\n"
        f"Создатель: {DATA['users'][camp['creator']]['name']} (ID: {camp['creator']})\n"
        f"Код: {camp['code']}\n"
        f"Участники:\n" + "\n".join(f"- {p}" for p in players) or "нет" + "\n"
        f"Сессий: {len(sessions)}\n"
        f"Активная сессия: {'да' if any(s['active'] for s in sessions.values()) else 'нет'}"
    )
    buttons = [("Удалить", f"admin_delete_campaign|{short_name}")]
    await send_menu(chat_id, text, buttons, back_to="admin_campaigns", buttons_per_row=1)

async def delete_campaign(chat_id, user_id, short_name):
    global DATA_CHANGED, CAMPAIGN_BY_CODE
    if not await check_access(chat_id, user_id, admin=True):
        return
    if short_name not in DATA["campaigns"]:
        await send_menu(chat_id, "Кампания не найдена!", back_to="admin_campaigns")
        return
    code = DATA["campaigns"][short_name]["code"]
    full_name = DATA["campaigns"][short_name]["full_name"]
    for char_id in DATA["campaigns"][short_name]["players"]:
        DATA["characters"][char_id]["campaigns"].remove(short_name)
    del DATA["campaigns"][short_name]
    del CAMPAIGN_BY_CODE[code]
    DATA_CHANGED = True
    await send_menu(chat_id, f"Кампания {full_name} удалена!", back_to="admin_campaigns")

@bot.callback_query_handler(func=lambda call: call.data in ["register_dm", "register_player"])
async def handle_register_choice(call):
    user_id = str(call.from_user.id)
    if user_id in DATA["users"]:
        buttons = [("Войти", "login")]
        await send_menu(call.message.chat.id, "Ты уже зарегистрирован!", buttons)
        return
    role = "dm" if call.data == "register_dm" else "player"
    user_states[user_id] = {"state": "waiting_for_registration", "data": {"role": role}}
    await send_menu(call.message.chat.id, "Введи имя и пароль в формате: Имя Пароль\nПример: Иван pass123")

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
        save_data()
        buttons = [("Войти", "login")]
        await send_menu(message.chat.id, f"Ты зарегистрирован как {'мастер' if role == 'dm' else 'игрок'}, {name}!\nТеперь войди.", buttons)
    except ValueError:
        await send_menu(message.chat.id, "Неверный формат! Введи: Имя Пароль")
    finally:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "login")
async def ask_login(call):
    user_id = str(call.from_user.id)
    if user_id not in DATA["users"]:
        buttons = [("Зарегистрироваться", "start")]
        await send_menu(call.message.chat.id, "Ты не зарегистрирован! Начни заново:", buttons)
        return
    user_states[user_id] = {"state": "waiting_for_login_password"}
    await send_menu(call.message.chat.id, "Введи пароль для входа:")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_login_password")
async def login_user_input(message):
    user_id = str(message.from_user.id)
    if user_id not in DATA["users"]:
        await send_menu(message.chat.id, "Ты не зарегистрирован! Начни заново: /start")
        del user_states[user_id]
        return
    if DATA["users"][user_id]["password"] != message.text.strip():
        buttons = [("Снова", "login")]
        await send_menu(message.chat.id, "Неверный пароль!", buttons)
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
    await send_menu(message.chat.id, "Введи имя своего персонажа:")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_character_name")
async def create_character_name_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    name = message.text.strip()
    if not name:
        await send_menu(message.chat.id, "Имя не может быть пустым!")
        del user_states[user_id]
        return
    character_id = f"char_{len(DATA['characters']) + 1}"
    user_states[user_id] = {"state": "waiting_for_character_backstory", "data": {"character_id": character_id, "name": name, "backstory_parts": []}}
    await send_menu(message.chat.id, f"Персонаж {name} (ID: {character_id}) создан!\nВведи предысторию (по частям, пиши 'готово', чтобы закончить):")

@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states and user_states[str(message.from_user.id)].get("state") == "waiting_for_character_backstory")
async def create_character_backstory_input(message):
    global DATA_CHANGED
    user_id = str(message.from_user.id)
    character_id = user_states[user_id]["data"]["character_id"]
    name = user_states[user_id]["data"]["name"]
    text = message.text.strip()
    if text.lower() == "готово":
        backstory_parts = user_states[user_id]["data"]["backstory_parts"]
        if not backstory_parts:
            backstory = "Предыстория отсутствует"
        else:
            full_backstory = " ".join(backstory_parts)
            if len(full_backstory) > 500:
                backstory = await generate_text(f"Сократи эту предысторию до 2-3 предложений:\n{full_backstory}", message.chat.id, is_shortening=True)
            else:
                backstory = full_backstory
        DATA["characters"][character_id] = {
            "name": name,
            "owner": user_id,
            "campaigns": [],
            "backstory": backstory,
            "image_path": None
        }
        DATA_CHANGED = True
        save_data()
        buttons = [("Предыстория", f"show_character|{character_id}"), ("Кампании", "join_campaign")]
        await send_menu(message.chat.id, f"Персонаж {name} создан с ID: {character_id}!", buttons, buttons_per_row=2)
        del user_states[user_id]
    else:
        user_states[user_id]["data"]["backstory_parts"].append(text)
        await send_menu(message.chat.id, "Часть предыстории добавлена! Продолжай или напиши 'готово':")

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_character|"))
async def show_character(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "Ошибка в запросе!")
        return
    character_id = parts[1]
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "Это не твой персонаж!")
        return
    char = DATA["characters"][character_id]
    text = (
        f"Персонаж: {char['name']}\n"
        f"ID: {character_id}\n"
        f"Предыстория: {char['backstory']}\n"
        f"Кампании:\n" + "\n".join(f"- {DATA['campaigns'][c]['full_name']}" for c in char['campaigns']) or "нет"
    )
    buttons = [(f"{DATA['campaigns'][c]['short_name']}", f"history|{c}") for c in char["campaigns"]]
    buttons.append(("Вступить в новую", "join_campaign"))
    buttons.append(("Сгенерировать портрет", f"generate_character_image|{character_id}"))
    if char.get("image_path"):
        buttons.append(("Перегенерировать портрет", f"regenerate_character_image|{character_id}"))
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("generate_character_image|") or call.data.startswith("regenerate_character_image|"))
async def generate_character_image(call):
        user_id = str(call.from_user.id)
        is_regenerate = call.data.startswith("regenerate_character_image|")
        parts = call.data.split("|")
        if len(parts) < 2:
            await send_menu(call.message.chat.id, "Ошибка в запросе!")
            return
        character_id = parts[1]
        if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
            await send_menu(call.message.chat.id, "Это не твой персонаж!")
            return
        char = DATA["characters"][character_id]
        player_name = DATA["users"][user_id]["name"]
        backstory_en = await translate_to_english(char["backstory"])
        prompt = (
            f"A detailed portrait of a fantasy character named {char['name']}, "
            f"a unique adventurer from a Dungeons & Dragons world. "
            f"Based on the backstory: {backstory_en}. "
            f"The character has distinct features reflecting their personality and history, "
            f"set against a dramatic background that hints at their journey. "
            f"Highly detailed, cinematic lighting, vibrant colors, fantasy art style."
        )
        image = await generate_image(prompt, call.message.chat.id)
        if isinstance(image, str):
            logging.error(f"Ошибка при генерации изображения для {char['name']}: {image}")
            await send_menu(call.message.chat.id, image, back_to=f"show_character|{character_id}")
        else:
            image_path = os.path.join(IMAGE_FOLDER, f"{char['name']}_{player_name}.png")
            with open(image_path, "wb") as f:
                f.write(image.getvalue())
            DATA["characters"][character_id]["image_path"] = image_path
            global DATA_CHANGED
            DATA_CHANGED = True
            save_data()
            try:
                backup_images_to_drive()
                await bot.send_photo(call.message.chat.id, image, caption=f"Портрет {char['name']}")
                await send_menu(call.message.chat.id, f"Портрет {'перегенерирован' if is_regenerate else 'сгенерирован'} и сохранён!", back_to=f"show_character|{character_id}")
            except Exception as e:
                logging.error(f"Ошибка при резервном копировании или отправке фото: {str(e)}")
                await send_menu(call.message.chat.id, f"Ошибка после генерации: {str(e)}", back_to=f"show_character|{character_id}")

async def show_main_menu(chat_id, user_id):
    role, name = DATA["users"][user_id]["role"], DATA["users"][user_id]["name"]
    buttons = []
    if role == "dm":
        campaigns = [(c["short_name"], c["full_name"]) for c in DATA["campaigns"].values() if c["creator"] == user_id]
        text = (
            f"Привет, {name}!\n"
            f"Ты вошёл как мастер.\n"
            f"Твои кампании: {', '.join(n for _, n in campaigns) or 'нет кампаний'}\n"
            f"Что хочешь сделать?"
        )
        for short_name, _ in campaigns:
            buttons.append((f"'{short_name}'", f"manage_campaign|{short_name}"))
        buttons.extend([("Новая", "new_campaign"), ("Как игрок", "join_campaign"), ("Персонаж", "/newcharacter")])
        await send_menu(chat_id, text, buttons, buttons_per_row=2)
    else:
        characters = [(cid, c["name"], c["campaigns"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id]
        text = (
            f"Привет, {name}!\n"
            f"Ты вошёл как игрок.\n"
            f"Твои персонажи:\n"
        )
        if characters:
            for cid, char_name, campaigns in characters:
                text += f"- {char_name}: {', '.join(DATA['campaigns'][c]['full_name'] for c in campaigns) or 'без кампаний'}\n"
            buttons = [(f"{char_name}", f"show_character|{cid}") for cid, char_name, _ in characters]
        else:
            text += "Нет персонажей.\n"
        buttons.extend([("Вступить", "join_campaign"), ("Новый", "/newcharacter")])
        await send_menu(chat_id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data == "new_campaign")
async def ask_new_campaign(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id, allow_dm_only=True):
        return
    user_states[user_id] = {"state": "waiting_for_campaign_name"}
    await send_menu(call.message.chat.id, "Введи краткое (до 16 символов) и полное название кампании через пробел:\nПример: Тест Очень Длинное Название Кампании")

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
        save_data()
        buttons = [(f"'{short_name}'", f"manage_campaign|{short_name}")]
        await send_menu(message.chat.id, f"Кампания {full_name} создана!\nКод: {code}", buttons)
    except ValueError:
        await send_menu(message.chat.id, "Введи краткое (до 16 символов) и полное название через пробел, краткое должно быть уникальным!\nПример: Тест Очень Длинное Название")
    finally:
        del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "join_campaign")
async def ask_join_campaign(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id):
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id]
    if not characters:
        await send_menu(call.message.chat.id, "У тебя нет персонажей! Создай одного с помощью /newcharacter")
        return
    user_states[user_id] = {"state": "waiting_for_campaign_code"}
    await send_menu(call.message.chat.id, "Введи код кампании:")

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
        await send_menu(message.chat.id, "Неверный код!")
        del user_states[user_id]
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id]
    buttons = [(name, f"join_with_char|{short_name}|{cid}") for cid, name in characters]
    user_states[user_id] = {"state": "waiting_for_character_selection", "data": {"short_name": short_name}}
    await send_menu(message.chat.id, "Выбери персонажа для вступления в кампанию:", buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("join_with_char|"))
async def join_with_character(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "Ошибка в запросе!")
        return
    short_name, character_id = parts[1], parts[2]
    if user_id not in user_states or user_states[user_id].get("state") != "waiting_for_character_selection":
        await send_menu(call.message.chat.id, "Сессия истекла, попробуй снова!")
        return
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "Это не твой персонаж!")
        return
    DATA["campaigns"][short_name]["players"].append(character_id)
    DATA["characters"][character_id]["campaigns"].append(short_name)
    global DATA_CHANGED
    DATA_CHANGED = True
    save_data()
    buttons = [
        ("История", f"history|{short_name}"),
        ("Выйти", "leave_campaign")
    ]
    await send_menu(call.message.chat.id, f"Персонаж {DATA['characters'][character_id]['name']} присоединился к {DATA['campaigns'][short_name]['full_name']}!", buttons, buttons_per_row=2)
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
        await send_menu(call.message.chat.id, "У тебя нет персонажей в кампаниях!")
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
        await send_menu(call.message.chat.id, "Ты не создатель этой кампании!")
        return
    full_name = DATA["campaigns"][short_name]["full_name"]
    buttons = [
        ("Начать", f"start_session|{short_name}"),
        ("Завершить", f"end_session|{short_name}"),
        ("Удалить", f"delete_session|{short_name}"),
        ("История", f"dm_history|{short_name}"),
        ("Последние", f"last_sessions_dm|{short_name}"),
        ("Код", f"show_code|{short_name}")
    ]
    text = f"Кампания: {full_name}\nЧто хочешь сделать?"
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=3)

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_code|"))
async def show_code(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Ты не создатель этой кампании!")
        return
    buttons = [("Назад", f"manage_campaign|{short_name}")]
    text = f"Код кампании {DATA['campaigns'][short_name]['full_name']}: {DATA['campaigns'][short_name]['code']}"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("start_session|"))
async def start_session(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может начать сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if any(s["active"] for s in sessions.values()):
        buttons = [("Завершить", f"end_session|{short_name}")]
        await send_menu(call.message.chat.id, "Уже есть активная сессия!", buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)
        return
    session_num = len(sessions) + 1
    session_name = f"Сессия {session_num}"
    sessions[session_name] = {"active": True, "notes": {}, "player_histories": {}}
    global DATA_CHANGED
    DATA_CHANGED = True
    save_data()
    full_name = DATA["campaigns"][short_name]["full_name"]
    buttons = [("Завершить", f"end_session|{short_name}")]
    await send_menu(call.message.chat.id, f"Сессия {session_name} в {full_name} началась!", buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)
    for char_id in DATA["campaigns"][short_name]["players"]:
        player_id = DATA["characters"][char_id]["owner"]
        buttons = [("Заметки", f"start_adding_notes|{short_name}|{session_num}")]
        await send_menu(player_id, f"Сессия {session_name} в кампании {full_name} началась!\nДобавляй заметки за {DATA['characters'][char_id]['name']}:", buttons, buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("end_session|"))
async def end_session(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(chat_id, "Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "Только создатель может завершить сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    if not active_session:
        await send_menu(chat_id, "Нет активной сессии!", back_to=f"manage_campaign|{short_name}")
        return
    all_notes = [f"{DATA['users'].get(DATA['characters'][char_id]['owner'], {}).get('name', 'Неизвестный')}: {note}"
                 for char_id in DATA["campaigns"][short_name]["players"]
                 for note in sessions[active_session]["notes"].get(char_id, [])]
    if not all_notes:
        buttons = [("Да", f"delete_empty_session|{short_name}|{active_session}"), ("Нет", f"manage_campaign|{short_name}")]
        await send_menu(chat_id, f"Сессия {active_session} пустая. Удалить её?", buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)
        return
    session_num = int(active_session.split()[1])
    new_title = await generate_text(f"Создай название из двух слов на основе заметок: {'; '.join(all_notes)}", chat_id, is_title=True)
    new_session_name = f"{new_title} ({session_num})"
    history = await generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{' '.join(all_notes)}", chat_id, is_dm=True)
    sessions[new_session_name] = sessions.pop(active_session)
    sessions[new_session_name]["active"] = False
    global DATA_CHANGED
    DATA_CHANGED = True
    save_data()
    buttons = [
        ("Сохранить", f"save_history|{short_name}|{session_num}"),
        ("Переписать", f"rewrite_history|{short_name}|{session_num}"),
        ("Перегенерировать название", f"regenerate_title|{short_name}|{session_num}"),
        ("Сгенерировать сцену", f"generate_session_image|{short_name}|{session_num}")
    ]
    text = (
        f"Сессия завершена\n"
        f"Названа {new_session_name} в {DATA['campaigns'][short_name]['full_name']}:\n"
        f"{history}\n"
        f"Сохранить этот пересказ, перегенерировать название или создать изображение?"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("generate_session_image|"))
async def generate_session_image(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(call.message.chat.id, "Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может генерировать изображения!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "Сессия не найдена!", back_to=f"manage_campaign|{short_name}")
        return
    if "history" in sessions[session_name]:
        history_en = await translate_to_english(sessions[session_name]["history"])
        prompt = (
            f"A detailed scene from the Dungeons & Dragons campaign '{DATA['campaigns'][short_name]['full_name']}', "
            f"session titled '{session_name}'. Based on the events: {history_en}. "
            f"Featuring key moments and characters involved, set in a vivid fantasy environment with dramatic lighting, "
            f"rich colors, and cinematic composition. High detail, epic fantasy art style."
        )
    elif "notes" in sessions[session_name]:
        all_notes = [f"{DATA['characters'][cid]['name']}: {n}" for cid in DATA["campaigns"][short_name]["players"] for n in sessions[session_name]["notes"].get(cid, [])]
        notes_en = await translate_to_english("; ".join(all_notes))
        prompt = (
            f"A detailed scene from the Dungeons & Dragons campaign '{DATA['campaigns'][short_name]['full_name']}', "
            f"session titled '{session_name}'. Based on the notes: {notes_en}. "
            f"Depicting the actions and interactions of characters in a dynamic fantasy setting, "
            f"with cinematic lighting, vibrant colors, and high detail in an epic fantasy art style."
        )
    else:
        await send_menu(call.message.chat.id, "Нет данных для генерации изображения!", back_to=f"manage_campaign|{short_name}")
        return
    image = await generate_image(prompt, call.message.chat.id)
    if isinstance(image, str):
        await send_menu(call.message.chat.id, image, back_to=f"manage_campaign|{short_name}")
    else:
        await bot.send_photo(call.message.chat.id, image, caption=f"Сцена из {session_name} в {DATA['campaigns'][short_name]['full_name']}")
        await send_menu(call.message.chat.id, "Изображение сгенерировано!", back_to=f"manage_campaign|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("regenerate_title|"))
async def regenerate_title(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "Только создатель может перегенерировать название!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or sessions[session_name]["active"]:
        await send_menu(chat_id, "Сессия не завершена или не существует!", back_to=f"manage_campaign|{short_name}")
        return
    if "notes" in sessions[session_name]:
        all_notes = [f"{DATA['users'].get(DATA['characters'][char_id]['owner'], {}).get('name', 'Неизвестный')}: {note}"
                     for char_id in DATA["campaigns"][short_name]["players"]
                     for note in sessions[session_name]["notes"].get(char_id, [])]
        new_title = await generate_text(f"Создай название из двух слов на основе заметок: {'; '.join(all_notes)}", chat_id, is_title=True)
    elif "history" in sessions[session_name]:
        new_title = await generate_text(f"Создай название из двух слов на основе текста: {sessions[session_name]['history']}", chat_id, is_title=True)
    else:
        await send_menu(chat_id, "Нет данных для перегенерации названия!", back_to=f"manage_campaign|{short_name}")
        return
    old_session_name = session_name
    new_session_name = f"{new_title} ({session_num})"
    sessions[new_session_name] = sessions.pop(old_session_name)
    global DATA_CHANGED
    DATA_CHANGED = True
    save_data()
    buttons = [
        ("Сохранить", f"save_history|{short_name}|{session_num}"),
        ("Переписать", f"rewrite_history|{short_name}|{session_num}"),
        ("Перегенерировать название", f"regenerate_title|{short_name}|{session_num}"),
        ("Сгенерировать сцену", f"generate_session_image|{short_name}|{session_num}")
    ]
    text = (
        f"Название перегенерировано\n"
        f"Сессия {old_session_name} в {DATA['campaigns'][short_name]['full_name']} теперь называется {new_session_name}:\n"
        f"{sessions[new_session_name]['history'] if 'history' in sessions[new_session_name] else 'Заметки ещё не пересказаны'}\n"
        f"Сохранить пересказ, перегенерировать снова или создать изображение?"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_history|"))
async def save_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "Только создатель может сохранить историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(chat_id, "Сессия не найдена!", back_to=f"manage_campaign|{short_name}")
        return
    if "history" in sessions[session_name]:
        history = sessions[session_name]["history"]
        text = f"История для {session_name} уже сохранена:\n{history}"
        await send_menu(chat_id, text, back_to=f"manage_campaign|{short_name}")
        return
    if "notes" in sessions[session_name]:
        all_notes = {note for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])}
        history = await generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{'; '.join(all_notes)}", chat_id, is_dm=True)
        sessions[session_name]["history"] = history
        del sessions[session_name]["notes"]
        global DATA_CHANGED
        DATA_CHANGED = True
        save_data()
    else:
        await send_menu(chat_id, "Нет заметок для создания истории!", back_to=f"manage_campaign|{short_name}")
        return
    buttons = [
        ("Новая", f"start_session|{short_name}"),
        ("Удалить", f"delete_session|{short_name}"),
        ("Сгенерировать сцену", f"generate_session_image|{short_name}|{session_num}")
    ]
    text = f"История сессии {session_name} сохранена:\n{history}"
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rewrite_history|"))
async def rewrite_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 3:
        await send_menu(chat_id, "Ошибка в запросе!")
        return
    short_name, session_num = parts[1], parts[2]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(chat_id, "Только создатель может переписать историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or "notes" not in sessions[session_name]:
        await send_menu(chat_id, "Заметки для переписывания не найдены!", back_to=f"manage_campaign|{short_name}")
        return
    all_notes = {note for char_id in DATA["campaigns"][short_name]["players"] for note in sessions[session_name]["notes"].get(char_id, [])}
    history = await generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{'; '.join(all_notes)}", chat_id, is_dm=True)
    buttons = [
        ("Сохранить", f"save_history|{short_name}|{session_num}"),
        ("Переписать", f"rewrite_history|{short_name}|{session_num}"),
        ("Сгенерировать сцену", f"generate_session_image|{short_name}|{session_num}")
    ]
    text = (
        f"Новый пересказ\n"
        f"Сессия {session_name}:\n"
        f"{history}\n"
        f"Сохранить этот пересказ или создать изображение?"
    )
    await send_menu(chat_id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_empty_session|"))
async def delete_empty_session(call):
    user_id, short_name, session_name = str(call.from_user.id), *call.data.split("|")[1:]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может удалить сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if session_name in sessions and sessions[session_name]["active"]:
        del sessions[session_name]
        global DATA_CHANGED
        DATA_CHANGED = True
        buttons = [("Новая", f"start_session|{short_name}")]
        await send_menu(call.message.chat.id, f"Пустая сессия {session_name} удалена!", buttons, back_to=f"manage_campaign|{short_name}")
    else:
        await send_menu(call.message.chat.id, "Сессия уже удалена или завершена!", back_to=f"manage_campaign|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_session|"))
async def delete_session(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может удалить сессию!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if not sessions:
        await send_menu(call.message.chat.id, "В кампании нет сессий!", back_to=f"manage_campaign|{short_name}")
        return
    last_session = list(sessions)[-1]
    if sessions[last_session]["active"]:
        await send_menu(call.message.chat.id, "Нельзя удалить активную сессию!", back_to=f"manage_campaign|{short_name}")
        return
    del sessions[last_session]
    global DATA_CHANGED
    DATA_CHANGED = True
    buttons = [("Новая", f"start_session|{short_name}")]
    await send_menu(call.message.chat.id, f"Сессия {last_session} удалена!", buttons, back_to=f"manage_campaign|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("start_adding_notes|"))
async def start_adding_notes(call):
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "Ошибка доступа!")
        return
    session_name = f"Сессия {session_num}"
    sessions = DATA["campaigns"][short_name]["sessions"]
    if session_name not in sessions or not sessions[session_name]["active"]:
        await send_menu(call.message.chat.id, "Сессия не активна или не существует!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "У тебя нет персонажей в этой кампании!")
        return
    buttons = [(name, f"add_note_with_char|{short_name}|{session_num}|{cid}") for cid, name in characters]
    user_states[user_id] = {"state": "waiting_for_note_character", "data": {"short_name": short_name, "session_name": session_name}}
    text = f"Выбери персонажа для добавления заметок в '{session_name}':"
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_note_with_char|"))
async def select_character_for_notes(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(call.message.chat.id, "Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if user_id not in user_states or user_states[user_id]["state"] != "waiting_for_note_character":
        await send_menu(call.message.chat.id, "Сессия истекла!")
        return
    if character_id not in DATA["characters"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(call.message.chat.id, "Это не твой персонаж!")
        return
    session_name = f"Сессия {session_num}"
    user_states[user_id] = {"state": "waiting_for_notes", "data": {"short_name": short_name, "session_name": session_name, "character_id": character_id}}
    buttons = [("Завершить", f"finish_adding_notes|{short_name}")]
    text = f"Пиши заметки для '{DATA['characters'][character_id]['name']}' в '{session_name}' в '{DATA['campaigns'][short_name]['full_name']}':"
    await send_menu(call.message.chat.id, text, buttons)

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
    buttons = [("Завершить", f"finish_adding_notes|{short_name}")]
    if not note:
        await send_menu(message.chat.id, "Укажи заметку! Продолжай:", buttons)
    else:
        sessions = DATA["campaigns"][short_name]["sessions"]
        sessions[session_name]["notes"].setdefault(character_id, []).append(note)
        DATA_CHANGED = True
        await send_menu(message.chat.id, f"Заметка добавлена в {session_name} для {DATA['characters'][character_id]['name']}! Продолжай:", buttons)

@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_adding_notes|"))
async def finish_adding_notes(call):
    user_id = str(call.from_user.id)
    parts = call.data.split("|")
    if len(parts) < 2:
        await send_menu(call.message.chat.id, "Ошибка в запросе!")
        return
    short_name = parts[1]
    if not await check_access(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    if not active_session:
        await send_menu(call.message.chat.id, "Нет активной сессии!")
        if user_id in user_states:
            del user_states[user_id]
        return
    characters = [cid for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not any(user_id == DATA["characters"][cid]["owner"] for cid in sessions[active_session]["notes"]):
        await send_menu(call.message.chat.id, "У тебя нет заметок для сохранения истории!")
        if user_id in user_states:
            del user_states[user_id]
        return
    char_notes = {cid: sessions[active_session]["notes"].get(cid, []) for cid in characters if cid in sessions[active_session]["notes"]}
    buttons = [("История", f"history|{short_name}")]
    text = f"Заметки для {active_session} в {DATA['campaigns'][short_name]['full_name']} сохранены!"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"history|{short_name}")
    if user_id in user_states:
            del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("history|"))
async def show_player_history(call):
    user_id = str(call.from_user.id)
    short_name = call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "Ошибка доступа!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "У тебя нет персонажей в этой кампании!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    text = f"Кампания: {DATA['campaigns'][short_name]['full_name']}\n"
    if active_session:
        text += f"Активная сессия: {active_session}\n"
        for cid, name in characters:
            if cid in sessions[active_session]["notes"]:
                text += f"- {name}: {'; '.join(sessions[active_session]['notes'][cid])}\n"
    buttons = [
        ("Последние сессии", f"last_sessions_player|{short_name}"),
        ("Полная история", f"full_history_player|{short_name}")
    ]
    if active_session:
        session_num = active_session.split()[1]
        buttons.append(("Заметки", f"start_adding_notes|{short_name}|{session_num}"))
    await send_menu(call.message.chat.id, text, buttons, buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_player_history|"))
async def save_player_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(chat_id, "Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or character_id not in sessions[session_name].get("notes", {}):
        await send_menu(chat_id, "Заметки для сохранения не найдены!", back_to=f"history|{short_name}")
        return
    notes = sessions[session_name]["notes"].get(character_id, [])
    history = await generate_text(f"Перескажи эти события от лица героя кратко, без спойлеров и выдумок:\n{'; '.join(notes)}", chat_id)
    sessions[session_name].setdefault("player_histories", {})[character_id] = history
    global DATA_CHANGED
    DATA_CHANGED = True
    save_data()
    buttons = [
        ("Кампания", f"history|{short_name}"),
        ("Выйти", "leave_campaign")
    ]
    text = (
        f"История сохранена\n"
        f"Для {DATA['characters'][character_id]['name']} в {session_name}:\n"
        f"{history}"
    )
    await send_menu(chat_id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rewrite_player_history|"))
async def rewrite_player_history(call):
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    parts = call.data.split("|")
    if len(parts) < 4:
        await send_menu(chat_id, "Ошибка в запросе!")
        return
    short_name, session_num, character_id = parts[1], parts[2], parts[3]
    if not await check_access(chat_id, user_id) or short_name not in DATA["campaigns"] or DATA["characters"][character_id]["owner"] != user_id:
        await send_menu(chat_id, "Ошибка доступа или это не твой персонаж!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name or character_id not in sessions[session_name].get("notes", {}):
        await send_menu(chat_id, "Заметки для переписывания не найдены!", back_to=f"history|{short_name}")
        return
    notes = sessions[session_name]["notes"].get(character_id, [])
    history = await generate_text(f"Перескажи эти события от лица героя кратко, без спойлеров и выдумок:\n{'; '.join(notes)}", chat_id)
    buttons = [
        ("Сохранить", f"save_player_history|{short_name}|{session_num}|{character_id}"),
        ("Переписать", f"rewrite_player_history|{short_name}|{session_num}|{character_id}"),
        ("Кампания", f"history|{short_name}")
    ]
    text = (
        f"Новый пересказ\n"
        f"Для {DATA['characters'][character_id]['name']} в {session_name}:\n"
        f"{history}\n"
        f"Сохранить этот пересказ?"
    )
    await send_menu(chat_id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_player|"))
async def session_history_player(call):
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "Ошибка доступа!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "У тебя нет персонажей в этой кампании!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "Сессия не найдена!", back_to=f"history|{short_name}")
        return
    text = f"Сессия {session_name} в {DATA['campaigns'][short_name]['full_name']}\n"
    buttons = []
    for cid, name in characters:
        if cid in sessions[session_name].get("notes", {}):
            notes = "; ".join(sessions[session_name]["notes"][cid])
            text += f"- Заметки {name}: {notes}\n"
            if "player_histories" not in sessions[session_name] or cid not in sessions[session_name]["player_histories"]:
                buttons.append(("Сохранить пересказ", f"save_player_history|{short_name}|{session_num}|{cid}"))
                buttons.append(("Переписать", f"rewrite_player_history|{short_name}|{session_num}|{cid}"))
            else:
                text += f"- История {name}: {sessions[session_name]['player_histories'][cid]}\n"
    if not buttons and "notes" in sessions[session_name]:
        text += "Все пересказы сохранены.\n"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("last_sessions_player|"))
async def last_sessions_player(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "Ошибка доступа!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "У тебя нет персонажей в этой кампании!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    last_sessions = sorted([s for s in sessions if not sessions[s]["active"]], key=lambda x: int(x.split("(")[-1][:-1]))[-3:]
    text = f"Последние сессии в {DATA['campaigns'][short_name]['full_name']} (до 3):\n"
    buttons = []
    for session in last_sessions:
        text += f"- {session}\n"
        for cid, name in characters:
            if cid in sessions[session].get("notes", {}):
                text += f"  Заметки {name}: {'; '.join(sessions[session]['notes'][cid])}\n"
            if cid in sessions[session].get("player_histories", {}):
                text += f"  История {name}: {sessions[session]['player_histories'][cid]}\n"
        buttons.append((session, f"session_history_player|{short_name}|{session.split()[1][1:-1]}"))
    if not last_sessions:
        text += "Нет завершённых сессий.\n"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"history|{short_name}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("full_history_player|"))
async def full_history_player(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"]:
        await send_menu(call.message.chat.id, "Ошибка доступа!")
        return
    characters = [(cid, c["name"]) for cid, c in DATA["characters"].items() if c["owner"] == user_id and short_name in c["campaigns"]]
    if not characters:
        await send_menu(call.message.chat.id, "У тебя нет персонажей в этой кампании!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    text = f"Полная история в {DATA['campaigns'][short_name]['full_name']}:\n"
    for session, data in sorted(sessions.items(), key=lambda x: int(x[0].split("(")[-1][:-1])):
        if not data["active"]:
            text += f"- {session}\n"
            for cid, name in characters:
                if cid in data.get("player_histories", {}):
                    text += f"  История {name}: {data['player_histories'][cid]}\n"
    if all(not s["active"] and "player_histories" not in s for s in sessions.values()):
        text += "История пока пуста.\n"
    await send_menu(call.message.chat.id, text, back_to=f"history|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("dm_history|"))
async def dm_history(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может просматривать историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    text = f"Кампания: {DATA['campaigns'][short_name]['full_name']}\n"
    if active_session:
        text += f"Активная сессия: {active_session}\n"
        for char_id in sessions[active_session].get("notes", {}):
            char_name = DATA["characters"][char_id]["name"]
            notes = "; ".join(sessions[active_session]["notes"][char_id])
            text += f"- {char_name}: {notes}\n"
    buttons = [
        ("Последние сессии", f"last_sessions_dm|{short_name}"),
        ("Полная история", f"full_history_dm|{short_name}")
    ]
    await send_menu(call.message.chat.id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("last_sessions_dm|"))
async def last_sessions_dm(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может просматривать последние сессии!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    last_sessions = sorted([s for s in sessions if not sessions[s]["active"]], key=lambda x: int(x.split("(")[-1][:-1]))[-3:]
    text = f"Последние сессии в {DATA['campaigns'][short_name]['full_name']} (до 3):\n"
    buttons = []
    for session in last_sessions:
        text += f"- {session}: {sessions[session].get('history', 'История не сохранена')}\n"
        buttons.append((session, f"session_history_dm|{short_name}|{session.split()[1][1:-1]}"))
    if not last_sessions:
        text += "Нет завершённых сессий.\n"
    await send_menu(call.message.chat.id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=1)

@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_dm|"))
async def session_history_dm(call):
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может просматривать историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        await send_menu(call.message.chat.id, "Сессия не найдена!", back_to=f"manage_campaign|{short_name}")
        return
    text = f"Сессия {session_name} в {DATA['campaigns'][short_name]['full_name']}\n"
    if "history" in sessions[session_name]:
        text += f"История: {sessions[session_name]['history']}\n"
    else:
        text += "История не сохранена.\n"
        for char_id in sessions[session_name].get("notes", {}):
            char_name = DATA["characters"][char_id]["name"]
            notes = "; ".join(sessions[session_name]["notes"][char_id])
            text += f"- Заметки {char_name}: {notes}\n"
    buttons = [
        ("Сохранить", f"save_history|{short_name}|{session_num}"),
        ("Переписать", f"rewrite_history|{short_name}|{session_num}"),
        ("Перегенерировать название", f"regenerate_title|{short_name}|{session_num}"),
        ("Сгенерировать сцену", f"generate_session_image|{short_name}|{session_num}")
    ]
    await send_menu(call.message.chat.id, text, buttons, back_to=f"manage_campaign|{short_name}", buttons_per_row=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith("full_history_dm|"))
async def full_history_dm(call):
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not await check_access(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        await send_menu(call.message.chat.id, "Только создатель может просматривать полную историю!")
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    text = f"Полная история в {DATA['campaigns'][short_name]['full_name']}:\n"
    for session, data in sorted(sessions.items(), key=lambda x: int(x[0].split("(")[-1][:-1])):
        if not data["active"]:
            text += f"- {session}: {data.get('history', 'История не сохранена')}\n"
    if all(not s["active"] and "history" not in s for s in sessions.values()):
        text += "История пока пуста.\n"
    await send_menu(call.message.chat.id, text, back_to=f"manage_campaign|{short_name}")

@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
async def return_to_main_menu(call):
    user_id = str(call.from_user.id)
    if not await check_access(call.message.chat.id, user_id):
        return
    await show_main_menu(call.message.chat.id, user_id)

@bot.message_handler(commands=['backup'])
async def manual_backup(message):
    user_id = str(message.from_user.id)
    if not await check_access(message.chat.id, user_id, admin=True):
        return
    backup_to_drive()
    backup_images_to_drive()
    await send_menu(message.chat.id, "Резервная копия данных и изображений создана!")

async def main():
    load_data()
    await bot.polling(none_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
