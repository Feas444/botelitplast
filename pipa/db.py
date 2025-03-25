# db.py

import os
import sqlite3
from datetime import datetime
from config import BASE_DIR

DB_PATH = os.path.join(BASE_DIR, 'users.db')
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ------------------ Создаём таблицы (если не существуют) ------------------
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    name TEXT,
    role TEXT,
    username TEXT
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient INTEGER,
    subject TEXT,
    body TEXT,
    status TEXT,
    attachment_file_id TEXT,
    test_id INTEGER
)
''')
conn.commit()

try:
    cursor.execute("ALTER TABLE emails ADD COLUMN test_id INTEGER")
except sqlite3.OperationalError:
    pass
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    header TEXT,
    test_link TEXT,
    for_group INTEGER,
    role TEXT,
    user_id INTEGER,
    attachment_file_id TEXT
)
''')
conn.commit()

try:
    cursor.execute("ALTER TABLE tests ADD COLUMN attachment_file_id TEXT")
except sqlite3.OperationalError:
    pass
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS tests_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    username TEXT,
    score INTEGER,
    total INTEGER,
    date TEXT
)
''')
conn.commit()

# ------------------ Функции для работы с таблицей users ------------------
def get_user_by_id(user_id: int):
    """
    Возвращает кортеж (telegram_id, name, role, username) или None,
    если пользователя нет в БД.
    """
    cursor.execute("SELECT telegram_id, name, role, username FROM users WHERE telegram_id=?", (user_id,))
    return cursor.fetchone()

def get_all_users():
    """
    Возвращает список (telegram_id, name, username, role) для всех пользователей.
    """
    cursor.execute("SELECT telegram_id, name, username, role FROM users")
    return cursor.fetchall()

def create_user(user_id: int, name: str, username: str, role: str):
    """
    Создаёт (или обновляет) пользователя в таблице users.
    """
    cursor.execute("""
        INSERT OR REPLACE INTO users (telegram_id, name, username, role)
        VALUES (?,?,?,?)
    """, (user_id, name, username, role))
    conn.commit()

def update_user_role(user_id: int, role: str):
    cursor.execute("UPDATE users SET role=? WHERE telegram_id=?", (role, user_id))
    conn.commit()

def delete_user(user_id: int):
    """
    Удаляет запись о пользователе (user_id) из таблицы users.
    """
    cursor.execute("DELETE FROM users WHERE telegram_id=?", (user_id,))
    conn.commit()

def get_role(user_id: int) -> str:
    """
    Возвращает строку role или пустую строку, если пользователя нет.
    """
    cursor.execute("SELECT role FROM users WHERE telegram_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else ""

def get_developer_id(dev_username: str):
    """
    Возвращает telegram_id разработчика по его username,
    или None, если не найден.
    """
    cursor.execute("SELECT telegram_id FROM users WHERE lower(username)=?", (dev_username.lower(),))
    row = cursor.fetchone()
    return row[0] if row else None

# ------------------ Функции для таблицы emails ------------------
def insert_email(recipient, subject, body, attachment, test_id=None):
    cursor.execute("""
        INSERT INTO emails (recipient, subject, body, status, attachment_file_id, test_id)
        VALUES (?, ?, ?, 'unread', ?, ?)
    """, (recipient, subject, body, attachment, test_id))
    conn.commit()

def get_unread_emails(user_id: int):
    cursor.execute("""
        SELECT id, subject, body, attachment_file_id, test_id
        FROM emails
        WHERE recipient=? AND status='unread'
    """, (user_id,))
    return cursor.fetchall()

def get_read_emails(user_id: int):
    cursor.execute("""
        SELECT id, subject, body, attachment_file_id, test_id
        FROM emails
        WHERE recipient=? AND status='read'
    """, (user_id,))
    return cursor.fetchall()

def mark_email_read(mail_id: int):
    cursor.execute("UPDATE emails SET status='read' WHERE id=?", (mail_id,))
    conn.commit()

def get_all_emails():
    cursor.execute("""
        SELECT id, recipient, subject, body, status, attachment_file_id, test_id
        FROM emails
    """)
    return cursor.fetchall()

def delete_email(mail_id: int):
    cursor.execute("DELETE FROM emails WHERE id=?", (mail_id,))
    conn.commit()

# ------------------ Функции для таблицы tests ------------------
def insert_test(header: str, test_link: str, for_group: bool, role=None, user_id=None, attachment_file_id=None):
    fg = 1 if for_group else 0
    cursor.execute("""
        INSERT INTO tests (header, test_link, for_group, role, user_id, attachment_file_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (header, test_link, fg, role, user_id, attachment_file_id))
    conn.commit()

def get_all_tests():
    cursor.execute("""
        SELECT id, header, test_link, for_group, role, user_id, attachment_file_id
        FROM tests
    """)
    return cursor.fetchall()

def save_test_result(user_id: int, username: str, score: int, total: int):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO tests_results (telegram_id, username, score, total, date)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, score, total, date_str))
    conn.commit()

def get_all_test_results():
    cursor.execute("""
        SELECT telegram_id, username, score, total, date
        FROM tests_results
        ORDER BY id DESC
    """)
    return cursor.fetchall()
