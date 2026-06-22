import os

EMAIL_CONFIG = {
    "sender_email":  os.environ.get("SENDER_EMAIL", ""),
    "sender_name":   os.environ.get("SENDER_NAME", "Vision AI System"),
    "brevo_api_key": os.environ.get("BREVO_API_KEY", ""),
}

def is_email_configured() -> bool:
    return bool(
        EMAIL_CONFIG["brevo_api_key"] and
        EMAIL_CONFIG["sender_email"]
    )