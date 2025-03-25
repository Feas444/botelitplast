# handlers/menus.py

import logging
from telegram import Update
from telegram.ext import ContextTypes
from db import get_role
from handlers.files import handle_files_obshaya, handle_files_role
from handlers.search import start_search_callback
from handlers.keyboards import get_admin_keyboard, get_user_keyboard

logger = logging.getLogger(__name__)

async def global_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Глобальный обработчик меню (если ConversationHandler не взял callback_data).
    """
    query = update.callback_query
    data = query.data
    await query.answer()

    user_id = query.from_user.id
    role = get_role(user_id) or ""
    role_lower = role.lower()
    is_admin_or_pom = (role_lower in ("администратор", "помощник директора"))

    if data == "files_obshaya":
        return await handle_files_obshaya(update, context)
    elif data == "files_role":
        return await handle_files_role(update, context)
    elif data == "search_files":
        return await start_search_callback(update, context)
    elif data == "mail_main":
        from handlers.mail.mail_other import mail_command
        return await mail_command(update, context)
    elif data == "main_menu":
        if is_admin_or_pom:
            text = f"Главное меню (Админ / Помощник директора): {role}"
            markup = get_admin_keyboard()
        else:
            text = f"Главное меню (Пользователь): {role}"
            markup = get_user_keyboard(role)
        await query.edit_message_text(text, reply_markup=markup)
        return
    else:
        # игнорируем неузнанные кнопки
        pass
