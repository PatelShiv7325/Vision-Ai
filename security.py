"""
security.py  -  Vision AI
===========================
FIX 1:  Real bcrypt password hashing (was SHA-256 with static salt)
FIX 4:  Rate limiting helper for /attendance endpoint
FIX 5:  Origin validation for OTP/reset-password endpoints
"""

import os
import secrets
import hashlib
import hmac
import time
from functools import wraps
from flask import request, jsonify, session
from datetime import datetime, timedelta

# ── bcrypt import ─────────────────────────────────────────────────────
# bcrypt is the correct choice: slow by design, salted automatically,
# immune to rainbow tables and GPU cracking at reasonable cost.
try:
    import bcrypt as _bcrypt
    _USE_BCRYPT = True
    print("[Security] bcrypt loaded — strong password hashing active")
except ImportError:
    _bcrypt = None
    _USE_BCRYPT = False
    print("[Security] WARNING: bcrypt not installed — run: pip install bcrypt")


# ═══════════════════════════════════════════════════════════════════════
# FIX 1: PASSWORD HASHING
# ═══════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt (preferred) or SHA-256 fallback.

    bcrypt automatically:
      - generates a unique random salt per hash
      - is slow by design (work factor 12 = ~200ms per check on modern hardware)
      - produces a self-contained hash string that includes the salt

    IMPORTANT: The old SHA-256 hashes in your database are INCOMPATIBLE
    with bcrypt. Run the migration script (migrate_passwords.py) once to
    force all users to reset their passwords on next login.
    """
    if _USE_BCRYPT:
        # bcrypt.hashpw returns bytes; store as UTF-8 string in DB
        salt = _bcrypt.gensalt(rounds=12)
        return _bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    else:
        # Fallback: SHA-256 with a per-password random salt stored together
        # Still better than the old static-salt approach, but bcrypt is far
        # preferred — install it with: pip install bcrypt
        random_salt = secrets.token_hex(16)
        combined = (random_salt + password).encode('utf-8')
        digest = hashlib.sha256(combined).hexdigest()
        return f"sha256${random_salt}${digest}"


def verify_password(password_raw: str, stored_hash: str) -> bool:
    """
    Verify a password against its stored hash.
    Handles three formats:
      1. bcrypt hash (starts with $2b$ or $2a$)
      2. new SHA-256 format (starts with sha256$)
      3. old legacy SHA-256 format (plain hex, for migration)
    """
    if not password_raw or not stored_hash:
        return False

    # Format 1: bcrypt
    if stored_hash.startswith(('$2b$', '$2a$', '$2y$')):
        if not _USE_BCRYPT:
            print("[Security] ERROR: bcrypt hash in DB but bcrypt not installed!")
            return False
        try:
            return _bcrypt.checkpw(
                password_raw.encode('utf-8'),
                stored_hash.encode('utf-8')
            )
        except Exception as e:
            print(f"[Security] bcrypt verify error: {e}")
            return False

    # Format 2: new SHA-256 (sha256$salt$digest)
    if stored_hash.startswith('sha256$'):
        parts = stored_hash.split('$')
        if len(parts) != 3:
            return False
        _, random_salt, stored_digest = parts
        combined = (random_salt + password_raw).encode('utf-8')
        computed = hashlib.sha256(combined).hexdigest()
        return hmac.compare_digest(computed, stored_digest)

    # Format 3: legacy static-salt SHA-256 (old format from original app.py)
    # This allows old users to still log in while you migrate them
    _LEGACY_SECRET = "vision_ai_fixed_secret_key_2024_do_not_change"
    _LEGACY_SALT   = "vision_ai_v2"
    key = (_LEGACY_SECRET + _LEGACY_SALT + password_raw).encode()
    legacy_hash = hashlib.sha256(key).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash)


def needs_password_upgrade(stored_hash: str) -> bool:
    """
    Return True if the stored hash is in the old legacy format and
    should be upgraded to bcrypt on next successful login.
    """
    return not stored_hash.startswith(('$2b$', '$2a$', '$2y$', 'sha256$'))


def upgrade_password_on_login(db, table: str, id_field: str,
                               id_value: str, password_raw: str):
    """
    After a successful login with a legacy hash, silently upgrade it to bcrypt.
    Call this inside your login route after verify_password() returns True.
    """
    if not _USE_BCRYPT:
        return
    try:
        new_hash = hash_password(password_raw)
        db.execute(
            f"UPDATE {table} SET password=? WHERE {id_field}=?",
            (new_hash, id_value)
        )
        db.commit()
        print(f"[Security] Upgraded password hash for {id_value} to bcrypt")
    except Exception as e:
        print(f"[Security] Password upgrade failed for {id_value}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# FIX 4: RATE LIMITING FOR /attendance AND OTHER ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

# In-memory rate limit store: { "ip:endpoint" -> [timestamp, timestamp, ...] }
# For production with multiple workers, use Redis instead.
_RATE_LIMIT_STORE: dict[str, list[float]] = {}


def _get_rate_key(ip: str, endpoint: str) -> str:
    return f"{ip}:{endpoint}"


def check_rate_limit(ip: str, endpoint: str,
                     max_requests: int = 10,
                     window_seconds: int = 60) -> tuple[bool, int]:
    """
    Check if an IP is within the rate limit for a given endpoint.

    Returns:
        (allowed: bool, remaining: int)
        allowed=False means the request should be rejected.
        remaining = how many requests are left in the window.
    """
    key  = _get_rate_key(ip, endpoint)
    now  = time.time()
    cutoff = now - window_seconds

    # Prune old entries
    timestamps = [t for t in _RATE_LIMIT_STORE.get(key, []) if t > cutoff]

    if len(timestamps) >= max_requests:
        _RATE_LIMIT_STORE[key] = timestamps
        return False, 0

    timestamps.append(now)
    _RATE_LIMIT_STORE[key] = timestamps
    return True, max_requests - len(timestamps)


def rate_limit(max_requests: int = 10, window_seconds: int = 60,
               key_func=None):
    """
    Decorator for Flask routes to enforce rate limiting.

    Usage:
        @app.route("/attendance", methods=["POST"])
        @rate_limit(max_requests=5, window_seconds=60)
        @login_required_student
        def attendance():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = _get_client_ip()
            endpoint = f.__name__
            allowed, remaining = check_rate_limit(
                ip, endpoint, max_requests, window_seconds
            )
            if not allowed:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        "success": False,
                        "error": f"Too many requests. Please wait {window_seconds} seconds."
                    }), 429
                return f"Too many requests. Wait {window_seconds}s and try again.", 429
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _get_client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


