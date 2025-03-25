# search.py

import logging
import os
import random
import string
from rapidfuzz import fuzz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from config import BASE_DIR, OBSHAYA_DIR, DEVELOPER_USERNAME
from db import get_role
from handlers.files import browse_directory
from handlers.keyboards import get_admin_keyboard, get_user_keyboard
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

SEARCH_STATE = 44

def generate_id(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def safe_edit_message(query, new_text, reply_markup=None):
    try:
        await query.edit_message_text(text=new_text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise

async def block_menu_while_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer("Сначала завершите поиск (нажмите «Завершить поиск»).", show_alert=True)
    else:
        await update.message.reply_text("Сначала завершите поиск (нажмите «Завершить поиск»).")
    return SEARCH_STATE

async def start_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["search_cache"] = {}
    await query.answer()
    await safe_edit_message(query, "🔎 Введите ключевые слова для поиска (через пробел):")
    return SEARCH_STATE

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["search_cache"] = {}
    await update.message.reply_text("🔎 Введите ключевые слова для поиска (через пробел):")
    return SEARCH_STATE

def match_all_tokens(filename_lower: str, tokens, threshold=75) -> float:
    if not tokens:
        return 0
    total_score = 0
    for token in tokens:
        ratio_full = fuzz.ratio(token, filename_lower)
        ratio_part = fuzz.partial_ratio(token, filename_lower)
        best = max(ratio_full, ratio_part)
        if best < threshold:
            return 0
        total_score += best
    return total_score / len(tokens)

async def return_to_main_menu_after_search(query, context):
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    dev_name = (query.from_user.username or "").lower()
    is_admin_or_pom = (role.lower() == "администратор" or role.lower() == "помощник директора" or dev_name == DEVELOPER_USERNAME.lower())

    if is_admin_or_pom:
        text = f"Поиск завершён. Возвращаемся в меню для роли: {role} (админ)."
        markup = get_admin_keyboard()
    else:
        text = f"Поиск завершён. Возвращаемся в меню для роли: {role}"
        markup = get_user_keyboard(role)
    await safe_edit_message(query, text, markup)

async def search_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text.strip().lower()
    tokens = query_text.split()
    if not tokens:
        await update.message.reply_text("Ничего не введено. Попробуйте ещё раз.")
        return SEARCH_STATE

    user_id = update.effective_user.id
    role = get_role(user_id) or ""
    dev_name = (update.effective_user.username or "").lower()
    is_admin = (role.lower() == "администратор" or dev_name == DEVELOPER_USERNAME.lower())

    search_dirs = []
    if is_admin:
        search_dirs.append(BASE_DIR)
    else:
        role_dir = os.path.join(BASE_DIR, role)
        if os.path.exists(role_dir):
            search_dirs.append(role_dir)
        if os.path.exists(OBSHAYA_DIR):
            search_dirs.append(OBSHAYA_DIR)

    results = []
    for sd in search_dirs:
        if not os.path.isdir(sd):
            continue
        for root, dirs, files in os.walk(sd):
            for f in files:
                name_lower = f.lower()
                score = match_all_tokens(name_lower, tokens, threshold=75)
                if score > 0:
                    rel_path = os.path.relpath(root, BASE_DIR)
                    results.append(("file", score, rel_path, f))
            for d in dirs:
                d_lower = d.lower()
                score = match_all_tokens(d_lower, tokens, threshold=75)
                if score > 0:
                    rel_path = os.path.relpath(root, BASE_DIR)
                    results.append(("dir", score, rel_path, d))

    if not results:
        keyboard = [
            [InlineKeyboardButton("🔄 Новый поиск", callback_data="search_tryagain")],
            [InlineKeyboardButton("🔙 Завершить поиск", callback_data="search_back")]
        ]
        await update.message.reply_text("Ничего не найдено.", reply_markup=InlineKeyboardMarkup(keyboard))
        return SEARCH_STATE
    else:
        results.sort(key=lambda x: x[1], reverse=True)
        context.user_data["search_cache"] = {}
        keyboard = []
        for (kind, score, rel_path, name) in results:
            uid = generate_id(6)
            context.user_data["search_cache"][uid] = (kind, rel_path, name)
            scr_int = round(score)
            if kind == "file":
                label = f"📄 {name} (/{rel_path}) [{scr_int}]"
                callback_data = f"searchfile|{uid}"
            else:
                label = f"📁 {name} (/{rel_path}) [{scr_int}]"
                callback_data = f"searchdir|{uid}"
            keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])
        keyboard.append([InlineKeyboardButton("🔄 Новый поиск", callback_data="search_tryagain")])
        keyboard.append([InlineKeyboardButton("🔙 Завершить поиск", callback_data="search_back")])
        await update.message.reply_text("Результаты поиска:", reply_markup=InlineKeyboardMarkup(keyboard))
        return SEARCH_STATE

