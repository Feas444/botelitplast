import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
)
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Предполагаем, что в db.py и config.py есть нужные функции/переменные:
from db import (
    get_role, get_all_users, get_user_by_id,
    get_all_emails, insert_email, delete_email, mark_email_read,
    get_unread_emails, get_read_emails, get_all_tests, insert_test
)
from config import DEVELOPER_USERNAME, ROLES

logger = logging.getLogger(__name__)

########################################
# Состояния (константы)
########################################

MAIL_MENU = 100

# --- Рассылка группе ---
MAIL_GROUP_CHOOSE_ROLE = 110
MAIL_GROUP_SUBJECT = 111
MAIL_GROUP_BODY = 112
MAIL_GROUP_ATTACHMENT = 113
MAIL_GROUP_CHOOSE_TEST = 114
MAIL_GROUP_PREVIEW = 115

# --- Рассылка одному ---
MAIL_ONE_CHOOSEUSER = 120
MAIL_ONE_SUBJECT = 121
MAIL_ONE_BODY = 122
MAIL_ONE_ATTACHMENT = 123
MAIL_ONE_ATTACH_TEST = 125
MAIL_ONE_PREVIEW = 124

# --- Тесты ---
TEST_MENU = 310
TEST_CREATE_MENU = 311
TEST_CREATE_HEADER = 312
TEST_CREATE_LINK = 313
TEST_CREATE_CONFIRM = 314

# --- «Все сообщения» (админ) ---
MAIL_ALL_ROLES = 410
MAIL_ALL_LIST = 411

########################################
# Вспомогательные функции
########################################

def is_admin_or_dev(query: CallbackQuery) -> bool:
    role = (get_role(query.from_user.id) or "").lower()
    dev_name = (query.from_user.username or "").lower()
    return (role in ("администратор", "помощник директора")) or (dev_name == DEVELOPER_USERNAME.lower())

async def safe_edit_menu(query: CallbackQuery, text: str, markup=None):
    """
    Редактируем сообщение, избегая ошибки «Message is not modified».
    При невозможности — удаляем и отправляем новое.
    """
    from telegram.error import BadRequest
    try:
        await query.edit_message_text(text=text, reply_markup=markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        try:
            await query.message.delete()
        except:
            pass
        if markup:
            await query.message.chat.send_message(text, reply_markup=markup)
        else:
            await query.message.chat.send_message(text)

async def safe_edit_or_send(update, context, text: str, reply_markup=None):
    """
    Универсальная функция для отправки/редактирования сообщения.
    Если update – это CallbackQuery, берём chat_id из query.message.chat.id.
    Если update – это обычный Update с update.message, берём update.effective_chat.id.
    """
    bot = context.bot

    if isinstance(update, CallbackQuery):
        # update — это объект CallbackQuery
        query = update
        chat_id = query.message.chat.id
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            context.user_data["last_bot_msg_id"] = query.message.message_id
        except Exception:
            # Если редактировать не получилось, пробуем удалить и отправить новое
            try:
                await query.message.delete()
            except:
                pass
            msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            context.user_data["last_bot_msg_id"] = msg.message_id

    elif hasattr(update, 'message') and update.message:
        # update — это обычный объект Update с сообщением
        chat_id = update.effective_chat.id
        last_bot_msg_id = context.user_data.get("last_bot_msg_id")
        if last_bot_msg_id:
            # Пробуем отредактировать старое сообщение
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_bot_msg_id,
                    text=text,
                    reply_markup=reply_markup
                )
            except Exception:
                # Если не вышло — удаляем/шлём новое
                msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
                context.user_data["last_bot_msg_id"] = msg.message_id
        else:
            # Нет «старого» сообщения — отправляем новое
            msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
            context.user_data["last_bot_msg_id"] = msg.message_id

    else:
        # Если вдруг что-то третье
        raise ValueError("safe_edit_or_send: не удалось определить тип update (CallbackQuery или message).")


def get_admin_keyboard():
    """Клавиатура для админов / помощников / разработчика."""
    kb = [
        [InlineKeyboardButton("📁 Общие файлы", callback_data="files_obshaya"),
         InlineKeyboardButton("📁 Файлы работы", callback_data="files_role")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="search_files"),
         InlineKeyboardButton("💬 Сообщения", callback_data="mail_main")],
        [InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_panel")]
    ]
    return InlineKeyboardMarkup(kb)

def get_user_keyboard(role: str):
    """Клавиатура для обычных пользователей."""
    kb = [
        [InlineKeyboardButton("📁 Общие файлы", callback_data="files_obshaya"),
         InlineKeyboardButton("📁 Файлы работы", callback_data="files_role")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="search_files"),
         InlineKeyboardButton("💬 Сообщения", callback_data="mail_main")]
    ]
    return InlineKeyboardMarkup(kb)

