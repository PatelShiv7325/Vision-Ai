#!/usr/bin/env python3
"""
Vision AI Attendance System - Startup Script
============================================
This script handles the complete startup of the Vision AI attendance system.
"""

import os
import sys
from database import init_db

def check_dependencies():
    """Check if required packages are installed"""
    required_packages = ['flask', 'opencv-contrib-python', 'numpy', 'Pillow']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("Missing required packages:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\nInstall them using:")
        print("pip install -r requirements.txt")
        return False
    
    return True

def initialize_database():
    """Initialize the database if needed"""
    try:
        print("Initializing database...")
        init_db()
        print("Database initialized successfully!")
        return True
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return False

def create_directories():
    """Create necessary directories"""
    directories = ['static', 'static/faces', 'templates']
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")

def main():
    """Main startup function"""
    print("=" * 50)
    print("Vision AI Attendance System")
    print("=" * 50)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Create directories
    create_directories()
    
    # Initialize database
    if not initialize_database():
        sys.exit(1)
    
    # Start Flask app
    print("\nStarting Flask application...")
    print("Access the application at: http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    print("-" * 50)
    
    try:
        from app import app
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Failed to start application: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
