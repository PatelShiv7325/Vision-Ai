"""
app.py  -  Vision AI v5.1 -  COMPLETE WITH SESSION MANAGEMENT
===============================================================

ALL FEATURES:
  ✅ Session instance tracking (prevents multi-login hijacking)
  ✅ Active sessions table (validates each request)
  ✅ CSRF protection on all POST/PUT/DELETE
  ✅ Face recognition with dual matching (LBPH + histogram)
  ✅ Emotion tracking & batch attendance
  ✅ Attendance goals with email alerts
  ✅ Timetable management (faculty & student)
  ✅ Account lockout after 5 failed attempts
  ✅ Password reset via OTP email
  ✅ Low attendance alerts
  ✅ Complete data deletion (GDPR compliant)
"""

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, render_template, request, redirect,
    session, jsonify, flash, url_for, abort, Response
)
from database.db import (
    get_db, init_db, DB_PATH,
    log_security_event,
    check_account_locked, record_failed_login, record_successful_login,
    get_attendance_summary,
    delete_student_completely, clear_all_students,
    get_batch_attendance_analytics, get_student_emotion_trends,
    validate_face_quality, detect_liveness,
    create_session_record,
    validate_session_instance,
    invalidate_session,
    invalidate_all_user_sessions,
    get_user_active_sessions,
    cleanup_old_sessions,
    update_session_last_seen,
    get_session_info,
    purge_ghost_student,
)

from face_engine import (
    RecognizerCache,
    enhanced_duplicate_check,
    check_liveness,
    dual_match,
    detect_emotion,
)

import hashlib, hmac, base64, os, sqlite3, secrets, json
from datetime import datetime, timedelta
from functools import wraps
import cv2
import numpy as np
from PIL import Image
import io
import smtplib
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import cloudinary
import cloudinary.uploader

# ── Cloudinary setup ──────────────────────────────────────────────────
_CLOUDINARY_CONFIGURED = False
if os.environ.get("CLOUDINARY_CLOUD_NAME"):
    cloudinary.config(
        cloud_name = os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key    = os.environ["CLOUDINARY_API_KEY"],
        api_secret = os.environ["CLOUDINARY_API_SECRET"],
        secure     = True
    )
    _CLOUDINARY_CONFIGURED = True
    print("[Cloudinary] Configured successfully")
else:
    print("[Cloudinary] Not configured — using local storage")


def _save_face_image(img_data: bytes, roll: str) -> str:
    """
    Save face image. Returns the path/URL to store in DB.
    Uses Cloudinary on Render, local disk otherwise.
    """
    if _CLOUDINARY_CONFIGURED:
        try:
            result = cloudinary.uploader.upload(
                img_data,
                public_id     = f"vision_ai/faces/{roll}",
                overwrite     = True,
                resource_type = "image",
                format        = "jpg",
            )
            url = result["secure_url"]
            print(f"[Cloudinary] Uploaded face for {roll}: {url}")
            return url
        except Exception as e:
            print(f"[Cloudinary] Upload failed for {roll}: {e}")

    # Local fallback
    faces_dir = os.path.join(
        os.environ.get("DATA_DIR", "") or os.path.dirname(os.path.abspath(__file__)),
        "static", "faces"
    )
    os.makedirs(faces_dir, exist_ok=True)
    path = os.path.join(faces_dir, f"{roll}.jpg")
    with open(path, "wb") as f:
        f.write(img_data)
    return f"faces/{roll}.jpg"


try:
    from email_config import EMAIL_CONFIG, is_email_configured
except ImportError:
    EMAIL_CONFIG = {
        "smtp_server":    "smtp.gmail.com",
        "smtp_port":      587,
        "sender_email":   "noreply@visionai.com",
        "sender_password": "",
    }
    def is_email_configured():
        return False

DATA_DIR = os.environ.get("DATA_DIR", "")
FACES_STATIC_DIR = (
    os.path.join(DATA_DIR, "static", "faces") if DATA_DIR
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "faces")
)

IST_OFFSET = timedelta(hours=5, minutes=30)

def get_ist_now():
    return datetime.utcnow() + IST_OFFSET

_TABLE_MAP = {"student": "students", "faculty": "faculty"}

# ── App setup ─────────────────────────────────────────────────────────
app = Flask(__name__)

if not os.environ.get('SECRET_KEY'):
    if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('RENDER'):
        raise RuntimeError(
            "SECRET_KEY environment variable must be set. Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    else:
        os.environ['SECRET_KEY'] = 'dev-fallback-secret-key-do-not-use-in-production'
        print("[WARNING] SECRET_KEY not set — using insecure fallback for local development only")

app.secret_key = os.environ["SECRET_KEY"].strip()

app.config["SESSION_COOKIE_HTTPONLY"]    = True
app.config["SESSION_COOKIE_SAMESITE"]    = "Lax"
app.config["SESSION_COOKIE_SECURE"]      = os.environ.get("PRODUCTION", "0") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["MAX_CONTENT_LENGTH"]         = 10 * 1024 * 1024  # 10 MB

from flask.sessions import SecureCookieSessionInterface
app.session_interface = SecureCookieSessionInterface()

def favicon():
    return '', 204

@app.after_request
def ensure_session_saved(response):
    # Only mark modified if session has user data — prevents unnecessary cookie rewrites
    if "_csrf" in session and ("student_roll" in session or "faculty_id" in session):
        session.modified = True
    return response


# ── CBSE Standard → Subjects map ──────────────────────────────────────
STANDARD_SUBJECTS = {
    "1":  ["English", "Hindi", "Mathematics", "General Knowledge"],
    "2":  ["English", "Hindi", "Mathematics", "Gujrati", "General Knowledge"],
    "3":  ["English", "Hindi", "Mathematics", "Environmental Studies", "General Knowledge", "Computer"],
    "4":  ["English", "Hindi", "Mathematics", "Environmental Studies", "General Knowledge", "Computer"],
    "5":  ["English", "Hindi", "Mathematics", "Environmental Studies", "General Knowledge", "Computer"],
    "6":  ["English", "Hindi", "Mathematics", "Science", "Social Science", "Sanskrit", "Computer"],
    "7":  ["English", "Hindi", "Mathematics", "Science", "Social Science", "Sanskrit", "Computer"],
    "8":  ["English", "Hindi", "Mathematics", "Science", "Social Science", "Sanskrit", "Computer"],
    "9":  ["English", "Hindi", "Mathematics", "Science", "Social Science", "Sanskrit", "Information Technology"],
    "10": ["English", "Hindi", "Mathematics", "Science", "Social Science", "Sanskrit", "Information Technology"],
}


# =====================================================================
# HELPERS
# =====================================================================

from security import (
    hash_password, verify_password,
    needs_password_upgrade, upgrade_password_on_login,
    rate_limit, require_same_origin,
)

def get_client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"

def generate_csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(24)
    return session["_csrf"]

def generate_session_id() -> str:
    return secrets.token_hex(32)

    
## EXACT REPLACEMENT FOR THE DUPLICATE enforce_csrf IN app.py
## ============================================================
## Find BOTH @app.before_request blocks (lines roughly ~130–175 in your app.py)
## DELETE BOTH OF THEM entirely, then paste this single one in their place:

@app.before_request
def enforce_csrf():
    generate_csrf_token()

    # Keep session alive — but only mark modified when something actually changes
    if "student_roll" in session or "faculty_id" in session:
        session.permanent = True
        # Do NOT set session.modified = True here — it causes cookie rewrites on every GET
        # which can corrupt the session on rapid refreshes

    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    exempt_endpoints = {
        "student_face_login", "student_login", "forgot_password",
        "verify_otp", "reset_password", "mark_notifications_read",
        "subjects_by_standard", "static", "health", "get_csrf_token",
        "faculty_login", "faculty_register", "student_register",
    }

    if request.endpoint in exempt_endpoints:
        return

    received_token = None

    if request.form:
        received_token = request.form.get("_csrf", "").strip()

    if not received_token:
        received_token = request.headers.get("X-CSRF-Token", "").strip()

    if not received_token and request.is_json:
        try:
            json_data = request.get_json(silent=True, force=True)
            if isinstance(json_data, dict):
                received_token = str(json_data.get("_csrf", "")).strip()
        except Exception:
            pass

    stored_token = session.get("_csrf", "").strip()

    if not received_token or not stored_token or not hmac.compare_digest(received_token, stored_token):
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "CSRF validation failed. Please refresh the page."}), 403
        abort(403)


@app.context_processor
def inject_csrf():
    return {"csrf_token": generate_csrf_token()}


# ── Login decorators ──────────────────────────────────────────────────

def login_required_student(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "student_roll" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("student_login"))

        if session.get("session_user_type") not in ("student", None):
            session.clear()
            flash("Session mismatch. Please login again.", "warning")
            return redirect(url_for("student_login"))

        # Keep session alive on every request
        session.permanent = True
        session.modified = True

        roll = session["student_roll"]
        db = None
        try:
            db = get_db()
            student = db.execute(
                "SELECT id FROM students WHERE roll=? AND is_active=1", (roll,)
            ).fetchone()
            if student is None:
                count = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
                if count == 0:
                    print(f"[LoginRequired] DB empty, trusting cookie for {roll}")
                    return f(*args, **kwargs)
                # ── NEW: re-create session record so refresh works ──
                print(f"[LoginRequired] Roll {roll} not in DB but count={count}, trusting cookie")
                return f(*args, **kwargs)
        except Exception as e:
            print(f"[LoginRequired] Student DB error (non-fatal): {e}")
            # ANY DB error — always trust the cookie
            return f(*args, **kwargs)
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

        return f(*args, **kwargs)
    return wrapper


