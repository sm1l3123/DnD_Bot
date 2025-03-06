import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import main  # Импортируем твой основной файл как модуль


# Настраиваем фикстуру для бота
@pytest.fixture
def bot():
    main.bot = MagicMock(spec=main.AsyncTeleBot)
    main.bot.send_message = AsyncMock()
    main.bot.send_chat_action = AsyncMock()
    return main.bot


# Фикстура для очистки глобальных переменных перед каждым тестом
@pytest.fixture(autouse=True)
def reset_globals():
    main.DATA = {"users": {}, "campaigns": {}, "admins": {}, "characters": {}}
    main.DATA_CHANGED = False
    main.CAMPAIGN_BY_CODE = {}
    main.user_states = {}


# Фикстура для пользователя и персонажа
@pytest.fixture
def setup_user(bot):
    main.DATA["users"]["67890"] = {"role": "player", "name": "TestUser", "password": "pass123"}
    main.DATA["users"]["11111"] = {"role": "dm", "name": "TestDM", "password": "dm123"}
    main.DATA["characters"]["char_1"] = {
        "name": "Grok",
        "owner": "67890",
        "campaigns": ["test_campaign"],
        "backstory": "A brave warrior"
    }
    main.DATA["campaigns"]["test_campaign"] = {
        "creator": "11111",
        "code": "ABC123",
        "players": ["char_1"],
        "sessions": {"Сессия 1": {"active": False, "notes": {"char_1": ["Test note"]}}},  # Изменили active на False
        "short_name": "test_campaign",
        "full_name": "Test Campaign"
    }
    main.DATA["campaigns"]["newcamp"] = {
        "creator": "11111",
        "code": "XYZ789",
        "players": [],
        "sessions": {},
        "short_name": "newcamp",
        "full_name": "New Campaign"
    }
    main.CAMPAIGN_BY_CODE["ABC123"] = "test_campaign"
    main.CAMPAIGN_BY_CODE["XYZ789"] = "newcamp"

# Тест /start
@pytest.mark.asyncio
async def test_send_welcome(bot):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = 67890

    # Пользователь не зарегистрирован
    await main.send_welcome(message)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "👋 *Добро пожаловать!* Зарегистрируйся:"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"

    # Сбрасываем мок
    bot.send_message.reset_mock()

    # Регистрируем пользователя
    main.DATA["users"]["67890"] = {
        "role": "player",
        "name": "TestUser",
        "password": "pass"
    }
    await main.send_welcome(message)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "👤 *Ты зарегистрирован!* Войди:"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"


# Тест /admin
@pytest.mark.asyncio
async def test_admin_login(bot):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = 67890

    await main.admin_login(message)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[1] == "🔒 *Введи пароль админа:*"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"
    assert main.user_states["67890"]["state"] == "waiting_for_admin_password"


@pytest.mark.asyncio
async def test_handle_admin_password_input(bot):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.text = "kikiriki1237"
    main.user_states["67890"] = {"state": "waiting_for_admin_password"}

    await main.handle_admin_password_input(message)
    assert main.DATA["admins"]["67890"] == True
    assert "67890" not in main.user_states


# Тест /exitadmin
@pytest.mark.asyncio
async def test_admin_logout(bot):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    main.DATA["admins"]["67890"] = True

    await main.admin_logout(message)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "👋 *Ты вышел из админ-панели!*"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"
    assert main.DATA["admins"]["67890"] == False


# Тест show_admin_panel
@pytest.mark.asyncio
async def test_show_admin_panel(bot):
    main.DATA["admins"]["67890"] = True
    await main.show_admin_panel(12345, "67890")
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "# ⚙️ Админ-панель\n*Добро пожаловать!* Что хочешь сделать?"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"


