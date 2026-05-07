"""
app.py  ·  Vision AI v5  ·  ALL BUGS FIXED
==========================================
"""

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
    delete_faculty_completely, verify_database_integrity,
    detect_emotion, record_emotion_tracking, create_batch_attendance_record,
    get_batch_attendance_analytics, get_student_emotion_trends,
    validate_face_quality, detect_liveness,
)

import hashlib, hmac, base64, os, sqlite3, secrets, json
from datetime import datetime, timedelta
from functools import wraps
import cv2
import numpy as np
from PIL import Image
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from email_config import EMAIL_CONFIG, is_email_configured
except ImportError:
    EMAIL_CONFIG = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "sender_email": "noreply@visionai.com",
        "sender_password": "",
    }
    def is_email_configured():
        return False

# ── App setup ─────────────────────────────────────────────────────────
app = Flask(__name__)

_SECRET = os.environ.get("SECRET_KEY") or "vision_ai_fixed_secret_key_2024_do_not_change"
app.secret_key = _SECRET

app.config["SESSION_COOKIE_HTTPONLY"]     = True
app.config["SESSION_COOKIE_SAMESITE"]    = "Lax"
app.config["SESSION_COOKIE_SECURE"]      = os.environ.get("PRODUCTION", "0") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["MAX_CONTENT_LENGTH"]         = 10 * 1024 * 1024   # 10 MB


# =====================================================================
# HELPERS
# =====================================================================

# Replace the existing hash_password function with this:
def hash_password(password: str, salt: str = "vision_ai_v2") -> str:
    key = (_SECRET + salt + password).encode()
    return hashlib.sha256(key).hexdigest()

def get_client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def generate_csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(24)
    return session["_csrf"]


def validate_csrf() -> bool:
    token = (
        request.form.get("_csrf")
        or request.headers.get("X-CSRF-Token")
        or (request.get_json(silent=True) or {}).get("_csrf")
    )
    session_token = session.get("_csrf", "")
    if not token or not session_token:
        return False
    return hmac.compare_digest(token, session_token)
    hmac.new(key, msg, digestmod)  


# ── CSRF enforcement ──────────────────────────────────────────────────
@app.before_request
def enforce_csrf():
    exempt_endpoints = {
        "student_face_login",
        "student_login",
        "forgot_password",
        "verify_otp",
        "reset_password",
        "mark_notifications_read",
        "static",
    }
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.endpoint in exempt_endpoints:
        return
    if not validate_csrf():
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "CSRF validation failed."}), 403
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
        return f(*args, **kwargs)
    return wrapper


