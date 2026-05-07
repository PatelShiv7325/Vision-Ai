import sqlite3
import os

db_path = 'database/db.sqlite3'

try:
    # Remove WAL files first
    if os.path.exists(db_path + '-shm'):
        os.remove(db_path + '-shm')
    if os.path.exists(db_path + '-wal'):
        os.remove(db_path + '-wal')
    
    # Connect to database
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    
    # Clear all tables
    cursor.execute('DELETE FROM students')
    cursor.execute('DELETE FROM faculty')
    cursor.execute('DELETE FROM attendance')
    cursor.execute('DELETE FROM face_attempts')
    cursor.execute('DELETE FROM notifications')
    cursor.execute('DELETE FROM emotion_tracking')
    cursor.execute('DELETE FROM batch_attendance')
    
    conn.commit()
    conn.close()
    
    print("Database cleared successfully!")
except Exception as e:
    print(f"Error: {e}")
