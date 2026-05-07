with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
new_lines = []
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "print(f\"\\n{'='*40}\")" or stripped == "print(f\"{'='*40}\\n\")":
        continue
    elif stripped == "print(f\"[DEV MODE] OTP for {email}: {otp}\")":
        continue
    else:
        new_lines.append(line)
with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Done! Removed bad print lines')
