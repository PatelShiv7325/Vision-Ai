"""
app_face_routes.py  ·  Vision AI
=================================
Drop-in replacement routes for app.py that use face_engine.py
for high-accuracy, anti-duplicate face recognition.

INSTRUCTIONS:
  1. Copy face_engine.py into your project root (same level as app.py)
  2. Replace the matching routes in your app.py with these functions
  3. Add this import at the top of app.py:
       from face_engine import (
           detect_face, detect_all_faces, build_recognizer,
           match_face, encode_face_from_image, is_duplicate_face,
           augment_face, QualityReport
       )
"""

import base64, os
from datetime import datetime

import cv2
import numpy as np
from flask import request, session, jsonify, render_template, redirect
from PIL import Image
import io

from face_engine import (
    detect_face, detect_all_faces, build_recognizer,
    match_face, encode_face_from_image, is_duplicate_face,
    augment_face, QualityReport
)
from database import get_db


# =====================================================================
# HELPER — load all students for recognition
# =====================================================================
def _load_students_for_recognition(db):
    """Load students preferring face_encoding, fallback to face_image."""
    students = db.execute(
        'SELECT * FROM students WHERE face_encoding IS NOT NULL ORDER BY name'
    ).fetchall()
    use_encoding = True
    if not students:
        students = db.execute(
            'SELECT * FROM students WHERE face_image IS NOT NULL ORDER BY name'
        ).fetchall()
        use_encoding = False
    return list(students), use_encoding


