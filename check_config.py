import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from email_config import EMAIL_CONFIG, is_email_configured

print('Current EMAIL_CONFIG:')
for key, value in EMAIL_CONFIG.items():
    if 'password' in key.lower():
        print(f'{key}: {"SET" if value else "NOT SET"}')
    else:
        print(f'{key}: {value}')
print(f'Email configured: {is_email_configured()}')
