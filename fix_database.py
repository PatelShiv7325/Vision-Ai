#!/usr/bin/env python3
"""
Database Fix Tool - Vision AI
============================
Fixes corrupted database by recreating it completely
"""

import sqlite3
import os
import shutil
from datetime import datetime

def fix_database():
    """Fix corrupted database by recreating it"""
    
    print("=" * 60)
    print("DATABASE FIX TOOL - VISION AI")
    print("=" * 60)
    
    # Database file path
    db_path = os.path.join(os.path.dirname(__file__), "database", "db.sqlite3")
    
    print(f"Database file: {db_path}")
    print(f"File exists: {os.path.exists(db_path)}")
    
    if os.path.exists(db_path):
        file_size = os.path.getsize(db_path)
        print(f"Current database size: {file_size} bytes")
        
        # Try to create backup first
        try:
            backup_path = os.path.join(os.path.dirname(__file__), "database", f"corrupted_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_db.sqlite3")
            shutil.copy2(db_path, backup_path)
            print(f"Corrupted database backed up to: {backup_path}")
        except Exception as e:
            print(f"Could not backup corrupted file: {e}")
    
    print("\nThis will completely recreate the database.")
    print("All existing data will be lost!")
    print("Type 'FIX' to continue:")
    
    confirmation = input("Confirm: ").strip()
    if confirmation != "FIX":
        print("Operation cancelled.")
        return
    
    try:
        # Force close any connections and delete the file
        for _ in range(3):
            try:
                if os.path.exists(db_path):
                    os.remove(db_path)
                    print("Database file deleted successfully.")
                    break
            except PermissionError:
                print("Database file is locked. Waiting...")
                import time
                time.sleep(1)
        
        # Recreate database with proper schema
        from database.db import init_db
        init_db()
        
        print("New database created successfully!")
        
        # Verify the database works
        from database.db import get_db
        db = get_db()
        
        # Test basic operations
        db.execute("SELECT COUNT(*) FROM students")
        db.execute("SELECT COUNT(*) FROM faculty") 
        db.execute("SELECT COUNT(*) FROM attendance")
        
        student_count = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        faculty_count = db.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
        attendance_count = db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        
        print(f"\nDatabase verification:")
        print(f"Students: {student_count}")
        print(f"Faculty: {faculty_count}")
        print(f"Attendance: {attendance_count}")
        
        db.close()
        
        print("\nDatabase is now fixed and ready to use!")
        print("You can now run: python app.py")
        
    except Exception as e:
        print(f"Error fixing database: {e}")
        print("Please try closing any applications that might be using the database.")

if __name__ == "__main__":
    fix_database()
