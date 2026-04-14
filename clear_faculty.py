import sqlite3

conn = sqlite3.connect('vision_ai.db')
conn.execute('DELETE FROM faculty')
conn.commit()
print("✅ All faculty deleted successfully!")

rows = conn.execute('SELECT * FROM faculty').fetchall()
print("Faculty remaining:", len(rows))
conn.close()