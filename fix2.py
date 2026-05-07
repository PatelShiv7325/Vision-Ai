with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()
old = '''                    else:
                print(f"\n{'='*40}")
                print(f"[DEV MODE] OTP for {email}: {otp}")
                print(f"{'='*40}\n")
                        result = {"success": True, "message": "OTP sent! Check CMD window for OTP code."}'''
new = '''                    else:
                        print(f"[DEV MODE] OTP for {email}: {otp}")
                        result = {"success": True, "message": "OTP sent! Check CMD window for OTP code."}'''
content = content.replace(old, new)
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed!')
