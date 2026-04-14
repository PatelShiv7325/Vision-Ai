import base64
import cv2
import numpy as np
import sqlite3
from .liveness_detector import LivenessDetector

DB = "database/db.sqlite3"

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

# ---------- DECODE IMAGE ----------
def decode_face_image(image_data):
    if not image_data:
        return None

    if ',' in image_data:
        image_data = image_data.split(',', 1)[1]

    try:
        image_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if img is None:
            return None
    except Exception:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=6,
        minSize=(120, 120)
    )

    if len(faces) == 0:
        return None

    # Take largest face
    x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
    face = gray[y:y+h, x:x+w]

    return cv2.resize(face, (100, 100))


# ---------- CAPTURE FACE ----------
def capture_face(max_attempts=15, enable_liveness=True):
    cam = cv2.VideoCapture(0)

    if not cam.isOpened():
        print("Cannot open camera")
        return None

    best_face = None
    best_area = 0
    attempt = 0
    
    # Initialize liveness detector
    liveness_detector = LivenessDetector() if enable_liveness else None
    liveness_scores = []

    while attempt < max_attempts:
        ret, frame = cam.read()

        if not ret:
            attempt += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=6,
            minSize=(120, 120)
        )

        for x, y, w, h in faces:
            area = w * h
            if area > best_area:
                best_area = area
                best_face = gray[y:y+h, x:x+w]

        # Liveness detection
        if liveness_detector and len(faces) > 0:
            liveness_result = liveness_detector.detect_liveness(frame)
            liveness_scores.append(liveness_result['confidence'])
            
            # Display liveness status
            status = "LIVE" if liveness_result['is_live'] else "SPOOF"
            color = (0, 255, 0) if liveness_result['is_live'] else (0, 0, 255)
            
            cv2.putText(frame, f"Liveness: {status} ({liveness_result['confidence']:.2f})", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            # Draw face rectangle
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
            
            cv2.imshow('Face Capture with Liveness Detection', frame)
            cv2.waitKey(1)

        if best_area >= 15000:
            break

        attempt += 1
        cv2.waitKey(150)

    cam.release()
    cv2.destroyAllWindows()

    if best_face is None:
        return None

    # Check liveness if enabled
    if liveness_detector and len(liveness_scores) > 0:
        avg_liveness = sum(liveness_scores) / len(liveness_scores)
        if avg_liveness < 0.7:
            print("Liveness check failed. Possible spoofing detected.")
            return None
        print(f"Liveness verified with confidence: {avg_liveness:.2f}")

    return cv2.resize(best_face, (100, 100))


# ---------- RECOGNIZE SINGLE FACE ----------
def recognize_face(face=None, max_attempts=15):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, face_encoding FROM students")
    data = cur.fetchall()
    conn.close()

    registered_faces = []
    ids = []

    for item in data:
        ids.append(item[0])
        registered_faces.append(
            np.frombuffer(item[1], dtype=np.uint8).reshape(100, 100)
        )

    if len(registered_faces) == 0:
        print("No registered students available.")
        return None

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(registered_faces, np.array(ids))

    # If face is provided
    if face is not None:
        predicted_id, confidence = recognizer.predict(face)
        if confidence < 70:
            return predicted_id, confidence
        return None

    # Live camera recognition
    cam = cv2.VideoCapture(0)

    if not cam.isOpened():
        print("Cannot open camera")
        return None

    best_match = None
    best_confidence = 1000
    attempt = 0

    while attempt < max_attempts:
        ret, frame = cam.read()

        if not ret:
            attempt += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detected_faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=6,
            minSize=(120, 120)
        )

        if len(detected_faces) == 0:
            attempt += 1
            cv2.waitKey(150)
            continue

        x, y, w, h = max(detected_faces, key=lambda item: item[2] * item[3])
        candidate_face = cv2.resize(gray[y:y+h, x:x+w], (100, 100))

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

    if best_match is not None and best_confidence < 70:
        return best_match, best_confidence

    return None


# ---------- MULTI-FACE RECOGNITION (NEW FEATURE 🔥) ----------
def recognize_multiple_faces(face_data):
    img = decode_face_image(face_data)

    if img is None:
        return []

    # Reload original image again for multiple detection
    if ',' in face_data:
        face_data = face_data.split(',', 1)[1]

    image_bytes = base64.b64decode(face_data)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    full_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    gray = cv2.cvtColor(full_img, cv2.COLOR_BGR2GRAY)

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=6,
        minSize=(120, 120)
    )

    if len(faces) == 0:
        return []

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, face_encoding FROM students")
    data = cur.fetchall()
    conn.close()

    registered_faces = []
    ids = []

    for item in data:
        ids.append(item[0])
        registered_faces.append(
            np.frombuffer(item[1], dtype=np.uint8).reshape(100, 100)
        )

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(registered_faces, np.array(ids))

    results = []

    for x, y, w, h in faces:
        face = cv2.resize(gray[y:y+h, x:x+w], (100, 100))
        predicted_id, confidence = recognizer.predict(face)

        if confidence < 70:
            results.append((predicted_id, confidence))

    return results