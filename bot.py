# Импортируем нужные библиотеки
import telebot
import json
import os
import random
import string
import requests
from telebot import types

# Получаем токены из секретов Replit
BOT_TOKEN = os.environ['BOT_TOKEN']
TOGETHER_API_KEY = os.environ['TOGETHER_API_KEY']
DATA_FILE = "dnd_data.json"
TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"
ADMIN_PASSWORD = "kikiriki1237"

# Инициализируем бота и данные
bot = telebot.TeleBot(BOT_TOKEN)
DATA = {"users": {}, "campaigns": {}, "admins": {}}

# Функция загрузки данных
def load_data():
    """📂 Загружает данные из файла."""
    global DATA
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as file:
            DATA = json.load(file)
    if "admins" not in DATA:
        DATA["admins"] = {}

# Функция сохранения данных
def save_data():
    """💾 Сохраняет данные в файл."""
    with open(DATA_FILE, "w") as file:
        json.dump(DATA, file, indent=2)

# Генерация кода кампании
def generate_code():
    """🔑 Генерирует код из 6 символов."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# Генерация текста через Together.ai
def generate_text(prompt, chat_id, is_dm=False, is_title=False):
    """📜 Генерирует текст через DeepSeek-V3."""
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    system_prompt = (
        "Ты помощник, который создаёт название сессии из двух слов (максимум 20 символов с номером) на русском языке на основе заметок. Название должно быть кратким, логичным и отражать ключевые события в порядке их следования. Не используй выдуманные детали."
        if is_title else
        ("Ты помощник, который пересказывает события от лица героя на русском языке, сохраняя естественные склонения, связность текста и строгую последовательность событий в порядке их появления, без скачков и выдумок. Перескажи всё, что указано, кратко, но полно."
         if not is_dm else
         "Ты помощник, который составляет краткую хронику событий кампании на русском языке в третьем лице, сохраняя естественные склонения, связность текста и строгую последовательность событий в порядке их появления, без скачков и выдумок. Перескажи всё, что указано, кратко, но полно.")
    )
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        "max_tokens": 10 if is_title else 500000,
        "temperature": 0.5,
        "top_p": 0.9,
        "stream": True
    }
    try:
        bot.send_chat_action(chat_id, 'typing')
        response = requests.post(TOGETHER_API_URL, headers=headers, json=payload, stream=True, timeout=10)
        response.raise_for_status()
        full_text = ""
        for chunk in response.iter_lines():
            if chunk and (data := chunk.decode('utf-8').strip().removeprefix("data:").strip()) and data != "[DONE]":
                chunk_data = json.loads(data)
                if content := chunk_data.get("choices", [{}])[0].get("delta", {}).get("content", ""):
                    full_text += content
        return full_text.strip() or f"Ошибка: пустой ответ. Заметки: {prompt}"
    except requests.RequestException as e:
        return f"Ошибка API: {str(e)}. Заметки: {prompt}"
    except Exception as e:
        return f"Ошибка: {str(e)}. Заметки: {prompt}"

# Проверка авторизации пользователя
def check_user(chat_id, user_id, allow_dm_only=False):
    """🔒 Проверяет, зарегистрирован ли пользователь и имеет ли права."""
    if user_id not in DATA["users"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔑 Войти", callback_data="login"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(chat_id, "❌ Ты не зарегистрирован!", reply_markup=markup)
        return False
    if allow_dm_only and DATA["users"][user_id]["role"] != "dm":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(chat_id, "🚫 Только мастер может это сделать!", reply_markup=markup)
        return False
    return True

# Проверка состояния админа
def check_admin(chat_id, user_id):
    """🔐 Проверяет, является ли пользователь админом."""
    if user_id not in DATA["admins"] or not DATA["admins"][user_id]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(chat_id, "🚫 Доступ только для админов! Используй /admin", reply_markup=markup)
        return False
    return True

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """🚪 Обрабатывает команду /start."""
    user_id = str(message.from_user.id)
    markup = types.InlineKeyboardMarkup()
    if user_id in DATA["users"]:
        markup.add(types.InlineKeyboardButton("🔑 Войти", callback_data="login"))
        text = "👤 Ты зарегистрирован! Войди:"
    else:
        markup.add(types.InlineKeyboardButton("🎲 Как мастер", callback_data="register_dm"), types.InlineKeyboardButton("⚔️ Как игрок", callback_data="register_player"))
        text = "👋 Добро пожаловать! Зарегистрируйся:"
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

# Вход в админ-панель
@bot.message_handler(commands=['admin'])
def admin_login(message):
    """🔐 Запрашивает пароль для входа в админ-панель."""
    user_id = str(message.from_user.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(message.chat.id, "🔒 Введи пароль админа:", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, handle_admin_password)

def handle_admin_password(message):
    """🔐 Проверяет пароль и включает админ-режим."""
    user_id = str(message.from_user.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    if message.text.strip() == ADMIN_PASSWORD:
        DATA["admins"][user_id] = True
        save_data()
        show_admin_panel(message.chat.id, user_id)
    else:
        bot.send_message(message.chat.id, "❌ Неверный пароль админа!", reply_markup=markup)

# Выход из админ-панели
@bot.message_handler(commands=['exitadmin'])
def admin_logout(message):
    """🚪 Выход из админ-панели."""
    user_id = str(message.from_user.id)
    if user_id in DATA["admins"] and DATA["admins"][user_id]:
        DATA["admins"][user_id] = False
        save_data()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(message.chat.id, "👋 Ты вышел из админ-панели!", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ Ты не в админ-панели!")

# Админ-панель
def show_admin_panel(chat_id, user_id):
    """⚙️ Показывает админ-панель."""
    if not check_admin(chat_id, user_id):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👤 Пользователи", callback_data="admin_users"))
    markup.add(types.InlineKeyboardButton("🏰 Кампании", callback_data="admin_campaigns"))
    markup.add(types.InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit"))
    bot.send_message(chat_id, "⚙️ Добро пожаловать в админ-панель!\nЧто хочешь сделать?", reply_markup=markup)

# Обработчик админ-команд
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def handle_admin_commands(call):
    """⚙️ Обрабатывает команды админ-панели."""
    user_id = str(call.from_user.id)
    if not check_admin(call.message.chat.id, user_id):
        return
    parts = call.data.split("|")
    command = parts[0].replace("admin_", "")

    if command == "users":
        show_users_panel(call.message.chat.id, user_id)
    elif command == "campaigns":
        show_campaigns_panel(call.message.chat.id, user_id)
    elif command == "exit":
        DATA["admins"][user_id] = False
        save_data()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "👋 Ты вышел из админ-панели!", reply_markup=markup)
    elif command == "panel":
        show_admin_panel(call.message.chat.id, user_id)
    elif command == "user_details" and len(parts) > 1:
        target_uid = parts[1]
        show_user_details(call.message.chat.id, user_id, target_uid)
    elif command == "reset_password" and len(parts) > 1:
        target_uid = parts[1]
        reset_password_prompt(call.message.chat.id, user_id, target_uid)
    elif command == "delete_user" and len(parts) > 1:
        target_uid = parts[1]
        delete_user(call.message.chat.id, user_id, target_uid)
    elif command == "campaign_details" and len(parts) > 1:
        short_name = parts[1]
        show_campaign_details(call.message.chat.id, user_id, short_name)
    elif command == "delete_campaign" and len(parts) > 1:
        short_name = parts[1]
        delete_campaign(call.message.chat.id, user_id, short_name)

# Панель пользователей
def show_users_panel(chat_id, user_id):
    """👤 Показывает список пользователей."""
    markup = types.InlineKeyboardMarkup()
    text = "👤 Список пользователей:\n"
    for uid, user in DATA["users"].items():
        campaigns = [c["full_name"] for c in DATA["campaigns"].values() if uid in c["players"]]
        text += f"ID: {uid} | Имя: {user['name']} | Роль: {'мастер' if user['role'] == 'dm' else 'игрок'} | Кампании: {', '.join(campaigns) or 'нет'}\n"
        markup.add(types.InlineKeyboardButton(f"👤 {user['name']}", callback_data=f"admin_user_details|{uid}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    bot.send_message(chat_id, text, reply_markup=markup)

def show_user_details(chat_id, user_id, target_uid):
    """👤 Показывает детали пользователя."""
    if not check_admin(chat_id, user_id):
        return
    user = DATA["users"].get(target_uid, {})
    if not user:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_users"))
        bot.send_message(chat_id, "❌ Пользователь не найден!", reply_markup=markup)
        return
    campaigns = [c["full_name"] for c in DATA["campaigns"].values() if target_uid in c["players"]]
    text = (f"👤 Детали пользователя:\n"
            f"ID: {target_uid}\n"
            f"Имя: {user['name']}\n"
            f"Роль: {'мастер' if user['role'] == 'dm' else 'игрок'}\n"
            f"Пароль: {user['password']}\n"
            f"Кампании: {', '.join(campaigns) or 'нет'}")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔑 Сбросить пароль", callback_data=f"admin_reset_password|{target_uid}"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить пользователя", callback_data=f"admin_delete_user|{target_uid}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_users"))
    bot.send_message(chat_id, text, reply_markup=markup)

def reset_password_prompt(chat_id, user_id, target_uid):
    """🔑 Запрашивает новый пароль."""
    if not check_admin(chat_id, user_id):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_user_details|{target_uid}"))
    bot.send_message(chat_id, f"🔑 Введи новый пароль для {DATA['users'][target_uid]['name']}:", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(chat_id, lambda msg: reset_password(msg, target_uid))

def reset_password(message, target_uid):
    """🔑 Сбрасывает пароль пользователя."""
    user_id = str(message.from_user.id)
    if not check_admin(message.chat.id, user_id):
        return
    new_password = message.text.strip()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_user_details|{target_uid}"))
    if not new_password:
        bot.send_message(message.chat.id, "❌ Пароль не может быть пустым!", reply_markup=markup)
        return
    DATA["users"][target_uid]["password"] = new_password
    save_data()
    bot.send_message(message.chat.id, f"✅ Пароль для {DATA['users'][target_uid]['name']} сброшен на '{new_password}'!", reply_markup=markup)

def delete_user(chat_id, user_id, target_uid):
    """🗑 Удаляет пользователя."""
    if not check_admin(chat_id, user_id):
        return
    if target_uid not in DATA["users"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_users"))
        bot.send_message(chat_id, "❌ Пользователь не найден!", reply_markup=markup)
        return
    user_name = DATA["users"][target_uid]["name"]
    for campaign in DATA["campaigns"].values():
        if target_uid in campaign["players"]:
            campaign["players"].remove(target_uid)
    del DATA["users"][target_uid]
    if target_uid in DATA["admins"]:
        del DATA["admins"][target_uid]
    save_data()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_users"))
    bot.send_message(chat_id, f"🗑 Пользователь {user_name} удалён!", reply_markup=markup)

# Панель кампаний
def show_campaigns_panel(chat_id, user_id):
    """🏰 Показывает список кампаний."""
    markup = types.InlineKeyboardMarkup()
    text = "🏰 Список кампаний:\n"
    for short_name, camp in DATA["campaigns"].items():
        players = [DATA["users"][p]["name"] for p in camp["players"]]
        text += f"Краткое: {short_name} | Полное: {camp['full_name']} | Создатель: {DATA['users'][camp['creator']]['name']} | Участники: {', '.join(players) or 'нет'}\n"
        markup.add(types.InlineKeyboardButton(f"🏰 {short_name}", callback_data=f"admin_campaign_details|{short_name}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    bot.send_message(chat_id, text, reply_markup=markup)

def show_campaign_details(chat_id, user_id, short_name):
    """🏰 Показывает детали кампании."""
    if not check_admin(chat_id, user_id):
        return
    camp = DATA["campaigns"].get(short_name, {})
    if not camp:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_campaigns"))
        bot.send_message(chat_id, "❌ Кампания не найдена!", reply_markup=markup)
        return
    players = [DATA["users"][p]["name"] for p in camp["players"]]
    sessions = len(camp["sessions"])
    text = (f"🏰 Детали кампании:\n"
            f"Краткое название: {short_name}\n"
            f"Полное название: {camp['full_name']}\n"
            f"Создатель: {DATA['users'][camp['creator']]['name']} (ID: {camp['creator']})\n"
            f"Код: {camp['code']}\n"
            f"Участники: {', '.join(players) or 'нет'}\n"
            f"Сессий: {sessions}")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🗑 Удалить кампанию", callback_data=f"admin_delete_campaign|{short_name}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_campaigns"))
    bot.send_message(chat_id, text, reply_markup=markup)

def delete_campaign(chat_id, user_id, short_name):
    """🗑 Удаляет кампанию."""
    if not check_admin(chat_id, user_id):
        return
    if short_name not in DATA["campaigns"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_campaigns"))
        bot.send_message(chat_id, "❌ Кампания не найдена!", reply_markup=markup)
        return
    full_name = DATA["campaigns"][short_name]["full_name"]
    del DATA["campaigns"][short_name]
    save_data()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_campaigns"))
    bot.send_message(chat_id, f"🗑 Кампания '{full_name}' удалена!", reply_markup=markup)

# Обработчик выбора роли и регистрации
@bot.callback_query_handler(func=lambda call: call.data in ["register_dm", "register_player"])
def handle_register_choice(call):
    """🎭 Обрабатывает выбор роли."""
    user_id = str(call.from_user.id)
    if user_id in DATA["users"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔑 Войти", callback_data="login"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "👤 Ты уже зарегистрирован!", reply_markup=markup)
        return
    role = "dm" if call.data == "register_dm" else "player"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, "📝 Введи имя и пароль в формате: Имя Пароль\nПример: Иван pass123", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda msg: register_user(msg, role))

def register_user(message, role):
    """📋 Регистрирует пользователя."""
    user_id = str(message.from_user.id)
    markup = types.InlineKeyboardMarkup()
    try:
        name, password = message.text.split(" ", 1)
        if not (name and password):
            raise ValueError
        DATA["users"][user_id] = {"role": role, "name": name, "password": password}
        save_data()
        markup.add(types.InlineKeyboardButton("🔑 Войти", callback_data="login"))
        text = f"✅ Ты зарегистрирован как {'мастер' if role == 'dm' else 'игрок'}, {name}!\nТеперь войди."
    except ValueError:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        text = "❌ Неверный формат! Введи: Имя Пароль"
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

# Обработчик входа
@bot.callback_query_handler(func=lambda call: call.data == "login")
def ask_login(call):
    """🔑 Запрашивает пароль для входа."""
    user_id = str(call.from_user.id)
    if user_id not in DATA["users"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Зарегистрироваться", callback_data="start"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "❌ Ты не зарегистрирован! Начни заново:", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, "🔒 Введи пароль для входа:", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, login_user)

def login_user(message):
    """🔓 Проверяет пароль и показывает меню."""
    user_id = str(message.from_user.id)
    markup = types.InlineKeyboardMarkup()
    if user_id not in DATA["users"]:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(message.chat.id, "❌ Ты не зарегистрирован! Начни заново: /start", reply_markup=markup)
        return
    if DATA["users"][user_id]["password"] != message.text.strip():
        markup.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data="login"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(message.chat.id, "❌ Неверный пароль!", reply_markup=markup)
        return
    show_main_menu(message.chat.id, user_id)

# Главное меню
def show_main_menu(chat_id, user_id):
    """🏠 Показывает главное меню."""
    role, name = DATA["users"][user_id]["role"], DATA["users"][user_id]["name"]
    markup = types.InlineKeyboardMarkup()
    if role == "dm":
        campaigns = [(c["short_name"], c["full_name"]) for c in DATA["campaigns"].values() if c["creator"] == user_id]
        text = f"👋 Привет, {name}! Ты вошёл как мастер.\n📜 Твои кампании: {', '.join(n for _, n in campaigns) or 'нет кампаний'}.\nЧто хочешь сделать?"
        for short_name, _ in campaigns:
            markup.add(types.InlineKeyboardButton(f"🏰 Перейти к '{short_name}'", callback_data=f"manage_campaign|{short_name}"))
        markup.add(types.InlineKeyboardButton("➕ Создать кампанию", callback_data="new_campaign"), types.InlineKeyboardButton("⚔️ Присоединиться как игрок", callback_data="join_campaign"))
    else:
        campaign = next(((n, c["full_name"]) for n, c in DATA["campaigns"].items() if user_id in c["players"]), None)
        text = f"👋 Привет, {name}! Ты вошёл как игрок.\n🏰 Текущая кампания: {campaign[1] if campaign else 'нет кампании'}."
        if campaign:
            markup.add(types.InlineKeyboardButton("📜 Посмотреть историю", callback_data=f"history|{campaign[0]}"), types.InlineKeyboardButton("🚪 Выйти из кампании", callback_data="leave_campaign"))
        else:
            markup.add(types.InlineKeyboardButton("🤝 Присоединиться к кампании", callback_data="join_campaign"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(chat_id, text, reply_markup=markup)

# Создание кампании
@bot.callback_query_handler(func=lambda call: call.data == "new_campaign")
def ask_new_campaign(call):
    """➕ Запрашивает название кампании."""
    user_id = str(call.from_user.id)
    if not check_user(call.message.chat.id, user_id, allow_dm_only=True):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, "📝 Введи краткое (до 16 символов) и полное название кампании через пробел:\nПример: Тест Очень Длинное Название Кампании", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, create_campaign)

def create_campaign(message):
    """🏰 Создаёт новую кампанию."""
    user_id = str(message.from_user.id)
    if not check_user(message.chat.id, user_id):
        return
    markup = types.InlineKeyboardMarkup()
    try:
        short_name, *full_name_parts = message.text.split()
        full_name = " ".join(full_name_parts)
        if not (short_name and full_name and len(short_name) <= 16 and short_name not in DATA["campaigns"]):
            raise ValueError
        code = generate_code()
        DATA["campaigns"][short_name] = {"creator": user_id, "code": code, "players": [], "sessions": {}, "short_name": short_name, "full_name": full_name}
        save_data()
        markup.add(types.InlineKeyboardButton(f"🏰 Перейти к '{short_name}'", callback_data=f"manage_campaign|{short_name}"))
        text = f"✅ Кампания '{full_name}' создана! Код: {code}"
    except ValueError:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        text = "❌ Введи краткое (до 16 символов) и полное название через пробел, краткое должно быть уникальным!\nПример: Тест Очень Длинное Название"
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

# Присоединение к кампании
@bot.callback_query_handler(func=lambda call: call.data == "join_campaign")
def ask_join_campaign(call):
    """🤝 Запрашивает код кампании."""
    user_id = str(call.from_user.id)
    if not check_user(call.message.chat.id, user_id):
        return
    if any(user_id in c["players"] for c in DATA["campaigns"].values()):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🚪 Выйти", callback_data="leave_campaign"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        campaign = next(c["full_name"] for c in DATA["campaigns"].values() if user_id in c["players"])
        bot.send_message(call.message.chat.id, f"🏰 Ты уже в '{campaign}'! Выйди, чтобы сменить.", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, "🔑 Введи код кампании:", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, join_campaign)

def join_campaign(message):
    """🤝 Присоединяет игрока к кампании."""
    user_id = str(message.from_user.id)
    if not check_user(message.chat.id, user_id):
        return
    code = message.text.strip()
    campaign = next((n for n, c in DATA["campaigns"].items() if c["code"] == code), None)
    markup = types.InlineKeyboardMarkup()
    if not campaign:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(message.chat.id, "❌ Неверный код!", reply_markup=markup)
        return
    DATA["campaigns"][campaign]["players"].append(user_id)
    save_data()
    markup.add(types.InlineKeyboardButton("📜 Посмотреть историю", callback_data=f"history|{campaign}"), types.InlineKeyboardButton("🚪 Выйти", callback_data="leave_campaign"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(message.chat.id, f"✅ Ты присоединился к '{DATA['campaigns'][campaign]['full_name']}'!", reply_markup=markup)

# Выход из кампании
@bot.callback_query_handler(func=lambda call: call.data == "leave_campaign")
def leave_campaign(call):
    """🚪 Выводит игрока из кампании."""
    user_id = str(call.from_user.id)
    if not check_user(call.message.chat.id, user_id):
        return
    campaign = next((n for n, c in DATA["campaigns"].items() if user_id in c["players"]), None)
    if not campaign:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🏰 Ты не в кампании!", reply_markup=markup)
        return
    DATA["campaigns"][campaign]["players"].remove(user_id)
    save_data()
    show_main_menu(call.message.chat.id, user_id)

# Управление кампанией (DM)
@bot.callback_query_handler(func=lambda call: call.data.startswith("manage_campaign|"))
def manage_campaign(call):
    """⚙️ Показывает меню управления кампанией."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не создатель этой кампании!", reply_markup=markup)
        return
    full_name = DATA["campaigns"][short_name]["full_name"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("▶️ Начать сессию", callback_data=f"start_session|{short_name}"), types.InlineKeyboardButton("⏹ Завершить сессию", callback_data=f"end_session|{short_name}"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить последнюю сессию", callback_data=f"delete_session|{short_name}"))
    markup.add(types.InlineKeyboardButton("📜 Полная история", callback_data=f"dm_history|{short_name}"), types.InlineKeyboardButton("🎥 В предыдущих сериях", callback_data=f"last_sessions_dm|{short_name}"))
    markup.add(types.InlineKeyboardButton("🔑 Показать код", callback_data=f"show_code|{short_name}"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, f"🏰 Кампания: '{full_name}'. Что хочешь сделать?", reply_markup=markup)

# Показать код кампании
@bot.callback_query_handler(func=lambda call: call.data.startswith("show_code|"))
def show_code(call):
    """🔑 Показывает код кампании мастеру."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не создатель этой кампании!", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    bot.send_message(call.message.chat.id, f"🔑 Код кампании '{DATA['campaigns'][short_name]['full_name']}': **{DATA['campaigns'][short_name]['code']}**", reply_markup=markup)

# Начало сессии
@bot.callback_query_handler(func=lambda call: call.data.startswith("start_session|"))
def start_session(call):
    """▶️ Начинает новую сессию."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Только создатель может начать сессию!", reply_markup=markup)
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if any(s["active"] for s in sessions.values()):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⏹ Завершить сессию", callback_data=f"end_session|{short_name}"), types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
        bot.send_message(call.message.chat.id, "⏳ Уже есть активная сессия!", reply_markup=markup)
        return
    session_num = len(sessions) + 1
    session_name = f"Сессия {session_num}"
    sessions[session_name] = {"active": True, "notes": {}}
    save_data()
    full_name = DATA["campaigns"][short_name]["full_name"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏹ Завершить сессию", callback_data=f"end_session|{short_name}"), types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    bot.send_message(call.message.chat.id, f"▶️ Сессия '{session_name}' в '{full_name}' началась!", reply_markup=markup)
    for player_id in DATA["campaigns"][short_name]["players"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Начать добавлять заметки", callback_data=f"start_adding_notes|{short_name}|{session_num}"), types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(player_id, f"▶️ Сессия '{session_name}' в кампании '{full_name}' началась! Добавляй заметки:", reply_markup=markup)

# Завершение сессии
@bot.callback_query_handler(func=lambda call: call.data.startswith("end_session|"))
def end_session(call):
    """⏹ Завершает сессию и генерирует название."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Только создатель может завершить сессию!", reply_markup=markup)
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    active_session = next((s for s, d in sessions.items() if d["active"]), None)
    if not active_session:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
        bot.send_message(call.message.chat.id, "⏳ Нет активной сессии!", reply_markup=markup)
        return
    all_notes = {note for notes in sessions[active_session]["notes"].values() for note in notes}
    if not all_notes:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Да", callback_data=f"delete_empty_session|{short_name}|{active_session}"), types.InlineKeyboardButton("❌ Нет", callback_data=f"manage_campaign|{short_name}"))
        bot.send_message(call.message.chat.id, f"📭 Сессия '{active_session}' пустая. Удалить её?", reply_markup=markup)
        return
    session_num = int(active_session.split()[1])
    new_title = generate_text(f"Создай название из двух слов на основе заметок: {'; '.join(all_notes)}", call.message.chat.id, is_title=True)
    new_session_name = f"{new_title} ({session_num})"
    sessions[new_session_name] = sessions.pop(active_session)
    sessions[new_session_name]["active"] = False
    save_data()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("▶️ Начать новую сессию", callback_data=f"start_session|{short_name}"), types.InlineKeyboardButton("🗑 Удалить последнюю сессию", callback_data=f"delete_session|{short_name}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    bot.send_message(call.message.chat.id, f"⏹ Сессия завершена и названа '{new_session_name}' в '{DATA['campaigns'][short_name]['full_name']}'!", reply_markup=markup)

# Удаление пустой сессии
@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_empty_session|"))
def delete_empty_session(call):
    """🗑 Удаляет пустую сессию."""
    user_id, short_name, session_name = str(call.from_user.id), *call.data.split("|")[1:]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Только создатель может удалить сессию!", reply_markup=markup)
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    markup = types.InlineKeyboardMarkup()
    if session_name in sessions and sessions[session_name]["active"]:
        del sessions[session_name]
        save_data()
        markup.add(types.InlineKeyboardButton("▶️ Начать новую сессию", callback_data=f"start_session|{short_name}"))
        text = f"🗑 Пустая сессия '{session_name}' удалена!"
    else:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
        text = "📭 Сессия уже удалена или завершена!"
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    bot.send_message(call.message.chat.id, text, reply_markup=markup)

# Удаление последней сессии
@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_session|"))
def delete_session(call):
    """🗑 Удаляет последнюю завершённую сессию."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Только создатель может удалить сессию!", reply_markup=markup)
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    if not sessions:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 В кампании нет сессий!", reply_markup=markup)
        return
    last_session = list(sessions)[-1]
    if sessions[last_session]["active"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
        bot.send_message(call.message.chat.id, "🚫 Нельзя удалить активную сессию!", reply_markup=markup)
        return
    del sessions[last_session]
    save_data()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("▶️ Начать сессию", callback_data=f"start_session|{short_name}"), types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    bot.send_message(call.message.chat.id, f"🗑 Сессия '{last_session}' удалена!", reply_markup=markup)

# Начало добавления заметок
@bot.callback_query_handler(func=lambda call: call.data.startswith("start_adding_notes|"))
def start_adding_notes(call):
    """📝 Начинает добавление заметок."""
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or user_id not in DATA["campaigns"][short_name]["players"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не участвуешь в этой кампании!", reply_markup=markup)
        return
    session_name = f"Сессия {session_num}"
    if session_name not in DATA["campaigns"][short_name]["sessions"] or not DATA["campaigns"][short_name]["sessions"][session_name]["active"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "⏳ Сессия не активна или не существует!", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏁 Завершить", callback_data=f"finish_adding_notes|{short_name}"))
    bot.send_message(call.message.chat.id, f"📝 Пиши свои заметки для '{session_name}' в '{DATA['campaigns'][short_name]['full_name']}':", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, lambda msg: add_note(msg, short_name, session_name))

def add_note(message, short_name, session_name):
    """📝 Добавляет заметку."""
    user_id = str(message.from_user.id)
    if not check_user(message.chat.id, user_id):
        return
    note = message.text.strip()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏁 Завершить", callback_data=f"finish_adding_notes|{short_name}"))
    if not note:
        bot.send_message(message.chat.id, "❌ Укажи заметку! Продолжай:", reply_markup=markup)
    else:
        sessions = DATA["campaigns"][short_name]["sessions"]
        sessions[session_name]["notes"].setdefault(user_id, []).append(note)
        save_data()
        bot.send_message(message.chat.id, f"✅ Заметка добавлена в '{session_name}'! Продолжай:", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda msg: add_note(msg, short_name, session_name))

# Завершение добавления заметок
@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_adding_notes|"))
def finish_adding_notes(call):
    """🏁 Завершает добавление заметок."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📜 Посмотреть историю", callback_data=f"history|{short_name}"), types.InlineKeyboardButton("🚪 Выйти", callback_data="leave_campaign"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, "🏁 Добавление заметок завершено!", reply_markup=markup)

# История игрока
@bot.callback_query_handler(func=lambda call: call.data.startswith("history|"))
def player_history(call):
    """📜 Показывает меню истории для игрока."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or user_id not in DATA["campaigns"][short_name]["players"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не участвуешь в этой кампании!", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📜 Общая история", callback_data=f"full_history_player|{short_name}"), types.InlineKeyboardButton("🎥 В предыдущих сериях", callback_data=f"last_sessions_player|{short_name}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
    bot.send_message(call.message.chat.id, f"📜 История кампании '{DATA['campaigns'][short_name]['full_name']}'. Что посмотреть?", reply_markup=markup)

# Последние сессии (игрок)
@bot.callback_query_handler(func=lambda call: call.data.startswith("last_sessions_player|"))
def last_sessions_player(call):
    """🎥 Показывает последние 3 сессии для игрока."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or user_id not in DATA["campaigns"][short_name]["players"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не участвуешь в этой кампании!", reply_markup=markup)
        return
    sessions = list(DATA["campaigns"][short_name]["sessions"])
    last_three = sessions[-3:] if len(sessions) >= 3 else sessions
    if not last_three:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"history|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 В кампании нет сессий!", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    for session in reversed(last_three):
        session_num = session.split('(')[-1].strip(')')
        markup.add(types.InlineKeyboardButton(f"🎬 {session}", callback_data=f"session_history_player|{short_name}|{session_num}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"history|{short_name}"))
    bot.send_message(call.message.chat.id, f"🎥 В предыдущих сериях '{DATA['campaigns'][short_name]['full_name']}':", reply_markup=markup)

# История конкретной сессии (игрок)
@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_player|"))
def session_history_player(call):
    """📜 Генерирует историю сессии для игрока."""
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not check_user(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_player|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 Такой сессии нет!", reply_markup=markup)
        return
    notes = sessions[session_name]["notes"].get(user_id, [])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Заметки сессии", callback_data=f"session_notes_player|{short_name}|{session_num}"), types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_player|{short_name}"))
    if not notes:
        bot.send_message(call.message.chat.id, f"📭 У тебя нет заметок в '{session_name}'!", reply_markup=markup)
        return
    history = generate_text(f"Перескажи эти события от лица героя кратко, без спойлеров и выдумок:\n{'; '.join(notes)}", call.message.chat.id)
    bot.send_message(call.message.chat.id, f"📜 История '{session_name}' в '{DATA['campaigns'][short_name]['full_name']}':\n{history}", reply_markup=markup)

# Заметки конкретной сессии (игрок)
@bot.callback_query_handler(func=lambda call: call.data.startswith("session_notes_player|"))
def session_notes_player(call):
    """📝 Показывает заметки сессии для игрока."""
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not check_user(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_player|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 Такой сессии нет!", reply_markup=markup)
        return
    notes = sessions[session_name]["notes"].get(user_id, [])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_player|{short_name}"))
    if not notes:
        bot.send_message(call.message.chat.id, f"📭 У тебя нет заметок в '{session_name}'!", reply_markup=markup)
        return
    bot.send_message(call.message.chat.id, f"📝 Заметки '{session_name}' в '{DATA['campaigns'][short_name]['full_name']}':\n" + "\n".join(f"- {note}" for note in notes), reply_markup=markup)

# Общая история игрока
@bot.callback_query_handler(func=lambda call: call.data.startswith("full_history_player|"))
def full_history_player(call):
    """📜 Генерирует общую историю для игрока."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or user_id not in DATA["campaigns"][short_name]["players"]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не участвуешь в этой кампании!", reply_markup=markup)
        return
    notes = {note for s in DATA["campaigns"][short_name]["sessions"].values() for note in s["notes"].get(user_id, [])}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"history|{short_name}"))
    if not notes:
        bot.send_message(call.message.chat.id, "📭 У тебя нет заметок в этой кампании!", reply_markup=markup)
        return
    history = generate_text(f"Перескажи эти события от лица героя кратко, без спойлеров и выдумок:\n{'; '.join(notes)}", call.message.chat.id)
    bot.send_message(call.message.chat.id, f"📜 Твоя общая история в '{DATA['campaigns'][short_name]['full_name']}':\n{history}", reply_markup=markup)

# Последние сессии (DM)
@bot.callback_query_handler(func=lambda call: call.data.startswith("last_sessions_dm|"))
def last_sessions_dm(call):
    """🎥 Показывает последние 3 сессии для мастера."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не создатель этой кампании!", reply_markup=markup)
        return
    sessions = list(DATA["campaigns"][short_name]["sessions"])
    last_three = sessions[-3:] if len(sessions) >= 3 else sessions
    if not last_three:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 В кампании нет сессий!", reply_markup=markup)
        return
    markup = types.InlineKeyboardMarkup()
    for session in reversed(last_three):
        session_num = session.split('(')[-1].strip(')')
        markup.add(types.InlineKeyboardButton(f"🎬 {session}", callback_data=f"session_history_dm|{short_name}|{session_num}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    bot.send_message(call.message.chat.id, f"🎥 В предыдущих сериях '{DATA['campaigns'][short_name]['full_name']}':", reply_markup=markup)

# История конкретной сессии (DM)
@bot.callback_query_handler(func=lambda call: call.data.startswith("session_history_dm|"))
def session_history_dm(call):
    """📜 Генерирует историю сессии для мастера."""
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not check_user(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_dm|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 Такой сессии нет!", reply_markup=markup)
        return
    all_notes = {f"{DATA['users'][u]['name']}: {n}" for u, notes in sessions[session_name]["notes"].items() for n in notes}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Заметки сессии", callback_data=f"session_notes_dm|{short_name}|{session_num}"), types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_dm|{short_name}"))
    if not all_notes:
        bot.send_message(call.message.chat.id, f"📭 В '{session_name}' нет заметок!", reply_markup=markup)
        return
    history = generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{'; '.join(all_notes)}", call.message.chat.id, is_dm=True)
    bot.send_message(call.message.chat.id, f"📜 История '{session_name}' в '{DATA['campaigns'][short_name]['full_name']}':\n{history}", reply_markup=markup)

# Заметки конкретной сессии (DM)
@bot.callback_query_handler(func=lambda call: call.data.startswith("session_notes_dm|"))
def session_notes_dm(call):
    """📝 Показывает заметки сессии для мастера."""
    user_id, short_name, session_num = str(call.from_user.id), *call.data.split("|")[1:]
    if not check_user(call.message.chat.id, user_id):
        return
    sessions = DATA["campaigns"][short_name]["sessions"]
    session_name = next((s for s in sessions if s.endswith(f"({session_num})")), None)
    if not session_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_dm|{short_name}"))
        bot.send_message(call.message.chat.id, "📭 Такой сессии нет!", reply_markup=markup)
        return
    all_notes = {f"{DATA['users'][u]['name']}: {n}" for u, notes in sessions[session_name]["notes"].items() for n in notes}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"last_sessions_dm|{short_name}"))
    if not all_notes:
        bot.send_message(call.message.chat.id, f"📭 В '{session_name}' нет заметок!", reply_markup=markup)
        return
    bot.send_message(call.message.chat.id, f"📝 Заметки '{session_name}' в '{DATA['campaigns'][short_name]['full_name']}':\n" + "\n".join(f"- {note}" for note in all_notes), reply_markup=markup)

# Полная история (DM)
@bot.callback_query_handler(func=lambda call: call.data.startswith("dm_history|"))
def dm_history(call):
    """📜 Генерирует полную историю для мастера."""
    user_id, short_name = str(call.from_user.id), call.data.split("|")[1]
    if not check_user(call.message.chat.id, user_id) or short_name not in DATA["campaigns"] or DATA["campaigns"][short_name]["creator"] != user_id:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, "🚫 Ты не создатель этой кампании!", reply_markup=markup)
        return
    all_notes = {f"{DATA['users'][u]['name']}: {n}" for s in DATA["campaigns"][short_name]["sessions"].values() for u, notes in s["notes"].items() for n in notes}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_campaign|{short_name}"))
    if not all_notes:
        bot.send_message(call.message.chat.id, "📭 В этой кампании нет заметок!", reply_markup=markup)
        return
    history = generate_text(f"Составь краткую хронику событий на основе заметок, без выдумок:\n{'; '.join(all_notes)}", call.message.chat.id, is_dm=True)
    bot.send_message(call.message.chat.id, f"📜 Полная история '{DATA['campaigns'][short_name]['full_name']}':\n{history}", reply_markup=markup)

# Возврат в главное меню
@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def back_to_main_menu(call):
    """⬅️ Возвращает в главное меню."""
    user_id = str(call.from_user.id)
    if check_user(call.message.chat.id, user_id):
        show_main_menu(call.message.chat.id, user_id)

# Инициализация данных
load_data()

# Запуск бота
bot.polling()