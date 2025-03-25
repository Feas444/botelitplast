# handlers/keyboards.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Общие файлы", callback_data="files_obshaya"),
            InlineKeyboardButton("📁 Файлы работы", callback_data="files_role")
        ],
        [
            InlineKeyboardButton("🔍 Поиск файлов", callback_data="search_files"),
            InlineKeyboardButton("💬 Сообщения", callback_data="mail_main")
        ],
        [
            InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_panel")
        ]
    ])

def get_user_keyboard(role: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Общие файлы", callback_data="files_obshaya"),
            InlineKeyboardButton("📁 Файлы работы", callback_data="files_role")
        ],
        [
            InlineKeyboardButton("🔍 Поиск файлов", callback_data="search_files"),
            InlineKeyboardButton("💬 Сообщения", callback_data="mail_main")
        ]
    ])
