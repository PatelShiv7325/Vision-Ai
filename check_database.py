#!/usr/bin/env python3
"""
Check Database Status - Vision AI
===============================
Check if database exists and show its contents
"""

import sqlite3
import os

def check_database():
    """Check database status and contents"""
    
    print("=" * 60)
    print("DATABASE STATUS CHECK - VISION AI")
    print("=" * 60)
    
    # Database file path
    db_path = os.path.join(os.path.dirname(__file__), "database", "db.sqlite3")
    
    print(f"Database file: {db_path}")
    print(f"File exists: {os.path.exists(db_path)}")
    
    if os.path.exists(db_path):
        file_size = os.path.getsize(db_path)
        print(f"File size: {file_size} bytes")
        
        try:
            # Connect to database
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            print(f"\nTables found: {tables}")
            
            # Check each table
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"\n{table.upper()}: {count} records")
                
                if count > 0:
                    cursor.execute(f"SELECT * FROM {table} LIMIT 3")
                    records = cursor.fetchall()
                    
                    # Get column names
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = [col[1] for col in cursor.fetchall()]
                    
                    print(f"Sample data:")
                    print(f"Columns: {columns}")
                    for record in records:
                        print(f"  {record}")
            
            conn.close()
            print(f"\nDatabase Status: WORKING")
            
        except Exception as e:
            print(f"Database Error: {e}")
            print("Database Status: CORRUPTED or INACCESSIBLE")
    else:
        print("Database Status: NOT FOUND")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    check_database()
