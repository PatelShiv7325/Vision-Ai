import cv2
import numpy as np
from PIL import Image
import os
import sqlite3
import base64

DB = "vision_ai.db"

# Load cascade once at module level
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

# ─────────────────────────────────────────────
# DUPLICATE DETECTION THRESHOLD
# Lower = stricter matching (fewer false positives)
# Range: 0–100. Recommended: 50–65 for LBPH.
DUPLICATE_CONFIDENCE_THRESHOLD = 60
# ─────────────────────────────────────────────


def detect_faces(image):
    """Detect faces in an image using OpenCV."""
    try:
        if isinstance(image, Image.Image):
            image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        return faces
    except Exception as e:
        print(f"[detect_faces] Error: {e}")
        return []


def save_face_image(face_data, roll_number):
    """Save face image to static/faces directory."""
    try:
        os.makedirs('static/faces', exist_ok=True)
        face_filename = f'faces/{roll_number}.jpg'
        if isinstance(face_data, str) and ',' in face_data:
            image_data = base64.b64decode(face_data.split(',')[1])
            with open(f'static/{face_filename}', 'wb') as f:
                f.write(image_data)
        else:
            with open(f'static/{face_filename}', 'wb') as f:
                f.write(face_data)
        return face_filename
    except Exception as e:
        print(f"[save_face_image] Error: {e}")
        return None


def get_student_faces():
    """Get all student face encodings from database."""
    try:
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT roll, name, face_encoding FROM students WHERE face_encoding IS NOT NULL'
        )
        students = cursor.fetchall()
        conn.close()
        return students
    except Exception as e:
        print(f"[get_student_faces] Error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CORE FIX: Duplicate face check using LBPH recognizer against stored encodings
# ─────────────────────────────────────────────────────────────────────────────

def check_duplicate_face(new_face: np.ndarray) -> dict:
    """
    Check if the given face already exists in the database.

    Uses the same LBPH recognizer as recognition — so confidence scores
    are directly comparable. Lower LBPH confidence = better match.

    Args:
        new_face: Grayscale face image, resized to (100, 100).

    Returns:
        {
            'is_duplicate': bool,
            'matched_roll': str | None,   # roll number of matching student
            'matched_name': str | None,
            'confidence': float           # LBPH confidence (lower = better match)
        }
    """
    result = {
        'is_duplicate': False,
        'matched_roll': None,
        'matched_name': None,
        'confidence': None,
    }

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT id, roll, name, face_encoding FROM students WHERE face_encoding IS NOT NULL")
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"[check_duplicate_face] DB error: {e}")
        return result

    if not rows:
        # No students registered yet — cannot be a duplicate
        return result

    # Build training data
    registered_faces = []
    ids = []
    roll_map = {}   # internal id → (roll, name)

    for row in rows:
        student_id, roll, name, encoding_blob = row
        try:
            face_arr = np.frombuffer(encoding_blob, dtype=np.uint8).reshape(100, 100)
            registered_faces.append(face_arr)
            ids.append(student_id)
            roll_map[student_id] = (roll, name)
        except Exception as e:
            print(f"[check_duplicate_face] Skipping corrupt encoding for roll={roll}: {e}")
            continue

    if not registered_faces:
        return result

    # Train LBPH recognizer on all stored faces
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(registered_faces, np.array(ids))

    # Predict against the new face
    new_face_resized = cv2.resize(new_face, (100, 100))
    predicted_id, confidence = recognizer.predict(new_face_resized)

    print(f"[check_duplicate_face] Predicted ID={predicted_id}, Confidence={confidence:.2f} "
          f"(threshold={DUPLICATE_CONFIDENCE_THRESHOLD})")

    result['confidence'] = confidence

    if confidence < DUPLICATE_CONFIDENCE_THRESHOLD:
        roll, name = roll_map.get(predicted_id, (None, None))
        result['is_duplicate'] = True
        result['matched_roll'] = roll
        result['matched_name'] = name
        print(f"[check_duplicate_face] ⚠️  DUPLICATE DETECTED — matches '{name}' (Roll: {roll})")

    return result


def enroll_face(roll_number: str, name: str, face_image: np.ndarray) -> dict:
    """
    Enroll a new student face after checking for duplicates.

    Args:
        roll_number: Student's roll number.
        name:        Student's name.
        face_image:  Grayscale face image (any size — will be resized).

    Returns:
        {
            'success': bool,
            'error': str | None,          # reason for failure
            'duplicate_info': dict | None # set if duplicate detected
        }
    """
    face_resized = cv2.resize(face_image, (100, 100))

    # ── Step 1: Duplicate check ───────────────────────────────────────────
    dup_result = check_duplicate_face(face_resized)

    if dup_result['is_duplicate']:
        return {
            'success': False,
            'error': (
                f"Face already registered for student '{dup_result['matched_name']}' "
                f"(Roll: {dup_result['matched_roll']}). "
                f"Each student must enroll with their own unique face."
            ),
            'duplicate_info': dup_result,
        }

    # ── Step 2: Save encoding to DB ──────────────────────────────────────
    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        encoding_blob = face_resized.tobytes()

        cur.execute(
            "UPDATE students SET face_encoding = ? WHERE roll = ?",
            (encoding_blob, roll_number)
        )

        if cur.rowcount == 0:
            # Student row doesn't exist yet — insert
            cur.execute(
                "INSERT INTO students (roll, name, face_encoding) VALUES (?, ?, ?)",
                (roll_number, name, encoding_blob)
            )

        conn.commit()
        conn.close()

        print(f"[enroll_face] ✅ Enrolled '{name}' (Roll: {roll_number}) successfully.")
        return {'success': True, 'error': None, 'duplicate_info': None}

    except Exception as e:
        print(f"[enroll_face] DB error: {e}")
        return {'success': False, 'error': str(e), 'duplicate_info': None}


