import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS students (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        roll       TEXT NOT NULL UNIQUE,
        phone      TEXT,
        email      TEXT NOT NULL UNIQUE,
        password   TEXT NOT NULL,
        face_image TEXT,
        standard   TEXT,
        division   TEXT,
        gender     TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS faculty (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        faculty_id TEXT NOT NULL UNIQUE,
        department TEXT NOT NULL,
        email      TEXT NOT NULL UNIQUE,
        password   TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        student_roll TEXT NOT NULL,
        student_name TEXT NOT NULL,
        subject      TEXT NOT NULL,
        date         TEXT NOT NULL,
        time         TEXT NOT NULL,
        marked_by    TEXT NOT NULL,
        created_at   TEXT DEFAULT (datetime('now'))
    )""")
    db.commit()
    db.close()