# registration.py

import logging
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from config import ROLE_PASSWORDS, ROLES
from db import create_user, get_user_by_id
from handlers.keyboards import get_admin_keyboard, get_user_keyboard

logger = logging.getLogger(__name__)

# Шаги ConversationHandler
REGISTRATION_ROLE = 5
REGISTRATION_PASSWORD = 10

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка команды /start:
    1) Если пользователь уже есть в БД — сразу показываем меню.
    2) Иначе предлагаем выбрать роль из списка.
    """
    user_id = update.effective_user.id
    user_info = get_user_by_id(user_id)
    if user_info:
        # Пользователь уже зарегистрирован — показываем меню
        role = user_info[2] or ""
        await show_main_menu(update, role)
        return ConversationHandler.END
    else:
        # Предлагаем выбрать роль
        roles_keyboard = [[role] for role in ROLES]
        reply_markup = ReplyKeyboardMarkup(
            roles_keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
        await update.message.reply_text(
            "Выберите вашу роль:",
            reply_markup=reply_markup
        )
        return REGISTRATION_ROLE

async def role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка выбранной роли. Если роль допустима — запрашиваем пароль,
    иначе снова предлагаем выбрать из списка.
    """
    chosen_role = update.message.text.strip()
    if chosen_role not in ROLES:
        roles_keyboard = [[role] for role in ROLES]
        reply_markup = ReplyKeyboardMarkup(
            roles_keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
        await update.message.reply_text(
            "Пожалуйста, выберите роль из списка:",
            reply_markup=reply_markup
        )
        return REGISTRATION_ROLE

    # Сохраняем выбранную роль в user_data
    context.user_data["chosen_role"] = chosen_role
    await update.message.reply_text(
        f"Вы выбрали роль «{chosen_role}». Теперь введите пароль для этой роли:"
    )
    return REGISTRATION_PASSWORD

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка введённого пароля: сверяем с ROLE_PASSWORDS[chosen_role].
    """
    entered_password = update.message.text.strip()
    chosen_role = context.user_data.get("chosen_role")

    if not chosen_role:
        await update.message.reply_text(
            "Ошибка: роль не выбрана. Попробуйте /start снова."
        )
        return ConversationHandler.END

    correct_password = ROLE_PASSWORDS.get(chosen_role)
    if entered_password != correct_password:
        await update.message.reply_text(
            "Неверный пароль. Попробуйте ещё раз или /start для отмены."
        )
        return REGISTRATION_PASSWORD

    # Пароль верен — регистрируем пользователя
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    full_name = update.effective_user.full_name or "Noname"
    create_user(user_id, full_name, username, chosen_role)

    # Показываем главное меню в зависимости от роли
    is_admin_or_pom = (chosen_role.lower() in ("администратор", "помощник директора"))
    if is_admin_or_pom:
        markup = get_admin_keyboard()
        text = f"Пароль верный! Роль «{chosen_role}» установлена (админ-меню)."
    else:
        markup = get_user_keyboard(chosen_role)
        text = f"Пароль верный! Роль «{chosen_role}» установлена."
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END

async def show_main_menu(update: Update, role: str):
    """
    Показываем главное меню, если пользователь уже зарегистрирован.
    """
    is_admin_or_pom = (role.lower() in ("администратор", "помощник директора"))
    if is_admin_or_pom:
        text = f"Вы уже зарегистрированы как {role}. Админ-меню:"
        markup = get_admin_keyboard()
    else:
        text = f"Вы уже зарегистрированы как {role}. Меню пользователя:"
        markup = get_user_keyboard(role)
    await update.message.reply_text(text, reply_markup=markup)

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Регистрация прервана.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

registration_conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_command)],
    states={
        REGISTRATION_ROLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, role_handler)
        ],
        REGISTRATION_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)
        ],
    },
    fallbacks=[CommandHandler("start", cancel_registration)],
)
