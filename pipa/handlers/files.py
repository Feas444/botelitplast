import os
import logging
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import BASE_DIR
from db import get_role
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

def get_short_id(context, rel_path: str) -> str:
    """Генерирует короткий ID и сохраняет путь rel_path в context.user_data["path_map"][short_id]."""
    if "path_map" not in context.user_data:
        context.user_data["path_map"] = {}
    short_id = uuid.uuid4().hex[:8]
    context.user_data["path_map"][short_id] = rel_path
    return short_id

async def safe_edit_menu(query, text: str, markup=None):
    """
    Безопасно редактирует текущее сообщение или отправляет новое,
    чтобы избежать ошибки "Message is not modified".
    """
    try:
        await query.edit_message_text(text=text, reply_markup=markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        # Если не удалось отредактировать, пытаемся удалить и отправить новое сообщение
        try:
            await query.message.delete()
        except Exception:
            pass
        if markup:
            await query.message.chat.send_message(text, reply_markup=markup)
        else:
            await query.message.chat.send_message(text)

async def browse_directory(query, context: ContextTypes.DEFAULT_TYPE,
                           rel_path: str, is_admin: bool, allowed_root: str):
    """
    Открывает содержимое директории (BASE_DIR/rel_path):
      - Показывает папки и файлы, генерируя кнопки с короткими ID.
      - Если rel_path != allowed_root, добавляет кнопку "🔙 Назад", иначе "🚪 В главное меню".
      - Сохраняет текущую директорию в context.user_data["current_dir"].
    """
    full_path = os.path.join(BASE_DIR, rel_path)
    if not os.path.isdir(full_path):
        await safe_edit_menu(query, f"❌ Директория /{rel_path} не найдена!")
        return

    context.user_data["current_dir"] = rel_path

    try:
        items = sorted(os.listdir(full_path))
    except Exception as e:
        logger.error(f"Ошибка при чтении директории {full_path}: {e}")
        await safe_edit_menu(query, f"❌ Ошибка при чтении /{rel_path}.")
        return

    dirs = []
    files = []
    for item in items:
        item_full = os.path.join(full_path, item)
        if os.path.isdir(item_full):
            dirs.append(item)
        elif os.path.isfile(item_full):
            files.append(item)

    keyboard = []
    # Кнопки для папок
    for d in dirs:
        new_rel = os.path.join(rel_path, d)
        short_id = get_short_id(context, new_rel)
        keyboard.append([InlineKeyboardButton(f"📁 {d}", callback_data=f"dir|{short_id}")])
    # Кнопки для файлов
    for f in files:
        file_rel = os.path.join(rel_path, f)
        short_id = get_short_id(context, file_rel)
        keyboard.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"file|{short_id}")])

    if not dirs and not files:
        text = f"📂 Папка /{rel_path} пуста."
    else:
        text = f"📁 Папка: /{rel_path}"

    # Кнопка назад или в меню
    if rel_path != allowed_root:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="files_back")])
    else:
        keyboard.append([InlineKeyboardButton("🚪 В главное меню", callback_data="main_menu")])

    await safe_edit_menu(query, text, InlineKeyboardMarkup(keyboard))

async def directory_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие на папку: callback_data формата "dir|<short_id>"."""
    query = update.callback_query
    await query.answer()
    try:
        _, short_id = query.data.split("|", 1)
    except ValueError:
        await query.answer("❌ Некорректные данные для открытия папки!", show_alert=True)
        return
    path_map = context.user_data.get("path_map", {})
    new_rel = path_map.get(short_id)
    if not new_rel:
        await query.answer("❌ Путь не найден.", show_alert=True)
        return
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    is_admin = (role.lower() == "администратор")
    allowed_root = "Администратор" if is_admin else role
    await browse_directory(query, context, new_rel, is_admin, allowed_root)

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие на файл: callback_data "file|<short_id>". Отправляет файл и остаётся в той же директории."""
    query = update.callback_query
    await query.answer()
    try:
        _, short_id = query.data.split("|", 1)
    except ValueError:
        await query.answer("❌ Некорректные данные для файла!", show_alert=True)
        return
    path_map = context.user_data.get("path_map", {})
    file_rel = path_map.get(short_id)
    if not file_rel:
        await query.answer("❌ Путь к файлу не найден.", show_alert=True)
        return
    full_path = os.path.join(BASE_DIR, file_rel)
    if not os.path.isfile(full_path):
        await query.answer("❌ Файл не найден!", show_alert=True)
        return
    # Отправляем файл пользователю
    try:
        with open(full_path, "rb") as f:
            await context.bot.send_document(chat_id=query.message.chat_id, document=f, filename=os.path.basename(full_path))
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {full_path}: {e}")
        await query.answer("❌ Ошибка при отправке файла!", show_alert=True)
        return
    # После отправки файла обновляем список директории (остаёмся в той же папке)
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    is_admin = (role.lower() == "администратор")
    allowed_root = "Администратор" if is_admin else role
    parent_dir = os.path.dirname(file_rel)
    await browse_directory(query, context, parent_dir or allowed_root, is_admin, allowed_root)

async def files_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажатие кнопки «🔙 Назад»: подняться на уровень выше. Если уже в корне, показать меню."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    is_admin = (role.lower() == "администратор")
    allowed_root = "Администратор" if is_admin else role
    current_dir = context.user_data.get("current_dir", "")
    if not current_dir or current_dir == allowed_root:
        # Уже на верхнем уровне – выйти в главное меню
        await safe_edit_menu(
            query,
            "🚪 Вы уже в корневой директории.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🚪 В главное меню", callback_data="main_menu")]])
        )
        return
    # Поднимаемся вверх по пути
    parent_dir = os.path.dirname(current_dir)
    if not parent_dir:
        parent_dir = allowed_root
    await browse_directory(query, context, parent_dir, is_admin, allowed_root)

# -------------------- ДОПОЛНИТЕЛЬНЫЕ ХЕНДЛЕРЫ (Открытие разделов) --------------------

async def handle_files_obshaya(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает корневую папку «Общая» (общие файлы)."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    is_admin = (role.lower() == "администратор")
    allowed_root = "Общая"
    rel_path = "Общая"
    await browse_directory(query, context, rel_path, is_admin, allowed_root)

async def handle_files_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает папку по роли пользователя («Файлы работы»), для админа – папка 'Администратор'."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = get_role(user_id) or ""
    is_admin = (role.lower() == "администратор")
    if is_admin:
        start_path = "Администратор"
        allowed_root = "Администратор"
    else:
        if not role:
            await query.message.reply_text("У вас не задана роль, нет доступных файлов.")
            return
        start_path = role
        allowed_root = role
    await browse_directory(query, context, start_path, is_admin, allowed_root)
