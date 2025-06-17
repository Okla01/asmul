from .database import conn, create_admin_registration_table

def init_db():
    """Инициализирует базу данных, создавая необходимые таблицы."""
    # Создаём таблицу для заявок на регистрацию администраторов
    create_admin_registration_table()
    
    # Здесь можно добавить создание других таблиц, если потребуется
    
    conn.commit()
