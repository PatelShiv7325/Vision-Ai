#!/usr/bin/env python3
"""
Student Data Management for SQLite Database
Run this script when the Flask application is NOT running
"""

import sqlite3
import os

def clear_all_student_data():
    """Clear all student data and related records"""
    db_path = os.path.join('database', 'db.sqlite3')
    
    try:
        # Connect to database directly
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute('PRAGMA busy_timeout = 30000')
        
        print("Connected to database, clearing student data...")
        
        # Delete all student-related data in proper order
        tables_to_clear = [
            'attendance',
            'face_attempts', 
            'notifications',
            'security_events',
            'audit_log',
            'students'
        ]
        
        for table in tables_to_clear:
            if table in ['notifications', 'security_events', 'audit_log']:
                conn.execute(f'DELETE FROM {table} WHERE user_type = ?', ('student',))
            else:
                conn.execute(f'DELETE FROM {table}')
            print(f"Cleared table: {table}")
        
        conn.commit()
        
        # Verify deletion
        count = conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        print(f"Successfully cleared all student data. {count} students remaining.")
        
        conn.close()
        return True, f"All student data cleared. {count} students remaining."
        
    except Exception as e:
        return False, f"Error clearing student data: {e}"

def delete_student_by_roll(roll_number):
    """Delete a specific student by roll number"""
    db_path = os.path.join('database', 'db.sqlite3')
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute('PRAGMA busy_timeout = 30000')
        
        print(f"Deleting student with roll: {roll_number}")
        
        # Delete student and all related data
        tables_to_check = [
            ('attendance', 'roll'),
            ('face_attempts', 'roll'),
            ('notifications', 'user_id'),
            ('security_events', 'user_id'),
            ('audit_log', 'user_id'),
            ('students', 'roll')
        ]
        
        for table, column in tables_to_check:
            if table in ['notifications', 'security_events', 'audit_log']:
                cursor = conn.execute(f'DELETE FROM {table} WHERE user_type = ? AND {column} = ?', ('student', roll_number))
            else:
                cursor = conn.execute(f'DELETE FROM {table} WHERE {column} = ?', (roll_number,))
            
            deleted_count = cursor.rowcount
            print(f"  Deleted {deleted_count} records from {table}")
        
        conn.commit()
        conn.close()
        
        print(f"Successfully deleted student {roll_number}")
        return True
        
    except Exception as e:
        print(f"Error deleting student {roll_number}: {e}")
        return False

def delete_student_by_email(email):
    """Delete a specific student by email"""
    db_path = os.path.join('database', 'db.sqlite3')
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute('PRAGMA busy_timeout = 30000')
        
        print(f"Deleting student with email: {email}")
        
        # First get the roll number
        cursor = conn.execute('SELECT roll FROM students WHERE email = ?', (email,))
        result = cursor.fetchone()
        
        if not result:
            print(f"No student found with email: {email}")
            conn.close()
            return False
        
        roll_number = result[0]
        conn.close()
        
        # Delete using roll number
        return delete_student_by_roll(roll_number)
        
    except Exception as e:
        print(f"Error deleting student by email {email}: {e}")
        return False

def list_all_students():
    """List all students in database"""
    db_path = os.path.join('database', 'db.sqlite3')
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.execute('SELECT roll, name, email, department FROM students')
        students = cursor.fetchall()
        conn.close()
        
        print("Current Students:")
        print("Roll\tName\t\tEmail\t\t\tDepartment")
        print("-" * 60)
        for student in students:
            print(f"{student[0]}\t{student[1][:15]}\t{student[2][:20]}\t{student[3]}")
        
        return students
        
    except Exception as e:
        print(f"Error listing students: {e}")
        return []

if __name__ == "__main__":
    print("SQLite Student Data Management")
    print("=" * 40)
    print("Make sure the Flask application is NOT running!")
    
    # List current students first
    list_all_students()
    
    print("\nOptions:")
    print("1. Delete student by roll number")
    print("2. Delete student by email")
    print("3. Delete ALL students")
    print("4. List all students")
    print("5. Exit")
    
    while True:
        choice = input("\nEnter choice (1-5): ").strip()
        
        if choice == "1":
            roll = input("Enter roll number: ").strip()
            delete_student_by_roll(roll)
        elif choice == "2":
            email = input("Enter email: ").strip()
            delete_student_by_email(email)
        elif choice == "3":
            confirm = input("Are you sure you want to delete ALL students? (yes/no): ").strip().lower()
            if confirm == "yes":
                success, message = clear_all_student_data()
                if success:
                    print(f"SUCCESS: {message}")
                else:
                    print(f"ERROR: {message}")
            else:
                print("Operation cancelled")
        elif choice == "4":
            list_all_students()
        elif choice == "5":
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")