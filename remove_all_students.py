#!/usr/bin/env python3
"""
Remove all students from Vision AI database
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import get_db, clear_all_students

def main():
    print("Removing all students from Vision AI database...")
    
    try:
        success, message = clear_all_students()
        
        if success:
            print(f"Success: {message}")
            print("All student records, attendance, and related data have been removed.")
            print("Face images will also be deleted from static/faces/ directory.")
        else:
            print(f"Error: {message}")
            
    except Exception as e:
        print(f"Critical Error: {e}")
        return 1
        
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
