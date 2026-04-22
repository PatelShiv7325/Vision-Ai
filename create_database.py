#!/usr/bin/env python3
"""
Create Database - Vision AI
==========================
Creates fresh database and restores sample data
"""

import sqlite3
import os
from datetime import datetime

def create_fresh_database():
    """Create fresh database with sample data"""
    
    print("=" * 60)
    print("CREATE FRESH DATABASE - VISION AI")
    print("=" * 60)
    
    # Database file path
    db_path = os.path.join(os.path.dirname(__file__), "database", "db.sqlite3")
    
    print(f"Creating database at: {db_path}")
    
    # Remove old database if exists
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print("Old database removed.")
        except Exception as e:
            print(f"Could not remove old database: {e}")
    
    # Create new database
    print("\nCreating new database...")
    
    try:
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
        print("Database tables created successfully!")
        
        # Add sample data
        print("\nAdding sample data...")
        
        # Sample students
        sample_students = [
            ("John Doe", "CS21001", "9876543210", "john@example.com", "password123", None),
            ("Jane Smith", "CS21002", "9876543211", "jane@example.com", "password123", None),
            ("Mike Johnson", "CS21003", "9876543212", "mike@example.com", "password123", None)
        ]
        
        cursor.executemany("""
            INSERT INTO students (name, roll, phone, email, password, face_image)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sample_students)
        
        # Sample faculty
        sample_faculty = [
            ("Dr. Smith", "FAC001", "Computer Science", "smith@university.edu", "password123"),
            ("Dr. Johnson", "FAC002", "Information Technology", "johnson@university.edu", "password123")
        ]
        
        cursor.executemany("""
            INSERT INTO faculty (name, faculty_id, department, email, password)
            VALUES (?, ?, ?, ?, ?)
        """, sample_faculty)
        
        # Sample attendance
        sample_attendance = [
            ("CS21001", "John Doe", "Database Systems", "2024-04-20", "10:30:00", "FAC001"),
            ("CS21002", "Jane Smith", "Web Development", "2024-04-20", "11:30:00", "FAC001"),
            ("CS21003", "Mike Johnson", "Data Structures", "2024-04-20", "14:30:00", "FAC002")
        ]
        
        cursor.executemany("""
            INSERT INTO attendance (student_roll, student_name, subject, date, time, marked_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sample_attendance)
        
        conn.commit()
        conn.close()
        
        print("Sample data added successfully!")
        
        # Verify database
        print("\nVerifying database...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        student_count = cursor.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        faculty_count = cursor.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
        attendance_count = cursor.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        
        conn.close()
        
        print(f"Students: {student_count}")
        print(f"Faculty: {faculty_count}")
        print(f"Attendance: {attendance_count}")
        
        print("\n" + "=" * 60)
        print("DATABASE CREATION COMPLETED!")
        print("Your database is ready with sample data.")
        print("You can now run: python app.py")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"Error creating database: {e}")
        return False

if __name__ == "__main__":
    print("Creating fresh database with sample data...")
    if create_fresh_database():
        print("\nDatabase created successfully!")
    else:
        print("\nDatabase creation failed!")
