# Email Setup Guide for Vision AI

## Current Status
✅ **OTP functionality is now fixed and working**
- Database queries corrected
- OTP verification logic fixed
- Error handling improved
- Email configuration enhanced

## Configure Email for OTP Sending

### Option 1: Gmail (Recommended)

1. **Enable 2-Factor Authentication**
   - Go to your Google Account settings
   - Security → 2-Step Verification → Enable

2. **Generate App Password**
   - Go to Google Account settings
   - Security → App passwords
   - Select "Mail" for app and "Other (Custom name)" for device
   - Enter "Vision AI" as the name
   - Copy the 16-character password

3. **Set Environment Variables**
   ```powershell
   $env:EMAIL_USERNAME = "your-email@gmail.com"
   $env:EMAIL_PASSWORD = "your-16-character-app-password"
   ```

4. **Test Configuration**
   ```powershell
   cd d:\vision_ai
   python test_email_config.py
   ```

### Option 2: Other SMTP Providers

Update `email_config.py` with your SMTP settings:

```python
EMAIL_CONFIG = {
    'smtp_server': 'smtp.your-provider.com',
    'smtp_port': 587,
    'sender_email': 'your-email@domain.com',
    'sender_password': 'your-password',
    'sender_name': 'Vision AI System'
}
```

## Testing the Forgot Password Flow

1. **Start the application**
   ```powershell
   python app.py
   ```

2. **Test OTP Generation**
   - Go to `http://localhost:5000/forgot-password`
   - Enter a registered email
   - Check console for OTP (if email not configured)
   - Or check your email (if configured)

3. **Test OTP Verification**
   - Use the received OTP to verify
   - Reset your password

## What Was Fixed

### ✅ Database Issues
- Fixed incorrect `ON CONFLICT` SQL syntax
- Corrected parameter binding in INSERT statements
- Proper handling of unique constraints

### ✅ OTP Verification
- Fixed verification to use `otp` field instead of `token` field
- Consistent field usage across all functions
- Proper expiration and used-token checking

### ✅ Error Handling
- Added specific SMTP error handling
- Better logging for debugging
- Configuration validation
- Clear user feedback

### ✅ Email Configuration
- Environment variable support
- Configuration validation function
- Development mode with OTP display
- Clear setup instructions

## Development Mode

If email is not configured, OTPs will be displayed in the console for testing:
```
[Email] Email not configured - OTP for user@example.com: 123456
```

## Production Deployment

For production, ensure:
1. Set environment variables for email credentials
2. Use a dedicated email account
3. Monitor email sending logs
4. Set up proper email rate limiting

## Troubleshooting

**"Email not configured" error:**
- Check environment variables are set
- Verify email and password are correct
- For Gmail, ensure you're using an App Password (not regular password)

**"SMTP Authentication Error":**
- Verify email credentials
- For Gmail, regenerate App Password
- Check 2-factor authentication is enabled

**"SMTP Connection Error":**
- Check internet connection
- Verify SMTP server and port
- Check firewall settings

**OTP not working:**
- Verify OTP is being generated (check console)
- Check database for reset_tokens table
- Ensure OTP hasn't expired (10 minutes)
- Verify OTP hasn't been marked as used
