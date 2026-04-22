#!/usr/bin/env python3
"""
Force Rebuild Database - Vision AI
=================================
Force complete database rebuild with new filename
"""

import sqlite3
import os
import shutil
from datetime import datetime

def force_rebuild():
    """Force rebuild database with new filename"""
    
    print("=" * 60)
    print("FORCE REBUILD DATABASE - VISION AI")
    print("=" * 60)
    
    # Database paths
    old_db_path = os.path.join(os.path.dirname(__file__), "database", "db.sqlite3")
    new_db_path = os.path.join(os.path.dirname(__file__), "database", "db_new.sqlite3")
    
    print(f"Old database: {old_db_path}")
    print(f"New database: {new_db_path}")
    
    # Step 1: Backup old database if it exists
    if os.path.exists(old_db_path):
        try:
            backup_path = os.path.join(os.path.dirname(__file__), "database", f"corrupted_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_db.sqlite3")
            shutil.copy2(old_db_path, backup_path)
            print(f"Old database backed up to: {backup_path}")
        except Exception as e:
            print(f"Could not backup old database: {e}")
    
    # Step 2: Create new database with different name
    print("\nStep 2: Creating new database...")
    
    try:
        # Create new database file
        conn = sqlite3.connect(new_db_path)
        cursor = conn.cursor()
        
        # Create students table
        cursor.execute("""
            CREATE TABLE students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                roll TEXT NOT NULL UNIQUE,
                phone TEXT,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                face_image TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # Create faculty table
        cursor.execute("""
            CREATE TABLE faculty (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                faculty_id TEXT NOT NULL UNIQUE,
                department TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # Create attendance table
        cursor.execute("""
            CREATE TABLE attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_roll TEXT NOT NULL,
                student_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                marked_by TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        conn.commit()
        conn.close()
        
        print("  New database created successfully!")
        
    except Exception as e:
        print(f"  ERROR creating database: {e}")
        return False
    
    # Step 3: Update database path in db.py
    print("\nStep 3: Updating database configuration...")
    
    try:
        # Read current db.py
        db_py_path = os.path.join(os.path.dirname(__file__), "database", "db.py")
        with open(db_py_path, 'r') as f:
            content = f.read()
        
        # Update DB_PATH to use new database
        new_content = content.replace(
            'DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3")',
            'DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_new.sqlite3")'
        )
        
        # Write updated content
        with open(db_py_path, 'w') as f:
            f.write(new_content)
        
        print("  Database configuration updated!")
        
    except Exception as e:
        print(f"  ERROR updating configuration: {e}")
        return False
    
    # Step 4: Verify new database
    print("\nStep 4: Verifying new database...")
    
    try:
        conn = sqlite3.connect(new_db_path)
        cursor = conn.cursor()
        
        # Test all tables
        cursor.execute("SELECT COUNT(*) FROM students")
        student_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM faculty")
        faculty_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM attendance")
        attendance_count = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"  Students: {student_count}")
        print(f"  Faculty: {faculty_count}")
        print(f"  Attendance: {attendance_count}")
        print("  Database verification: PASSED!")
        
    except Exception as e:
        print(f"  ERROR verifying database: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("FORCE REBUILD COMPLETED SUCCESSFULLY!")
    print("Your database has been rebuilt with a new filename.")
    print("You can now run your application.")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    print("Force rebuilding database...")
    if force_rebuild():
        print("\nRebuild completed! You can now run your application.")
        print("Run: python app.py")
    else:
        print("\nRebuild failed. Please check file permissions.")
