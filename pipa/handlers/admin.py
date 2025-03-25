# admin.py

import os
import sys
import asyncio
import shutil
import logging
import random
import string

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from db import (
    get_all_users, get_role, delete_user,
    get_all_tests, insert_email
)
from config import DEVELOPER_USERNAME, BASE_DIR, ROLES

logger = logging.getLogger(__name__)

############################
# Состояния
############################
ADMIN_MENU = 500
ADMIN_ASK_BROADCAST = 501

ADMIN_FILES_BROWSE = 600
ADMIN_FILES_UPLOAD = 601
ADMIN_FILES_UPLOAD_ASK_TEST = 602
ADMIN_FILES_UPLOAD_CHOOSE_TEST = 603

############################
# Утилиты
############################
def is_admin_or_dev(update: Update) -> bool:
    user = update.callback_query.from_user if update.callback_query else update.effective_user
    role = (get_role(user.id) or "").lower()
    dev_name = (user.username or "").lower()
    return (role in ("администратор", "помощник директора")) or (dev_name == DEVELOPER_USERNAME.lower())

def short_id(context: ContextTypes.DEFAULT_TYPE, name: str) -> str:
    """Генерируем короткий ID и храним «short → name» в user_data."""
    sid = ''.join(random.choices(string.ascii_letters+string.digits, k=8))
    context.user_data.setdefault("short_map", {})[sid] = name
    return sid

def restore_id(context: ContextTypes.DEFAULT_TYPE, sid: str) -> str|None:
    return context.user_data.get("short_map", {}).get(sid)

def get_top_role_folder(rel_path: str) -> str|None:
    """
    Возвращает имя роли, если «верхняя папка» из rel_path совпадает с одним из ROLES (без учёта регистра).
    Игнорирует начальные "./" или ".\".

    Пример:
      rel_path = "./Помощник директора/папка1"
      → вернёт "Помощник директора", если в ROLES есть "Помощник директора"
    """
    if not rel_path or rel_path == ".":
        return None

    # Удаляем ведущие "./" или ".\":
    if rel_path.startswith("./") or rel_path.startswith(".\\"):
        rel_path = rel_path[2:]  # отрезаем два символа

    # Нормализуем слэши
    rel_path = rel_path.replace("\\", "/").strip().lstrip("/")
    if not rel_path:
        return None

    # Первый сегмент
    parts = rel_path.split("/")
    top = parts[0].strip()

    # Сравниваем без учёта регистра и лишних пробелов
    top_lower = top.lower()

    for r in ROLES:  # ROLES из config.py
        if r.lower() == top_lower:
            return r

    return None

def notify_role_about_file(role: str, filename: str, test_id=None):
    """Создаём «непрочитанное» письмо для всех пользователей, у кого роль=role."""
    from db import get_all_users, insert_email
    allu = get_all_users()
    for (tid, nm, un, rl) in allu:
        if (rl or "").lower() == role.lower():
            subj = "Добавлен файл"
            body = f"В папку роли '{role}' загружен файл '{filename}'."
            if test_id:
                body += f"\nК нему прикреплён тест ID={test_id}."
            insert_email(tid, subj, body, None, test_id)