# ─────────────────────────────────────────────────────────────────────────────
# FACE CAPTURE (unchanged logic, just cleaned up)
# ─────────────────────────────────────────────────────────────────────────────

def capture_face(max_attempts=15, enable_liveness=True):
    """Capture the best face from webcam with optional liveness detection."""
    from liveness import LivenessDetector  # local import to avoid circular deps

    cam = cv2.VideoCapture(0)
    if not cam.isOpened():
        print("[capture_face] Cannot open camera")
        return None

    best_face = None
    best_area = 0
    attempt = 0
    liveness_detector = LivenessDetector() if enable_liveness else None
    liveness_scores = []

    while attempt < max_attempts:
        ret, frame = cam.read()
        if not ret:
            attempt += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=6, minSize=(120, 120)
        )

        for x, y, w, h in faces:
            area = w * h
            if area > best_area:
                best_area = area
                best_face = gray[y:y + h, x:x + w]

        if liveness_detector and len(faces) > 0:
            liveness_result = liveness_detector.detect_liveness(frame)
            liveness_scores.append(liveness_result['confidence'])
            status = "LIVE" if liveness_result['is_live'] else "SPOOF"
            color = (0, 255, 0) if liveness_result['is_live'] else (0, 0, 255)
            cv2.putText(frame, f"Liveness: {status} ({liveness_result['confidence']:.2f})",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.imshow('Face Capture', frame)
            cv2.waitKey(1)

        if best_area >= 15000:
            break

        attempt += 1
        cv2.waitKey(150)

    cam.release()
    cv2.destroyAllWindows()

    if best_face is None:
        return None

    if liveness_detector and liveness_scores:
        avg_liveness = sum(liveness_scores) / len(liveness_scores)
        if avg_liveness < 0.7:
            print("[capture_face] ❌ Liveness check failed — possible spoofing.")
            return None
        print(f"[capture_face] ✅ Liveness verified ({avg_liveness:.2f})")

    return cv2.resize(best_face, (100, 100))


# ─────────────────────────────────────────────────────────────────────────────
# RECOGNITION (unchanged logic, cleaned up)
# ─────────────────────────────────────────────────────────────────────────────

def recognize_face(face=None, max_attempts=15):
    """Recognize a face against enrolled students."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, face_encoding FROM students WHERE face_encoding IS NOT NULL")
    data = cur.fetchall()
    conn.close()

    if not data:
        print("[recognize_face] No registered students.")
        return None

    registered_faces, ids = [], []
    for item in data:
        ids.append(item[0])
        registered_faces.append(np.frombuffer(item[1], dtype=np.uint8).reshape(100, 100))

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(registered_faces, np.array(ids))

    if face is not None:
        predicted_id, confidence = recognizer.predict(face)
        return (predicted_id, confidence) if confidence < 70 else None

    # Live camera recognition
    cam = cv2.VideoCapture(0)
    if not cam.isOpened():
        print("[recognize_face] Cannot open camera")
        return None

    best_match, best_confidence = None, 1000
    attempt = 0

    while attempt < max_attempts:
        ret, frame = cam.read()
        if not ret:
            attempt += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detected_faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=6, minSize=(120, 120)
        )

        if len(detected_faces) == 0:
            attempt += 1
            cv2.waitKey(150)
            continue

        x, y, w, h = max(detected_faces, key=lambda f: f[2] * f[3])
        candidate_face = cv2.resize(gray[y:y + h, x:x + w], (100, 100))
        predicted_id, confidence = recognizer.predict(candidate_face)

        if confidence < best_confidence:
            best_confidence = confidence
            best_match = predicted_id

        if confidence < 65:
            break

        attempt += 1
        cv2.waitKey(150)

    cam.release()
    cv2.destroyAllWindows()

    return (best_match, best_confidence) if best_match and best_confidence < 70 else None


def recognize_multiple_faces(face_data: str):
    """Recognize all faces in a single uploaded image."""
    if ',' in face_data:
        face_data_b64 = face_data.split(',', 1)[1]
    else:
        face_data_b64 = face_data

    image_bytes = base64.b64decode(face_data_b64)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    full_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if full_img is None:
        return []

    gray = cv2.cvtColor(full_img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.2, minNeighbors=6, minSize=(120, 120)
    )

    if len(faces) == 0:
        return []

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, face_encoding FROM students WHERE face_encoding IS NOT NULL")
    data = cur.fetchall()
    conn.close()

    if not data:
        return []

    registered_faces, ids = [], []
    for item in data:
        ids.append(item[0])
        registered_faces.append(np.frombuffer(item[1], dtype=np.uint8).reshape(100, 100))

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(registered_faces, np.array(ids))

    results = []
    for x, y, w, h in faces:
        face = cv2.resize(gray[y:y + h, x:x + w], (100, 100))
        predicted_id, confidence = recognizer.predict(face)
        if confidence < 70:
            results.append((predicted_id, confidence))

    return results