# ═══════════════════════════════════════════════════════════════════════
# FIX 5: ORIGIN VALIDATION FOR OTP / RESET-PASSWORD
# ═══════════════════════════════════════════════════════════════════════

def get_allowed_origins() -> list[str]:
    """
    Return the list of trusted origins for the application.
    Set ALLOWED_ORIGINS in .env as comma-separated list, e.g.:
      ALLOWED_ORIGINS=https://vision-ai.onrender.com,http://localhost:5000
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Sensible defaults
    defaults = ["http://localhost:5000", "http://127.0.0.1:5000"]
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        defaults.append(render_url.rstrip("/"))
    return defaults


def validate_request_origin() -> bool:
    """
    Validate that a JSON request comes from an allowed origin.
    Returns True if the origin is acceptable, False if it should be rejected.

    This prevents CSRF-via-fetch attacks from malicious third-party pages.
    Add this check at the top of /verify-otp and /reset-password.
    """
    origin  = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")

    # Requests with no Origin header are usually same-origin (form POSTs
    # from the same page) — allow them.
    if not origin and not referer:
        return True

    allowed = get_allowed_origins()
    check   = origin or referer

    return any(check.startswith(o) for o in allowed)


def require_same_origin(f):
    """
    Decorator: reject requests from unknown origins.
    Use on sensitive JSON endpoints like /verify-otp and /reset-password.

    Usage:
        @app.route("/verify-otp", methods=["POST"])
        @require_same_origin
        def verify_otp():
            ...
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not validate_request_origin():
            origin = request.headers.get("Origin", "unknown")
            print(f"[Security] Origin rejected: {origin}")
            return jsonify({
                "success": False,
                "error": "Request origin not allowed."
            }), 403
        return f(*args, **kwargs)
    return wrapper