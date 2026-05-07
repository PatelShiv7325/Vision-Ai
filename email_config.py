import os

EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'shivay0735@gmail.com',
    'sender_password': 'qhxzjtqvthhzztlv',
    'sender_name': 'Vision AI System'
}

def is_email_configured():
    pwd = EMAIL_CONFIG['sender_password']
    email = EMAIL_CONFIG['sender_email']
    bad = ('', 'your-app-password', 'SET_YOUR_GMAIL_APP_PASSWORD_HERE')
    return bool(email and pwd and pwd not in bad)