async def search_tryagain_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["search_cache"] = {}
    await query.answer()
    await safe_edit_message(query, "🔎 Введите ключевые слова для поиска (через пробел):")
    return SEARCH_STATE

async def search_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await return_to_main_menu_after_search(query, context)
    return ConversationHandler.END

async def searchfile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, uid = query.data.split("|", 1)
    except ValueError:
        await query.answer("Ошибка в данных файла.", show_alert=True)
        return SEARCH_STATE
    cache = context.user_data.get("search_cache", {})
    result = cache.get(uid)
    if not result:
        await query.answer("Старая кнопка!", show_alert=True)
        return SEARCH_STATE
    kind, rel_path, filename = result
    if kind != "file":
        await query.answer("Ожидался файл.", show_alert=True)
        return SEARCH_STATE

    full_path = os.path.join(BASE_DIR, rel_path, filename)
    if not os.path.isfile(full_path):
        await query.answer("Файл не найден!", show_alert=True)
        return SEARCH_STATE
    try:
        with open(full_path, "rb") as f:
            await context.bot.send_document(chat_id=query.message.chat.id, document=f, filename=filename)
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {full_path}: {e}")
        await query.answer("Ошибка при отправке файла", show_alert=True)
        return SEARCH_STATE

    keyboard = [[InlineKeyboardButton("🔙 Завершить поиск", callback_data="search_back")]]
    await safe_edit_message(query, "Файл отправлен.", InlineKeyboardMarkup(keyboard))
    return SEARCH_STATE

async def searchdir_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, uid = query.data.split("|", 1)
    except ValueError:
        await query.answer("Ошибка в данных директории.", show_alert=True)
        return SEARCH_STATE
    cache = context.user_data.get("search_cache", {})
    result = cache.get(uid)
    if not result:
        await query.answer("Старая кнопка!", show_alert=True)
        return SEARCH_STATE
    kind, rel_path, dirname = result
    if kind != "dir":
        await query.answer("Ожидалась папка.", show_alert=True)
        return SEARCH_STATE

    new_rel = os.path.join(rel_path, dirname)
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    dev_name = (query.from_user.username or "").lower()
    is_admin = (role.lower() == "администратор" or dev_name == DEVELOPER_USERNAME.lower())
    allowed_root = "Администратор" if is_admin else role

    # завершаем поиск, переходим к просмотру папки
    await browse_directory(query, context, new_rel, is_admin, allowed_root)
    return ConversationHandler.END

async def search_exit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await return_to_main_menu_after_search(query, context)
    return ConversationHandler.END

search_conv = ConversationHandler(
    entry_points=[
        CommandHandler("search", search_command),
        CallbackQueryHandler(start_search_callback, pattern="^search_files$")
    ],
    states={
        SEARCH_STATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, search_query_handler),
            CallbackQueryHandler(search_tryagain_callback, pattern="^search_tryagain$"),
            CallbackQueryHandler(searchfile_handler, pattern="^searchfile\\|"),
            CallbackQueryHandler(searchdir_handler, pattern="^searchdir\\|"),
            CallbackQueryHandler(search_back_handler, pattern="^search_back$"),
            CallbackQueryHandler(search_exit_handler, pattern="^search_exit$"),
            # Не блокируем admin_falise
            CallbackQueryHandler(block_menu_while_search,
                pattern="^(files_obshaya|files_role|search_files|mail_main|admin_panel|main_menu)$"
            ),
        ],
    },
    fallbacks=[]
)