# =====================================================================
# STUDENT REGISTER  (with duplicate-face guard + quality check)
# =====================================================================
def student_register():
    if request.method == 'POST':
        name         = request.form.get('name',       '').strip()
        roll         = request.form.get('roll',       '').strip()
        phone        = request.form.get('phone',      '').strip()
        email        = request.form.get('email',      '').strip()
        standard     = request.form.get('standard',   '').strip()
        division     = request.form.get('division',   '').strip()
        gender       = request.form.get('gender',     '').strip()
        department   = request.form.get('department', '').strip()
        password_raw = request.form.get('password',   '')
        face_data    = request.form.get('face_image', '')

        # ── Basic field validation ───────────────────────────────────
        missing = [lbl for lbl, v in [
            ('Name', name), ('Roll Number', roll),
            ('Email', email), ('Password', password_raw)
        ] if not v]
        if missing:
            return render_template('student_register.html',
                error=f'Missing: {", ".join(missing)}')

        if not face_data or ',' not in face_data:
            return render_template('student_register.html',
                error='Please capture your face photo before submitting.')

        db = None
        try:
            db = get_db()

            # ── Duplicate roll / email check ─────────────────────────
            if db.execute('SELECT id FROM students WHERE roll=?', (roll,)).fetchone():
                return render_template('student_register.html',
                    error=f'Roll Number {roll} is already registered!')
            if db.execute('SELECT id FROM students WHERE email=?', (email,)).fetchone():
                return render_template('student_register.html',
                    error=f'Email {email} is already registered!')

            # ── Decode image ─────────────────────────────────────────
            img_bytes = base64.b64decode(face_data.split(',')[1])
            np_arr    = np.frombuffer(img_bytes, np.uint8)
            img_cv    = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_cv is None:
                return render_template('student_register.html',
                    error='Could not decode image. Please retake.')

            # ── Quality + encoding ───────────────────────────────────
            encoding, face_jpg_bytes, quality = encode_face_from_image(img_cv)
            if not quality.passed:
                return render_template('student_register.html',
                    error=f'Face quality too low: {quality.reason}. '
                          f'Please retake in better lighting.')

            if encoding is None:
                return render_template('student_register.html',
                    error='No face detected in the photo. Please retake.')

            # ── DUPLICATE FACE GUARD ─────────────────────────────────
            existing_students = db.execute(
                'SELECT roll, name, face_encoding FROM students '
                'WHERE face_encoding IS NOT NULL'
            ).fetchall()

            dup_roll = is_duplicate_face(encoding, existing_students, exclude_roll=roll)
            if dup_roll:
                dup_name = db.execute(
                    'SELECT name FROM students WHERE roll=?', (dup_roll,)
                ).fetchone()['name']
                return render_template('student_register.html',
                    error=f'This face is already registered to "{dup_name}" '
                          f'(Roll: {dup_roll}). Each student must use their own face.')

            # ── Save face image file ─────────────────────────────────
            os.makedirs('static/faces', exist_ok=True)
            face_filename = f'faces/{roll}.jpg'
            with open(f'static/{face_filename}', 'wb') as f:
                f.write(img_bytes)   # store original photo

            # ── Insert student ───────────────────────────────────────
            from app import hash_password
            db.execute(
                '''INSERT INTO students
                   (name, roll, phone, email, password, face_image, face_encoding,
                    standard, division, gender, department)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (name, roll, phone, email, hash_password(password_raw),
                 face_filename, encoding, standard, division, gender, department)
            )
            db.commit()

            new_id = db.execute(
                'SELECT id FROM students WHERE roll=?', (roll,)
            ).fetchone()['id']
            session['student_roll'] = roll
            session['student_name'] = name
            session['student_id']   = new_id
            return redirect('/student-dashboard')

        except Exception as e:
            if db:
                try: db.rollback()
                except: pass
            print(f"[Register] Error: {e}")
            return render_template('student_register.html',
                error=f'Registration failed: {e}')
        finally:
            if db: db.close()

    return render_template('student_register.html')


# =====================================================================
# PROCESS ATTENDANCE — Face Recognition (faculty group capture)
# =====================================================================
def process_attendance():
    """
    High-accuracy group attendance via face recognition.
    Uses dual-algorithm (LBPH + histogram) matching.
    """
    if 'faculty_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data       = request.get_json(silent=True) or {}
        image_data = data.get('image', '')
        subject    = data.get('subject', '').strip()

        if not image_data or not subject:
            return jsonify({'success': False, 'error': 'Missing image or subject'})

        # ── Decode image ─────────────────────────────────────────────
        img_bytes   = base64.b64decode(image_data.split(',')[1])
        image       = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        image_array = np.array(image)
        image_cv    = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)

        # ── Detect ALL faces in the classroom photo ──────────────────
        all_face_results = detect_all_faces(image_cv)

        if not all_face_results:
            return jsonify({
                'success': False,
                'error': 'No faces detected in the image. '
                         'Ensure the room is well-lit and faces are visible.'
            })

        # ── Load students & train recognizer ─────────────────────────
        db = get_db()
        all_students, use_encoding = _load_students_for_recognition(db)

        if not all_students:
            db.close()
            return jsonify({'success': False,
                            'error': 'No students with face data registered yet.'})

        recognizer, roll_labels = build_recognizer(all_students, use_encoding)
        if recognizer is None:
            db.close()
            return jsonify({'success': False,
                            'error': 'Could not build face model. Check face data.'})

        now              = datetime.now()
        present_students = []
        absent_students  = []
        low_quality      = []
        detected_rolls   = set()

        # ── Match each detected face ──────────────────────────────────
        for face_roi, bbox, quality in all_face_results:
            if not quality.passed:
                low_quality.append({
                    'bbox': list(bbox),
                    'reason': quality.reason
                })
                continue

            result = match_face(face_roi, recognizer, roll_labels,
                                all_students, use_encoding)

            if result.is_match and result.roll not in detected_rolls:
                detected_rolls.add(result.roll)
                present_students.append({
                    'roll':       result.roll,
                    'name':       result.name,
                    'lbph_conf':  round(result.lbph_conf, 1),
                    'hist_score': round(result.hist_score, 3),
                    'reason':     result.reason
                })

                # ── Insert attendance (no same-day duplicate) ─────────
                existing = db.execute(
                    'SELECT id FROM attendance '
                    'WHERE student_roll=? AND subject=? AND date=?',
                    (result.roll, subject, now.strftime('%Y-%m-%d'))
                ).fetchone()
                if not existing:
                    db.execute(
                        'INSERT INTO attendance '
                        '(student_roll, student_name, subject, date, time, '
                        ' marked_by, method) VALUES (?,?,?,?,?,?,?)',
                        (result.roll, result.name, subject,
                         now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'),
                         session['faculty_id'], 'face')
                    )

        # ── Absent = registered students not detected ─────────────────
        for student in all_students:
            if student['roll'] not in detected_rolls:
                absent_students.append({
                    'roll': student['roll'],
                    'name': student['name']
                })

        db.commit()
        db.close()

        return jsonify({
            'success':          True,
            'present_students': present_students,
            'absent_students':  absent_students,
            'faces_detected':   len(all_face_results),
            'faces_matched':    len(present_students),
            'low_quality':      low_quality,
        })

    except Exception as e:
        print(f"[ProcessAttendance] ERROR: {e}")
        return jsonify({'success': False, 'error': str(e)})


# =====================================================================
# STUDENT SELF-ATTENDANCE  (student marks own attendance via face)
# =====================================================================
def attendance():
    if request.method == 'POST':
        subject   = request.form.get('subject', '').strip()
        face_data = request.form.get('face_image', '')

        if not subject or not face_data or ',' not in face_data:
            return render_template('attendance.html',
                message='Please capture your face and enter subject.', status='error')

        try:
            img_bytes = base64.b64decode(face_data.split(',')[1])
            np_arr    = np.frombuffer(img_bytes, np.uint8)
            img_cv    = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            face_roi, bbox, quality = detect_face(img_cv)

            if not quality.passed:
                return render_template('attendance.html',
                    message=f'Face quality issue: {quality.reason}. '
                             'Try better lighting or move closer.',
                    status='error')

            db = get_db()
            all_students, use_encoding = _load_students_for_recognition(db)

            if not all_students:
                db.close()
                return render_template('attendance.html',
                    message='No student face data available.', status='error')

            recognizer, roll_labels = build_recognizer(all_students, use_encoding)
            if recognizer is None:
                db.close()
                return render_template('attendance.html',
                    message='Face model unavailable.', status='error')

            result = match_face(face_roi, recognizer, roll_labels,
                                all_students, use_encoding)

            if not result.is_match:
                db.close()
                return render_template('attendance.html',
                    message=f'Face not recognized ({result.reason}). '
                             'Please register first or try again.',
                    status='error')

            # ── Check same-day duplicate ──────────────────────────────
            now      = datetime.now()
            existing = db.execute(
                'SELECT id FROM attendance '
                'WHERE student_roll=? AND subject=? AND date=?',
                (result.roll, subject, now.strftime('%Y-%m-%d'))
            ).fetchone()

            if existing:
                db.close()
                return render_template('attendance.html',
                    message=f'Attendance already marked for {result.name} in {subject} today.',
                    status='info', student_name=result.name)

            db.execute(
                'INSERT INTO attendance '
                '(student_roll, student_name, subject, date, time, marked_by, method) '
                'VALUES (?,?,?,?,?,?,?)',
                (result.roll, result.name, subject,
                 now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'),
                 'self', 'face')
            )
            db.commit()
            db.close()

            return render_template('attendance.html',
                message=f'✅ Attendance marked for {result.name} in {subject}! '
                        f'(Confidence: {result.lbph_conf:.1f})',
                status='success', student_name=result.name)

        except Exception as e:
            print(f"[SelfAttendance] Error: {e}")
            return render_template('attendance.html',
                message=f'Error: {e}', status='error')

    return render_template('attendance.html')


# =====================================================================
# API — Re-enroll face for existing student (quality check + dup guard)
# =====================================================================
def student_face_enroll():
    """PUT /student-face-enroll — update face data for logged-in student."""
    if 'student_roll' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    data      = request.get_json(silent=True) or {}
    face_data = data.get('face_image', '')

    if not face_data or ',' not in face_data:
        return jsonify({'success': False, 'error': 'No image received'})

    try:
        img_bytes = base64.b64decode(face_data.split(',')[1])
        np_arr    = np.frombuffer(img_bytes, np.uint8)
        img_cv    = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        encoding, _, quality = encode_face_from_image(img_cv)
        if not quality.passed:
            return jsonify({'success': False,
                            'error': f'Quality too low: {quality.reason}'})

        db               = get_db()
        existing_students = db.execute(
            'SELECT roll, name, face_encoding FROM students WHERE face_encoding IS NOT NULL'
        ).fetchall()

        # Exclude current student from dup check (re-enroll is OK)
        dup_roll = is_duplicate_face(
            encoding, existing_students, exclude_roll=session['student_roll']
        )
        if dup_roll:
            dup_name = db.execute(
                'SELECT name FROM students WHERE roll=?', (dup_roll,)
            ).fetchone()['name']
            db.close()
            return jsonify({
                'success': False,
                'error': f'This face already belongs to "{dup_name}". '
                         'Cannot enroll the same face for two accounts.'
            })

        roll = session['student_roll']
        os.makedirs('static/faces', exist_ok=True)
        face_filename = f'faces/{roll}.jpg'
        with open(f'static/{face_filename}', 'wb') as f:
            f.write(img_bytes)

        db.execute(
            'UPDATE students SET face_image=?, face_encoding=? WHERE roll=?',
            (face_filename, encoding, roll)
        )
        db.commit()
        db.close()

        return jsonify({'success': True,
                        'message': 'Face re-enrolled successfully!'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})