def login_required_faculty(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "faculty_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("faculty_login"))
        return f(*args, **kwargs)
    return wrapper


# ── Email ─────────────────────────────────────────────────────────────

def send_otp_email(email: str, otp: str, user_type: str = "student") -> bool:
    if not EMAIL_CONFIG.get("sender_email") or not EMAIL_CONFIG.get("sender_password"):
        print(f"[Email] Email not configured - OTP for {email}: {otp}")
        return False

    try:
        msg            = MIMEMultipart()
        msg["From"]    = EMAIL_CONFIG["sender_email"]
        msg["To"]      = email
        msg["Subject"] = f"Vision AI - Password Reset OTP ({user_type.capitalize()})"

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
        msg.attach(MIMEText(body, "html"))

        print(f"[Email] Sending OTP to {email} via {EMAIL_CONFIG['smtp_server']}")
        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"],
                          EMAIL_CONFIG["smtp_port"],
                          timeout=15) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"],
                         EMAIL_CONFIG["sender_password"])
            server.send_message(msg)
        print(f"[Email] OTP sent successfully to {email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"[Email] SMTP Authentication Error: {e}")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"[Email] SMTP Connection Error: {e}")
        return False
    except Exception as e:
        print(f"[Email] Failed to send OTP to {email}: {e}")
        return False


# =====================================================================
# FACE RECOGNITION HELPERS
# =====================================================================

def _train_recognizer(all_students, use_encoding):
    face_samples, roll_labels = [], []
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    for student in all_students:
        try:
            if use_encoding and student.get("face_encoding"):
                base = np.frombuffer(
                    student["face_encoding"], dtype=np.uint8
                ).reshape(100, 100)
            else:
                path = os.path.join("static", student["face_image"])
                stored = cv2.imread(path)
                if stored is None:
                    continue
                base = cv2.resize(
                    cv2.cvtColor(stored, cv2.COLOR_BGR2GRAY), (100, 100)
                )

            base = clahe.apply(base)
            variants = [
                base,
                np.clip(base.astype(np.int32) + 25, 0, 255).astype(np.uint8),
                np.clip(base.astype(np.int32) - 25, 0, 255).astype(np.uint8),
                cv2.flip(base, 1),
                cv2.equalizeHist(base),
                cv2.GaussianBlur(base, (3, 3), 0),
            ]
            for v in variants:
                face_samples.append(cv2.resize(v, (100, 100)))
                roll_labels.append(student["roll"])
        except Exception as e:
            print(f"[Train] Skipping {student.get('roll', '?')}: {e}")

    if not face_samples:
        return None, []

    recognizer = cv2.face.LBPHFaceRecognizer_create(
        radius=1, neighbors=8, grid_x=8, grid_y=8, threshold=100.0
    )
    label_indices = list(range(len(face_samples)))
    recognizer.train(face_samples, np.array(label_indices))
    return recognizer, roll_labels


def _face_histogram(face_gray):
    hist = cv2.calcHist([face_gray], [0], None, [256], [0, 256])
    cv2.normalize(hist, hist)
    return hist


def _dual_match(face_roi, recognizer, roll_labels, all_students, use_encoding):
    try:
        idx, lbph_conf = recognizer.predict(face_roi)
    except Exception:
        return "", "", 999.0, 0.0, False

    candidate_roll = roll_labels[idx] if 0 <= idx < len(roll_labels) else None

    face_hist = _face_histogram(face_roi)
    best_hist = 0.0
    best_roll = None

    for s in all_students:
        enc = s.get("face_encoding")
        if not enc:
            continue
        try:
            stored    = np.frombuffer(enc, dtype=np.uint8).reshape(100, 100)
            s_hist    = _face_histogram(stored)
            corr      = cv2.compareHist(face_hist, s_hist, cv2.HISTCMP_CORREL)
            intersect = cv2.compareHist(face_hist, s_hist, cv2.HISTCMP_INTERSECT)
            combined  = corr * 0.7 + intersect * 0.3
            if combined > best_hist:
                best_hist = combined
                best_roll = s["roll"]
        except Exception:
            continue

    LBPH_T = 85.0
    HIST_T  = 0.40
    lbph_ok = lbph_conf < LBPH_T
    hist_ok  = best_hist > HIST_T
    agree    = (candidate_roll == best_roll)

    def _student_name(roll):
        s = next((x for x in all_students if x["roll"] == roll), None)
        return s["name"] if s else ""

    if candidate_roll and best_roll and agree and lbph_ok and hist_ok:
        return candidate_roll, _student_name(candidate_roll), lbph_conf, best_hist, True
    if lbph_ok and lbph_conf < 60.0 and candidate_roll:
        return candidate_roll, _student_name(candidate_roll), lbph_conf, best_hist, True
    if hist_ok and best_hist > 0.65 and best_roll and lbph_conf < 95.0:
        return best_roll, _student_name(best_roll), lbph_conf, best_hist, True

    return "", "", lbph_conf, best_hist, False


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


def _enhanced_duplicate_check(face_encoding, existing_students, exclude_roll: str = ""):
    if not face_encoding or not existing_students:
        return False, None, None, 0.0
    try:
        new_face = np.frombuffer(face_encoding, dtype=np.uint8).reshape(100, 100)
        new_hist = _face_histogram(new_face)
    except Exception:
        return False, None, None, 0.0

    best_score, best_roll, best_name = 0.0, None, None

    for student in existing_students:
        if student.get("roll") == exclude_roll:
            continue
        enc = student.get("face_encoding")
        if not enc:
            continue
        try:
            stored = np.frombuffer(enc, dtype=np.uint8).reshape(100, 100)
            s_hist = _face_histogram(stored)

            hist_corr = cv2.compareHist(new_hist, s_hist, cv2.HISTCMP_CORREL)
            tmatch    = float(cv2.matchTemplate(
                new_face.astype(np.float32),
                stored.astype(np.float32),
                cv2.TM_CCOEFF_NORMED,
            )[0][0])
            nf = new_face.astype(np.float64).flatten()
            sf = stored.astype(np.float64).flatten()
            nf -= nf.mean(); sf -= sf.mean()
            denom      = np.linalg.norm(nf) * np.linalg.norm(sf)
            pixel_corr = float(np.dot(nf, sf) / denom) if denom > 0 else 0.0

            combined = hist_corr * 0.40 + tmatch * 0.35 + pixel_corr * 0.25
            if combined > best_score:
                best_score = combined
                best_roll  = student["roll"]
                best_name  = student["name"]
        except Exception:
            continue

    if best_score >= 0.75:
        return True, best_roll, best_name, best_score
    return False, None, None, best_score


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
        department   = request.form.get("department", "").strip()
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
            clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            face_roi = clahe.apply(
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
                is_dup, dup_roll, dup_name, dup_score = _enhanced_duplicate_check(
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

                if dup_score >= 0.65:
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

            os.makedirs("static/faces", exist_ok=True)
            face_filename = f"faces/{roll}.jpg"
            with open(f"static/{face_filename}", "wb") as f:
                f.write(img_data)

            db.execute(
                """INSERT INTO students
                   (name, roll, phone, email, password, face_image, face_encoding,
                    standard, division, gender, department)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (name, roll, phone_digits, email, hash_password(password_raw),
                 face_filename, face_encoding,
                 standard, division, gender, department)
            )
            db.commit()

            new_row = db.execute(
                "SELECT id FROM students WHERE roll=?", (roll,)
            ).fetchone()
            new_id = new_row["id"] if new_row else None

            _notify(db, "student", roll, "Welcome to Vision AI!",
                    f"Hi {name}, your account has been created successfully.", "success")
            log_security_event(db, "STUDENT_REGISTER", roll, "student",
                               get_client_ip())
            db.commit()

            session.clear()
            session.permanent       = True
            session["student_roll"] = roll
            session["student_name"] = name
            session["student_id"]   = new_id
            return redirect(url_for("student_dashboard"))

        except Exception as e:
            if db:
                try: db.rollback()
                except Exception: pass
            print(f"[Register] Error: {e}")
            import traceback; traceback.print_exc()
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
            login_field = "email"

            if not student:
                return render_template("student_login.html",
                                       error="Invalid email or password.")

            if check_account_locked(db, "students", login_field, email):
                return render_template(
                    "student_login.html",
                    error="Account locked due to too many failed attempts. Try again in 15 minutes."
                )

            input_hash  = hash_password(password_raw)
            stored_hash = student["password"]
            print(f"[DEBUG] Login attempt for {email}:")
            print(f"[DEBUG] Hashes match: {input_hash == stored_hash}")

            if not hmac.compare_digest(stored_hash, input_hash):
                record_failed_login(db, "students", login_field, email)
                attempts  = (student["login_attempts"] or 0) + 1
                remaining = max(0, 5 - attempts)
                log_security_event(db, "FAILED_LOGIN", email, "student",
                                   get_client_ip(), severity="medium")
                db.commit()
                msg = "Invalid email or password."
                if remaining > 0:
                    msg += f" {remaining} attempt(s) remaining before lockout."
                return render_template("student_login.html", error=msg)

            record_successful_login(db, "students", login_field, email)
            log_security_event(db, "STUDENT_LOGIN", student["roll"],
                               "student", get_client_ip())
            db.commit()

            session.clear()
            session.permanent       = True
            session["student_roll"] = student["roll"]
            session["student_name"] = student["name"]
            session["student_id"]   = student["id"]
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

        recognizer, roll_labels = _train_recognizer(all_students, use_encoding)
        if recognizer is None:
            return jsonify({"success": False, "error": "No face data available for matching."})

        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        face_roi   = clahe.apply(
            cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
        )

        quality_ok, quality_msg = _check_face_quality(face_roi, strict=True)
        if not quality_ok:
            return jsonify({"success": False, "error": quality_msg})

        roll, name, lbph_conf, hist_score, matched = _dual_match(
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
            db.commit()

            session.clear()
            session.permanent       = True
            session["student_roll"] = student["roll"]
            session["student_name"] = student["name"]
            session["student_id"]   = student["id"]
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
            session.clear()
            flash("Your account no longer exists. Please register again.", "warning")
            return redirect(url_for("student_login"))

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

        total   = len(attendance)
        present = sum(1 for a in attendance if a and a["method"] in ("manual", "bulk", "face"))
        percent = round((present / total) * 100) if total > 0 else 0

        student_dict = dict(student) if student else {}

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
            name         = request.form.get("name",  "").strip()
            phone        = request.form.get("phone", "").strip()
            standard     = request.form.get("standard", "").strip()
            division     = request.form.get("division", "").strip()
            department   = request.form.get("department", "").strip()
            gender       = request.form.get("gender", "").strip()
            phone_digits = "".join(filter(str.isdigit, phone))

            errors = []
            if not name or len(name) < 2:
                errors.append("Name must be at least 2 characters.")
            if phone_digits and len(phone_digits) != 10:
                errors.append("Phone must be exactly 10 digits.")
            if phone_digits and phone_digits[0] not in "6789":
                errors.append("Phone must start with 6, 7, 8, or 9.")

            if errors:
                return render_template("student_profile_edit.html",
                                       student=student, errors=errors)

            db.execute(
                """UPDATE students
                   SET name=?, phone=?, standard=?, division=?, department=?, gender=?
                   WHERE roll=?""",
                (name,
                 phone_digits if phone_digits else student["phone"],
                 standard or student["standard"],
                 division or student["division"],
                 department or student["department"],
                 gender or student["gender"],
                 session["student_roll"])
            )
            db.commit()
            session["student_name"] = name
            flash("Profile updated successfully!", "success")
            return redirect(url_for("student_dashboard"))

        return render_template("student_profile_edit.html",
                               student=student, errors=[])
    finally:
        if db:
            db.close()


# =====================================================================
# STUDENT — FACE ENROLL
# =====================================================================
@app.route("/student-face-enroll", methods=["GET", "POST"])
@login_required_student
def student_face_enroll():
    if request.method == "POST":
        face_data = request.form.get("face_image", "")
        if not face_data or "," not in face_data:
            flash("Please capture your face photo.", "error")
            return render_template("student_face_enroll.html")

        db = None
        try:
            img_data = base64.b64decode(face_data.split(",")[1])
            np_arr   = np.frombuffer(img_data, np.uint8)
            img_cv   = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_cv is None:
                flash("Could not decode image. Please try again.", "error")
                return render_template("student_face_enroll.html")

            gray    = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            gray_eq = cv2.equalizeHist(gray)
            faces   = _detect_faces_multipass(gray_eq)
            if not faces:
                flash("No face detected. Please try again in better lighting.", "error")
                return render_template("student_face_enroll.html")

            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            face_roi   = clahe.apply(
                cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
            )

            quality_ok, quality_msg = _check_face_quality(face_roi, strict=True)
            if not quality_ok:
                flash(f"Face quality issue: {quality_msg}", "error")
                return render_template("student_face_enroll.html")

            face_encoding = face_roi.tobytes()
            roll = session["student_roll"]

            db = get_db()

            existing_faces = [
                dict(r)
                for r in db.execute(
                    "SELECT roll, name, face_encoding FROM students "
                    "WHERE face_encoding IS NOT NULL AND is_active=1 AND roll!=?",
                    (roll,)
                ).fetchall()
            ]
            is_dup, dup_roll, dup_name, dup_score = _enhanced_duplicate_check(
                face_encoding, existing_faces
            )
            if is_dup:
                flash("This face appears to already be registered to another student.", "error")
                return render_template("student_face_enroll.html")

            os.makedirs("static/faces", exist_ok=True)
            face_filename = f"faces/{roll}.jpg"
            with open(f"static/{face_filename}", "wb") as f:
                f.write(img_data)

            db.execute(
                "UPDATE students SET face_image=?, face_encoding=? WHERE roll=?",
                (face_filename, face_encoding, roll)
            )
            db.commit()
            flash("Face enrolled successfully! You can now use face login.", "success")
            return redirect(url_for("student_dashboard"))

        except Exception as e:
            flash("Enrollment failed: Please try again.", "error")
            print(f"[FaceEnroll] Error: {e}")
            return render_template("student_face_enroll.html")
        finally:
            if db:
                db.close()

    return render_template("student_face_enroll.html")


# =====================================================================
# FACULTY — REGISTER
# =====================================================================
@app.route("/faculty-register", methods=["GET", "POST"])
def faculty_register():
    if request.method == "POST":
        name        = request.form.get("name",        "").strip()
        faculty_id  = request.form.get("faculty_id",  "").strip().upper()
        department  = request.form.get("department",  "").strip()
        email       = request.form.get("email",       "").strip().lower()
        password    = request.form.get("password",    "")
        designation = request.form.get("designation", "").strip()
        phone       = request.form.get("phone",       "").strip()

        for label, val in [
            ("Faculty ID", faculty_id), ("Name", name),
            ("Department", department), ("Email", email),
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
            if db.execute(
                "SELECT id FROM faculty WHERE faculty_id=?", (faculty_id,)
            ).fetchone():
                return render_template(
                    "faculty_register.html",
                    error=f"Faculty ID {faculty_id} is already registered!"
                )
            if db.execute(
                "SELECT id FROM faculty WHERE email=?", (email,)
            ).fetchone():
                return render_template(
                    "faculty_register.html",
                    error=f"Email {email} is already registered!"
                )

            db.execute(
                "INSERT INTO faculty "
                "(name, faculty_id, department, email, password, designation, phone) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, faculty_id, department, email,
                 hash_password(password), designation, phone_digits)
            )
            db.commit()
            log_security_event(db, "FACULTY_REGISTER", faculty_id,
                               "faculty", get_client_ip())
            db.commit()

            session.clear()
            session.permanent       = True
            session["faculty_id"]   = faculty_id
            session["faculty_name"] = name
            return redirect(url_for("faculty_dashboard"))

        except Exception as e:
            if db:
                try: db.rollback()
                except Exception: pass
            return render_template("faculty_register.html",
                                   error="Registration error. Please try again.")
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
            login_input = request.form.get("fid", "").strip().lower()
            password = request.form.get("password", "")

            if not login_input or not password:
                return render_template("faculty_login.html",
                                       error="Faculty ID/Email and password are required.")

            db = get_db()

            if "@" in login_input:
                faculty = db.execute(
                    "SELECT * FROM faculty WHERE email=? AND is_active=1", (login_input,)
                ).fetchone()
                login_field = "email"
            else:
                faculty = db.execute(
                    "SELECT * FROM faculty WHERE faculty_id=? AND is_active=1", (login_input.upper(),)
                ).fetchone()
                login_field = "faculty_id"

            if not faculty:
                return render_template("faculty_login.html",
                                       error="Invalid Faculty ID/Email or password.")

            if check_account_locked(db, "faculty", login_field, login_input):
                return render_template(
                    "faculty_login.html",
                    error="Account locked. Too many failed attempts. Try again in 15 minutes."
                )

            if not hmac.compare_digest(faculty["password"], hash_password(password)):
                record_failed_login(db, "faculty", "faculty_id", login_input)
                attempts  = (faculty["login_attempts"] or 0) + 1
                remaining = max(0, 5 - attempts)
                log_security_event(db, "FAILED_LOGIN", login_input, "faculty",
                                   get_client_ip(), severity="medium")
                db.commit()
                msg = "Invalid Faculty ID or password."
                if remaining > 0:
                    msg += f" {remaining} attempt(s) remaining."
                return render_template("faculty_login.html", error=msg)

            record_successful_login(db, "faculty", "faculty_id", login_input)
            log_security_event(db, "FACULTY_LOGIN", login_input, "faculty", get_client_ip())
            db.commit()

            session.clear()
            session.permanent       = True
            session["faculty_id"]   = faculty["faculty_id"]
            session["faculty_name"] = faculty["name"]
            return redirect(url_for("faculty_dashboard"))

        except Exception as e:
            print(f"[FacultyLogin] Error: {e}")
            return render_template("faculty_login.html",
                                   error="Login failed. Please try again.")
        finally:
            if db:
                db.close()

    return render_template("faculty_login.html")


# =====================================================================
# FACULTY — DASHBOARD
# =====================================================================
@app.route("/faculty-dashboard")
@login_required_faculty
def faculty_dashboard():
    db = get_db()
    try:
        faculty = db.execute(
            "SELECT * FROM faculty WHERE faculty_id=? AND is_active=1",
            (session["faculty_id"],)
        ).fetchone()
        if not faculty:
            session.clear()
            flash("Account not found.", "warning")
            return redirect(url_for("faculty_login"))

        students   = db.execute(
            "SELECT * FROM students WHERE is_active=1 ORDER BY name"
        ).fetchall()
        attendance = db.execute(
            "SELECT * FROM attendance ORDER BY date DESC, time DESC LIMIT 100"
        ).fetchall()

        total_students   = len(students)
        total_attendance = db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        face_enrolled    = db.execute(
            "SELECT COUNT(*) FROM students WHERE face_image IS NOT NULL AND is_active=1"
        ).fetchone()[0]

        notifications = db.execute(
            "SELECT * FROM notifications "
            "WHERE user_type='faculty' AND user_id=? AND is_read=0 "
            "ORDER BY created_at DESC LIMIT 5",
            (session["faculty_id"],)
        ).fetchall()

        return render_template(
            "faculty_dashboard.html",
            faculty=faculty,
            students=students,
            attendance=attendance,
            total_students=total_students,
            total_attendance=total_attendance,
            face_enrolled=face_enrolled,
            notifications=notifications,
        )
    except Exception as e:
        print(f"[FacultyDashboard] Error: {e}")
        flash("Error loading dashboard.", "error")
        return redirect(url_for("faculty_login"))
    finally:
        db.close()


# =====================================================================
# MARK ATTENDANCE — Manual
# =====================================================================
@app.route("/mark-attendance", methods=["POST"])
@login_required_faculty
def mark_attendance():
    roll    = request.form.get("roll",    "").strip()
    subject = request.form.get("subject", "").strip()
    now     = datetime.now()
    db      = get_db()
    try:
        if roll and subject:
            student = db.execute(
                "SELECT * FROM students WHERE roll=? AND is_active=1", (roll,)
            ).fetchone()
            if student:
                existing = db.execute(
                    "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
                    (roll, subject, now.strftime("%Y-%m-%d"))
                ).fetchone()
                if not existing:
                    db.execute(
                        "INSERT INTO attendance "
                        "(student_roll, student_name, subject, date, time, marked_by, method) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (roll, student["name"], subject,
                         now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                         session["faculty_id"], "manual")
                    )
                    db.commit()
                    flash(f"Attendance marked for {student['name']}.", "success")
                else:
                    flash(f"Attendance already marked for {student['name']} in {subject} today.", "info")
            else:
                flash(f"Student with roll '{roll}' not found.", "error")
        else:
            flash("Roll number and subject are required.", "error")
    except Exception as e:
        flash(f"Error marking attendance: {e}", "error")
    finally:
        db.close()
    return redirect(url_for("faculty_dashboard"))


# =====================================================================
# MARK ATTENDANCE — Bulk
# =====================================================================
@app.route("/mark-attendance-bulk", methods=["POST"])
@login_required_faculty
def mark_attendance_bulk():
    data    = request.get_json(silent=True) or {}
    rolls   = data.get("rolls", [])
    subject = data.get("subject", "").strip()
    now     = datetime.now()

    if not rolls or not subject:
        return jsonify({"success": False, "error": "Missing rolls or subject."})

    db = get_db()
    try:
        marked = 0
        for roll in rolls:
            roll = str(roll).strip()
            student = db.execute(
                "SELECT * FROM students WHERE roll=? AND is_active=1", (roll,)
            ).fetchone()
            if student:
                existing = db.execute(
                    "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
                    (roll, subject, now.strftime("%Y-%m-%d"))
                ).fetchone()
                if not existing:
                    db.execute(
                        "INSERT INTO attendance "
                        "(student_roll, student_name, subject, date, time, marked_by, method) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (roll, student["name"], subject,
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

        faces = _detect_faces_multipass(gray_eq)

        db           = get_db()
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
            return jsonify({"success": False,
                            "error": "No students with face data enrolled."})

        if not faces:
            absent_list = [{"roll": s["roll"], "name": s["name"]} for s in all_students]
            return jsonify({
                "success": True, "present_students": [],
                "absent_students": absent_list, "faces_detected": 0,
                "faces_matched": 0, "low_quality": [],
                "message": "No faces detected. All students marked absent.",
            })

        recognizer, roll_labels = _train_recognizer(all_students, use_encoding)
        if recognizer is None:
            return jsonify({"success": False,
                            "error": "Could not build face recognition model."})

        now              = datetime.now()
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
                low_quality.append({"bbox": [int(x), int(y), int(w), int(h)],
                                    "reason": quality_msg})
                continue

            roll, name, lbph_conf, hist_score, matched = _dual_match(
                face_roi, recognizer, roll_labels, all_students, use_encoding
            )

            if matched and roll and roll not in detected_rolls:
                detected_rolls.add(roll)
                present_students.append({
                    "roll": roll, "name": name,
                    "lbph_conf": round(lbph_conf, 1),
                    "hist_score": round(hist_score, 3),
                    "confidence": f"{max(0, 100 - lbph_conf):.0f}%",
                })
                existing = db.execute(
                    "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
                    (roll, subject, now.strftime("%Y-%m-%d"))
                ).fetchone()
                if not existing:
                    db.execute(
                        "INSERT INTO attendance "
                        "(student_roll, student_name, subject, date, time, "
                        " marked_by, method, lbph_conf, hist_score) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (roll, name, subject,
                         now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                         session["faculty_id"], "face", lbph_conf, hist_score)
                    )

        absent_students = [
            {"roll": s["roll"], "name": s["name"]}
            for s in all_students if s["roll"] not in detected_rolls
        ]
        db.commit()

        return jsonify({
            "success": True,
            "present_students": present_students,
            "absent_students": absent_students,
            "faces_detected": len(faces),
            "faces_matched": len(present_students),
            "low_quality": low_quality,
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
                return render_template("attendance.html",
                                       message="No face detected. Please ensure good lighting and face the camera.",
                                       status="error")

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
                return render_template("attendance.html",
                                       message="No student face data enrolled. Please register first.",
                                       status="error")

            recognizer, roll_labels = _train_recognizer(all_students, use_encoding)
            if recognizer is None:
                return render_template("attendance.html",
                                       message="No student face data enrolled.",
                                       status="error")

            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            face_roi   = clahe.apply(
                cv2.resize(gray_eq[y:y + h, x:x + w], (100, 100))
            )

            quality_ok, quality_msg = _check_face_quality(face_roi, strict=False)
            if not quality_ok:
                return render_template("attendance.html",
                                       message=quality_msg, status="error")

            roll, name, lbph_conf, hist_score, matched = _dual_match(
                face_roi, recognizer, roll_labels, all_students, use_encoding
            )

            if not matched:
                return render_template("attendance.html",
                                       message="Face not recognized. Please register first or try in better lighting.",
                                       status="error")

            now      = datetime.now()
            existing = db.execute(
                "SELECT id FROM attendance WHERE student_roll=? AND subject=? AND date=?",
                (roll, subject, now.strftime("%Y-%m-%d"))
            ).fetchone()
            if existing:
                return render_template("attendance.html",
                                       message=f"Attendance already marked for {name} in {subject} today.",
                                       status="info", student_name=name)

            db.execute(
                "INSERT INTO attendance "
                "(student_roll, student_name, subject, date, time, marked_by, method, lbph_conf, hist_score) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (roll, name, subject,
                 now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                 "self", "face", lbph_conf, hist_score)
            )
            db.commit()
            return render_template("attendance.html",
                                   message=(f"Attendance marked successfully for {name} in {subject}! "
                                            f"(Confidence: {max(0, 100 - lbph_conf):.0f}%)"),
                                   status="success", student_name=name)

        except Exception as e:
            import traceback; traceback.print_exc()
            return render_template("attendance.html",
                                   message="An error occurred. Please try again.", status="error")
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

        table = "students" if role == "student" else "faculty"
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
                    if is_email_configured():
                        result = {"success": False, "error": "Failed to send OTP. Please try again."}
                    else:
                        print(f"[DEV MODE] OTP for {email}: {otp}")
                        result = {"success": True, "message": "OTP sent! Check CMD window for OTP code."}
            else:
                result = {
                    "success": True,
                    "message": "If that email is registered, you'll receive an OTP."
                }

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
        return jsonify({"success": False, "error": "Invalid or expired OTP. Please request a new one."})
    except Exception as e:
        return jsonify({"success": False, "error": "Verification error."})
    finally:
        db.close()


# =====================================================================
# RESET PASSWORD
# =====================================================================
@app.route("/reset-password", methods=["POST"])
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
        return jsonify({"success": False, "error": "Password must be at least 8 characters."})

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

        table = "students" if role == "student" else "faculty"
        db.execute(
            f"UPDATE {table} SET password=?, login_attempts=0, locked_until=NULL WHERE email=?",
            (hash_password(new_password), email)
        )
        db.execute(
            "UPDATE reset_tokens SET used=1 WHERE email=? AND otp=?",
            (email, otp)
        )
        db.commit()
        log_security_event(db, "PASSWORD_RESET", email, role, get_client_ip())
        db.commit()
        return jsonify({"success": True, "message": "Password reset successfully. You can now login."})
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
            "FROM attendance ORDER BY date DESC, time DESC"
        ).fetchall()
        return render_template("view_attendance.html", data=[dict(r) for r in rows])
    except Exception as e:
        flash(f"Error loading attendance: {e}", "error")
        return redirect(url_for("faculty_dashboard"))
    finally:
        db.close()


# =====================================================================
# STUDENT MANAGEMENT
# =====================================================================
@app.route("/admin/delete-student/<student_roll>", methods=["POST"])
@login_required_faculty
def delete_student(student_roll):
    try:
        success, message = delete_student_completely(student_roll)
        db = get_db()
        try:
            if success:
                log_security_event(db, "STUDENT_DELETED", student_roll,
                                   "faculty", get_client_ip())
                db.commit()
        finally:
            db.close()
        flash(message, "success" if success else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("faculty_dashboard"))


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
        finally:
            db.close()
        flash(message, "success" if success else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("faculty_dashboard"))


@app.route("/admin/delete-faculty/<fac_id>", methods=["POST"])
@login_required_faculty
def delete_faculty(fac_id):
    if fac_id == session.get("faculty_id"):
        flash("You cannot delete your own account while logged in.", "error")
        return redirect(url_for("faculty_dashboard"))
    try:
        success, message = delete_faculty_completely(fac_id)
        db = get_db()
        try:
            if success:
                log_security_event(db, "FACULTY_DELETED", fac_id,
                                   "faculty", get_client_ip())
                db.commit()
        finally:
            db.close()
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
    ip_saved = get_client_ip()

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
            "audit_log", "reset_tokens",
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
            try: db.rollback()
            except Exception: pass
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
        today = datetime.now().strftime("%Y-%m-%d")
        data  = {
            "total_students":   db.execute(
                "SELECT COUNT(*) FROM students WHERE is_active=1"
            ).fetchone()[0],
            "total_attendance": db.execute(
                "SELECT COUNT(*) FROM attendance"
            ).fetchone()[0],
            "today_attendance": db.execute(
                "SELECT COUNT(*) FROM attendance WHERE date=?", (today,)
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
            "SELECT id FROM attendance WHERE id=?", (record_id,)
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
            "FROM attendance ORDER BY date DESC"
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
    if "student_roll" not in session and "faculty_id" not in session:
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
        flash("Your account no longer exists.", "warning")
        return redirect(url_for("home"))

    if request.method == "POST":
        old_pw_raw = request.form.get("old_password", "")
        new_pw_raw = request.form.get("new_password", "")

        if len(new_pw_raw) < 8:
            flash("New password must be at least 8 characters.", "error")
            return render_template("change_password.html")

        old_pw = hash_password(old_pw_raw)
        new_pw = hash_password(new_pw_raw)
        db     = get_db()
        try:
            if "student_roll" in session:
                user = db.execute(
                    "SELECT id FROM students WHERE roll=? AND password=?",
                    (session["student_roll"], old_pw)
                ).fetchone()
                if user:
                    db.execute(
                        "UPDATE students SET password=? WHERE roll=?",
                        (new_pw, session["student_roll"])
                    )
                    db.commit()
                    flash("Password changed successfully!", "success")
                    return redirect(url_for("student_dashboard"))
                else:
                    flash("Current password is incorrect.", "error")
            else:
                user = db.execute(
                    "SELECT id FROM faculty WHERE faculty_id=? AND password=?",
                    (session["faculty_id"], old_pw)
                ).fetchone()
                if user:
                    db.execute(
                        "UPDATE faculty SET password=? WHERE faculty_id=?",
                        (new_pw, session["faculty_id"])
                    )
                    db.commit()
                    flash("Password changed successfully!", "success")
                    return redirect(url_for("faculty_dashboard"))
                else:
                    flash("Current password is incorrect.", "error")
        except Exception as e:
            db.rollback()
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
        if "student_roll" in session:
            log_security_event(db, "STUDENT_LOGOUT", session["student_roll"],
                               "student", get_client_ip())
            db.commit()
        elif "faculty_id" in session:
            log_security_event(db, "FACULTY_LOGOUT", session["faculty_id"],
                               "faculty", get_client_ip())
            db.commit()
    except Exception:
        pass
    finally:
        db.close()
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("home"))


# =====================================================================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)