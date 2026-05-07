from email_config import EMAIL_CONFIG, is_email_configured 
import smtplib 
print('Configured:', is_email_configured()) 
print('Email:', EMAIL_CONFIG['sender_email']) 
print('Password:', EMAIL_CONFIG['sender_password']) 
s = smtplib.SMTP('smtp.gmail.com', 587, timeout=15) 
s.starttls() 
s.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password']) 
print('LOGIN SUCCESS') 
