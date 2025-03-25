# pipa.py

import logging
import sys
import os
import asyncio

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler
)

# Импорт настроек
from config import BOT_TOKEN, setup_directories, DEVELOPER_USERNAME
from db import get_developer_id, get_role

# Импорт ConversationHandler’ов
from handlers.registration import registration_conv   # /start (регистрация)
from handlers.mail.mail_other import mail_conv        # Почта
from handlers.search import search_conv               # Поиск
from handlers.admin import admin_conv                 # Админ-панель (теперь с файловым менеджером в одном файле)

# Импорт «обычного» файлового менеджера (для простых пользователей, если нужно)
from handlers.files import (
    directory_handler,
    file_handler,
    files_back_handler,
    handle_files_obshaya,
    handle_files_role
)

# Глобальный обработчик меню
from handlers.menus import global_menu_handler


async def help_command(update, context):
    user_id = update.effective_user.id
    role = get_role(user_id) or ""
    dev_name = (update.effective_user.username or "").lower()
    if role.lower() in ("администратор", "помощник директора") or dev_name == DEVELOPER_USERNAME.lower():
        text = (
            "Справка для администратора:\n\n"
            "• /start — запуск/перезапуск.\n"
            "• /help — эта справка.\n"
            "• Кнопки меню: Общие файлы, Файлы работы, Сообщения, Поиск, Админ-панель.\n"
            "• В «Админ-панель» можно зайти для управления пользователями, рассылки, файлового менеджера и т. д."
        )
    else:
        text = (
            "Справка для пользователя:\n\n"
            "• /start — регистрация.\n"
            "• /help — эта справка.\n"
            "• Кнопки меню: Общие файлы, Файлы работы, Сообщения, Поиск файлов."
        )
    await update.message.reply_text(text)


async def notify_developer_startup(app):
    dev_id = get_developer_id("zxcegorka4")
    if dev_id:
        try:
            await app.bot.send_message(chat_id=dev_id, text="Бот запущен! 🚀")
        except Exception as e:
            logging.warning(f"Не удалось уведомить разработчика: {e}")


async def error_handler(update, context):
    import traceback
    err_text = ''.join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logging.error("Ошибка: %s", err_text)
    dev_id = get_developer_id("zxcegorka4")
    if dev_id:
        try:
            await context.bot.send_message(chat_id=dev_id, text=f"Ошибка:\n{err_text}")
        except Exception as e:
            logging.error(f"Не удалось отправить ошибку разработчику: {e}")


async def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.DEBUG
    )

    setup_directories()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 1) ConversationHandler’ы приоритетом 0
    app.add_handler(registration_conv, 0)
    app.add_handler(mail_conv, 0)
    app.add_handler(search_conv, 0)
    app.add_handler(admin_conv, 0)  # <-- тут теперь ВЕСЬ функционал админ-панели и файлов

    # 2) «Обычный» файловый менеджер (для рядовых пользователей)
    # Если используете — пусть тоже будет приоритет 0
    app.add_handler(CallbackQueryHandler(directory_handler, pattern="^dir\\|"), 0)
    app.add_handler(CallbackQueryHandler(file_handler, pattern="^file\\|"), 0)
    app.add_handler(CallbackQueryHandler(files_back_handler, pattern="^files_back$"), 0)
    app.add_handler(CallbackQueryHandler(handle_files_obshaya, pattern="^files_obshaya$"), 0)
    app.add_handler(CallbackQueryHandler(handle_files_role, pattern="^files_role$"), 0)

    # 3) Глобальный CallbackQueryHandler – приоритет 1
    app.add_handler(CallbackQueryHandler(global_menu_handler), 1)

    # 4) /help
    app.add_handler(CommandHandler("help", help_command))

    # 5) Обработчик ошибок
    app.add_error_handler(error_handler)

    # Уведомляем разработчика
    await notify_developer_startup(app)

    logging.info("Запуск бота...")
    await app.run_polling()
    logging.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "already running" in str(e):
            import nest_asyncio
            nest_asyncio.apply()
            asyncio.get_event_loop().run_until_complete(main())
        else:
            raise