async def return_to_global_menu(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    Завершает почтовый диалог. Выходим в обычное меню:
    - Админ-меню, если роль=администратор/помощник директора или dev
    - Иначе пользовательское меню
    """
    from telegram.ext import ConversationHandler
    user_id = query.from_user.id
    role = (get_role(user_id) or "").lower()
    dev_name = (query.from_user.username or "").lower()
    if role in ("администратор", "помощник директора") or dev_name == DEVELOPER_USERNAME.lower():
        text = f"💬 Вы вышли из сообщений.\nАдмин-меню (роль: {role})"
        markup = get_admin_keyboard()
    else:
        text = f"💬 Вы вышли из сообщений.\nМеню для роли: {role}"
        markup = get_user_keyboard(role)
    await query.edit_message_text(text, reply_markup=markup)
    return ConversationHandler.END

########################################
# 1) Главное меню «Сообщений»
########################################

async def mail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Точка входа в почту: /mail или callback_data='mail_main'.
    """
    chat_id = update.effective_chat.id
    attach_id = context.user_data.pop("current_attachment_msg_id", None)
    if attach_id:
        try:
            await update.effective_message.bot.delete_message(chat_id, attach_id)
        except:
            pass

    if update.callback_query:
        query = update.callback_query
        await query.answer()

    user_id = update.effective_user.id
    role = (get_role(user_id) or "").lower()
    dev_name = (update.effective_user.username or "").lower()
    can_admin = (role in ("администратор", "помощник директора")) or (dev_name == DEVELOPER_USERNAME.lower())

    kb = [
        [InlineKeyboardButton("📥 Непрочитанные", callback_data="mail_unread"),
         InlineKeyboardButton("📖 Прочитанные", callback_data="mail_read")],
        [InlineKeyboardButton("📝 Тесты", callback_data="mail_tests")]
    ]
    if can_admin:
        kb.append([
            InlineKeyboardButton("📤 Отправить сообщение", callback_data="mail_send_msg"),
            InlineKeyboardButton("📂 Все сообщения", callback_data="mail_all")
        ])
    kb.append([InlineKeyboardButton("🚪 Выйти", callback_data="mail_exit")])
    markup = InlineKeyboardMarkup(kb)

    text = "💬 Меню сообщений"
    if update.callback_query:
        await safe_edit_menu(update.callback_query, text, markup)
    else:
        await safe_edit_or_send(update, context, text, markup)
    return MAIL_MENU

async def mail_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик меню почты (MAIL_MENU)."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "mail_exit":
        return await return_to_global_menu(query, context)
    elif data == "mail_unread":
        return await show_unread_inbox(query, context)
    elif data == "mail_read":
        return await show_read_inbox(query, context)
    elif data == "mail_tests":
        return await show_tests_menu(update, context)
    elif data == "mail_all":
        return await mail_all_roles(query, context)  # «Все сообщения»
    elif data == "mail_send_msg":
        kb = [
            [InlineKeyboardButton("👥 Группе", callback_data="mail_send_group"),
             InlineKeyboardButton("👤 Одному", callback_data="mail_send_one")],
            [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
        ]
        await safe_edit_menu(query, "📤 Отправить сообщение:", InlineKeyboardMarkup(kb))
        return MAIL_MENU
    elif data == "mail_send_group":
        return await start_mail_sending_group(query, context)
    elif data == "mail_send_one":
        return await start_mail_sending_one(query, context)
    else:
        await query.answer("Неизвестная команда.")
        return MAIL_MENU

########################################
# 2) Непрочитанные/прочитанные
########################################

async def show_unread_inbox(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    mails = get_unread_emails(user_id)  # [(mail_id, subj, body, att, test_id), ...]
    if not mails:
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]]
        await safe_edit_menu(query, "📪 У вас нет новых сообщений.", InlineKeyboardMarkup(kb))
    else:
        kb = []
        for (m_id, s, b, a, t) in mails:
            kb.append([InlineKeyboardButton(s, callback_data=f"unread_mail:{m_id}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_main")])
        await safe_edit_menu(query, "📬 Непрочитанные сообщения:", InlineKeyboardMarkup(kb))
    return MAIL_MENU

async def open_unread_mail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # data: "unread_mail:<mail_id>"
    _, mail_id_str = query.data.split(":", 1)
    mail_id = int(mail_id_str)
    # Ищем письмо среди непрочитанных
    all_unread = get_unread_emails(query.from_user.id)
    found = None
    for (m_id, s, b, a, t_id) in all_unread:
        if m_id == mail_id:
            found = (s, b, a, t_id)
            break
    if not found:
        await safe_edit_menu(query, "📪 Сообщение не найдено или уже прочитано.")
        return MAIL_MENU

    subj, bod, att, test_id = found
    text = f"📧 Тема: {subj}\n\n{bod}"

    # Попытка отправки вложения
    if att:
        from telegram.error import BadRequest
        try:
            sent = await query.message.reply_document(att)
            context.user_data["current_attachment_msg_id"] = sent.message_id
            text += "\n(📎 Вложение отправлено как документ)"
        except BadRequest as e:
            if "can't use file of type photo as document" in str(e).lower():
                sent = await query.message.reply_photo(att)
                context.user_data["current_attachment_msg_id"] = sent.message_id
                text += "\n(🖼 Вложение отправлено как фото)"
            else:
                text += f"\n(Ошибка отправки вложения: {e})"

    kb = [
        [InlineKeyboardButton("✅ Прочитано", callback_data=f"mark_read:{mail_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_unread")]
    ]
    await safe_edit_menu(query, text, InlineKeyboardMarkup(kb))
    return MAIL_MENU

from db import cursor, get_all_tests, mark_email_read

async def mark_read_handler(update, context):
    query = update.callback_query
    await query.answer()
    _, mail_id_str = query.data.split(":", 1)
    mail_id = int(mail_id_str)

    # 1. Узнаём, есть ли test_id у этого письма
    cursor.execute("SELECT test_id FROM emails WHERE id=?", (mail_id,))
    row = cursor.fetchone()
    test_id = row[0] if row else None

    # 2. Помечаем письмо прочитанным
    mark_email_read(mail_id)

    # 3. Удаляем вложение (если было отправлено как отдельное сообщение)
    attach_id = context.user_data.pop("current_attachment_msg_id", None)
    if attach_id:
        try:
            await query.message.bot.delete_message(query.message.chat_id, attach_id)
        except:
            pass

    # 4. Если письмо содержит тест, показываем одну кнопку с URL (чтобы открыть в браузере)
    if test_id:
        all_tests = get_all_tests()  # [(id, header, link, for_group, role, user_id, attach_id), ...]
        found = None
        for (tid, header, link, fg, rl, uid, attach_id) in all_tests:
            if tid == test_id:
                found = (header, link)
                break
        
        if found:
            header, link = found
            text = (
                "✅ Сообщение прочитано.\n"
                f"У вас теперь доступен тест: «{header}»\n\n"
                f"Ссылка: {link}"
            )
            # Кнопка с url=... сразу открывает ссылку
            kb = [
                [InlineKeyboardButton("Открыть тест", url=link)],
                [InlineKeyboardButton("Назад", callback_data="mail_main")]
            ]
            await safe_edit_menu(query, text, InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("Назад", callback_data="mail_main")]]
            await safe_edit_menu(query, "✅ Сообщение прочитано. Но тест не найден в БД.", InlineKeyboardMarkup(kb))
    else:
        kb = [[InlineKeyboardButton("Назад", callback_data="mail_main")]]
        await safe_edit_menu(query, "✅ Сообщение прочитано.", InlineKeyboardMarkup(kb))

    return MAIL_MENU

