EMAIL_CONFIG = {
    'sender_email': 'shivay0735@gmail.com',
    'sender_name':  'Vision AI System',
    'brevo_api_key': 'PASTE_YOUR_BREVO_API_KEY_HERE',
}

def is_email_configured():
    key = EMAIL_CONFIG.get('brevo_api_key', '')
    bad = ('', 'PASTE_YOUR_BREVO_API_KEY_HERE')
    return bool(key and key not in bad)