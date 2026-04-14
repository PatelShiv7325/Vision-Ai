import sqlite3

DB_PATH = 'vision_ai.db'


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    conn.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL,
        roll       TEXT    UNIQUE NOT NULL,
        phone      TEXT    UNIQUE,
        email      TEXT    UNIQUE NOT NULL,
        password   TEXT    NOT NULL,
        face_image TEXT    UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS faculty (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL,
        faculty_id TEXT    UNIQUE NOT NULL,
        department TEXT    NOT NULL,
        email      TEXT    UNIQUE NOT NULL,
        password   TEXT    NOT NULL
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        student_roll TEXT    NOT NULL,
        student_name TEXT    NOT NULL,
        subject      TEXT    NOT NULL,
        date         TEXT    NOT NULL,
        time         TEXT    NOT NULL,
        marked_by    TEXT    NOT NULL
    )
    ''')

    conn.commit()
    conn.close()