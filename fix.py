import re
with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
# Find and fix the broken section
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    if '            if email_sent:' in line:
        new_lines.append('                if email_sent:\n')
        i += 1
    elif '              result = {"success": True, "message": f"OTP sent to' in line:
        new_lines.append('                    result = {"success": True, "message": f"OTP sent to {email}."}\n')
        i += 1
    elif '            else:' in line and i > 0 and 'email_sent' in lines[i-2]:
        new_lines.append('                else:\n')
        i += 1
    elif '             if is_email_configured():' in line:
        new_lines.append('                    if is_email_configured():\n')
        i += 1
    elif '                   result = {"success": False, "error": "Failed to send OTP' in line:
        new_lines.append('                        result = {"success": False, "error": "Failed to send OTP. Please try again."}\n')
        i += 1
    elif '             else:' in line:
        new_lines.append('                    else:\n')
        i += 1
    elif '                result = {"success": True, "message": f"OTP sent! Check CMD' in line:
        new_lines.append('                        result = {"success": True, "message": "OTP sent! Check CMD window for OTP code."}\n')
        i += 1
    else:
        new_lines.append(line)
        i += 1
with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Fixed!')
