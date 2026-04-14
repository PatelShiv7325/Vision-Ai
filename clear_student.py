import sqlite3

conn = sqlite3.connect('vision_ai.db')
conn.execute('DELETE FROM students')
conn.commit()
print("✅ All students deleted successfully!")

rows = conn.execute('SELECT * FROM students').fetchall()
print("Students remaining:", len(rows))
conn.close()