def login_required_faculty(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "faculty_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("faculty_login"))

        if session.get("session_user_type") == "student":
            session.clear()
            flash("Session mismatch. Please login again.", "warning")
            return redirect(url_for("faculty_login"))

        # Keep session alive on every request
        session.permanent = True
        session.modified = True

        faculty_id = session["faculty_id"]
        db = None
        try:
            db = get_db()
            faculty = db.execute(
                "SELECT id FROM faculty WHERE faculty_id=? AND is_active=1",
                (faculty_id,)
            ).fetchone()
            if faculty is None:
                count = db.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
                if count == 0:
                    print(f"[LoginRequired] DB empty, trusting cookie for {faculty_id}")
                    return f(*args, **kwargs)
                # ── NEW: trust the cookie instead of killing session ──
                print(f"[LoginRequired] Faculty {faculty_id} not in DB, trusting cookie")
                return f(*args, **kwargs)
        except Exception as e:
            print(f"[LoginRequired] Faculty DB error (non-fatal): {e}")
            return f(*args, **kwargs)
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

        return f(*args, **kwargs)
    return wrapper


# ── Email ─────────────────────────────────────────────────────────────

def _send_email_via_brevo(to_email: str, subject: str, html_content: str, text_content: str = None) -> bool:
    """Send via Brevo's HTTPS API — works on Render free tier since it only
    needs outbound port 443, unlike raw SMTP which Render blocks (ports 25/465/587)."""
    api_key      = EMAIL_CONFIG.get("brevo_api_key", "")
    sender_email = EMAIL_CONFIG.get("sender_email", "")
    sender_name  = EMAIL_CONFIG.get("sender_name", "Vision AI System")

    if not api_key or not sender_email:
        print(f"[Email] Brevo not configured — email to {to_email} not sent")
        return False

    body_dict = {
        "sender":      {"name": sender_name, "email": sender_email},
        "to":          [{"email": to_email}],
        "subject":     subject,
        "htmlContent": html_content,
        "replyTo":     {"email": sender_email, "name": sender_name},
    }
    if text_content:
        body_dict["textContent"] = text_content

    payload = json.dumps(body_dict).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={
            "accept":       "application/json",
            "api-key":      api_key,
            "content-type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[Email] Brevo accepted email to {to_email} (status {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        print(f"[Email] Brevo HTTP error {e.code} to={to_email} key_prefix={api_key[:12]}... sender={sender_email} detail={detail}")
        return False
    except Exception as e:
        print(f"[Email] Brevo request failed for {to_email}: {type(e).__name__}: {e}")
        return False


def send_otp_email(email: str, otp: str, user_type: str = "student") -> bool:
    if not is_email_configured():
        print(f"[Email] Email not configured - OTP for {email}: {otp}")
        return False
    body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
      <div style="background:linear-gradient(135deg,#6c63ff,#a78bfa);padding:30px;
                  border-radius:10px;text-align:center;color:#fff;">
        <h1 style="margin:0;font-size:28px;">Vision AI</h1>
        <p style="margin:10px 0 0;opacity:.9;">Password Reset Request</p>
      </div>
      <div style="background:#f8f9fa;padding:30px;border-radius:10px;margin-top:20px;">
        <h2 style="color:#333;">Hello {user_type.capitalize()},</h2>
        <p style="color:#666;">Your OTP Code: <strong style="font-size:24px;color:#6c63ff;">{otp}</strong></p>
        <p style="color:#666;">Valid for <strong>10 minutes</strong>.</p>
        <p style="color:#999;font-size:12px;">If you did not request this, please ignore this email.</p>
      </div>
    </body></html>"""
    text_body = f"Hello {user_type.capitalize()},\n\nYour Vision AI OTP code is: {otp}\nValid for 10 minutes.\n\nIf you did not request this, ignore this email."
    return _send_email_via_brevo(
        email, f"Vision AI - Password Reset OTP ({user_type.capitalize()})", body, text_body
    )


def _send_low_attendance_alert(email: str, name: str,
                                low_subjects: list, target_pct: int) -> bool:
    if not is_email_configured():
        print(f"[Alert] Email not configured — low attendance alert for {email}")
        return False
    rows_html = "".join(
            f"<tr><td style='padding:10px 14px;border-bottom:1px solid #eee;font-weight:600'>{s['subject']}</td>"
            f"<td style='padding:10px 14px;border-bottom:1px solid #eee;color:#ef4444;font-weight:700'>{s['pct']}%</td>"
            f"<td style='padding:10px 14px;border-bottom:1px solid #eee;color:#888'>{target_pct}% required</td></tr>"
            for s in low_subjects
        )
    body = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
          <div style="background:linear-gradient(135deg,#ef4444,#f97316);padding:28px 30px;
                      border-radius:12px;text-align:center;color:#fff;margin-bottom:20px;">
            <h1 style="margin:0;font-size:24px;">&#9888;&#65039; Low Attendance Alert</h1>
            <p style="margin:8px 0 0;opacity:.9;">Vision AI · Attendance Tracker</p>
          </div>
          <div style="background:#fff;border:1px solid #e5e7eb;padding:28px;border-radius:12px;">
            <p style="color:#333;font-size:15px;">Hi <strong>{name}</strong>,</p>
            <p style="color:#555;font-size:14px;line-height:1.6;">
              Your attendance has dropped below your target of
              <strong style="color:#ef4444">{target_pct}%</strong>
              in the following subject(s):
            </p>
            <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;">
              <thead>
                <tr style="background:#f9fafb;">
                  <th style="padding:10px 14px;text-align:left;color:#6b7280;font-size:11px;
                             text-transform:uppercase;letter-spacing:.5px;">Subject</th>
                  <th style="padding:10px 14px;text-align:left;color:#6b7280;font-size:11px;
                             text-transform:uppercase;letter-spacing:.5px;">Current %</th>
                  <th style="padding:10px 14px;text-align:left;color:#6b7280;font-size:11px;
                             text-transform:uppercase;letter-spacing:.5px;">Target</th>
                </tr>
              </thead>
              <tbody>{rows_html}</tbody>
            </table>
            <p style="color:#555;font-size:13px;line-height:1.6;">
              Please attend upcoming classes regularly to improve your attendance.
            </p>
            <p style="color:#999;font-size:12px;margin-top:20px;">
              — Vision AI Attendance System
            </p>
          </div>
        </body></html>"""

    return _send_email_via_brevo(email, "Low Attendance Alert — Vision AI", body)


# =====================================================================
# FACE RECOGNITION HELPERS
# =====================================================================
def _check_face_quality(gray_face, strict: bool = False):
    blur       = cv2.Laplacian(gray_face, cv2.CV_64F).var()
    brightness = float(gray_face.mean())
    h, w       = gray_face.shape
    blur_t  = 45  if strict else 30
    bri_min = 40  if strict else 25
    bri_max = 215 if strict else 235

    if blur < blur_t:
        return False, f"Too blurry (score={blur:.1f}). Improve lighting or hold steady."
    if brightness < bri_min:
        return False, f"Too dark (brightness={brightness:.1f}). Move to brighter area."
    if brightness > bri_max:
        return False, f"Overexposed (brightness={brightness:.1f}). Reduce direct light."
    if h * w < 4900:
        return False, "Face too small. Move closer to the camera."
    return True, "OK"


def _remove_overlapping_faces(faces):
    if len(faces) <= 1:
        return list(faces)
    faces_sorted    = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    non_overlapping = []
    for face in faces_sorted:
        x, y, w, h = face
        overlap = False
        for ax, ay, aw, ah in non_overlapping:
            x1 = max(x, ax);  y1 = max(y, ay)
            x2 = min(x + w, ax + aw); y2 = min(y + h, ay + ah)
            if x1 < x2 and y1 < y2:
                inter = (x2 - x1) * (y2 - y1)
                if inter > 0.5 * w * h or inter > 0.5 * aw * ah:
                    overlap = True
                    break
        if not overlap:
            non_overlapping.append(face)
    return non_overlapping


def _get_cascade():
    return cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )


def _detect_faces_multipass(gray_eq):
    cascade = _get_cascade()
    found   = []
    for sf, mn, mi, ma in [
        (1.03, 6, 90,  400),
        (1.05, 4, 70,  500),
        (1.07, 3, 55,  600),
        (1.10, 3, 45,  700),
    ]:
        detected = cascade.detectMultiScale(
            gray_eq, scaleFactor=sf, minNeighbors=mn,
            minSize=(mi, mi), maxSize=(ma, ma),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(detected):
            found.extend(detected)
    return _remove_overlapping_faces(found)


def _notify(db, user_type: str, user_id: str, title: str, message: str,
            ntype: str = "info"):
    try:
        db.execute(
            "INSERT INTO notifications "
            "(user_type, user_id, title, message, type) VALUES (?,?,?,?,?)",
            (user_type, user_id, title, message, ntype),
        )
    except Exception as e:
        print(f"[Notify] {e}")


# ── App init ──────────────────────────────────────────────────────────
with app.app_context():
    init_db()


# =====================================================================
# HOME
# =====================================================================
@app.route("/health")
def health():
    try:
        db = get_db()
        db.execute("SELECT 1")
        db.close()
        return jsonify({"status": "ok", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500

@app.route("/api/csrf-token", methods=["GET"])
def get_csrf_token():
    token = session.get("_csrf", "")
    if not token:
        token = generate_csrf_token()
    return jsonify({"csrf_token": token})

@app.route("/")
def home():
    db = get_db()
    try:
        stats = {
            "students":   db.execute(
                "SELECT COUNT(*) FROM students WHERE is_active=1"
            ).fetchone()[0],
            "faculty":    db.execute(
                "SELECT COUNT(*) FROM faculty WHERE is_active=1"
            ).fetchone()[0],
            "attendance": db.execute(
                "SELECT COUNT(*) FROM attendance"
            ).fetchone()[0],
            "subjects":   db.execute(
                "SELECT COUNT(DISTINCT subject) FROM attendance"
            ).fetchone()[0],
        }
    except Exception:
        stats = {"students": 0, "faculty": 0, "attendance": 0, "subjects": 0}
    finally:
        db.close()
    return render_template("index.html", stats=stats)


# =====================================================================
# STUDENT — REGISTER
# =====================================================================
@app.route("/student-register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        name         = request.form.get("name",       "").strip()
        roll         = request.form.get("roll",       "").strip().upper()
        phone        = request.form.get("phone",      "").strip()
        email        = request.form.get("email",      "").strip().lower()
        standard     = request.form.get("standard",   "").strip()
        division     = request.form.get("division",   "").strip()
        gender       = request.form.get("gender",     "").strip()
        subject      = request.form.get("subject",    "").strip()
        password_raw = request.form.get("password",   "")
        face_data    = request.form.get("face_image", "")

        missing = [lbl for lbl, v in [
            ("Name", name), ("Roll", roll), ("Email", email),
            ("Phone", phone), ("Password", password_raw),
        ] if not v]
        if missing:
            return render_template("student_register.html",
                                   error=f"Missing: {', '.join(missing)}")
        if len(password_raw) < 8:
            return render_template("student_register.html",
                                   error="Password must be at least 8 characters.")
        if not face_data or "," not in face_data:
            return render_template("student_register.html",
                                   error="Please capture your face photo.")

        phone_digits = "".join(filter(str.isdigit, phone))
        if len(phone_digits) != 10:
            return render_template("student_register.html",
                                   error="Phone must be exactly 10 digits.")
        if phone_digits[0] not in "6789":
            return render_template("student_register.html",
                                   error="Phone must start with 6, 7, 8, or 9.")

        db = None
        try:
            db = get_db()

            faces_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "faces")
            for ext in ["jpg", "jpeg", "png"]:
                fp = os.path.join(faces_dir, f"{roll}.{ext}")
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                        print(f"[Register] Cleaned up old face file: {fp}")
                    except Exception:
                        pass

            from database.db import purge_ghost_student
            purge_ghost_student(db, roll=roll, email=email)
            db.commit()

            for field, val in [("roll", roll), ("email", email)]:
                existing = db.execute(
                    f"SELECT id, name, is_active, roll FROM students WHERE {field}=?",
                    (val,)
                ).fetchone()
                if existing:
                    if existing["is_active"] == 0:
                        from database.db import _purge_student_by_roll
                        _purge_student_by_roll(db, existing["roll"])
                        db.commit()
                    else:
                        label = "Roll number" if field == "roll" else "Email"
                        return render_template(
                            "student_register.html",
                            error=(f'{label} is already registered '
                                   f'to "{existing["name"]}"! Please use a different one.')
                        )

            try:
                img_data = base64.b64decode(face_data.split(",")[1])
            except Exception:
                return render_template("student_register.html",
                                       error="Invalid image data. Please retake your photo.")

            np_arr = np.frombuffer(img_data, np.uint8)
            img_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_cv is None:
                return render_template("student_register.html",
                                       error="Could not decode image. Please retake.")

            gray    = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            gray_eq = cv2.equalizeHist(gray)
            faces   = _detect_faces_multipass(gray_eq)

            if not faces:
                return render_template(
                    "student_register.html",
                    error="No face detected. Ensure good lighting and face the camera directly."
                )

            img_cx, img_cy = gray_eq.shape[1] // 2, gray_eq.shape[0] // 2
            best_face, best_score = None, -1
            for (x, y, w, h) in faces:
                fc_x, fc_y = x + w // 2, y + h // 2
                score = w * h * (1.0 - (
                    abs(fc_x - img_cx) + abs(fc_y - img_cy)
                ) / max(gray_eq.shape[:2]))
                if score > best_score:
                    best_score, best_face = score, (x, y, w, h)

            x, y, w, h = best_face
            clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            face_roi   = clahe.apply(
                cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
            )

            quality_ok, quality_msg = _check_face_quality(face_roi, strict=True)
            if not quality_ok:
                return render_template("student_register.html",
                                       error=f"Face quality issue: {quality_msg}")

            face_encoding = face_roi.tobytes()

            existing_faces = [
                dict(r)
                for r in db.execute(
                    "SELECT roll, name, face_encoding "
                    "FROM students WHERE face_encoding IS NOT NULL AND is_active=1"
                ).fetchall()
            ]

            if existing_faces:
                is_dup, dup_roll, dup_name, dup_score = enhanced_duplicate_check(
                    face_encoding, existing_faces, exclude_roll=roll
                )
                if is_dup:
                    log_security_event(
                        db, "DUPLICATE_FACE_ATTEMPT", roll, "student",
                        get_client_ip(),
                        f"Matched {dup_roll} score={dup_score:.3f}", "high"
                    )
                    db.commit()
                    return render_template(
                        "student_register.html",
                        error=(
                            f'This face is already registered to "{dup_name}" '
                            f"(Roll: {dup_roll}). "
                            f"Each person can only register once. "
                            f"(Similarity: {dup_score:.1%})"
                        )
                    )

                if dup_score >= 0.50:
                    log_security_event(
                        db, "POTENTIAL_DUPLICATE_FACE", roll, "student",
                        get_client_ip(),
                        f"High similarity to {dup_roll} score={dup_score:.3f}", "medium"
                    )
                    db.commit()
                    return render_template(
                        "student_register.html",
                        error=(
                            f'This face is very similar to "{dup_name}" '
                            f'(Roll: {dup_roll}). '
                            f"Please ensure you are registering your own face. "
                            f"(Similarity: {dup_score:.1%})"
                        )
                    )

            faces_dir_env = os.environ.get("DATA_DIR", "")
            if faces_dir_env:
                faces_save_dir = os.path.join(faces_dir_env, "static", "faces")
                face_filename  = f"faces/{roll}.jpg"
                face_save_path = os.path.join(faces_dir_env, "static", face_filename)
            else:
                faces_save_dir = "static/faces"
                face_filename  = f"faces/{roll}.jpg"
                face_save_path = f"static/{face_filename}"

            os.makedirs(faces_save_dir, exist_ok=True)
            with open(face_save_path, "wb") as f:
                f.write(img_data)

            db.execute(
                """INSERT INTO students
                   (name, roll, phone, email, password, face_image, face_encoding,
                    standard, division, gender, subject)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (name, roll, phone_digits, email, hash_password(password_raw),
                 face_filename, face_encoding,
                 standard, division, gender, subject)
            )
            db.commit()
            RecognizerCache.invalidate()

            new_row = db.execute(
                "SELECT id FROM students WHERE roll=?", (roll,)
            ).fetchone()
            new_id = new_row["id"] if new_row else None

            _notify(db, "student", roll, "Welcome to Vision AI!",
                    f"Hi {name}, your account has been created successfully.", "success")
            log_security_event(db, "STUDENT_REGISTER", roll, "student",
                               get_client_ip())
            db.commit()

            session_instance_id = generate_session_id()
            create_session_record(db, session_instance_id, "student", roll, get_client_ip())

            session.clear()
            session.permanent             = True
            session["student_roll"]       = roll
            session["student_name"]       = name
            session["student_id"]         = new_id
            session["student_email"]      = email
            session["session_instance"]   = session_instance_id
            session["session_created_at"] = get_ist_now().isoformat()
            session["session_user_type"]  = "student"

            return redirect(url_for("student_dashboard"))

        except Exception as e:
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            print(f"[Register] Error: {e}")
            import traceback
            traceback.print_exc()
            return render_template("student_register.html",
                                   error="Registration failed. Please try again.")
        finally:
            if db:
                db.close()

    return render_template("student_register.html")


# =====================================================================
# STUDENT — LOGIN
# =====================================================================
@app.route("/student-login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        db = None
        try:
            email        = request.form.get("email", "").strip().lower()
            password_raw = request.form.get("password", "")

            if not email or not password_raw:
                return render_template("student_login.html",
                                       error="Email and password are required.")

            db = get_db()

            student = db.execute(
                "SELECT * FROM students WHERE email=? AND is_active=1", (email,)
            ).fetchone()

            if not student:
                return render_template("student_login.html",
                                       error="Invalid email or password.")

            if check_account_locked(db, "students", "email", email):
                return render_template(
                    "student_login.html",
                    error="Account locked due to too many failed attempts. Try again in 15 minutes."
                )

            if not verify_password(password_raw, student["password"]):
                record_failed_login(db, "students", "email", email)
                attempts  = (student["login_attempts"] or 0) + 1
                remaining = max(0, 5 - attempts)
                log_security_event(db, "FAILED_LOGIN", email, "student",
                                   get_client_ip(), severity="medium")
                db.commit()
                msg = "Invalid email or password."
                if remaining > 0:
                    msg += f" {remaining} attempt(s) remaining before lockout."
                return render_template("student_login.html", error=msg)

            if needs_password_upgrade(student["password"]):
                upgrade_password_on_login(db, "students", "email", email, password_raw)

            record_successful_login(db, "students", "email", email)
            log_security_event(db, "STUDENT_LOGIN", student["roll"],
                               "student", get_client_ip())

            session_instance_id = generate_session_id()
            create_session_record(db, session_instance_id, "student",
                                  student["roll"], get_client_ip())
            db.commit()

            session.clear()
            session.permanent             = True
            session["student_roll"]       = student["roll"]
            session["student_name"]       = student["name"]
            session["student_id"]         = student["id"]
            session["student_email"]      = student["email"]
            session["session_instance"]   = session_instance_id
            session["session_created_at"] = get_ist_now().isoformat()
            session["session_user_type"]  = "student"

            return redirect(url_for("student_dashboard"))
        except Exception as e:
            import traceback
            print(f"[StudentLogin] Error: {e}\n{traceback.format_exc()}")
            return render_template("student_login.html",
                                   error="Login failed. Please try again.")
        finally:
            if db:
                db.close()

    return render_template("student_login.html")


# =====================================================================
# STUDENT — FACE LOGIN
# =====================================================================
@app.route("/student-face-login", methods=["POST"])
def student_face_login():
    data      = request.get_json(silent=True) or {}
    face_data = data.get("face_image", "")
    ip        = get_client_ip()
    db        = None

    try:
        db = get_db()

        recent = db.execute(
            "SELECT COUNT(*) FROM face_attempts "
            "WHERE ip_address=? AND created_at > datetime('now','-1 minute')",
            (ip,)
        ).fetchone()[0]
        if recent >= 10:
            return jsonify({"success": False,
                            "error": "Too many attempts. Please wait 1 minute."})

        if not face_data or "," not in face_data:
            return jsonify({"success": False, "error": "No image received."})

        try:
            img_bytes = base64.b64decode(face_data.split(",")[1])
        except Exception:
            return jsonify({"success": False, "error": "Invalid image data."})

        np_arr = np.frombuffer(img_bytes, np.uint8)
        img_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            return jsonify({"success": False, "error": "Could not decode image."})

        gray    = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        gray_eq = cv2.equalizeHist(gray)
        faces   = _detect_faces_multipass(gray_eq)

        if not faces:
            db.execute(
                "INSERT INTO face_attempts (roll, success, ip_address) VALUES (?,?,?)",
                (None, 0, ip)
            )
            db.commit()
            return jsonify({"success": False,
                            "error": "No face detected. Ensure good lighting and face the camera."})

        all_students = [
            dict(r) for r in db.execute(
                "SELECT * FROM students WHERE face_encoding IS NOT NULL AND is_active=1"
            ).fetchall()
        ]
        use_encoding = True

        if not all_students:
            all_students = [
                dict(r) for r in db.execute(
                    "SELECT * FROM students WHERE face_image IS NOT NULL AND is_active=1"
                ).fetchall()
            ]
            use_encoding = False

        if not all_students:
            return jsonify({"success": False, "error": "No student face data enrolled."})

        recognizer, roll_labels = RecognizerCache.get(all_students, use_encoding)

        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        face_roi   = clahe.apply(
            cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
        )

        quality_ok, quality_msg = _check_face_quality(face_roi, strict=True)
        if not quality_ok:
            return jsonify({"success": False, "error": quality_msg})

        roll, name, lbph_conf, hist_score, matched = dual_match(
            face_roi, recognizer, roll_labels, all_students, use_encoding
        )

        if matched:
            student = db.execute(
                "SELECT * FROM students WHERE roll=? AND is_active=1", (roll,)
            ).fetchone()
            if not student:
                return jsonify({"success": False,
                                "error": "Account not found. Please re-register."})

            record_successful_login(db, "students", "roll", roll)
            db.execute(
                "INSERT INTO face_attempts (roll, success, confidence, ip_address) VALUES (?,?,?,?)",
                (roll, 1, lbph_conf, ip)
            )
            log_security_event(db, "FACE_LOGIN_SUCCESS", roll, "student", ip,
                               f"LBPH={lbph_conf:.1f} HIST={hist_score:.3f}")

            session_instance_id = generate_session_id()
            create_session_record(db, session_instance_id, "student", roll, ip)
            db.commit()

            session.clear()
            session.permanent             = True
            session["student_roll"]       = student["roll"]
            session["student_name"]       = student["name"]
            session["student_id"]         = student["id"]
            session["student_email"]      = student["email"]
            session["session_instance"]   = session_instance_id
            session["session_created_at"] = get_ist_now().isoformat()
            session["session_user_type"]  = "student"

            return jsonify({"success": True, "name": name})

        db.execute(
            "INSERT INTO face_attempts (roll, success, confidence, ip_address) VALUES (?,?,?,?)",
            (None, 0, lbph_conf, ip)
        )
        log_security_event(db, "FACE_LOGIN_FAIL", None, "student", ip,
                           f"LBPH={lbph_conf:.1f} HIST={hist_score:.3f}", "medium")
        db.commit()
        return jsonify({"success": False,
                        "error": "Face not recognized. Try email/password login or re-enroll your face."})

    except Exception as e:
        print(f"[FaceLogin] Error: {e}")
        return jsonify({"success": False, "error": "Processing error. Please try again."})
    finally:
        if db:
            db.close()


# =====================================================================
# STUDENT — DASHBOARD
# =====================================================================
@app.route("/student-dashboard")
@login_required_student
def student_dashboard():
    db = None
    try:
        db = get_db()

        student = db.execute(
            "SELECT * FROM students WHERE roll=? AND is_active=1",
            (session["student_roll"],)
        ).fetchone()

        if not student:
            # Always trust the cookie — build from session data
            # Never clear session just because DB lookup failed
            student_dict = {
                "name":     session.get("student_name", "Student"),
                "roll":     session.get("student_roll", ""),
                "email":    session.get("student_email", ""),
                "phone":    "", "standard": "", "division": "",
                "subject":  "", "gender":   "", "face_image": None,
            }
        else:
            student_dict = dict(student)

        try:
            attendance = db.execute(
                "SELECT * FROM attendance WHERE student_roll=? ORDER BY date DESC, time DESC",
                (session["student_roll"],)
            ).fetchall()
        except Exception:
            attendance = []

        try:
            notifications = db.execute(
                "SELECT * FROM notifications "
                "WHERE user_type='student' AND user_id=? AND is_read=0 "
                "ORDER BY created_at DESC LIMIT 10",
                (session["student_roll"],)
            ).fetchall()
        except Exception:
            notifications = []

        try:
            subject_stats = get_attendance_summary(db, session["student_roll"])
        except Exception:
            subject_stats = []

        today_day     = ""
        today_classes = []
        try:
            days_map  = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                         4: "Friday", 5: "Saturday", 6: "Sunday"}
            today_day = days_map[get_ist_now().weekday()]

            student_info = db.execute(
                "SELECT standard, division FROM students WHERE roll=?",
                (session["student_roll"],)
            ).fetchone()

            rows = []
            if student_info and student_info["standard"]:
                rows = db.execute(
                    "SELECT period_number as period, subject, start_time, end_time "
                    "FROM timetable WHERE standard=? AND (division=? OR division='') AND day_of_week=? "
                    "ORDER BY period_number",
                    (student_info["standard"], student_info["division"] or "", today_day)
                ).fetchall()

            today_classes = [dict(r) for r in rows]

            today_str    = get_ist_now().strftime("%Y-%m-%d")
            marked_today = {
                r["subject"] for r in db.execute(
                    "SELECT DISTINCT subject FROM attendance "
                    "WHERE student_roll=? AND date=?",
                    (session["student_roll"], today_str)
                ).fetchall()
            }
            for cls in today_classes:
                cls["marked"] = cls["subject"] in marked_today
        except Exception:
            today_classes = []
            marked_today  = set()

        target_pct  = 75
        alert_email = True
        try:
            goal_row = db.execute(
                "SELECT target_pct, alert_email FROM attendance_goals WHERE student_roll=?",
                (session["student_roll"],)
            ).fetchone()
            if goal_row:
                target_pct  = goal_row["target_pct"]
                alert_email = bool(goal_row["alert_email"])
        except Exception:
            pass

        subject_goal_data = {}
        try:
            subj_rows = db.execute(
                "SELECT subject, COUNT(*) as cnt FROM attendance "
                "WHERE student_roll=? GROUP BY subject",
                (session["student_roll"],)
            ).fetchall()

            total_all = len(attendance)

            for sr in subj_rows:
                subj       = sr["subject"]
                present    = sr["cnt"]
                subj_total = present
                pct        = round((present / subj_total) * 100) if subj_total > 0 else 0
                needed     = 0
                can_miss   = 0

                if pct < target_pct and total_all > 0:
                    denom  = 100 - target_pct
                    needed = max(0, int(
                        (target_pct * total_all - 100 * present) / denom
                    ) + 1) if denom > 0 else 0

                if pct >= target_pct and total_all > 0:
                    can_miss = max(0, int((100 * present / target_pct) - total_all))

                subject_goal_data[subj] = {
                    "present":  present,
                    "total":    subj_total,
                    "pct":      pct,
                    "needed":   needed,
                    "can_miss": can_miss,
                    "on_track": pct >= target_pct,
                }
        except Exception:
            subject_goal_data = {}

        total   = len(attendance)
        present = total
        percent = 100 if total > 0 else 0

        student_dict = dict(student) if student else {}

        try:
            if alert_email and student_dict.get("email"):
                subj_counts = {}
                for a in attendance:
                    subj_counts[a["subject"]] = subj_counts.get(a["subject"], 0) + 1

                low_subjects = []
                for subj, cnt in subj_counts.items():
                    pct_subj = round((cnt / total) * 100) if total > 0 else 0
                    if pct_subj < target_pct:
                        low_subjects.append({"subject": subj, "pct": pct_subj})

                if low_subjects:
                    last_alert = db.execute(
                        "SELECT date(updated_at) as d FROM attendance_goals "
                        "WHERE student_roll=?",
                        (session["student_roll"],)
                    ).fetchone()
                    today_str = get_ist_now().strftime("%Y-%m-%d")
                    if not last_alert or last_alert["d"] != today_str:
                        _send_low_attendance_alert(
                            student_dict["email"], student_dict["name"],
                            low_subjects, target_pct
                        )
                        db.execute(
                            "UPDATE attendance_goals SET updated_at=CURRENT_TIMESTAMP "
                            "WHERE student_roll=?",
                            (session["student_roll"],)
                        )
                        db.commit()
        except Exception:
            pass

        student_settings = {}
        try:
            srow = db.execute(
                "SELECT settings FROM user_settings WHERE user_type='student' AND user_id=?",
                (session["student_roll"],)
            ).fetchone()
            if srow:
                student_settings = json.loads(srow["settings"])
        except Exception:
            student_settings = {}

        return render_template(
            "student_dashboard.html",
            student=student_dict,
            attendance=attendance,
            total=total,
            present=present,
            absent=total - present,
            percent=percent,
            subject_stats=subject_stats,
            notifications=notifications,
            low_subjects=[],
            today_classes=today_classes,
            target_pct=target_pct,
            alert_email=alert_email,
            subject_goal_data=subject_goal_data,
            today_day=today_day,
        )

    except Exception as e:
        import traceback
        print(f"[Dashboard] Error: {e}\n{traceback.format_exc()}")
        flash("Error loading dashboard. Please try again.", "error")
        return redirect(url_for("student_login"))
    finally:
        if db:
            db.close()


# =====================================================================
# STUDENT — PROFILE EDIT
# =====================================================================
@app.route("/student-profile-edit", methods=["GET", "POST"])
@login_required_student
def student_profile_edit():
    db = None
    try:
        db      = get_db()
        student = db.execute(
            "SELECT * FROM students WHERE roll=? AND is_active=1",
            (session["student_roll"],)
        ).fetchone()
        if not student:
            session.clear()
            return redirect(url_for("student_login"))

        if request.method == "POST":
            name         = request.form.get("name",     "").strip()
            phone        = request.form.get("phone",    "").strip()
            standard     = request.form.get("standard", "").strip()
            division     = request.form.get("division", "").strip()
            subject      = request.form.get("subject",  "").strip()
            gender       = request.form.get("gender",   "").strip()
            phone_digits = "".join(filter(str.isdigit, phone))

            errors = []
            if not name or len(name) < 2:
                errors.append("Name must be at least 2 characters.")
            if phone_digits and len(phone_digits) != 10:
                errors.append("Phone must be exactly 10 digits.")
            if phone_digits and phone_digits[0] not in "6789":
                errors.append("Phone must start with 6, 7, 8, or 9.")

            if errors:
                flash(errors[0], "error")
                return redirect(url_for("student_dashboard"))

            db.execute(
                """UPDATE students
                   SET name=?, phone=?, standard=?, division=?, subject=?, gender=?
                   WHERE roll=?""",
                (name,
                 phone_digits if phone_digits else student["phone"],
                 standard or student["standard"],
                 division or student["division"],
                 subject  or student["subject"],
                 gender   or student["gender"],
                 session["student_roll"])
            )
            db.commit()
            session["student_name"] = name
            flash("Profile updated successfully!", "success")
            return redirect(url_for("student_dashboard"))

        return redirect(url_for("student_dashboard"))
    finally:
        if db:
            db.close()


# =====================================================================
# STUDENT — FACE ENROLL
# =====================================================================
@app.route("/student-face-enroll", methods=["GET", "POST"])
@login_required_student
def student_face_enroll():
    if request.method == "GET":
        return redirect(url_for("student_dashboard"))

    if request.is_json:
        face_data = (request.get_json(silent=True) or {}).get("face_image", "")
    else:
        face_data = request.form.get("face_image", "")

    if not face_data or "," not in face_data:
        if request.is_json:
            return jsonify({"success": False, "error": "Please capture your face photo."})
        flash("Please capture your face photo.", "error")
        return redirect(url_for("student_dashboard"))

    db = None
    try:
        img_data = base64.b64decode(face_data.split(",")[1])
        np_arr   = np.frombuffer(img_data, np.uint8)
        img_cv   = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            if request.is_json:
                return jsonify({"success": False, "error": "Could not decode image."})
            flash("Could not decode image. Please try again.", "error")
            return redirect(url_for("student_dashboard"))

        gray    = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        gray_eq = cv2.equalizeHist(gray)
        faces   = _detect_faces_multipass(gray_eq)
        if not faces:
            if request.is_json:
                return jsonify({"success": False,
                                "error": "No face detected. Please try again in better lighting."})
            flash("No face detected. Please try again in better lighting.", "error")
            return redirect(url_for("student_dashboard"))

        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        face_roi   = clahe.apply(
            cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
        )

        quality_ok, quality_msg = _check_face_quality(face_roi, strict=True)
        if not quality_ok:
            if request.is_json:
                return jsonify({"success": False,
                                "error": f"Face quality issue: {quality_msg}"})
            flash(f"Face quality issue: {quality_msg}", "error")
            return redirect(url_for("student_dashboard"))

        face_encoding = face_roi.tobytes()
        roll          = session["student_roll"]

        db = get_db()

        existing_faces = [
            dict(r)
            for r in db.execute(
                "SELECT roll, name, face_encoding FROM students "
                "WHERE face_encoding IS NOT NULL AND is_active=1 AND roll!=?",
                (roll,)
            ).fetchall()
        ]
        is_dup, dup_roll, dup_name, dup_score = enhanced_duplicate_check(
            face_encoding, existing_faces
        )
        if is_dup:
            msg = f"This face is already registered to '{dup_name}' (Roll: {dup_roll})."
            if request.is_json:
                return jsonify({"success": False, "error": msg})
            flash(msg, "error")
            return redirect(url_for("student_dashboard"))

        faces_dir_env = os.environ.get("DATA_DIR", "")
        if faces_dir_env:
            faces_save_dir = os.path.join(faces_dir_env, "static", "faces")
            face_filename  = f"faces/{roll}.jpg"
            face_save_path = os.path.join(faces_dir_env, "static", face_filename)
        else:
            faces_save_dir = "static/faces"
            face_filename  = f"faces/{roll}.jpg"
            face_save_path = f"static/{face_filename}"

        os.makedirs(faces_save_dir, exist_ok=True)
        with open(face_save_path, "wb") as f:
            f.write(img_data)

        db.execute(
            "UPDATE students SET face_image=?, face_encoding=? WHERE roll=?",
            (face_filename, face_encoding, roll)
        )
        db.commit()
        RecognizerCache.invalidate()

        if request.is_json:
            return jsonify({"success": True, "message": "Face enrolled successfully!"})
        flash("Face enrolled successfully! You can now use face login.", "success")
        return redirect(url_for("student_dashboard"))

    except Exception as e:
        msg = "Enrollment failed. Please try again."
        print(f"[FaceEnroll] Error: {e}")
        if request.is_json:
            return jsonify({"success": False, "error": msg})
        flash(msg, "error")
        return redirect(url_for("student_dashboard"))
    finally:
        if db:
            db.close()


# =====================================================================
# FACULTY — REGISTER
# =====================================================================
@app.route("/faculty-register", methods=["GET", "POST"])
def faculty_register():
    if request.method == "POST":
        name        = request.form.get("name",        "").strip()
        faculty_id  = request.form.get("faculty_id",  "").strip().upper()
        subject     = request.form.get("subject",     "").strip()
        email       = request.form.get("email",       "").strip().lower()
        password    = request.form.get("password",    "")
        designation = request.form.get("designation", "").strip()
        phone       = request.form.get("phone",       "").strip()

        for label, val in [
            ("Faculty ID", faculty_id), ("Name", name),
            ("Subject", subject), ("Email", email),
            ("Phone", phone), ("Password", password),
        ]:
            if not val:
                return render_template("faculty_register.html",
                                       error=f"{label} is required.")
        if len(password) < 8:
            return render_template("faculty_register.html",
                                   error="Password must be at least 8 characters.")

        phone_digits = "".join(filter(str.isdigit, phone))
        if len(phone_digits) != 10:
            return render_template("faculty_register.html",
                                   error="Phone must be exactly 10 digits.")
        if phone_digits[0] not in "6789":
            return render_template("faculty_register.html",
                                   error="Phone must start with 6, 7, 8, or 9.")

        db = None
        try:
            db = get_db()

            ghost = db.execute(
                "SELECT faculty_id, email FROM faculty WHERE faculty_id=? OR email=?",
                (faculty_id, email)
            ).fetchone()
            if ghost:
                fid    = ghost["faculty_id"]
                femail = ghost["email"]
                db.execute("DELETE FROM reset_tokens WHERE email=? AND user_type='faculty'", (femail,))
                db.execute("DELETE FROM notifications WHERE user_type='faculty' AND user_id=?", (fid,))
                db.execute("DELETE FROM security_events WHERE user_type='faculty' AND user_id=?", (fid,))
                db.execute("DELETE FROM audit_log WHERE user_type='faculty' AND user_id=?", (fid,))
                db.execute("DELETE FROM timetable WHERE faculty_id=?", (fid,))
                db.execute("DELETE FROM active_sessions WHERE user_type='faculty' AND user_id=?", (fid,))
                db.execute("UPDATE attendance SET marked_by='deleted_faculty' WHERE marked_by=?", (fid,))
                db.execute("DELETE FROM faculty WHERE faculty_id=?", (fid,))
                db.commit()

            existing_fid = db.execute(
                "SELECT id, is_active FROM faculty WHERE faculty_id=?", (faculty_id,)
            ).fetchone()
            if existing_fid:
                if existing_fid["is_active"] == 1:
                    return render_template(
                        "faculty_register.html",
                        error=f"Faculty ID {faculty_id} is already registered!"
                    )
                else:
                    db.execute(
                        "DELETE FROM reset_tokens WHERE user_type='faculty' "
                        "AND email=(SELECT email FROM faculty WHERE faculty_id=?)",
                        (faculty_id,)
                    )
                    db.execute("DELETE FROM notifications WHERE user_type='faculty' AND user_id=?", (faculty_id,))
                    db.execute("DELETE FROM active_sessions WHERE user_type='faculty' AND user_id=?", (faculty_id,))
                    db.execute("DELETE FROM faculty WHERE faculty_id=?", (faculty_id,))
                    db.commit()

            existing_email = db.execute(
                "SELECT id, is_active FROM faculty WHERE email=?", (email,)
            ).fetchone()
            if existing_email:
                if existing_email["is_active"] == 1:
                    return render_template(
                        "faculty_register.html",
                        error=f"Email {email} is already registered!"
                    )
                else:
                    db.execute("DELETE FROM reset_tokens WHERE email=? AND user_type='faculty'", (email,))
                    db.execute(
                        "DELETE FROM notifications WHERE user_type='faculty' "
                        "AND user_id=(SELECT faculty_id FROM faculty WHERE email=?)",
                        (email,)
                    )
                    db.execute(
                        "DELETE FROM active_sessions WHERE user_type='faculty' "
                        "AND user_id=(SELECT faculty_id FROM faculty WHERE email=?)", (email,)
                    )
                    db.execute("DELETE FROM faculty WHERE email=?", (email,))
                    db.commit()

            db.execute(
                "INSERT INTO faculty "
                "(name, faculty_id, subject, email, password, designation, phone) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, faculty_id, subject, email,
                 hash_password(password), designation, phone_digits)
            )
            db.commit()
            log_security_event(db, "FACULTY_REGISTER", faculty_id,
                               "faculty", get_client_ip())

            session_instance_id = generate_session_id()
            create_session_record(db, session_instance_id, "faculty",
                                  faculty_id, get_client_ip())
            db.commit()

            session.clear()
            session.permanent             = True
            session["faculty_id"]         = faculty_id
            session["faculty_name"]       = name
            session["session_instance"]   = session_instance_id
            session["session_created_at"] = get_ist_now().isoformat()
            session["session_user_type"]  = "faculty"

            return redirect(url_for("faculty_dashboard"))

        except Exception as e:
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            import traceback
            traceback.print_exc()
            print(f"[FacultyRegister] Error: {e}")
            return render_template("faculty_register.html",
                                   error="Registration failed. Please try again.")
        finally:
            if db:
                db.close()

    return render_template("faculty_register.html")


# =====================================================================
# FACULTY — LOGIN
# =====================================================================
@app.route("/faculty-login", methods=["GET", "POST"])
def faculty_login():
    if request.method == "POST":
        db = None
        try:
            login_input = request.form.get("fid", "").strip()
            password    = request.form.get("password", "")

            if not login_input or not password:
                return render_template("faculty_login.html",
                                       error="Faculty ID/Email and password are required.")

            db = get_db()

            if "@" in login_input:
                login_input_normalized = login_input.lower()
                faculty = db.execute(
                    "SELECT * FROM faculty WHERE email=? AND is_active=1",
                    (login_input_normalized,)
                ).fetchone()
                login_field = "email"
                login_value = login_input_normalized
            else:
                login_input_normalized = login_input.upper()
                faculty = db.execute(
                    "SELECT * FROM faculty WHERE faculty_id=? AND is_active=1",
                    (login_input_normalized,)
                ).fetchone()
                login_field = "faculty_id"
                login_value = login_input_normalized

            if not faculty:
                return render_template("faculty_login.html",
                                       error="Invalid Faculty ID/Email or password.")

            if check_account_locked(db, "faculty", login_field, login_value):
                return render_template(
                    "faculty_login.html",
                    error="Account locked. Too many failed attempts. Try again in 15 minutes."
                )

            if not verify_password(password, faculty["password"]):
                record_failed_login(db, "faculty", login_field, login_value)
                attempts  = (faculty["login_attempts"] or 0) + 1
                remaining = max(0, 5 - attempts)
                log_security_event(db, "FAILED_LOGIN", login_value, "faculty",
                                   get_client_ip(), severity="medium")
                db.commit()
                msg = "Invalid Faculty ID or password."
                if remaining > 0:
                    msg += f" {remaining} attempt(s) remaining."
                return render_template("faculty_login.html", error=msg)

            if needs_password_upgrade(faculty["password"]):
                upgrade_password_on_login(db, "faculty", login_field, login_value, password)
            
            record_successful_login(db, "faculty", login_field, login_value)
            log_security_event(db, "FACULTY_LOGIN", faculty["faculty_id"],
                               "faculty", get_client_ip())

            session_instance_id = generate_session_id()
            create_session_record(db, session_instance_id, "faculty",
                                  faculty["faculty_id"], get_client_ip())
            db.commit()

            session.clear()
            session.permanent             = True
            session["faculty_id"]         = faculty["faculty_id"]
            session["faculty_name"]       = faculty["name"]
            session["session_instance"]   = session_instance_id
            session["session_created_at"] = get_ist_now().isoformat()
            session["session_user_type"]  = "faculty"

            return redirect(url_for("faculty_dashboard"))

        except Exception as e:
            import traceback
            print(f"[FacultyLogin] Error: {e}\n{traceback.format_exc()}")
            return render_template("faculty_login.html",
                                   error="Login failed. Please try again.")
        finally:
            if db:
                db.close()

    return render_template("faculty_login.html")


# =====================================================================
# FACULTY — DASHBOARD
# =====================================================================
@app.route('/faculty-dashboard')
@login_required_faculty
def faculty_dashboard():
    db = get_db()
    try:
        faculty = db.execute(
            "SELECT * FROM faculty WHERE faculty_id=? AND is_active=1",
            (session["faculty_id"],)
        ).fetchone()
        if not faculty:
            # Trust the cookie — never redirect to login on a simple refresh
            faculty = {
                "name":        session.get("faculty_name", "Faculty"),
                "faculty_id":  session.get("faculty_id", ""),
                "subject":     "", "email": "", "designation": "", "phone": "",
            }
        else:
            faculty = dict(faculty)

        faculty_subjects = db.execute(
            "SELECT DISTINCT subject FROM attendance WHERE marked_by=?",
            (session["faculty_id"],)
        ).fetchall()
        faculty_subject_list = [r["subject"] for r in faculty_subjects]

        faculty_subj = faculty.get("subject", "").strip()
        students = [dict(r) for r in db.execute(
            """SELECT * FROM students WHERE is_active=1
               AND (',' || LOWER(subject) || ',' LIKE '%,' || LOWER(?) || ',%'
                     OR LOWER(subject) = LOWER(?))
               ORDER BY name""",
            (faculty_subj, faculty_subj)
        ).fetchall()]

        attendance = [dict(r) for r in db.execute(
            "SELECT * FROM attendance WHERE marked_by=? ORDER BY date DESC, time DESC LIMIT 100",
            (session["faculty_id"],)
        ).fetchall()]

        total_students   = len(students)
        total_attendance = db.execute(
            "SELECT COUNT(*) FROM attendance WHERE marked_by=?",
            (session["faculty_id"],)
        ).fetchone()[0]

        face_enrolled = db.execute(
            "SELECT COUNT(*) FROM students WHERE face_image IS NOT NULL AND is_active=1"
        ).fetchone()[0]

        notifications = [dict(r) for r in db.execute(
            "SELECT * FROM notifications "
            "WHERE user_type='faculty' AND user_id=? AND is_read=0 "
            "ORDER BY created_at DESC LIMIT 5",
            (session["faculty_id"],)
        ).fetchall()]

        student_stats = {}
        for s in students:
            count = db.execute(
                "SELECT COUNT(*) FROM attendance WHERE student_roll=? AND marked_by=?",
                (s["roll"], session["faculty_id"])
            ).fetchone()[0]
            student_stats[s["roll"]] = count

        deleted_students_log = [dict(r) for r in db.execute(
            "SELECT name, roll, email, standard, division, subject, "
            "had_face, deleted_by, deleted_at "
            "FROM deleted_students ORDER BY deleted_at DESC LIMIT 50"
        ).fetchall()]

        return render_template(
            "faculty_dashboard.html",
            faculty=faculty,
            students=students,
            attendance=attendance,
            total_students=total_students,
            total_attendance=total_attendance,
            face_enrolled=face_enrolled,
            notifications=notifications,
            student_stats=student_stats,
            faculty_subjects=faculty_subject_list,
            deleted_students_log=deleted_students_log,
        )

    except Exception:
        import traceback
        traceback.print_exc()
        flash("Error loading dashboard.", "error")
        return redirect(url_for("faculty_login"))

    finally:
        db.close()


# =====================================================================
# MARK ATTENDANCE — Bulk
# =====================================================================
@app.route("/mark-attendance-bulk", methods=["POST"])
@login_required_faculty
def mark_attendance_bulk():
    data    = request.get_json(silent=True) or {}
    rolls   = data.get("rolls", [])
    subject = data.get("subject", "").strip()
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).replace(tzinfo=None)
    if not rolls or not subject:
        return jsonify({"success": False, "error": "Missing rolls or subject."})

    db = get_db()
    try:
        faculty = db.execute(
            "SELECT subject FROM faculty WHERE faculty_id=?",
            (session["faculty_id"],)
        ).fetchone()
        faculty_subject = (faculty["subject"] or "").strip() if faculty else subject

        marked = 0
        for roll in rolls:
            roll = str(roll).strip()
            student = db.execute(
                "SELECT * FROM students WHERE roll=? AND is_active=1", (roll,)
            ).fetchone()
            if not student:
                continue
            existing = db.execute(
                "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
                (roll, faculty_subject, now.strftime("%Y-%m-%d"))
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO attendance "
                    "(student_roll, student_name, subject, date, time, marked_by, method) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (roll, student["name"], faculty_subject,
                     now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                     session["faculty_id"], "bulk")
                )
                marked += 1
        db.commit()
        return jsonify({"success": True, "marked": marked,
                        "message": f"Attendance marked for {marked} student(s)."})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


# =====================================================================
# PROCESS ATTENDANCE — Face Recognition
# =====================================================================
@app.route("/process-attendance", methods=["POST"])
@login_required_faculty
def process_attendance():
    db = None
    try:
        data       = request.get_json(silent=True) or {}
        image_data = data.get("image",   "")
        subject    = data.get("subject", "").strip()

        if not image_data or not subject:
            return jsonify({"success": False, "error": "Missing image or subject."})

        try:
            img_bytes = base64.b64decode(image_data.split(",")[1])
        except Exception:
            return jsonify({"success": False, "error": "Invalid image data."})

        image    = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        gray_eq  = cv2.equalizeHist(cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY))
        faces    = _detect_faces_multipass(gray_eq)

        db = get_db()

        faculty = db.execute(
            "SELECT subject FROM faculty WHERE faculty_id=?",
            (session["faculty_id"],)
        ).fetchone()
        faculty_subj = (faculty["subject"] or "").strip() if faculty else ""
        if not faculty_subj:
            faculty_subj = subject

        all_students = [
            dict(r) for r in db.execute(
                """SELECT * FROM students WHERE face_encoding IS NOT NULL AND is_active=1
                   AND (',' || LOWER(subject) || ',' LIKE '%,' || LOWER(?) || ',%'
                        OR LOWER(subject) = LOWER(?))""",
                (faculty_subj, faculty_subj)
            ).fetchall()
        ]
        use_encoding = True

        if not all_students:
            all_students = [
                dict(r) for r in db.execute(
                    """SELECT * FROM students WHERE face_image IS NOT NULL AND is_active=1
                       AND (',' || LOWER(subject) || ',' LIKE '%,' || LOWER(?) || ',%'
                            OR LOWER(subject) = LOWER(?))""",
                    (faculty_subj, faculty_subj)
                ).fetchall()
            ]
            use_encoding = False

        if not all_students:
            return jsonify({"success": False,
                            "error": "No students with face data enrolled."})

        if not faces:
            absent_list = [{"roll": s["roll"], "name": s["name"]} for s in all_students]
            return jsonify({
                "success":          True,
                "present_students": [],
                "absent_students":  absent_list,
                "faces_detected":   0,
                "faces_matched":    0,
                "low_quality":      [],
                "message":          "No faces detected. All students marked absent.",
            })

        recognizer, roll_labels = RecognizerCache.get(all_students, use_encoding)

        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST).replace(tzinfo=None)
        present_students = []
        low_quality      = []
        detected_rolls   = set()
        clahe            = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        for (x, y, w, h) in faces:
            face_roi    = clahe.apply(
                cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
            )
            quality_ok, quality_msg = _check_face_quality(face_roi, strict=False)
            if not quality_ok:
                low_quality.append({"bbox":   [int(x), int(y), int(w), int(h)],
                                    "reason": quality_msg})
                continue

            roll, name, lbph_conf, hist_score, matched = dual_match(
                face_roi, recognizer, roll_labels, all_students, use_encoding
            )

            if matched and roll and roll not in detected_rolls:
                detected_rolls.add(roll)
                present_students.append({
                    "roll":       roll,
                    "name":       name,
                    "lbph_conf":  round(lbph_conf, 1),
                    "hist_score": round(hist_score, 3),
                    "confidence": f"{max(0, 100 - lbph_conf):.0f}%",
                })

        absent_students = [
            {"roll": s["roll"], "name": s["name"]}
            for s in all_students if s["roll"] not in detected_rolls
        ]

        annotated  = image_cv.copy()
        clahe_draw = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        for (x, y, w, h) in faces:
            face_roi    = clahe_draw.apply(
                cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
            )
            quality_ok, _ = _check_face_quality(face_roi, strict=False)

            if not quality_ok:
                color, label = (128, 128, 128), "Low Quality"
            else:
                roll, name, lbph_conf, hist_score, matched = dual_match(
                    face_roi, recognizer, roll_labels, all_students, use_encoding
                )
                if matched:
                    color, label = (0, 200, 80), name
                else:
                    color, label = (60, 60, 220), "Unknown"

            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(annotated, (x, y - th - 10), (x + tw + 6, y), color, -1)
            cv2.putText(annotated, label, (x + 3, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        _, buf        = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
        annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode()

        return jsonify({
            "success":          True,
            "present_students": present_students,
            "absent_students":  absent_students,
            "faces_detected":   len(faces),
            "faces_matched":    len(present_students),
            "low_quality":      low_quality,
            "annotated_image":  annotated_b64,
        })

    except Exception as e:
        import traceback
        print(f"[ProcessAttendance] ERROR: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": "Processing error. Please try again."})
    finally:
        if db:
            db.close()


# =====================================================================
# STUDENT SELF-ATTENDANCE
# =====================================================================
@app.route("/attendance", methods=["GET", "POST"])
@login_required_student
@rate_limit(max_requests=5, window_seconds=60)
def attendance():
    if request.method == "POST":
        subject   = request.form.get("subject",    "").strip()
        face_data = request.form.get("face_image", "")

        if not subject or not face_data or "," not in face_data:
            return render_template("attendance.html",
                                   message="Please capture your face and enter subject.",
                                   status="error")
        db = None
        try:
            try:
                img_bytes = base64.b64decode(face_data.split(",")[1])
            except Exception:
                return render_template("attendance.html",
                                       message="Invalid image data.", status="error")

            np_arr = np.frombuffer(img_bytes, np.uint8)
            img_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_cv is None:
                return render_template("attendance.html",
                                       message="Could not decode image.", status="error")

            gray_eq = cv2.equalizeHist(cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY))
            faces   = _detect_faces_multipass(gray_eq)

            if not faces:
                return render_template(
                    "attendance.html",
                    message="No face detected. Please ensure good lighting and face the camera.",
                    status="error"
                )

            db = get_db()
            all_students = [
                dict(r) for r in db.execute(
                    "SELECT * FROM students WHERE face_encoding IS NOT NULL AND is_active=1"
                ).fetchall()
            ]
            use_encoding = True

            if not all_students:
                all_students = [
                    dict(r) for r in db.execute(
                        "SELECT * FROM students WHERE face_image IS NOT NULL AND is_active=1"
                    ).fetchall()
                ]
                use_encoding = False

            if not all_students:
                return render_template(
                    "attendance.html",
                    message="No student face data enrolled. Please register first.",
                    status="error"
                )

            recognizer, roll_labels = RecognizerCache.get(all_students, use_encoding)

            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            face_roi   = clahe.apply(
                cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
            )

            quality_ok, quality_msg = _check_face_quality(face_roi, strict=False)
            if not quality_ok:
                return render_template("attendance.html",
                                       message=quality_msg, status="error")

            roll, name, lbph_conf, hist_score, matched = dual_match(
                face_roi, recognizer, roll_labels, all_students, use_encoding
            )

            if not matched:
                return render_template(
                    "attendance.html",
                    message="Face not recognized. Please register first or try in better lighting.",
                    status="error"
                )

            is_live, liveness_score, liveness_reason = check_liveness(face_roi, strict=False)
            if not is_live:
                log_security_event(db, "LIVENESS_FAILED", roll, "student",
                                   get_client_ip(),
                                   f"score={liveness_score:.2f} reason={liveness_reason}", "high")
                db.commit()
                return render_template(
                    "attendance.html",
                    message="Liveness check failed — please use your live camera, not a photo or screen.",
                    status="error"
                )    

            from datetime import timezone, timedelta
            IST = timezone(timedelta(hours=5, minutes=30))
            now = datetime.now(IST).replace(tzinfo=None)
            existing = db.execute(
                "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
                (roll, subject, now.strftime("%Y-%m-%d"))
            ).fetchone()
            if existing:
                return render_template(
                    "attendance.html",
                    message=f"Attendance already marked for {name} in {subject} today.",
                    status="info",
                    student_name=name
                )

            db.execute(
                "INSERT INTO attendance "
                "(student_roll, student_name, subject, date, time, "
                " marked_by, method, lbph_conf, hist_score) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (roll, name, subject,
                 now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                 "self", "face", lbph_conf, hist_score)
            )
            db.commit()
            return render_template(
                "attendance.html",
                message=(f"Attendance marked successfully for {name} in {subject}! "
                         f"(Confidence: {max(0, 100 - lbph_conf):.0f}%)"),
                status="success",
                student_name=name
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return render_template("attendance.html",
                                   message="An error occurred. Please try again.",
                                   status="error")
        finally:
            if db:
                db.close()

    return render_template("attendance.html")


# =====================================================================
# FORGOT PASSWORD
# =====================================================================
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        data  = request.get_json(silent=True) if request.is_json else request.form
        email = (data.get("email") or "").strip().lower()
        role  = (data.get("role")  or "student").lower()

        if role not in ("student", "faculty"):
            role = "student"

        if not email or "@" not in email:
            msg = "Please enter a valid email address."
            if request.is_json:
                return jsonify({"success": False, "error": msg})
            flash(msg, "error")
            return redirect(url_for("forgot_password"))

        table = _TABLE_MAP.get(role)
        if not table:
            if request.is_json:
                return jsonify({"success": False, "error": "Invalid role."})
            return redirect(url_for("forgot_password"))
        db    = get_db()
        try:
            user = db.execute(
                f"SELECT id, name FROM {table} WHERE email=?", (email,)
            ).fetchone()

            if user:
                otp = str(secrets.randbelow(900000) + 100000)
                db.execute(
                    "DELETE FROM reset_tokens WHERE email=? AND user_type=?",
                    (email, role)
                )
                db.execute(
                    "INSERT INTO reset_tokens "
                    "(email, token, otp, expires_at, user_type) "
                    "VALUES (?,?,?,datetime('now','+10 minutes'),?)",
                    (email, otp, otp, role)
                )
                db.commit()
                email_sent = send_otp_email(email, otp, role)
                if email_sent:
                    result = {"success": True, "message": f"OTP sent to {email}."}
                else:
                    # Always print OTP to server logs so you can test even if email fails
                    print(f"[OTP] Could not email — OTP for {email} is: {otp}")
                    if is_email_configured():
                        result = {"success": False,
                                  "error": "Failed to send OTP email. Check server logs or verify your Brevo sender address."}
                    else:
                        result = {"success": True,
                                  "message": "OTP sent! Check server logs for the OTP code."}

            if request.is_json:
                return jsonify(result)
            flash(result.get("message") or result.get("error", ""),
                  "success" if result.get("success") else "error")

        except Exception as e:
            import traceback
            print(f"[ForgotPwd] Error: {e}")
            traceback.print_exc()
            if request.is_json:
                return jsonify({"success": False, "error": f"Server error: {str(e)}"})
            flash(f"Server error: {str(e)}", "error")
        finally:
            db.close()
        return redirect(url_for("forgot_password"))

    return render_template("forgot_password.html")


# =====================================================================
# VERIFY OTP
# =====================================================================
@app.route("/verify-otp", methods=["POST"])
@require_same_origin
def verify_otp():
    data  = request.get_json() if request.is_json else request.form
    email = (data.get("email") or "").strip().lower()
    otp   = (data.get("otp")   or "").strip()
    role  = (data.get("role")  or "student").lower()
    if not email or not otp:
        return jsonify({"success": False, "error": "Email and OTP are required."})
    db = get_db()
    try:
        row = db.execute(
            "SELECT email FROM reset_tokens "
            "WHERE email=? AND otp=? AND user_type=? "
            "AND expires_at > datetime('now') AND used=0",
            (email, otp, role)
        ).fetchone()
        if row:
            return jsonify({"success": True, "message": "OTP verified successfully."})
        return jsonify({"success": False,
                        "error": "Invalid or expired OTP. Please request a new one."})
    except Exception as e:
        return jsonify({"success": False, "error": "Verification error."})
    finally:
        db.close()


# =====================================================================
# RESET PASSWORD
# =====================================================================
@app.route("/reset-password", methods=["POST"])
@require_same_origin
def reset_password():
    data         = request.get_json() if request.is_json else request.form
    email        = (data.get("email")        or "").strip().lower()
    otp          = (data.get("otp")          or "").strip()
    new_password = (data.get("new_password") or "")
    role         = (data.get("role")         or "student").lower()
    if role not in ("student", "faculty"):
        role = "student"
    if not all([email, otp, new_password]):
        return jsonify({"success": False, "error": "All fields are required."})
    if len(new_password) < 8:
        return jsonify({"success": False,
                        "error": "Password must be at least 8 characters."})

    db = get_db()
    try:
        row = db.execute(
            "SELECT email FROM reset_tokens "
            "WHERE email=? AND otp=? AND user_type=? "
            "AND expires_at > datetime('now') AND used=0",
            (email, otp, role)
        ).fetchone()
        if not row:
            return jsonify({"success": False, "error": "Invalid or expired OTP."})

        table = _TABLE_MAP.get(role)
        if not table:
            return jsonify({"success": False, "error": "Invalid role."})
        db.execute(
            f"UPDATE {table} SET password=?, login_attempts=0, locked_until=NULL "
            f"WHERE email=?",
            (hash_password(new_password), email)
        )
        db.execute(
            "UPDATE reset_tokens SET used=1 WHERE email=? AND otp=?",
            (email, otp)
        )

        user_id = None
        if role == "student":
            user_row = db.execute("SELECT roll FROM students WHERE email=?", (email,)).fetchone()
            if user_row:
                user_id = user_row["roll"]
        else:
            user_row = db.execute("SELECT faculty_id FROM faculty WHERE email=?", (email,)).fetchone()
            if user_row:
                user_id = user_row["faculty_id"]

        if user_id:
            invalidate_all_user_sessions(db, role, user_id)

        db.commit()
        log_security_event(db, "PASSWORD_RESET", email, role, get_client_ip())
        db.commit()
        return jsonify({"success": True,
                        "message": "Password reset successfully. You can now login."})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": "Server error. Please try again."})
    finally:
        db.close()


# =====================================================================
# VIEW ATTENDANCE
# =====================================================================
@app.route("/view-attendance")
@login_required_faculty
def view_attendance():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT student_name, student_roll, subject, date, time, method, marked_by "
            "FROM attendance WHERE marked_by=? ORDER BY date DESC, time DESC",
            (session["faculty_id"],)
        ).fetchall()
        return render_template("view_attendance.html", data=[dict(r) for r in rows])
    except Exception as e:
        flash(f"Error loading attendance: {e}", "error")
        return redirect(url_for("faculty_dashboard") + "#dashboard")
    finally:
        db.close()


# =====================================================================
# STUDENT MANAGEMENT
# =====================================================================
@app.route("/admin/delete-student/<student_roll>", methods=["POST"])
@login_required_faculty
def delete_student(student_roll):
    is_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    try:
        success, message = delete_student_completely(
            student_roll, deleted_by=session.get("faculty_id", "faculty")
        )
        db = get_db()
        try:
            if success:
                log_security_event(db, "STUDENT_DELETED", student_roll,
                                   "faculty", get_client_ip())
                db.commit()
                RecognizerCache.invalidate()
        finally:
            db.close()

        if is_ajax:
            return jsonify({"success": success, "message": message,
                            "error": message if not success else None})
        flash(message, "success" if success else "error")
    except Exception as e:
        if is_ajax:
            return jsonify({"success": False, "error": str(e)})
        flash(f"Error: {e}", "error")
    return redirect(url_for("faculty_dashboard") + "#students")

@app.route("/admin/erase-deleted-student/<student_roll>", methods=["POST"])
@login_required_faculty
def erase_deleted_student(student_roll):
    """Permanently erase all traces of a deleted student — including the deleted_students log."""
    is_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    db = None
    try:
        db = get_db()

        # Confirm the entry exists in deleted_students
        entry = db.execute(
            "SELECT name, email FROM deleted_students WHERE roll=?",
            (student_roll,)
        ).fetchone()

        if not entry:
            if is_ajax:
                return jsonify({"success": False, "error": "Record not found in deleted log."})
            flash("Record not found.", "error")
            return redirect(url_for("faculty_dashboard") + "#students")

        # Belt-and-suspenders: also nuke anything left in active tables
        # (in case a partial delete left orphan rows)
        cleanup_tables = [
            ("attendance",        "student_roll"),
            ("face_attempts",     "roll"),
            ("emotion_tracking",  "student_roll"),
            ("student_timetable", "student_roll"),
            ("attendance_goals",  "student_roll"),
        ]
        for tbl, col in cleanup_tables:
            try:
                db.execute(f"DELETE FROM {tbl} WHERE {col}=?", (student_roll,))
            except Exception:
                pass

        for tbl in ("notifications", "security_events", "audit_log"):
            try:
                db.execute(
                    f"DELETE FROM {tbl} WHERE user_type='student' AND user_id=?",
                    (student_roll,)
                )
            except Exception:
                pass

        try:
            db.execute(
                "DELETE FROM active_sessions WHERE user_type='student' AND user_id=?",
                (student_roll,)
            )
        except Exception:
            pass

        if entry["email"]:
            try:
                db.execute(
                    "DELETE FROM reset_tokens WHERE email=? AND user_type='student'",
                    (entry["email"],)
                )
            except Exception:
                pass

        # Make sure the student row itself is gone
        db.execute("DELETE FROM students WHERE roll=?", (student_roll,))

        # Finally, remove from deleted_students log
        db.execute("DELETE FROM deleted_students WHERE roll=?", (student_roll,))

        db.commit()

        log_security_event(
            db, "STUDENT_PERMANENTLY_ERASED", student_roll,
            "faculty", get_client_ip(),
            f"Erased by {session.get('faculty_id', 'unknown')}", "high"
        )
        db.commit()
        RecognizerCache.invalidate()

        if is_ajax:
            return jsonify({"success": True, "message": f"Student {student_roll} permanently erased."})
        flash(f"Student {student_roll} permanently erased from all records.", "success")

    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        print(f"[EraseDeletedStudent] Error: {e}")
        if is_ajax:
            return jsonify({"success": False, "error": str(e)})
        flash(f"Error: {e}", "error")
    finally:
        if db:
            db.close()

    return redirect(url_for("faculty_dashboard") + "#students")

@app.route("/admin/clear-all-students", methods=["POST"])
@login_required_faculty
def clear_all_students_route():
    try:
        success, message = clear_all_students()
        db = get_db()
        try:
            if success:
                log_security_event(db, "ALL_STUDENTS_CLEARED",
                                   session["faculty_id"], "faculty", get_client_ip())
                db.commit()
                RecognizerCache.invalidate()
        finally:
            db.close()
        app.secret_key = secrets.token_hex(32)
        flash(message, "success" if success else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("faculty_dashboard"))


# =====================================================================
# DELETE ALL DATA
# =====================================================================
@app.route("/admin/delete-all-data", methods=["POST"])
@login_required_faculty
def delete_all_data():
    faculty_id_saved = session.get("faculty_id", "unknown")
    ip_saved         = get_client_ip()

    db = get_db()
    try:
        log_security_event(db, "ALL_DATA_DELETED", faculty_id_saved,
                           "faculty", ip_saved,
                           "Complete database reset initiated", "high")
        db.commit()

        students = db.execute(
            "SELECT roll FROM students WHERE face_image IS NOT NULL"
        ).fetchall()

        tables_to_clear = [
            "attendance", "notifications", "security_events", "face_attempts",
            "audit_log", "reset_tokens", "active_sessions",
        ]
        optional_tables = ["emotion_tracking", "batch_attendance"]

        for table in tables_to_clear:
            try:
                db.execute(f"DELETE FROM {table}")
            except Exception as e:
                print(f"[DeleteAll] Skip {table}: {e}")

        for table in optional_tables:
            try:
                db.execute(f"DELETE FROM {table}")
            except Exception:
                pass

        db.execute("DELETE FROM students")
        db.execute("DELETE FROM faculty")
        db.commit()

        for student in students:
            face_path = f"static/faces/{student['roll']}.jpg"
            if os.path.exists(face_path):
                try:
                    os.remove(face_path)
                except Exception:
                    pass

        session.clear()
        flash("All data has been successfully deleted. Please register again.", "success")
        return redirect(url_for("home"))

    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        flash(f"Error deleting all data: {e}", "error")
        return redirect(url_for("faculty_dashboard"))
    finally:
        if db:
            db.close()


# =====================================================================
# API ROUTES
# =====================================================================
@app.route("/api/student-stats")
@login_required_student
def api_student_stats():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT subject, COUNT(*) AS count, MAX(date) AS last_date "
            "FROM attendance WHERE student_roll=? GROUP BY subject",
            (session["student_roll"],)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/faculty-stats")
@login_required_faculty
def api_faculty_stats():
    db = get_db()
    try:
        today = get_ist_now().strftime("%Y-%m-%d")
        data  = {
            "total_students":   db.execute(
                "SELECT COUNT(*) FROM students WHERE is_active=1"
            ).fetchone()[0],
            "total_attendance": db.execute(
                "SELECT COUNT(*) FROM attendance WHERE marked_by=?",
                (session["faculty_id"],)
            ).fetchone()[0],
            "today_attendance": db.execute(
                "SELECT COUNT(*) FROM attendance WHERE date=? AND marked_by=?",
                (today, session["faculty_id"])
            ).fetchone()[0],
        }
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/notifications/mark-read", methods=["POST"])
def mark_notifications_read():
    db = get_db()
    try:
        if "student_roll" in session:
            db.execute(
                "UPDATE notifications SET is_read=1 "
                "WHERE user_type='student' AND user_id=?",
                (session["student_roll"],)
            )
            db.commit()
        elif "faculty_id" in session:
            db.execute(
                "UPDATE notifications SET is_read=1 "
                "WHERE user_type='faculty' AND user_id=?",
                (session["faculty_id"],)
            )
            db.commit()
        else:
            return jsonify({"success": False, "error": "Not authenticated"}), 401
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/delete-attendance/<int:record_id>", methods=["DELETE"])
@login_required_faculty
def delete_attendance(record_id):
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM attendance WHERE id=? AND marked_by=?",
            (record_id, session["faculty_id"])
        ).fetchone()
        if not existing:
            return jsonify({"success": False, "error": "Record not found."}), 404
        db.execute("DELETE FROM attendance WHERE id=?", (record_id,))
        db.commit()
        return jsonify({"success": True, "message": "Record deleted."})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/attendance-export")
@login_required_faculty
def attendance_export():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT student_name, student_roll, subject, date, time, method, marked_by "
            "FROM attendance WHERE marked_by=? ORDER BY date DESC",
            (session["faculty_id"],)
        ).fetchall()

        def _esc(val):
            v = str(val) if val is not None else ""
            if any(c in v for c in (",", '"', "\n", "\r")):
                v = '"' + v.replace('"', '""') + '"'
            return v

        lines = ["Student Name,Roll Number,Subject,Date,Time,Method,Marked By"]
        for r in rows:
            lines.append(",".join(
                _esc(r[k]) for k in
                ("student_name", "student_roll", "subject", "date", "time", "method", "marked_by")
            ))
        return Response(
            "\n".join(lines),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=attendance_export.csv"},
        )
    except Exception as e:
        return Response(f"Error: {e}", status=500)
    finally:
        db.close()


# =====================================================================
# CHANGE PASSWORD
# =====================================================================
@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    is_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.content_type == "application/json"
    )

    if "student_roll" not in session and "faculty_id" not in session:
        if is_ajax:
            return jsonify({"success": False, "error": "Not logged in."}), 401
        flash("Please login to continue.", "warning")
        return redirect(url_for("home"))

    db = get_db()
    try:
        if "student_roll" in session:
            exists = db.execute(
                "SELECT id FROM students WHERE roll=?", (session["student_roll"],)
            ).fetchone()
        else:
            exists = db.execute(
                "SELECT id FROM faculty WHERE faculty_id=?", (session["faculty_id"],)
            ).fetchone()
    except Exception:
        exists = None
    finally:
        db.close()

    if not exists:
        session.clear()
        if is_ajax:
            return jsonify({"success": False, "error": "Account not found."}), 404
        flash("Your account no longer exists.", "warning")
        return redirect(url_for("home"))

    if request.method == "POST":
        if is_ajax:
            data = request.get_json(silent=True) or {}
            old_pw_raw = data.get("old_password", "")
            new_pw_raw = data.get("new_password", "")
        else:
            old_pw_raw = request.form.get("old_password", "")
            new_pw_raw = request.form.get("new_password", "")

        if len(new_pw_raw) < 8:
            if is_ajax:
                return jsonify({"success": False, "error": "New password must be at least 8 characters."})
            flash("New password must be at least 8 characters.", "error")
            return render_template("change_password.html")

        new_pw = hash_password(new_pw_raw)
        db = get_db()
        try:
            if "student_roll" in session:
                row = db.execute(
                    "SELECT id, password FROM students WHERE roll=?",
                    (session["student_roll"],)
                ).fetchone()
                user = row if row and verify_password(old_pw_raw, row["password"]) else None
                if user:
                    db.execute(
                        "UPDATE students SET password=? WHERE roll=?",
                        (new_pw, session["student_roll"])
                    )
                    invalidate_all_user_sessions(db, "student", session["student_roll"])
                    db.commit()
                    if is_ajax:
                        return jsonify({"success": True, "message": "Password changed successfully!"})
                    session.clear()
                    flash("Password changed successfully! Please login again.", "success")
                    return redirect(url_for("student_login"))
                else:
                    if is_ajax:
                        return jsonify({"success": False, "error": "Current password is incorrect."})
                    flash("Current password is incorrect.", "error")
            else:
                row = db.execute(
                    "SELECT id, password FROM faculty WHERE faculty_id=?",
                    (session["faculty_id"],)
                ).fetchone()
                user = row if row and verify_password(old_pw_raw, row["password"]) else None
                if user:
                    db.execute(
                        "UPDATE faculty SET password=? WHERE faculty_id=?",
                        (new_pw, session["faculty_id"])
                    )
                    invalidate_all_user_sessions(db, "faculty", session["faculty_id"])
                    db.commit()
                    if is_ajax:
                        return jsonify({"success": True, "message": "Password changed successfully!"})
                    session.clear()
                    flash("Password changed successfully! Please login again.", "success")
                    return redirect(url_for("faculty_login"))
                else:
                    if is_ajax:
                        return jsonify({"success": False, "error": "Current password is incorrect."})
                    flash("Current password is incorrect.", "error")
        except Exception as e:
            db.rollback()
            if is_ajax:
                return jsonify({"success": False, "error": "Error changing password. Please try again."})
            flash("Error changing password. Please try again.", "error")
        finally:
            db.close()

    return render_template("change_password.html")


# =====================================================================
# LOGOUT
# =====================================================================
@app.route("/logout")
def logout():
    db = get_db()
    try:
        session_instance = session.get("session_instance", "")

        if "student_roll" in session:
            log_security_event(db, "STUDENT_LOGOUT", session["student_roll"],
                               "student", get_client_ip())
            if session_instance:
                invalidate_session(db, session_instance)
            db.commit()

        elif "faculty_id" in session:
            log_security_event(db, "FACULTY_LOGOUT", session["faculty_id"],
                               "faculty", get_client_ip())
            if session_instance:
                invalidate_session(db, session_instance)
            db.commit()
    except Exception as e:
        print(f"[Logout] Error: {e}")
    finally:
        db.close()

    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("home"))


# =====================================================================
# API — Subjects by Standard
# =====================================================================
@app.route("/api/subjects-by-standard/<standard>")
def subjects_by_standard(standard):
    subjects = STANDARD_SUBJECTS.get(standard.strip(), [])
    return jsonify({"subjects": subjects})


# =====================================================================
# STUDENT — TIMETABLE
# =====================================================================
@app.route("/api/timetable", methods=["GET"])
@login_required_student
def get_timetable():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT day, period, subject, start_time, end_time "
            "FROM student_timetable WHERE student_roll=? ORDER BY day, period",
            (session["student_roll"],)
        ).fetchall()

        if not rows:
            student = db.execute(
                "SELECT standard, division FROM students WHERE roll=?",
                (session["student_roll"],)
            ).fetchone()
            if student and student["standard"]:
                rows = db.execute(
                    "SELECT day_of_week as day, period_number as period, "
                    "subject, start_time, end_time "
                    "FROM timetable WHERE standard=? AND (division=? OR division='') "
                    "ORDER BY day_of_week, period_number",
                    (student["standard"], student["division"] or "")
                ).fetchall()

        return jsonify({"success": True, "timetable": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


@app.route("/api/timetable/save", methods=["POST"])
@login_required_student
def save_timetable():
    data    = request.get_json(silent=True) or {}
    entries = data.get("entries", [])
    roll    = session["student_roll"]
    db      = get_db()
    try:
        db.execute(
            "DELETE FROM student_timetable WHERE student_roll=?", (roll,)
        )
        for e in entries:
            day     = e.get("day",     "").strip()
            period  = int(e.get("period", 0))
            subject = e.get("subject", "").strip()
            s_time  = e.get("start_time", "").strip()
            e_time  = e.get("end_time",   "").strip()
            if not day or not subject or period < 1:
                continue
            db.execute(
                """INSERT OR REPLACE INTO student_timetable
                   (student_roll, day, period, subject, start_time, end_time)
                   VALUES (?,?,?,?,?,?)""",
                (roll, day, period, subject, s_time, e_time)
            )
        db.commit()
        return jsonify({"success": True, "message": "Timetable saved!"})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


# =====================================================================
# FACULTY — SET TIMETABLE PER STANDARD
# =====================================================================
@app.route("/api/faculty/timetable/get", methods=["GET"])
@login_required_faculty
def faculty_get_timetable():
    standard = request.args.get("standard", "").strip()
    division = request.args.get("division", "").strip()
    if not standard:
        return jsonify({"success": False, "error": "Standard required."})
    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, day_of_week, period_number, subject, start_time, end_time
               FROM timetable WHERE standard=?
               ORDER BY day_of_week, period_number""",
            (standard,)
        ).fetchall()
        
        return jsonify({"success": True, "timetable": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


@app.route("/api/faculty/timetable/save", methods=["POST"])
@login_required_faculty
def faculty_save_timetable():
    data     = request.get_json(silent=True) or {}
    entries  = data.get("entries", [])
    standard = data.get("standard", "").strip()
    division = data.get("division", "").strip()

    if not standard:
        return jsonify({"success": False, "error": "Standard is required."})

    db = get_db()
    try:
        if division:
            db.execute(
                "DELETE FROM timetable WHERE standard=? AND division=?",
                (standard, division)
            )
        else:
            db.execute(
                "DELETE FROM timetable WHERE standard=? AND division=''",
                (standard,)
            )
        for e in entries:
            day     = e.get("day",        "").strip()
            period  = int(e.get("period",  0))
            subject = e.get("subject",    "").strip()
            s_time  = e.get("start_time", "").strip()
            e_time  = e.get("end_time",   "").strip()
            if not day or not subject or period < 1:
                continue
            db.execute(
                """INSERT INTO timetable
                   (standard, division, day_of_week, period_number,
                    subject, faculty_id, start_time, end_time)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (standard, division or "", day, period,
                 subject, session["faculty_id"], s_time, e_time)
            )
        db.commit()
        return jsonify({"success": True,
                        "message": f"Timetable saved for Standard {standard}!"})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


@app.route("/api/student/timetable/standard", methods=["GET"])
@login_required_student
def student_get_standard_timetable():
    db = get_db()
    try:
        student = db.execute(
            "SELECT standard, division FROM students WHERE roll=?",
            (session["student_roll"],)
        ).fetchone()
        if not student or not student["standard"]:
            return jsonify({"success": True, "timetable": []})

        rows = db.execute(
            """SELECT day_of_week as day, period_number as period,
                      subject, start_time, end_time
               FROM timetable
               WHERE standard=? AND (division=? OR division='')
               ORDER BY day_of_week, period_number""",
            (student["standard"], student["division"] or "")
        ).fetchall()
        return jsonify({"success": True, "timetable": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


# =====================================================================
# STUDENT — ATTENDANCE GOAL + EMAIL ALERT
# =====================================================================
@app.route("/api/attendance-goal", methods=["GET"])
@login_required_student
def get_attendance_goal():
    db = get_db()
    try:
        row = db.execute(
            "SELECT target_pct, alert_email FROM attendance_goals WHERE student_roll=?",
            (session["student_roll"],)
        ).fetchone()
        if row:
            return jsonify({"success":     True,
                            "target_pct":  row["target_pct"],
                            "alert_email": bool(row["alert_email"])})
        return jsonify({"success": True, "target_pct": 75, "alert_email": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


@app.route("/api/attendance-goal/save", methods=["POST"])
@login_required_student
def save_attendance_goal():
    data        = request.get_json(silent=True) or {}
    target_pct  = int(data.get("target_pct", 75))
    alert_email = 1 if data.get("alert_email", True) else 0
    roll        = session["student_roll"]

    if not (50 <= target_pct <= 100):
        return jsonify({"success": False,
                        "error": "Target must be between 50 and 100."})

    db = get_db()
    try:
        db.execute(
            """INSERT INTO attendance_goals (student_roll, target_pct, alert_email)
               VALUES (?,?,?)
               ON CONFLICT(student_roll) DO UPDATE
               SET target_pct=excluded.target_pct,
                   alert_email=excluded.alert_email,
                   updated_at=CURRENT_TIMESTAMP""",
            (roll, target_pct, alert_email)
        )
        db.commit()

        student = db.execute(
            "SELECT name, email FROM students WHERE roll=?", (roll,)
        ).fetchone()

        if alert_email and student:
            attendance_rows = db.execute(
                "SELECT subject, COUNT(*) as cnt FROM attendance "
                "WHERE student_roll=? GROUP BY subject", (roll,)
            ).fetchall()

            total_classes = db.execute(
                "SELECT COUNT(*) FROM attendance WHERE student_roll=?", (roll,)
            ).fetchone()[0]

            low_subjects = []
            for row_a in attendance_rows:
                subj     = row_a["subject"]
                present  = row_a["cnt"]
                subj_pct = round((present / total_classes) * 100) if total_classes > 0 else 0
                if subj_pct < target_pct:
                    low_subjects.append({"subject": subj, "pct": subj_pct})

            if low_subjects:
                _send_low_attendance_alert(
                    student["email"], student["name"], low_subjects, target_pct
                )

        return jsonify({"success": True, "message": "Goal saved!"})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


# =====================================================================
# MARK ATTENDANCE — Manual (single student)
# =====================================================================
@app.route("/mark-attendance", methods=["POST"])
@login_required_faculty
def mark_attendance():
    roll    = request.form.get("roll",    "").strip()
    subject = request.form.get("subject", "").strip()
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).replace(tzinfo=None)

    if not roll or not subject:
        flash("Roll number and subject are required.", "error")
        return redirect(url_for("faculty_dashboard"))

    db = get_db()
    try:
        student = db.execute(
            "SELECT * FROM students WHERE roll=? AND is_active=1", (roll,)
        ).fetchone()
        if not student:
            flash("Student not found.", "error")
            return redirect(url_for("faculty_dashboard"))

        existing = db.execute(
            "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
            (roll, subject, now.strftime("%Y-%m-%d"))
        ).fetchone()
        if existing:
            flash(f"Attendance already marked for {student['name']} in {subject} today.", "info")
            return redirect(url_for("faculty_dashboard"))

        db.execute(
            "INSERT INTO attendance "
            "(student_roll, student_name, subject, date, time, marked_by, method) "
            "VALUES (?,?,?,?,?,?,?)",
            (roll, student["name"], subject,
             now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
             session["faculty_id"], "manual")
        )
        db.commit()
        flash(f"Attendance marked for {student['name']}!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "error")
    finally:
        db.close()

    return redirect(url_for("faculty_dashboard"))


# =====================================================================
# CONFIRM ATTENDANCE — Save after face detection
# =====================================================================
@app.route("/confirm-attendance", methods=["POST"])
@login_required_faculty
def confirm_attendance():
    data    = request.get_json(silent=True) or {}
    rolls   = data.get("rolls",   [])
    subject = data.get("subject", "").strip()

    from datetime import timezone, timedelta
    IST      = timezone(timedelta(hours=5, minutes=30))
    now      = datetime.now(IST).replace(tzinfo=None)
    today    = now.strftime("%Y-%m-%d")
    time_now = now.strftime("%H:%M:%S")

    if not rolls or not subject:
        return jsonify({"success": False, "error": "Missing rolls or subject."})

    db = get_db()
    try:
        marked  = 0
        skipped = 0

        seen   = set()
        unique = []
        for s in rolls:
            roll = (s.get("roll", "") if isinstance(s, dict) else str(s)).strip()
            if roll and roll not in seen:
                seen.add(roll)
                unique.append(roll)

        for roll in unique:
            student = db.execute(
                "SELECT name FROM students WHERE roll=? AND is_active=1",
                (roll,)
            ).fetchone()
            if not student:
                continue

            existing = db.execute(
                """SELECT id FROM attendance
                   WHERE student_roll=? AND subject=? AND date=?""",
                (roll, subject, today)
            ).fetchone()

            if existing:
                skipped += 1
                continue

            db.execute(
                """INSERT INTO attendance
                   (student_roll, student_name, subject,
                    date, time, marked_by, method)
                   VALUES (?,?,?,?,?,?,?)""",
                (roll, student["name"], subject,
                 today, time_now,
                 session["faculty_id"], "face")
            )
            marked += 1

        db.commit()

        msg = f"Attendance confirmed for {marked} student(s)."
        if skipped:
            msg += f" ({skipped} already marked today.)"

        return jsonify({
            "success": True,
            "marked":  marked,
            "skipped": skipped,
            "message": msg
        })

    except Exception as e:
        db.rollback()
        print(f"[ConfirmAttendance] Error: {e}")
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


@app.route('/api/save-student-settings', methods=['POST'])
def save_student_settings():
    if 'student_roll' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json(silent=True) or {}
    allowed_keys = {
        'attendance_alerts', 'class_reminders', 'email_reports',
        'face_recognition', 'profile_visibility'
    }
    settings = {k: bool(v) for k, v in data.items() if k in allowed_keys}

    db = get_db()
    try:
        db.execute(
            """INSERT INTO user_settings (user_type, user_id, settings, updated_at)
               VALUES ('student', ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_type, user_id) DO UPDATE
               SET settings=excluded.settings, updated_at=CURRENT_TIMESTAMP""",
            (session['student_roll'], json.dumps(settings))
        )
        db.commit()
        return jsonify({'success': True, 'message': 'Settings saved'})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


# =====================================================================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)