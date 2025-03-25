import os

# --- Роли ---
NON_ADMIN_ROLES = [
    "Директор", "Помощник директора", "Бухгалтер", "Снабжение",
    "Начальник производства", "Водитель", "Маркетолог", "Менеджер",
    "Кладовщик", "Сотрудник производства", "Оператор", "Монтажник", "Разнорабочий"
]
ROLES = NON_ADMIN_ROLES + ["Администратор"]

# --- Пароли для ролей ---
ROLE_PASSWORDS = {
    "Директор": "7351",
    "Помощник директора": "1482",
    "Бухгалтер": "9623",
    "Снабжение": "8574",
    "Начальник производства": "3147",
    "Водитель": "2069",
    "Маркетолог": "5408",
    "Менеджер": "6381",
    "Кладовщик": "9074",
    "Сотрудник производства": "8520",
    "Оператор": "4369",
    "Монтажник": "5792",
    "Разнорабочий": "3208",
    "Администратор": "0000"
}

# Имя (username) разработчика, которому можно давать повышенные права
DEVELOPER_USERNAME = "zxcegorka4"

# Пути к папкам
BASE_DIR = os.getenv("BASE_DIR", r"C:\Users\semen\telegram_bot")
OBSHAYA_DIR = os.path.join(BASE_DIR, "Общая")

# Создаём базовые директории, если не существуют
def setup_directories():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(OBSHAYA_DIR, exist_ok=True)
    os.makedirs(os.path.join(OBSHAYA_DIR, "Личное"), exist_ok=True)
    for role in ROLES:
        role_dir = os.path.join(BASE_DIR, role)
        os.makedirs(role_dir, exist_ok=True)

# Токен бота (замените на ваш реальный токен)
BOT_TOKEN = "7916884832:AAE78BtNCoiYYhdNAb21vcgLHJTgXo1ggnM"
