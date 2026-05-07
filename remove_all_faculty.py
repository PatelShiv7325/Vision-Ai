#!/usr/bin/env python3
"""
Remove all faculty from Vision AI database
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import get_db, delete_faculty_completely

def main():
    print("Removing all faculty from Vision AI database...")
    
    try:
        success, message = clear_all_faculty()
        
        if success:
            print(f"Success: {message}")
            print("All faculty records and related data have been removed.")
            print("System will need to be re-initialized with at least one faculty account.")
        else:
            print(f"Error: {message}")
            
    except Exception as e:
        print(f"Critical Error: {e}")
        return 1
        
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
