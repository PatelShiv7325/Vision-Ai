#!/usr/bin/env python3
"""
Auto Database Fix - Vision AI
============================
Automatically fixes corrupted database without user input
"""

import sqlite3
import os
import time

def auto_fix_database():
    """Auto fix corrupted database"""
    
    print("=" * 60)
    print("AUTO DATABASE FIX - VISION AI")
    print("=" * 60)
    
    # Database file path
    db_path = os.path.join(os.path.dirname(__file__), "database", "db.sqlite3")
    
    print(f"Database file: {db_path}")
    print(f"File exists: {os.path.exists(db_path)}")
    
    # Step 1: Force delete the corrupted file
    print("\nStep 1: Removing corrupted database file...")
    
    if os.path.exists(db_path):
        try:
            # Try multiple methods to delete
            for i in range(5):
                try:
                    os.remove(db_path)
                    print(f"  Database file deleted successfully!")
                    break
                except PermissionError:
                    print(f"  Attempt {i+1}: File locked, waiting...")
                    time.sleep(1)
            else:
                print("  ERROR: Could not delete database file!")
                return False
        except Exception as e:
            print(f"  ERROR: {e}")
            return False
    else:
        print("  Database file doesn't exist (good!)")
    
    # Step 2: Create new database manually
    print("\nStep 2: Creating new database...")
    
    try:
        # Create new database file
        conn = sqlite3.connect(db_path)
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
    
    # Step 3: Verify database
    print("\nStep 3: Verifying new database...")
    
    try:
        conn = sqlite3.connect(db_path)
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
    print("AUTO FIX COMPLETED SUCCESSFULLY!")
    print("Your database is now fresh and ready to use.")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    print("Auto-fixing database corruption...")
    if auto_fix_database():
        print("\nFix completed! You can now run your application.")
        print("Run: python app.py")
    else:
        print("\nFix failed. Please check file permissions.")