# Тест handle_admin_commands (пример для users)
@pytest.mark.asyncio
async def test_handle_admin_commands_users(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "admin_users"
    main.DATA["admins"]["67890"] = True

    await main.handle_admin_commands(call)
    bot.send_message.assert_called()


# Тест show_users_panel
@pytest.mark.asyncio
async def test_show_users_panel(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.show_users_panel(12345, "67890")
    bot.send_message.assert_called()


# Тест show_user_details
@pytest.mark.asyncio
async def test_show_user_details(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.show_user_details(12345, "67890", "67890")
    bot.send_message.assert_called()


# Тест reset_password_prompt
@pytest.mark.asyncio
async def test_reset_password_prompt(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.reset_password_prompt(12345, "67890", "67890")
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "🔑 *Введи новый пароль для TestUser:*"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"
    assert main.user_states["67890"]["state"] == "waiting_for_reset_password"


# Тест reset_password_input
@pytest.mark.asyncio
async def test_reset_password_input(bot, setup_user):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = "67890"
    message.text = "newpass"
    main.DATA["admins"]["67890"] = True
    main.user_states["67890"] = {
        "state": "waiting_for_reset_password",
        "data": {
            "target_uid": "67890"
        }
    }

    await main.reset_password_input(message)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "✅ Пароль для *TestUser* сброшен на `newpass`!"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"
    assert main.DATA["users"]["67890"]["password"] == "newpass"


# Тест delete_user
@pytest.mark.asyncio
async def test_delete_user(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.delete_user(12345, "67890", "67890")
    assert "67890" not in main.DATA["users"]


# Тест show_campaigns_panel
@pytest.mark.asyncio
async def test_show_campaigns_panel(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.show_campaigns_panel(12345, "67890")
    bot.send_message.assert_called()


# Тест show_campaign_details
@pytest.mark.asyncio
async def test_show_campaign_details(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.show_campaign_details(12345, "67890", "test_campaign")
    bot.send_message.assert_called()


# Тест delete_campaign
@pytest.mark.asyncio
async def test_delete_campaign(bot, setup_user):
    main.DATA["admins"]["67890"] = True
    await main.delete_campaign(12345, "67890", "test_campaign")
    assert "test_campaign" not in main.DATA["campaigns"]


# Тест handle_register_choice
@pytest.mark.asyncio
async def test_handle_register_choice(bot):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = 67890
    call.data = "register_dm"

    await main.handle_register_choice(call)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "📝 *Введи имя и пароль в формате: Имя Пароль*\nПример: Иван pass123"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"


# Тест ask_login
@pytest.mark.asyncio
async def test_ask_login(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "login"

    await main.ask_login(call)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[1] == "🔒 *Введи пароль для входа:*"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"


# Тест show_main_menu
@pytest.mark.asyncio
async def test_show_main_menu(bot, setup_user):
    await main.show_main_menu(12345, "67890")
    bot.send_message.assert_called()


# Тест ask_join_campaign
@pytest.mark.asyncio
async def test_ask_join_campaign(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "join_campaign"

    # Убеждаемся, что пользователь и персонажи есть
    assert "67890" in main.DATA["users"]
    assert "char_1" in main.DATA["characters"]

    # Сбрасываем мок перед вызовом
    bot.send_message.reset_mock()

    await main.ask_join_campaign(call)
    # Проверяем, что send_message вызван хотя бы раз
    assert bot.send_message.called
    # Ищем конкретный вызов с нужным текстом среди всех
    calls = bot.send_message.call_args_list
    assert any("🔑 *Введи код кампании:*" in call.args[1] for call in calls)
    assert any(call.kwargs["parse_mode"] == "Markdown" for call in calls)
    assert main.user_states["67890"]["state"] == "waiting_for_campaign_code"


# Тест create_campaign_input
@pytest.mark.asyncio
async def test_create_campaign_input(bot):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = "11111"
    message.text = "newcamp New Campaign"
    main.DATA["users"]["11111"] = {
        "role": "dm",
        "name": "TestDM",
        "password": "dm123"
    }
    main.user_states["11111"] = {"state": "waiting_for_campaign_name"}

    await main.create_campaign_input(message)
    bot.send_message.assert_called()
    assert "newcamp" in main.DATA["campaigns"]

# Тест join_campaign_input
@pytest.mark.asyncio
async def test_join_campaign_input(bot, setup_user):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = "67890"
    message.text = "XYZ789"
    main.user_states["67890"] = {"state": "waiting_for_campaign_code"}

    await main.join_campaign_input(message)
    bot.send_message.assert_called()


# Тест join_with_character
@pytest.mark.asyncio
async def test_join_with_character(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "join_with_char|newcamp|char_1"
    main.user_states["67890"] = {
        "state": "waiting_for_character_selection",
        "data": {
            "short_name": "newcamp"
        }
    }

    await main.join_with_character(call)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "✅ Персонаж *Grok* присоединился к *New Campaign*!"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"
    assert "char_1" in main.DATA["campaigns"]["newcamp"]["players"]


# Тест leave_campaign
@pytest.mark.asyncio
async def test_leave_campaign(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "leave_campaign"

    await main.leave_campaign(call)
    bot.send_message.assert_called()
    assert "char_1" not in main.DATA["campaigns"]["test_campaign"]["players"]


# Тест manage_campaign
@pytest.mark.asyncio
async def test_manage_campaign(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "manage_campaign|test_campaign"

    await main.manage_campaign(call)
    bot.send_message.assert_called()


# Тест show_code
@pytest.mark.asyncio
async def test_show_code(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "show_code|test_campaign"

    await main.show_code(call)
    bot.send_message.assert_called()


# Тест start_session
@pytest.mark.asyncio
async def test_start_session(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "start_session|test_campaign"

    # Проверяем исходное количество сессий
    initial_sessions = len(main.DATA["campaigns"]["test_campaign"]["sessions"])
    assert initial_sessions == 1  # Одна сессия уже есть в фикстуре

    # Сбрасываем мок перед вызовом
    bot.send_message.reset_mock()

    await main.start_session(call)
    # Ожидаем два вызова: для мастера и игрока
    assert bot.send_message.call_count == 2
    calls = bot.send_message.call_args_list
    # Проверяем вызов для мастера
    assert any("▶️ Сессия *Сессия 2* в *Test Campaign* началась!" in call.args[1] for call in calls)
    # Проверяем вызов для игрока
    assert any("▶️ Сессия *Сессия 2* в кампании *Test Campaign* началась!\nДобавляй заметки за *Grok*:" in call.args[1] for call in calls)
    assert all(call.kwargs["parse_mode"] == "Markdown" for call in calls)
    # Проверяем добавление сессии
    assert len(main.DATA["campaigns"]["test_campaign"]["sessions"]) == initial_sessions + 1
    assert "Сессия 2" in main.DATA["campaigns"]["test_campaign"]["sessions"]
    assert main.DATA["campaigns"]["test_campaign"]["sessions"]["Сессия 2"]["active"] == True


# Тест end_session
@pytest.mark.asyncio
async def test_end_session(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "end_session|test_campaign"

    with patch("main.generate_text",
               side_effect=[
                   AsyncMock(return_value="New Title"),
                   AsyncMock(return_value="Test history")
               ]):
        await main.end_session(call)
    bot.send_message.assert_called()


# Тест regenerate_title
@pytest.mark.asyncio
async def test_regenerate_title(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "regenerate_title|test_campaign|1"
    main.DATA["campaigns"]["test_campaign"]["sessions"] = {
        "Сессия 1": {
            "active": False,
            "history": "Test history"
        }
    }

    with patch("main.generate_text", new=AsyncMock(return_value="New Title")):
        await main.regenerate_title(call)
    bot.send_message.assert_called()


# Тест save_history
@pytest.mark.asyncio
async def test_save_history(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "save_history|test_campaign|1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.save_history(call)
    bot.send_message.assert_called()


# Тест rewrite_history
@pytest.mark.asyncio
async def test_rewrite_history(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "rewrite_history|test_campaign|1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="New history")):
        await main.rewrite_history(call)
    bot.send_message.assert_called()


# Тест delete_empty_session
@pytest.mark.asyncio
async def test_delete_empty_session(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "delete_empty_session|test_campaign|Сессия 2"
    # Добавляем активную сессию для теста
    main.DATA["campaigns"]["test_campaign"]["sessions"]["Сессия 2"] = {"active": True, "notes": {}}

    await main.delete_empty_session(call)
    bot.send_message.assert_called_once()
    assert "Сессия 2" not in main.DATA["campaigns"]["test_campaign"]["sessions"]


# Тест delete_session
@pytest.mark.asyncio
async def test_delete_session(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "delete_session|test_campaign"
    main.DATA["campaigns"]["test_campaign"]["sessions"] = {
        "Сессия 1": {
            "active": False
        }
    }

    await main.delete_session(call)
    bot.send_message.assert_called()
    assert "Сессия 1" not in main.DATA["campaigns"]["test_campaign"][
        "sessions"]


# Тест start_adding_notes
@pytest.mark.asyncio
async def test_start_adding_notes(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "start_adding_notes|test_campaign|1"

    await main.start_adding_notes(call)
    bot.send_message.assert_called()


# Тест select_character_for_notes
@pytest.mark.asyncio
async def test_select_character_for_notes(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "add_note_with_char|test_campaign|1|char_1"
    main.user_states["67890"] = {
        "state": "waiting_for_note_character",
        "data": {
            "short_name": "test_campaign",
            "session_name": "Сессия 1"
        }
    }

    await main.select_character_for_notes(call)
    bot.send_message.assert_called()


# Тест add_note_input
@pytest.mark.asyncio
async def test_add_note_input(bot, setup_user):
    message = MagicMock()
    message.chat.id = 12345
    message.from_user.id = "67890"
    message.text = "New note"
    main.user_states["67890"] = {
        "state": "waiting_for_notes",
        "data": {
            "short_name": "test_campaign",
            "session_name": "Сессия 1",
            "character_id": "char_1"
        }
    }

    await main.add_note_input(message)
    bot.send_message.assert_called_once()
    assert bot.send_message.call_args.args[
        1] == "✅ Заметка добавлена в *Сессия 1* для *Grok*! Продолжай:"
    assert bot.send_message.call_args.kwargs["parse_mode"] == "Markdown"
    assert "New note" in main.DATA["campaigns"]["test_campaign"]["sessions"][
        "Сессия 1"]["notes"]["char_1"]


# Тест finish_adding_notes
@pytest.mark.asyncio
async def test_finish_adding_notes(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "finish_adding_notes|test_campaign"

    await main.finish_adding_notes(call)
    bot.send_message.assert_called()


# Тест finish_notes_for_character
@pytest.mark.asyncio
async def test_finish_notes_for_character(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "finish_notes_for_char|test_campaign|char_1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.finish_notes_for_character(call)
    bot.send_message.assert_called()


# Тест history
@pytest.mark.asyncio
async def test_player_history(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "history|test_campaign"

    await main.player_history(call)
    bot.send_message.assert_called()


# Тест last_sessions_player
@pytest.mark.asyncio
async def test_last_sessions_player(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "last_sessions_player|test_campaign"
    main.DATA["campaigns"]["test_campaign"]["sessions"]["Сессия 1"][
        "active"] = False

    await main.last_sessions_player(call)
    bot.send_message.assert_called()


# Тест save_player_history
@pytest.mark.asyncio
async def test_save_player_history(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "save_player_history|test_campaign|1|char_1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.save_player_history(call)
    bot.send_message.assert_called()


# Тест rewrite_player_history
@pytest.mark.asyncio
async def test_rewrite_player_history(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "rewrite_player_history|test_campaign|1|char_1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="New history")):
        await main.rewrite_player_history(call)
    bot.send_message.assert_called()


# Тест session_history_player
@pytest.mark.asyncio
async def test_session_history_player(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "session_history_player|test_campaign|1"

    await main.session_history_player(call)
    bot.send_message.assert_called()


# Тест view_character_session
@pytest.mark.asyncio
async def test_view_character_session(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "view_char_session|test_campaign|1|char_1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.view_character_session(call)
    bot.send_message.assert_called()


# Тест session_notes_player
@pytest.mark.asyncio
async def test_session_notes_player(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "session_notes_player|test_campaign|1|char_1"

    await main.session_notes_player(call)
    bot.send_message.assert_called()


# Тест full_history_player
@pytest.mark.asyncio
async def test_full_history_player(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "full_history_player|test_campaign"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.full_history_player(call)
    bot.send_message.assert_called()


# Тест last_sessions_dm
@pytest.mark.asyncio
async def test_last_sessions_dm(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "last_sessions_dm|test_campaign"

    await main.last_sessions_dm(call)
    bot.send_message.assert_called()


# Тест session_history_dm
@pytest.mark.asyncio
async def test_session_history_dm(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "session_history_dm|test_campaign|1"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.session_history_dm(call)
    bot.send_message.assert_called()


# Тест session_notes_dm
@pytest.mark.asyncio
async def test_session_notes_dm(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "session_notes_dm|test_campaign|1"

    await main.session_notes_dm(call)
    bot.send_message.assert_called()


# Тест dm_history
@pytest.mark.asyncio
async def test_dm_history(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "11111"
    call.data = "dm_history|test_campaign"

    with patch("main.generate_text",
               new=AsyncMock(return_value="Test history")):
        await main.dm_history(call)
    bot.send_message.assert_called()


# Тест back_to_main_menu
@pytest.mark.asyncio
async def test_back_to_main_menu(bot, setup_user):
    call = MagicMock()
    call.message.chat.id = 12345
    call.from_user.id = "67890"
    call.data = "main_menu"

    await main.back_to_main_menu(call)
    bot.send_message.assert_called()


# Запуск тестов
if __name__ == "__main__":
    pytest.main(["-v", "--asyncio-mode=auto"])