############################
# 1) Админ-панель
############################
async def return_to_main_menu_after_admin(query, context):
    from db import get_role
    from handlers.keyboards import get_admin_keyboard, get_user_keyboard
    user_id = query.from_user.id
    role = (get_role(user_id) or "").lower()
    dev_name = (query.from_user.username or "").lower()

    # проверяем, админ ли (или помощник директора, или dev)
    is_admin_or_pom = (role in ("администратор", "помощник директора") or dev_name == "zxcegorka4")

    if is_admin_or_pom:
        text = f"Админ-панель завершена. Возвращаемся в меню для роли: {role}"
        markup = get_admin_keyboard()
    else:
        text = f"Админ-панель завершена. Возвращаемся в меню для роли: {role}"
        markup = get_user_keyboard(role)

    try:
        await query.edit_message_text(text, reply_markup=markup)
    except:
        # Если редактировать не получилось, просто отправим новое сообщение
        await query.message.reply_text(text, reply_markup=markup)

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в админ-панель."""
    if not is_admin_or_dev(update):
        if update.message:
            await update.message.reply_text("🚫 Нет прав.")
        else:
            await update.callback_query.answer("🚫 Нет прав!", show_alert=True)
        return ConversationHandler.END
    return await show_admin_menu(update, context)

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = (get_role(update.effective_user.id) or "").lower()
    text = f"🔧 Админ-меню (Роль: {role}):"

    kb = []
    if role == "администратор":
        kb.append([InlineKeyboardButton("🔄 Перезапустить", callback_data="admin_restart")])
    kb.append([
        InlineKeyboardButton("📋 Список пользователей", callback_data="admin_users"),
        InlineKeyboardButton("💬 Рассылка", callback_data="admin_broadcast")
    ])
    kb.append([InlineKeyboardButton("🗂 Файлы", callback_data="admin_files")])
    kb.append([InlineKeyboardButton("🚪 Выход", callback_data="admin_exit")])
    markup = InlineKeyboardMarkup(kb)

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)

    return ADMIN_MENU

async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "admin_restart":
        await q.edit_message_text("Перезапуск...")
        await asyncio.sleep(0.3)
        python = os.path.abspath(sys.executable)
        os.execl(python, python, *sys.argv)
        return ConversationHandler.END

    elif data == "admin_users":
        return await show_users_list(update, context)

    elif data.startswith("reset_"):
        uid_str = data.split("_",1)[1]
        try:
            uid = int(uid_str)
            delete_user(uid)
            await q.message.reply_text(f"Пользователь {uid} сброшен.")
        except:
            await q.answer("Ошибка ID!", show_alert=True)
        return await show_users_list(update, context)

    elif data == "admin_broadcast":
        await q.edit_message_text("Введите текст рассылки:")
        return ADMIN_ASK_BROADCAST

    elif data == "admin_files":
        # Переход к файловому менеджеру
        await q.edit_message_text("Файловый менеджер, загрузка...")
        context.user_data["fm_chat_id"] = q.message.chat_id
        context.user_data["fm_message_id"] = q.message.message_id
        return await fm_browse(update, context, ".")

    elif data == "admin_exit":
        from .admin import return_to_main_menu_after_admin
        await return_to_main_menu_after_admin(q, context)
        return ConversationHandler.END


    else:
        await q.message.reply_text("Неизвестная команда.")
        return ADMIN_MENU

async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    from db import get_all_users
    us = get_all_users()
    text = "📋 Список пользователей:\n"
    kb = []
    for (tid, nm, un, rl) in us:
        text += f"{tid} | {nm} (@{un}) | {rl}\n"
        kb.append([InlineKeyboardButton(f"Сбросить {nm}", callback_data=f"reset_{tid}")])
    kb.append([InlineKeyboardButton("Назад", callback_data="admin_exit")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_MENU

async def admin_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    from db import get_all_users, insert_email
    for (tid, nm, un, rl) in get_all_users():
        try:
            insert_email(tid, "Рассылка", txt, None, None)
        except Exception as e:
            logger.warning(f"Ошибка рассылки {tid}: {e}")
    await update.message.reply_text("Рассылка выполнена!")
    return await admin_panel_command(update, context)

async def force_end_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Прервано.")
    else:
        await update.callback_query.answer("Прервано", show_alert=True)
    return ConversationHandler.END

############################
# 2) Файловый менеджер (одно сообщение)
############################

def get_main_fm_msg(context):
    return context.user_data.get("fm_chat_id"), context.user_data.get("fm_message_id")

async def fm_browse(update: Update, context: ContextTypes.DEFAULT_TYPE, rel_path: str):
    context.user_data["fm_curdir"] = rel_path
    bot = context.bot
    chat_id, msg_id = get_main_fm_msg(context)
    abs_path = os.path.join(BASE_DIR, rel_path)

    if not os.path.isdir(abs_path):
        kb = [[InlineKeyboardButton("Выйти", callback_data="fm_exit")]]
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=f"Папка /{rel_path} не найдена!",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return ADMIN_FILES_BROWSE

    items = sorted(os.listdir(abs_path))
    dirs, files = [], []

    for it in items:
        # 1) Пропускаем папку "pipa" (не добавляем её в списки)
        if it.lower() == "pipa":
            continue

        fp = os.path.join(abs_path, it)
        if os.path.isdir(fp):
            dirs.append(it)
        else:
            files.append(it)

    # дальше всё как у вас
    kb = []
    for d in dirs:
        sid = short_id(context, d)
        kb.append([
            InlineKeyboardButton(f"📁 {d}", callback_data=f"fm_goto|{sid}"),
            InlineKeyboardButton("🗑", callback_data=f"fm_rmdir|{sid}")
        ])
        
    for f in files:
        sf = short_id(context, f)
        kb.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"fm_file|{sf}")])

    row = [InlineKeyboardButton("Загрузить файл", callback_data="fm_upload")]
    if rel_path != ".":
        row.append(InlineKeyboardButton("🔼 Вверх", callback_data="fm_updir"))
    kb.append(row)
    kb.append([InlineKeyboardButton("Выйти", callback_data="fm_exit")])

    text = f"Папка: /{rel_path}"
    markup = InlineKeyboardMarkup(kb)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        reply_markup=markup
    )
    return ADMIN_FILES_BROWSE

async def fm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bot = context.bot
    await q.answer()
    data = q.data
    cur = context.user_data.get("fm_curdir", ".")

    if data == "fm_exit":
        # Возвращаемся в админ-меню
        return await show_admin_menu(update, context)

    elif data == "fm_updir":
        parent = os.path.dirname(cur) or "."
        return await fm_browse(update, context, parent)

    elif data.startswith("fm_goto|"):
        sid = data.split("|", 1)[1]
        folder_name = restore_id(context, sid)
        if folder_name:
            newp = os.path.join(cur, folder_name)
            return await fm_browse(update, context, newp)
        else:
            await q.message.reply_text("Ошибка папки!")
        return ADMIN_FILES_BROWSE

    elif data.startswith("fm_rmdir|"):
        sid = data.split("|", 1)[1]
        folder_name = restore_id(context, sid)
        if folder_name:
            fullp = os.path.join(BASE_DIR, cur, folder_name)
            try:
                shutil.rmtree(fullp)
            except Exception as e:
                logger.warning(f"Ошибка удаления папки {folder_name}: {e}")
        return await fm_browse(update, context, cur)

    elif data.startswith("fm_file|"):
        fid = data.split("|", 1)[1]
        fname = restore_id(context, fid)
        text = f"Файл: /{os.path.join(cur, fname)}"
        kb = [
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"fm_file_del|{fid}"),
             InlineKeyboardButton("Скачать", callback_data=f"fm_file_dl|{fid}")],
            [InlineKeyboardButton("Назад", callback_data="fm_back")]
        ]
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return ADMIN_FILES_BROWSE

    elif data.startswith("fm_file_del|"):
        fid = data.split("|", 1)[1]
        fname = restore_id(context, fid)
        if fname:
            fullf = os.path.join(BASE_DIR, cur, fname)
            try:
                os.remove(fullf)
            except Exception as e:
                logger.warning(f"Ошибка удаления файла {fullf}: {e}")
        return await fm_browse(update, context, cur)

    elif data.startswith("fm_file_dl|"):
        await q.answer("Скачивание не реализовано", show_alert=True)
        return ADMIN_FILES_BROWSE

    elif data == "fm_back":
        return await fm_browse(update, context, cur)

    elif data == "fm_upload":
        # Очищаем список «уже загруженных»
        context.user_data["fm_uploaded_list"] = []
    # Редактируем «главное» сообщение: покажем инструкцию загрузки
        await fm_update_upload_text(context, None, None)
        return ADMIN_FILES_UPLOAD


    else:
        await q.message.reply_text("Неизвестная команда ФМ.")
        return ADMIN_FILES_BROWSE

############################
# 3) Загрузка файлов: уведомление роли, прикрепление теста, и убрать меню
############################

async def fm_upload_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_in = (update.message.text or "").lower().strip()
    cur = context.user_data.get("fm_curdir", ".")

    # 1) Если пользователь ввёл «готово» => спрашиваем «Прикрепить тест?»
    if text_in in ["готово", "done"]:
        # Удаляем сообщение "готово"
        try:
            await update.message.delete()
        except:
            pass
        # Показываем кнопки «Да/Нет» в том же «главном» сообщении
        kb = [
            [InlineKeyboardButton("Да", callback_data="fm_attachtest_yes"),
             InlineKeyboardButton("Нет", callback_data="fm_attachtest_no")]
        ]
        await fm_update_upload_text(context, "Загрузка завершена. Прикрепить тест?", kb)
        return ADMIN_FILES_UPLOAD_ASK_TEST

    # 2) Иначе пользователь прислал файл (документ/фото/видео) или что-то другое
    doc = update.message.document
    photos = update.message.photo
    video = update.message.video  # <-- Добавлено для видео

    basep = os.path.join(BASE_DIR, cur)
    os.makedirs(basep, exist_ok=True)

    saved_name = None

    if doc:
        fobj = await context.bot.get_file(doc.file_id)
        fname = doc.file_name or f"doc_{doc.file_unique_id}"
        fullp = os.path.join(basep, fname)
        await fobj.download_to_drive(fullp)
        saved_name = fname

    elif photos:
        ph = photos[-1]
        fobj = await context.bot.get_file(ph.file_id)
        fname = f"photo_{ph.file_unique_id}.jpg"
        fullp = os.path.join(basep, fname)
        await fobj.download_to_drive(fullp)
        saved_name = fname

    elif video:
        fobj = await context.bot.get_file(video.file_id)
        fname = f"video_{video.file_unique_id}.mp4"
        fullp = os.path.join(basep, fname)
        await fobj.download_to_drive(fullp)
        saved_name = fname

    if saved_name:
        # Удаляем сообщение пользователя (с самим файлом)
        try:
            await update.message.delete()
        except:
            pass

        # Оповещаем роль (как было)
        role_top = get_top_role_folder(cur)
        if role_top:
            notify_role_about_file(role_top, saved_name, test_id=None)

        # Добавляем в user_data["fm_uploaded_list"]
        context.user_data.setdefault("fm_uploaded_list", [])
        context.user_data["fm_uploaded_list"].append(saved_name)

        # Редактируем главное сообщение, чтобы отразить «ещё один файл загружен»
        await fm_update_upload_text(context, None, None)
    else:
        # Если это не документ/фото/видео => говорим повторить
        await update.message.reply_text("Пришлите документ/фото/видео или «готово».")
    return ADMIN_FILES_UPLOAD


async def fm_update_upload_text(context: ContextTypes.DEFAULT_TYPE, override_text: str|None, override_kb):
    """
    Редактирует «главное» сообщение в чат/сообщении fm_chat_id/fm_message_id,
    чтобы пользователь видел все действия в одном сообщении.

    override_text — если передан, используем именно этот текст.
    override_kb   — если передана клавиатура, используем её.
                    Иначе ставим None (нет кнопок).
    """
    bot = context.bot
    fm_chat = context.user_data.get("fm_chat_id")
    fm_msg = context.user_data.get("fm_message_id")
    if not fm_chat or not fm_msg:
        return  # Не знаем, какое сообщение редактировать.

    if override_text is not None:
        # Если специально передан текст, используем его
        new_text = override_text
    else:
        # Иначе строим текст из списка уже загруженных файлов
        cur = context.user_data.get("fm_curdir", ".")
        uploaded_list = context.user_data.get("fm_uploaded_list", [])
        lines = [f"Загрузка файлов в /{cur}."]
        if uploaded_list:
            lines.append("Уже загружено:")
            for f in uploaded_list:
                lines.append(f" • {f}")
        else:
            lines.append("(пока ничего)")
        lines.append("Пришлите документ/фото/видео или введите «готово» для завершения.")
        new_text = "\n".join(lines)

    # Готовим клавиатуру
    if override_kb is not None:
        kb = override_kb
    else:
        kb = []

    from telegram import InlineKeyboardMarkup
    try:
        await bot.edit_message_text(
            chat_id=fm_chat,
            message_id=fm_msg,
            text=new_text,
            reply_markup=InlineKeyboardMarkup(kb) if kb else None
        )
    except:
        pass  # Если сообщение удалено или др. ошибка


async def fm_upload_asktest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "fm_attachtest_no":
        # Вместо удаления главного сообщения и ConversationHandler.END
        # просто показываем снова список файлов
        cur = context.user_data.get("fm_curdir", ".")
        # Если хотите, сбросьте список "fm_uploaded_list"
        context.user_data.pop("fm_uploaded_list", None)
        return await fm_browse(update, context, cur)

    else:
        # data == "fm_attachtest_yes"
        # Показать список тестов, как раньше
        tests = get_all_tests()
        kb = []
        if tests:
            for (tid, header, link, fg, rl, uid, attach_id) in tests:
                sid = short_id(context, str(tid))
                kb.append([InlineKeyboardButton(f"📝 {header}", callback_data=f"fm_testchoose:{sid}")])
        else:
            kb.append([InlineKeyboardButton("Нет тестов", callback_data="fm_testnone")])
        kb.append([InlineKeyboardButton("Отмена", callback_data="fm_attachtest_no")])
        await q.message.edit_text("Выберите тест:", reply_markup=InlineKeyboardMarkup(kb))
        return ADMIN_FILES_UPLOAD_CHOOSE_TEST


async def fm_upload_test_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    test_str = q.data.split(":",1)[1]
    real = restore_id(context, test_str)
    if real:
        test_id = int(real)
        lastf = context.user_data.get("last_uploaded_file","")
        cur = context.user_data.get("fm_curdir",".")
        role_top = get_top_role_folder(cur)
        if role_top:
            from db import get_all_users, insert_email
            for (tid, nm, un, rl) in get_all_users():
                if (rl or "").lower() == role_top.lower():
                    subj = f"Файл + Тест: {lastf}"  # или "Файл + Тест в Водитель: {lastf}"
                    body = (
                        f"К файлу '{lastf}' прикреплён тест (ID={test_id}).\n"
                    "Нажмите «Прочитано», чтобы увидеть ссылку на тест."
                    )
                    insert_email(tid, subj, body, None, test_id)
        await q.message.edit_text(f"Тест {test_id} прикреплён к '{lastf}'. Уведомление отправлено роли {role_top}.\n\nВозвращаемся в список...")
    
    # Вместо удаления главного сообщения — снова показываем список
    cur = context.user_data.get("fm_curdir", ".")
    context.user_data.pop("fm_uploaded_list", None)
    return await fm_browse(update, context, cur)


async def fm_upload_test_none(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_text("Нет тестов для прикрепления.\nВозвращаемся в список...")

    cur = context.user_data.get("fm_curdir", ".")
    context.user_data.pop("fm_uploaded_list", None)
    return await fm_browse(update, context, cur)


async def fm_upload_test_none(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Удаляем главное сообщение => меню пропадает
    fm_chat = context.user_data.get("fm_chat_id")
    fm_msg = context.user_data.get("fm_message_id")
    if fm_chat and fm_msg:
        try:
            await q.message.bot.delete_message(fm_chat, fm_msg)
        except:
            pass
    await q.message.reply_text("Операция завершена (нет тестов).")
    return ConversationHandler.END

############################
# ConversationHandler
############################
admin_conv = ConversationHandler(
    entry_points=[
        CommandHandler("admin", admin_panel_command),
        CallbackQueryHandler(admin_panel_command, pattern="^admin_panel$")
    ],
    states={
        # Админ-меню
        ADMIN_MENU: [
            CallbackQueryHandler(
                admin_menu_handler,
                pattern="^(admin_restart|admin_users|admin_broadcast|admin_files|admin_exit|reset_.*)$"
            )
        ],
        # Рассылка
        ADMIN_ASK_BROADCAST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_text)
        ],
        # ФМ
        ADMIN_FILES_BROWSE: [
            CallbackQueryHandler(
                fm_handler,
                pattern="^(fm_exit|fm_updir|fm_goto\\|.*|fm_rmdir\\|.*|fm_file\\|.*|fm_file_del\\|.*|fm_file_dl\\|.*|fm_back|fm_upload)$"
            )
        ],
        ADMIN_FILES_UPLOAD: [
            MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.TEXT, fm_upload_receive)

        ],
        ADMIN_FILES_UPLOAD_ASK_TEST: [
            CallbackQueryHandler(fm_upload_asktest_handler, pattern="^(fm_attachtest_yes|fm_attachtest_no)$")
        ],
        ADMIN_FILES_UPLOAD_CHOOSE_TEST: [
            CallbackQueryHandler(fm_upload_test_chosen, pattern="^fm_testchoose:"),
            CallbackQueryHandler(fm_upload_test_none, pattern="^fm_testnone$"),
            CallbackQueryHandler(fm_upload_asktest_handler, pattern="^fm_attachtest_no$")
        ]
    },
    fallbacks=[
        CommandHandler("start", force_end_admin),
        CommandHandler("admin", force_end_admin),
    ]
)