async def back_unread_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await show_unread_inbox(query, context)

async def show_read_inbox(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    mails = get_read_emails(user_id)  # [(mail_id, subj, body, att, test_id), ...]
    if not mails:
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]]
        await safe_edit_menu(query, "📪 Нет прочитанных сообщений.", InlineKeyboardMarkup(kb))
    else:
        kb = []
        for (m_id, s, b, a, t) in mails:
            kb.append([InlineKeyboardButton(s, callback_data=f"read_mail:{m_id}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_main")])
        await safe_edit_menu(query, "📖 Прочитанные сообщения:", InlineKeyboardMarkup(kb))
    return MAIL_MENU

async def open_read_mail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # data вида "read_mail:<mail_id>"
    _, mail_id_str = query.data.split(":", 1)
    mail_id = int(mail_id_str)

    # Ищем письмо среди прочитанных
    all_read = get_read_emails(query.from_user.id)
    found = None
    for (m_id, subj, bod, att, test_id) in all_read:
        if m_id == mail_id:
            found = (subj, bod, att, test_id)
            break

    if not found:
        await safe_edit_menu(query, "Сообщение не найдено.")
        return MAIL_MENU

    subj, bod, att, test_id = found
    text = f"📧 Тема: {subj}\n\n{bod}"

    # Попытка отправки вложения
    if att:
        from telegram.error import BadRequest
        try:
            sent = await query.message.reply_document(att)
            context.user_data["current_attachment_msg_id"] = sent.message_id
            text += "\n(📎 Вложение отправлено как документ)"
        except BadRequest as e:
            if "can't use file of type photo as document" in str(e).lower():
                sent = await query.message.reply_photo(att)
                context.user_data["current_attachment_msg_id"] = sent.message_id
                text += "\n(🖼 Вложение отправлено как фото)"
            else:
                text += f"\n(Ошибка отправки вложения: {e})"

    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_read")]]
    await safe_edit_menu(query, text, InlineKeyboardMarkup(kb))
    return MAIL_MENU

