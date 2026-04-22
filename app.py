from flask import Flask, render_template, request, redirect, session, jsonify
from database import init_db, get_db, DB_PATH
import hashlib, base64, os, sqlite3
from datetime import datetime
import cv2
import numpy as np
from PIL import Image
import io    

app = Flask(__name__)
app.secret_key = 'vision_ai_secret_key_2026'


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


with app.app_context():
    init_db()


# ==================== HOME ====================
@app.route('/')
def home():
    return render_template('index.html')


# ==================== FORGOT PASSWORD ====================
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    return render_template('forgot_password.html')


# ==================== STUDENT REGISTER ====================
@app.route('/student-register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        print(request.form)  # DEBUG

        name         = request.form.get('name', '')
        roll         = request.form.get('roll', '')
        phone        = request.form.get('phone', '')
        email        = request.form.get('email', '')
        standard     = request.form.get('standard', '')
        division     = request.form.get('division', '')
        gender       = request.form.get('gender', '')
        password_raw = request.form.get('password', '')
        password     = hash_password(password_raw)
        face_data    = request.form.get('face_image', '')

        # ── Validate required fields ──────────────────────────────────
        missing = [f for f, v in [('name', name), ('roll', roll),
                                   ('email', email), ('password', password_raw)] if not v]
        if missing:
            return render_template('student_register.html',
                                   error=f'Missing required fields: {", ".join(missing)}')

        # ── Require face image ────────────────────────────────────────
        if not face_data or ',' not in face_data:
            return render_template('student_register.html',
                                   error='Please capture your face photo before submitting.')

        db = None
        try:
            db = get_db()

            # Check duplicate roll
            if db.execute('SELECT id FROM students WHERE roll=?', (roll,)).fetchone():
                return render_template('student_register.html',
                                       error=f'Student with Roll Number {roll} already exists!')

            # Check duplicate email
            if db.execute('SELECT id FROM students WHERE email=?', (email,)).fetchone():
                return render_template('student_register.html',
                                       error=f'Email {email} is already registered!')

            # ── Save face image ───────────────────────────────────────
            face_filename = None
            try:
                img_data = base64.b64decode(face_data.split(',')[1])
                os.makedirs('static/faces', exist_ok=True)
                face_filename = f'faces/{roll}.jpg'
                with open(f'static/{face_filename}', 'wb') as f:
                    f.write(img_data)
                print(f"[Register] Face saved for roll={roll}")
            except Exception as e:
                print(f"[Register] Face save error: {e}")
                return render_template('student_register.html',
                                       error='Error processing face image. Please try again.')

            # ── Insert student ────────────────────────────────────────
            db.execute(
                'INSERT INTO students (name, roll, phone, email, password, face_image, standard, division, gender) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (name, roll, phone, email, password, face_filename, standard, division, gender)
            )
            db.commit()

            # Verify insertion
            inserted = db.execute('SELECT * FROM students WHERE roll=?', (roll,)).fetchone()
            if not inserted:
                raise Exception('Insert verification failed — record not found after commit.')

            print(f"[Register] Student inserted successfully: {name} ({roll})")

            session['student_roll'] = roll
            session['student_name'] = name
            return redirect('/student-dashboard')

        except Exception as e:
            print(f"[Register] ERROR: {e}")
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            return render_template('student_register.html',
                                   error=f'Registration failed: {str(e)}')
        finally:
            if db:
                db.close()

    return render_template('student_register.html')


# ==================== STUDENT LOGIN ====================
@app.route('/student-login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = hash_password(request.form.get('password', ''))

        db = get_db()
        student = db.execute(
            'SELECT * FROM students WHERE email=? AND password=?',
            (email, password)
        ).fetchone()
        db.close()

        if student:
            session['student_roll'] = student['roll']
            session['student_name'] = student['name']
            session['student_id']   = student['id']
            return redirect('/student-dashboard')
        else:
            return render_template('student_login.html', error='Invalid email or password.')

    return render_template('student_login.html')


# ==================== STUDENT DASHBOARD ====================
@app.route('/student-dashboard')
def student_dashboard():
    if 'student_roll' not in session:
        return redirect('/student-login')

    db = get_db()

    student = db.execute(
        'SELECT * FROM students WHERE roll=?',
        (session['student_roll'],)
    ).fetchone()

    attendance = db.execute(
        'SELECT * FROM attendance WHERE student_roll=? ORDER BY date DESC, time DESC',
        (session['student_roll'],)
    ).fetchall()

    db.close()

    total   = len(attendance)
    present = total
    absent  = 0  # Update this logic if you track absences separately
    percent = round((present / total) * 100) if total > 0 else 0

    return render_template(
        'student_dashboard.html',
        student=student,
        attendance=attendance,
        total=total,
        present=present,
        absent=absent,
        percent=percent
    )


# ==================== FACULTY REGISTER ====================
@app.route('/faculty-register', methods=['GET', 'POST'])
def faculty_register():
    if request.method == 'POST':
        name       = request.form.get('name', '').strip()
        faculty_id = request.form.get('faculty_id', '').strip()
        department = request.form.get('department', '').strip()
        email      = request.form.get('email', '').strip()
        password   = hash_password(request.form.get('password', ''))

        if not faculty_id:
            return render_template('faculty_register.html', error='Faculty ID is required.')
        if not name:
            return render_template('faculty_register.html', error='Name is required.')
        if not department:
            return render_template('faculty_register.html', error='Department is required.')
        if not email:
            return render_template('faculty_register.html', error='Email is required.')

        try:
            db = get_db()

            # Check duplicate faculty_id
            if db.execute('SELECT id FROM faculty WHERE faculty_id=?', (faculty_id,)).fetchone():
                db.close()
                return render_template('faculty_register.html',
                                       error=f'Faculty ID {faculty_id} is already registered!')

            # Check duplicate email
            if db.execute('SELECT id FROM faculty WHERE email=?', (email,)).fetchone():
                db.close()
                return render_template('faculty_register.html',
                                       error=f'Email {email} is already registered!')

            db.execute(
                'INSERT INTO faculty (name, faculty_id, department, email, password) '
                'VALUES (?,?,?,?,?)',
                (name, faculty_id, department, email, password)
            )
            db.commit()
            db.close()

            session['faculty_id']   = faculty_id
            session['faculty_name'] = name
            return redirect('/faculty-dashboard')

        except Exception as e:
            print(f"[FacultyRegister] ERROR: {e}")
            return render_template('faculty_register.html', error=f'Error: {e}')

    return render_template('faculty_register.html')


# ==================== FACULTY LOGIN ====================
@app.route('/faculty-login', methods=['GET', 'POST'])
def faculty_login():
    if request.method == 'POST':
        fid      = request.form.get('fid', '').strip()
        password = hash_password(request.form.get('password', ''))

        if not fid:
            return render_template('faculty_login.html', error='Faculty ID is required.')

        db = get_db()
        faculty = db.execute(
            'SELECT * FROM faculty WHERE faculty_id=? AND password=?',
            (fid, password)
        ).fetchone()
        db.close()

        if faculty:
            session['faculty_id']   = faculty['faculty_id']
            session['faculty_name'] = faculty['name']
            return redirect('/faculty-dashboard')
        else:
            return render_template('faculty_login.html', error='Invalid Faculty ID or password.')

    return render_template('faculty_login.html')


# ==================== FACULTY DASHBOARD ====================
@app.route('/faculty-dashboard')
def faculty_dashboard():
    if 'faculty_id' not in session:
        return redirect('/faculty-login')

    db = get_db()

    faculty = db.execute(
        'SELECT * FROM faculty WHERE faculty_id=?',
        (session['faculty_id'],)
    ).fetchone()

    students = db.execute('SELECT * FROM students ORDER BY name').fetchall()

    attendance = db.execute(
        'SELECT * FROM attendance ORDER BY date DESC, time DESC LIMIT 50'
    ).fetchall()

    total_students   = len(students)
    total_attendance = db.execute('SELECT COUNT(*) as c FROM attendance').fetchone()['c']

    db.close()

    return render_template(
        'faculty_dashboard.html',
        faculty=faculty,
        students=students,
        attendance=attendance,
        total_students=total_students,
        total_attendance=total_attendance
    )


# ==================== MARK ATTENDANCE ====================
@app.route('/mark-attendance', methods=['POST'])
def mark_attendance():
    if 'faculty_id' not in session:
        return redirect('/faculty-login')

    roll    = request.form.get('roll', '').strip()
    subject = request.form.get('subject', '').strip()
    now     = datetime.now()

    if not roll or not subject:
        return redirect('/faculty-dashboard')

    db = get_db()
    student = db.execute('SELECT * FROM students WHERE roll=?', (roll,)).fetchone()

    if student:
        db.execute(
            'INSERT INTO attendance (student_roll, student_name, subject, date, time, marked_by) '
            'VALUES (?,?,?,?,?,?)',
            (
                roll,
                student['name'],
                subject,
                now.strftime('%Y-%m-%d'),
                now.strftime('%H:%M:%S'),
                session['faculty_id']
            )
        )
        db.commit()

    db.close()
    return redirect('/faculty-dashboard')


# ==================== PROCESS ATTENDANCE (Face Recognition) ====================
@app.route('/process-attendance', methods=['POST'])
def process_attendance():
    if 'faculty_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        data       = request.get_json()
        image_data = data.get('image', '')
        subject    = data.get('subject', '')

        if not image_data or not subject:
            return jsonify({'success': False, 'error': 'Missing image or subject'})

        # Decode base64 image
        img_bytes    = base64.b64decode(image_data.split(',')[1])
        image        = Image.open(io.BytesIO(img_bytes))
        image_array  = np.array(image)
        image_cv     = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)

        # Detect faces
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        gray  = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        # Load all students with face images
        db           = get_db()
        all_students = db.execute('SELECT * FROM students WHERE face_image IS NOT NULL ORDER BY name').fetchall()
        db.close()

        if not all_students:
            return jsonify({'success': False, 'error': 'No students with face images found'})

        present_students = []
        absent_students  = []
        detected_rolls   = set()

        # Prepare training data for face recognizer
        face_samples = []
        roll_labels  = []

        for student in all_students:
            try:
                path = os.path.join('static', student['face_image'])
                if os.path.exists(path):
                    stored_face = cv2.imread(path)
                    if stored_face is not None:
                        stored_gray = cv2.cvtColor(stored_face, cv2.COLOR_BGR2GRAY)
                        stored_gray = cv2.resize(stored_gray, (100, 100))
                        face_samples.append(stored_gray)
                        roll_labels.append(student['roll'])
            except Exception as e:
                print(f"[TrainingData] Error for {student['roll']}: {e}")

        if not face_samples:
            return jsonify({'success': False, 'error': 'No valid face images found for training'})

        # Train LBPH face recognizer
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.train(face_samples, np.array(roll_labels))

        # Recognize faces in the captured image
        for (x, y, w, h) in faces:
            face_region = gray[y:y+h, x:x+w]
            face_region = cv2.resize(face_region, (100, 100))

            try:
                roll, confidence = recognizer.predict(face_region)

                # Lower confidence means better match (typically < 70 is good)
                if confidence < 70:
                    for student in all_students:
                        if student['roll'] == roll and roll not in detected_rolls:
                            present_students.append({'roll': roll, 'name': student['name']})
                            detected_rolls.add(roll)
                            print(f"[FaceRecognition] Matched: {student['name']} ({roll}) with confidence {confidence:.2f}")
                            break
            except Exception as e:
                print(f"[FaceRecognition] Error: {e}")

        # Find absent students
        for student in all_students:
            if student['roll'] not in detected_rolls:
                absent_students.append({'roll': student['roll'], 'name': student['name']})

        # Mark attendance in DB
        db  = get_db()
        now = datetime.now()

        for student in present_students:
            db.execute(
                'INSERT INTO attendance (student_roll, student_name, subject, date, time, marked_by) '
                'VALUES (?,?,?,?,?,?)',
                (student['roll'], student['name'], subject,
                 now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'),
                 session['faculty_id'])
            )

        db.commit()
        db.close()

        return jsonify({
            'success': True,
            'present_students': present_students,
            'absent_students': absent_students
        })

    except Exception as e:
        print(f"[ProcessAttendance] ERROR: {e}")
        return jsonify({'success': False, 'error': str(e)})


# ==================== HELPERS ====================
def compare_faces(face1, face2):
    """Simple face comparison using histogram correlation."""
    try:
        gray1 = cv2.cvtColor(face1, cv2.COLOR_BGR2GRAY) if len(face1.shape) == 3 else face1
        gray2 = cv2.cvtColor(face2, cv2.COLOR_BGR2GRAY) if len(face2.shape) == 3 else face2

        gray1 = cv2.resize(gray1, (100, 100))
        gray2 = cv2.resize(gray2, (100, 100))

        hist1 = cv2.calcHist([gray1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([gray2], [0], None, [256], [0, 256])

        correlation = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        return correlation > 0.7

    except Exception as e:
        print(f"[CompareFaces] Error: {e}")
        return False


# ==================== LOGOUT ====================
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    app.run(debug=True)