async def back_read_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    При нажатии «Назад» в разделе прочитанных сообщений возвращаемся
    к списку прочитанных сообщений.
    """
    query = update.callback_query
    await query.answer()
    return await show_read_inbox(query, context)

########################################
# 3) «Все сообщения» (админ)
########################################

async def mail_all_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update, CallbackQuery):
        query = update
    else:
        query = update.callback_query
    # Теперь можно использовать query.from_user.id и т.д.
    if not is_admin_or_dev(query):
        await safe_edit_menu(query, "Нет прав для просмотра всех сообщений.")
        return MAIL_MENU
    all_list = get_all_emails()
    if not all_list:
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]]
        await safe_edit_menu(query, "📪 Нет сообщений.", InlineKeyboardMarkup(kb))
        return MAIL_MENU

    role_to_mails = {}
    for (m_id, rec, s, b, st, a, t_id) in all_list:
        info = get_user_by_id(rec)
        if not info:
            role_to_mails.setdefault("Без роли", []).append((m_id, rec, s, b, st, a, t_id))
        else:
            r = info[2] or "Без роли"
            role_to_mails.setdefault(r, []).append((m_id, rec, s, b, st, a, t_id))

    kb = []
    for r, mails in role_to_mails.items():
        if mails:
            kb.append([InlineKeyboardButton(f"{r} ({len(mails)})", callback_data=f"mail_all_group:{r}")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_main")])
    await safe_edit_menu(query, "Выберите роль, чтобы посмотреть её письма:", InlineKeyboardMarkup(kb))
    return MAIL_ALL_ROLES

async def mail_all_choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chosen_role = query.data.split(":", 1)
    all_list = get_all_emails()
    relevant = []
    for (m_id, rec, s, b, st, a, t_id) in all_list:
        info = get_user_by_id(rec)
        if info:
            if info[2] == chosen_role:
                relevant.append((m_id, rec, s, b, st, a, t_id))
        else:
            if chosen_role == "Без роли":
                relevant.append((m_id, rec, s, b, st, a, t_id))
    if not relevant:
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_all")]]
        await query.edit_message_text(f"У роли '{chosen_role}' нет сообщений.", reply_markup=InlineKeyboardMarkup(kb))
        return MAIL_ALL_ROLES

    context.user_data["mail_all_chosen_role"] = chosen_role
    kb = []
    for (m_id, rec, subj, bod, st, att, test_id) in relevant:
        preview = f"{subj} | {bod[:20]}..."
        kb.append([
            InlineKeyboardButton(preview, callback_data=f"mail_all_view:{m_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"mail_all_del:{m_id}")
        ])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_all")])
    await query.edit_message_text(f"Письма для роли '{chosen_role}':", reply_markup=InlineKeyboardMarkup(kb))
    return MAIL_ALL_LIST

async def mail_all_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, mail_id_str = query.data.split(":", 1)
    mail_id = int(mail_id_str)
    all_list = get_all_emails()
    found = None
    for (m_id, rec, s, b, st, a, t_id) in all_list:
        if m_id == mail_id:
            found = (s, b, a, t_id)
            break
    if not found:
        await query.edit_message_text("Сообщение не найдено.")
        return MAIL_ALL_LIST
    subj, bod, att, test_id = found
    text = f"📧 Тема: {subj}\n\n{bod}"
    kb = [
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"mail_all_del:{mail_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_all_back")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return MAIL_ALL_LIST

async def mail_all_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, mail_id_str = query.data.split(":", 1)
    mail_id = int(mail_id_str)
    delete_email(mail_id)
    kb = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="mail_all_refresh")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_all_back")]
    ]
    await query.edit_message_text(f"Сообщение {mail_id} удалено.", reply_markup=InlineKeyboardMarkup(kb))
    return MAIL_ALL_LIST

async def mail_all_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chosen_role = context.user_data.get("mail_all_chosen_role", "Без роли")
    all_list = get_all_emails()
    relevant = []
    for (m_id, rec, s, b, st, a, t_id) in all_list:
        info = get_user_by_id(rec)
        if info:
            if info[2] == chosen_role:
                relevant.append((m_id, rec, s, b, st, a, t_id))
        else:
            if chosen_role == "Без роли":
                relevant.append((m_id, rec, s, b, st, a, t_id))
    if not relevant:
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_all")]]
        await query.edit_message_text(f"У роли '{chosen_role}' нет сообщений.", reply_markup=InlineKeyboardMarkup(kb))
        return MAIL_ALL_ROLES

    kb = []
    for (m_id, rec, subj, bod, st, att, test_id) in relevant:
        preview = f"{subj} | {bod[:20]}..."
        kb.append([
            InlineKeyboardButton(preview, callback_data=f"mail_all_view:{m_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"mail_all_del:{m_id}")
        ])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_all")])
    await query.edit_message_text(f"Письма для роли '{chosen_role}':", reply_markup=InlineKeyboardMarkup(kb))
    return MAIL_ALL_LIST

async def mail_all_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await mail_all_back(update, context)

########################################
# 4) Отправка группе
########################################

async def start_mail_sending_group(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_dev(query):
        await safe_edit_menu(query, "Нет прав!")
        return MAIL_MENU
    for k in ["mail_group_role", "mail_group_subject", "mail_group_body", "mail_group_attachment", "mail_group_test_id"]:
        context.user_data.pop(k, None)
    kb = [[InlineKeyboardButton("🌐 Все", callback_data="group_role:ALL")]]
    for r in ROLES:
        kb.append([InlineKeyboardButton(r, callback_data=f"group_role:{r}")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_main")])
    await safe_edit_menu(query, "Выберите роль получателей (или ALL):", InlineKeyboardMarkup(kb))
    return MAIL_GROUP_CHOOSE_ROLE

async def mail_group_role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chosen_role = query.data.split("group_role:", 1)
    context.user_data["mail_group_role"] = chosen_role

    # Сохраняем message_id, чтобы следующий шаг (ввод темы) редактировал то же сообщение
    context.user_data["last_bot_msg_id"] = query.message.message_id

    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]]
    text = f"🔖 Роль: {chosen_role}\n\nВведите ТЕМУ сообщения:"
    await safe_edit_or_send(query, context, text, InlineKeyboardMarkup(kb))
    return MAIL_GROUP_SUBJECT



async def mail_group_subject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subj = update.message.text.strip()
    context.user_data["mail_group_subject"] = subj

    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]]
    text = f"💬 Тема: {subj}\n\nВведите текст сообщения:"
    await safe_edit_or_send(update, context, text, InlineKeyboardMarkup(kb))
    return MAIL_GROUP_BODY




async def mail_group_body_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bod = update.message.text.strip()
    context.user_data["mail_group_body"] = bod
    kb = [
        [InlineKeyboardButton("📝 Прикрепить тест", callback_data="mail_group_attach_test"),
         InlineKeyboardButton("⛔ Пропустить вложение", callback_data="mail_group_skipfile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]
    await safe_edit_or_send(update, context, f"💬 Текст:\n{bod}\n\nПрикрепить тест или пропустить?", InlineKeyboardMarkup(kb))
    return MAIL_GROUP_ATTACHMENT

async def mail_group_attach_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tests = get_all_tests()
    kb = []
    if tests:
        for (tid, header, link, fg, rl, uid, attach_id) in tests:
            kb.append([InlineKeyboardButton(f"📝 {header}", callback_data=f"test_select:{tid}")])
    else:
        kb.append([InlineKeyboardButton("🚫 Нет тестов в базе", callback_data="test_none")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_group_body_back")])
    await safe_edit_or_send(update, context, "Выберите тест для прикрепления:", InlineKeyboardMarkup(kb))
    return MAIL_GROUP_CHOOSE_TEST

async def mail_group_test_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, test_id_str = query.data.split(":",1)
    context.user_data["mail_group_test_id"] = int(test_id_str)

    # Берём текст сообщения, который пользователь ввёл ранее
    bod = context.user_data.get("mail_group_body", "")
    text = (
        f"📝 Тест прикреплён!\n\n"
        f"Текст сообщения:\n{bod}\n\n"
        "Пришлите документ/фото для вложения или нажмите «Пропустить»."
    )

    kb = [
        [InlineKeyboardButton("⛔ Пропустить", callback_data="mail_group_skipfile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]

    # Показываем это же «шаг прикрепления», чтобы пользователь мог либо прислать файл, либо пропустить
    await safe_edit_or_send(update, context, text, InlineKeyboardMarkup(kb))
    return MAIL_GROUP_ATTACHMENT


    return MAIL_GROUP_ATTACHMENT

async def mail_group_skipfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mail_group_attachment"] = None
    return await mail_group_show_preview(query, context)

async def mail_group_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        context.user_data["mail_group_attachment"] = update.message.document.file_id
    elif update.message.photo:
        context.user_data["mail_group_attachment"] = update.message.photo[-1].file_id
    else:
        await safe_edit_or_send(update, context, "Пришлите документ/фото или «⛔ Пропустить».")
        return MAIL_GROUP_ATTACHMENT
    return await mail_group_show_preview(update, context)

async def mail_group_show_preview(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    query = update_or_query if isinstance(update_or_query, CallbackQuery) else None
    role_name = context.user_data.get("mail_group_role", "")
    subj = context.user_data.get("mail_group_subject", "")
    bod = context.user_data.get("mail_group_body", "")
    att = context.user_data.get("mail_group_attachment", None)
    test_id = context.user_data.get("mail_group_test_id", None)
    text_caption = f"💬 Сообщение группе: {role_name}\nТема: {subj}\n\n{bod}"
    if test_id:
        for (tid, header, link, fg, rl, uid, attach_id) in get_all_tests():
            if tid == test_id:
                text_caption += f"\n\n📝 Прикреплён тест:\n«{header}»\n🔗 {link}"
                break
    kb = [
    [InlineKeyboardButton("✅ Отправить!", callback_data="mail_group_send")],
    [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]

    if query:
        await safe_edit_menu(query, text_caption, InlineKeyboardMarkup(kb))
    else:
        await safe_edit_or_send(update_or_query, context, text_caption, InlineKeyboardMarkup(kb))
    return MAIL_GROUP_PREVIEW

async def mail_group_send_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role_name = context.user_data.get("mail_group_role", "")
    subj = context.user_data.get("mail_group_subject", "")
    bod = context.user_data.get("mail_group_body", "")
    att = context.user_data.get("mail_group_attachment", None)
    test_id = context.user_data.get("mail_group_test_id", None)

    all_u = get_all_users()
    if role_name == "ALL":
        for (tid, nm, un, rl) in all_u:
            insert_email(tid, subj, bod, att, test_id)
            try:
                await context.bot.send_message(tid, text=f"💬 Новое сообщение!\nТема: {subj}")
            except:
                pass
    else:
        for (tid, nm, un, rl) in all_u:
            if rl == role_name:
                insert_email(tid, subj, bod, att, test_id)
                try:
                    await context.bot.send_message(tid, text=f"💬 Новое сообщение!\nТема: {subj}")
                except:
                    pass
    for k in ["mail_group_role", "mail_group_subject", "mail_group_body", "mail_group_attachment", "mail_group_test_id"]:
        context.user_data.pop(k, None)
    await safe_edit_menu(query, f"✅ Сообщение успешно отправлено группе: {role_name}!")
    return MAIL_MENU



async def mail_group_body_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bod = context.user_data.get("mail_group_body", "")
    kb = [
        [InlineKeyboardButton("📝 Прикрепить тест", callback_data="mail_group_attach_test"),
         InlineKeyboardButton("⛔ Пропустить вложение", callback_data="mail_group_skipfile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]
    text = f"💬 Текст:\n{bod}\n\nПрикрепить тест или пропустить?"
    await safe_edit_menu(query, text, InlineKeyboardMarkup(kb))
    return MAIL_GROUP_ATTACHMENT

########################################
# 5) Рассылка одному
########################################

async def start_mail_sending_one(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_dev(query):
        await safe_edit_menu(query, "Нет прав!")
        return MAIL_MENU
    for k in ["mail_one_recipient", "mail_one_subject", "mail_one_body", "mail_one_attachment", "mail_one_test_id"]:
        context.user_data.pop(k, None)

    usrs = get_all_users()
    kb = []
    for (tid, nm, un, rl) in usrs:
        if tid == query.from_user.id:
            continue
        text_btn = f"{nm} (@{un}) - {rl}"
        kb.append([InlineKeyboardButton(text_btn, callback_data=f"mail_one_user:{tid}")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_main")])
    await safe_edit_menu(query, "👤 Выберите получателя:", InlineKeyboardMarkup(kb))
    return MAIL_ONE_CHOOSEUSER

async def mail_one_user_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, tid_str = query.data.split("mail_one_user:", 1)
    rid = int(tid_str)
    context.user_data["mail_one_recipient"] = rid

    # Сохраняем message_id, чтобы следующий шаг (ввод темы) редактировал то же сообщение
    context.user_data["last_bot_msg_id"] = query.message.message_id

    mk = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]])
    text = f"👤 Получатель: {rid}\n\nВведите ТЕМУ сообщения:"
    await safe_edit_or_send(query, context, text, mk)
    return MAIL_ONE_SUBJECT


async def mail_one_subject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Здесь уже user_data["last_bot_msg_id"] указывает на то же сообщение,
    # которое было создано/отредактировано в mail_one_user_chosen
    subj = update.message.text.strip()
    context.user_data["mail_one_subject"] = subj

    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]]
    text = f"💬 Тема: {subj}\n\nВведите текст сообщения:"
    await safe_edit_or_send(update, context, text, InlineKeyboardMarkup(kb))
    return MAIL_ONE_BODY



async def mail_one_body_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bod = update.message.text.strip()
    context.user_data["mail_one_body"] = bod
    kb = [
        [InlineKeyboardButton("📝 Прикрепить тест", callback_data="mail_one_attach_test"),
         InlineKeyboardButton("⛔ Пропустить вложение", callback_data="mail_one_skipfile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]
    await safe_edit_or_send(update, context, f"💬 Текст:\n{bod}\n\nПрикрепить тест или пропустить?", InlineKeyboardMarkup(kb))
    return MAIL_ONE_ATTACHMENT

async def mail_one_attach_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tests = get_all_tests()
    kb = []
    if tests:
        for (tid, header, link, fg, role, uid, attach_id) in tests:
            kb.append([InlineKeyboardButton(f"📝 {header}", callback_data=f"test_select_one:{tid}")])
    else:
        kb.append([InlineKeyboardButton("🚫 Нет тестов", callback_data="test_none")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="mail_one_body_back")])
    await safe_edit_or_send(update, context, "Выберите тест для прикрепления:", InlineKeyboardMarkup(kb))
    return MAIL_ONE_ATTACH_TEST

async def mail_one_test_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, test_id_str = query.data.split(":",1)
    context.user_data["mail_one_test_id"] = int(test_id_str)

    bod = context.user_data.get("mail_one_body", "")
    text = (
        f"📝 Тест прикреплён!\n\n"
        f"Текст сообщения:\n{bod}\n\n"
        "Пришлите документ/фото для вложения или нажмите «Пропустить»."
    )

    kb = [
        [InlineKeyboardButton("⛔ Пропустить", callback_data="mail_one_skipfile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]

    await safe_edit_or_send(update, context, text, InlineKeyboardMarkup(kb))
    return MAIL_ONE_ATTACHMENT


async def mail_one_skipfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["mail_one_attachment"] = None
    return await mail_one_show_preview(query, context)

async def mail_one_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        context.user_data["mail_one_attachment"] = update.message.document.file_id
    elif update.message.photo:
        context.user_data["mail_one_attachment"] = update.message.photo[-1].file_id
    else:
        await safe_edit_or_send(update, context, "Пришлите документ/фото или «⛔ Пропустить».")
        return MAIL_ONE_ATTACHMENT
    return await mail_one_show_preview(update, context)

async def mail_one_show_preview(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    query = update_or_query if isinstance(update_or_query, CallbackQuery) else None
    rid = context.user_data.get("mail_one_recipient")
    subj = context.user_data.get("mail_one_subject", "")
    bod = context.user_data.get("mail_one_body", "")
    att = context.user_data.get("mail_one_attachment", None)
    test_id = context.user_data.get("mail_one_test_id", None)
    text_caption = f"👤 Получатель: {rid}\n💬 Тема: {subj}\n\n{bod}"
    if test_id:
        for (tid, header, link, fg, rl, uid, attach_id) in get_all_tests():
            if tid == test_id:
                text_caption += f"\n\n📝 Прикреплён тест:\n«{header}»\n🔗 {link}"
                break
    kb = [
    [InlineKeyboardButton("✅ Отправить!", callback_data="mail_one_send")],
    [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]

    if query:
        await safe_edit_menu(query, text_caption, InlineKeyboardMarkup(kb))
    else:
        await safe_edit_or_send(update_or_query, context, text_caption, InlineKeyboardMarkup(kb))
    return MAIL_ONE_PREVIEW

async def mail_one_send_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rid = context.user_data.get("mail_one_recipient")
    subj = context.user_data.get("mail_one_subject", "")
    bod = context.user_data.get("mail_one_body", "")
    att = context.user_data.get("mail_one_attachment", None)
    test_id = context.user_data.get("mail_one_test_id", None)
    insert_email(rid, subj, bod, att, test_id)
    try:
        await context.bot.send_message(chat_id=rid, text=f"💬 Новое сообщение!\nТема: {subj}")
    except:
        pass
    for k in ["mail_one_recipient", "mail_one_subject", "mail_one_body", "mail_one_attachment", "mail_one_test_id"]:
        context.user_data.pop(k, None)
    await safe_edit_menu(query, f"✅ Сообщение отправлено пользователю {rid}!")
    return MAIL_MENU


async def mail_one_body_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bod = context.user_data.get("mail_one_body", "")
    kb = [
        [InlineKeyboardButton("📝 Прикрепить тест", callback_data="mail_one_attach_test"),
         InlineKeyboardButton("⛔ Пропустить вложение", callback_data="mail_one_skipfile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_main")]
    ]
    text = f"💬 Текст:\n{bod}\n\nПрикрепить тест или пропустить?"
    await safe_edit_menu(query, text, InlineKeyboardMarkup(kb))
    return MAIL_ONE_ATTACHMENT

########################################
# 7) Тесты: просмотр/удаление/создание
########################################

async def show_tests_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = (get_role(user_id) or "").lower()
    dev_name = (query.from_user.username or "").lower()
    can_admin = (role in ("администратор", "помощник директора")) or (dev_name == DEVELOPER_USERNAME.lower())

    if can_admin:
        tests = get_all_tests()
    else:
        # Для обычных пользователей: получаем все письма, где есть привязанный тест
        emails_unread = get_unread_emails(user_id)
        emails_read = get_read_emails(user_id)
        test_ids = set()
        for mail in emails_unread + emails_read:
            # mail: (id, subject, body, attachment, test_id)
            if mail[4]:
                test_ids.add(mail[4])
        tests = [test for test in get_all_tests() if test[0] in test_ids]

    kb = []
    if tests:
        for (tid, header, link, fg, rl, uid, attach_id) in tests:
            kb.append([InlineKeyboardButton(f"📝 {header}", callback_data=f"test_view:{tid}")])
    else:
        kb.append([InlineKeyboardButton("🚫 Нет тестов", callback_data="test_none")])
    if can_admin:
        kb.append([InlineKeyboardButton("Создать тест", callback_data="test_create_menu")])
    kb.append([InlineKeyboardButton("Назад", callback_data="mail_main")])
    await query.edit_message_text("Меню тестов: выберите действие.", reply_markup=InlineKeyboardMarkup(kb))
    return TEST_MENU

async def test_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, test_id_str = query.data.split(":", 1)
    test_id = int(test_id_str)
    all_t = get_all_tests()
    found = None
    for (tid, header, link, fg, rl, uid, attach_id) in all_t:
        if tid == test_id:
            found = (header, link, attach_id)
            break
    if not found:
        await query.edit_message_text("🚫 Тест не найден.")
        return TEST_MENU
    header, link, attach_id = found
    text = f"📝 Тест: {header}\n🔗 Ссылка: {link}"
    kb = [[InlineKeyboardButton("Открыть тест", url=link)]]
    if is_admin_or_dev(query):
        kb.append([InlineKeyboardButton("🗑 Удалить тест", callback_data=f"test_delete:{test_id}")])
    kb.append([InlineKeyboardButton("Назад", callback_data="mail_main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return TEST_MENU

async def test_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin_or_dev(query):
        await query.answer("Нет прав!", show_alert=True)
        return TEST_MENU
    _, tid_str = query.data.split(":", 1)
    test_id = int(tid_str)
    from db import cursor, conn
    cursor.execute("DELETE FROM tests WHERE id=?", (test_id,))
    conn.commit()
    await query.edit_message_text(f"🗑 Тест {test_id} удалён.")
    return await show_tests_menu(update, context)

async def test_create_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("👥 Тест для группы", callback_data="test_create_group"),
         InlineKeyboardButton("👤 Тест для пользователя", callback_data="test_create_user")],
        [InlineKeyboardButton("💾 Сохранить в хранилище", callback_data="test_create_storage")],
        [InlineKeyboardButton("🔙 Назад", callback_data="mail_tests")]
    ]
    await query.edit_message_text("Создание теста: выберите назначение.", reply_markup=InlineKeyboardMarkup(kb))
    return TEST_CREATE_MENU

async def test_create_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["test_for_group"] = True
    context.user_data["test_role"] = None
    context.user_data["test_user_id"] = None
    kb = []
    for r in ROLES:
        kb.append([InlineKeyboardButton(r, callback_data=f"test_grp_role:{r}")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="test_create_menu")])
    await query.edit_message_text("Выберите роль (группа), для которой создаётся тест:",
                                  reply_markup=InlineKeyboardMarkup(kb))
    return TEST_CREATE_MENU

async def test_grp_role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chosen_role = query.data.split("test_grp_role:", 1)
    context.user_data["test_role"] = chosen_role
    await query.edit_message_text(f"Роль: {chosen_role}\n\nВведите заголовок теста:")
    return TEST_CREATE_HEADER

async def test_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["test_for_group"] = False
    context.user_data["test_role"] = None
    context.user_data["test_user_id"] = None
    allu = get_all_users()
    kb = []
    for (tid, nm, un, rl) in allu:
        kb.append([InlineKeyboardButton(f"{nm} (@{un}) - {rl}", callback_data=f"test_usr:{tid}")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="test_create_menu")])
    await query.edit_message_text("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(kb))
    return TEST_CREATE_MENU

async def test_usr_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, tid_str = query.data.split("test_usr:", 1)
    uid = int(tid_str)
    context.user_data["test_user_id"] = uid
    await query.edit_message_text(f"Пользователь: {uid}\n\nВведите заголовок теста:")
    return TEST_CREATE_HEADER

async def test_create_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["test_for_group"] = False
    context.user_data["test_role"] = None
    context.user_data["test_user_id"] = None
    await query.edit_message_text("Тест без назначения. Введите заголовок:")
    return TEST_CREATE_HEADER

async def test_create_header_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    header = update.message.text.strip()
    context.user_data["test_header"] = header
    await safe_edit_or_send(update, context, f"Заголовок: {header}\nТеперь введите ссылку на тест:")
    return TEST_CREATE_LINK

async def test_create_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    context.user_data["test_link"] = link
    text = (f"Тест:\nЗаголовок: {context.user_data['test_header']}\n"
            f"Ссылка: {link}\n\nПодтвердить создание?")
    kb = [
        [InlineKeyboardButton("Создать", callback_data="test_create_confirm_yes"),
         InlineKeyboardButton("Отмена", callback_data="test_create_confirm_no")]
    ]
    await safe_edit_or_send(update, context, text, InlineKeyboardMarkup(kb))
    return TEST_CREATE_CONFIRM

async def test_create_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "test_create_confirm_no":
        for k in ["test_for_group", "test_role", "test_user_id", "test_header", "test_link"]:
            context.user_data.pop(k, None)
        await query.edit_message_text("Создание теста отменено.")
        return await show_tests_menu(update, context)
    else:
        header = context.user_data.pop("test_header", "Без названия")
        link = context.user_data.pop("test_link", "")
        is_group = context.user_data.pop("test_for_group", False)
        role = context.user_data.pop("test_role", None)
        user_id = context.user_data.pop("test_user_id", None)
        insert_test(header, link, is_group, role, user_id)

        # Если нужно, рассылаем уведомления
        new_all = get_all_tests()
        new_id = max(t[0] for t in new_all) if new_all else 1

        subj = f"Новый тест: {header}"
        bod = f"Вам назначен тест «{header}». Отметьте письмо прочитанным, чтобы получить ссылку."
        if is_group and role:
            for (tid, nm, un, rl) in get_all_users():
                if rl and rl.lower() == role.lower():
                    insert_email(tid, subj, bod, None, new_id)
        elif not is_group and user_id:
            insert_email(user_id, subj, bod, None, new_id)

        await query.edit_message_text(f"Тест «{header}» создан!")
        return await show_tests_menu(update, context)

########################################
# ConversationHandler (единый)
########################################

from telegram.ext import ConversationHandler

mail_conv = ConversationHandler(
    entry_points=[
        CommandHandler("mail", mail_command),
        CallbackQueryHandler(mail_command, pattern="^mail_main$")
    ],
    states={
        MAIL_MENU: [
            CallbackQueryHandler(mail_menu_handler,
                pattern="^(mail_unread|mail_read|mail_tests|mail_all|mail_send_msg|mail_exit|mail_main|mail_send_group|mail_send_one)$"),
            CallbackQueryHandler(open_unread_mail_handler, pattern="^unread_mail:"),
            CallbackQueryHandler(mark_read_handler, pattern="^mark_read:"),
            CallbackQueryHandler(back_unread_handler, pattern="^back_unread$"),
            CallbackQueryHandler(open_read_mail_handler, pattern="^read_mail:"),
            CallbackQueryHandler(back_read_handler, pattern="^back_read$")
        ],

        # «Все сообщения»
        MAIL_ALL_ROLES: [
            CallbackQueryHandler(mail_all_choose_role, pattern="^mail_all_group:"),
            CallbackQueryHandler(return_to_global_menu, pattern="^mail_main$")
        ],
        MAIL_ALL_LIST: [
            CallbackQueryHandler(mail_all_view, pattern="^mail_all_view:"),
            CallbackQueryHandler(mail_all_delete, pattern="^mail_all_del:"),
            CallbackQueryHandler(mail_all_back, pattern="^mail_all_back$"),
            CallbackQueryHandler(mail_all_refresh, pattern="^mail_all_refresh$"),
    # Добавляем обработчик для «Назад» (callback_data="mail_all"):
            CallbackQueryHandler(mail_all_roles, pattern="^mail_all$"),

            CallbackQueryHandler(return_to_global_menu, pattern="^mail_main$")
        ],

        # Рассылка группе
        MAIL_GROUP_CHOOSE_ROLE: [
            CallbackQueryHandler(mail_group_role_handler, pattern="^group_role:"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_GROUP_SUBJECT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, mail_group_subject_handler),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_GROUP_BODY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, mail_group_body_handler),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_GROUP_ATTACHMENT: [
            MessageHandler(filters.Document.ALL | filters.PHOTO, mail_group_file_handler),
            CallbackQueryHandler(mail_group_skipfile, pattern="^mail_group_skipfile$"),
            CallbackQueryHandler(mail_group_attach_test, pattern="^mail_group_attach_test$"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_GROUP_CHOOSE_TEST: [
            CallbackQueryHandler(mail_group_test_selected, pattern="^test_select:"),
            CallbackQueryHandler(mail_group_body_back, pattern="^mail_group_body_back$")
        ],
        MAIL_GROUP_PREVIEW: [
            CallbackQueryHandler(mail_group_send_final, pattern="^mail_group_send$"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],

        # Рассылка одному
        MAIL_ONE_CHOOSEUSER: [
            CallbackQueryHandler(mail_one_user_chosen, pattern="^mail_one_user:"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_ONE_SUBJECT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, mail_one_subject_handler),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_ONE_BODY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, mail_one_body_handler),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_ONE_ATTACHMENT: [
            MessageHandler(filters.Document.ALL | filters.PHOTO, mail_one_file_handler),
            CallbackQueryHandler(mail_one_skipfile, pattern="^mail_one_skipfile$"),
            CallbackQueryHandler(mail_one_attach_test, pattern="^mail_one_attach_test$"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        MAIL_ONE_ATTACH_TEST: [
            CallbackQueryHandler(mail_one_test_selected, pattern="^test_select_one:"),
            CallbackQueryHandler(mail_one_body_back, pattern="^mail_one_body_back$")
        ],
        MAIL_ONE_PREVIEW: [
            CallbackQueryHandler(mail_one_send_final, pattern="^mail_one_send$"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],

        # Тесты
        TEST_MENU: [
            CallbackQueryHandler(show_tests_menu, pattern="^mail_tests$"),
            CallbackQueryHandler(test_view_handler, pattern="^test_view:"),
            CallbackQueryHandler(test_delete_handler, pattern="^test_delete:"),
            CallbackQueryHandler(test_create_menu_handler, pattern="^test_create_menu$"),
            CallbackQueryHandler(mail_command, pattern="^mail_main$")
        ],
        TEST_CREATE_MENU: [
            CallbackQueryHandler(test_create_group, pattern="^test_create_group$"),
            CallbackQueryHandler(test_create_user, pattern="^test_create_user$"),
            CallbackQueryHandler(test_create_storage, pattern="^test_create_storage$"),
            CallbackQueryHandler(show_tests_menu, pattern="^mail_tests$")
        ],
        TEST_CREATE_HEADER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, test_create_header_handler)
        ],
        TEST_CREATE_LINK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, test_create_link_handler)
        ],
        TEST_CREATE_CONFIRM: [
            CallbackQueryHandler(test_create_confirm_handler, pattern="^(test_create_confirm_yes|test_create_confirm_no)$")
        ]
    },
    fallbacks=[],
    allow_reentry=True
)
