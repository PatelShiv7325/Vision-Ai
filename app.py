from flask import Flask, render_template, request, redirect, session, jsonify
from database import init_db, get_db, DB_PATH
import hashlib, base64, os, sqlite3
from datetime import datetime
import cv2
import numpy as np
from PIL import Image
import io
# from core.liveness_detector import LivenessDetector  # DISABLED - causing errors

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

# ==================== forgot password ====================
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    return render_template('forgot_password.html')


# ==================== STUDENT REGISTER ====================
@app.route('/student-register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        print(request.form)  # DEBUG

        name      = request.form.get('name', '')
        roll      = request.form.get('roll', '')
        phone     = request.form.get('phone', '')
        email     = request.form.get('email', '')
        password  = hash_password(request.form.get('password', ''))
        face_data = request.form.get('face_image', '')

        db = None
        try:
            db = get_db()
            
            # Security Check 1: Check if roll number already exists
            existing_student = db.execute(
                'SELECT * FROM students WHERE roll=?', (roll,)
            ).fetchone()
            
            if existing_student:
                return render_template('student_register.html', 
                                     error=f'Student with Roll Number {roll} already exists!')
            
            # Security Check 2: Check if email already exists
            existing_email = db.execute(
                'SELECT * FROM students WHERE email=?', (email,)
            ).fetchone()
            
            if existing_email:
                return render_template('student_register.html', 
                                     error=f'Email {email} is already registered!')
            
            # Security Check 3: Validate face data if provided
            face_filename = None
            if face_data and ',' in face_data:
                try:
                    img_data = base64.b64decode(face_data.split(',')[1])
                    
                    # Save face image
                    os.makedirs('static/faces', exist_ok=True)
                    face_filename = f'faces/{roll}.jpg'
                    with open(f'static/{face_filename}', 'wb') as f:
                        f.write(img_data)
                        
                    print(f"Face registered successfully for {roll}")
                        
                except Exception as e:
                    print(f"Face save error: {e}")
                    return render_template('student_register.html', 
                                         error='Error processing face image. Please try again.')
            
            # Insert new student
            db.execute(
                'INSERT INTO students (name, roll, phone, email, password, face_image) VALUES (?,?,?,?,?,?)',
                (name, roll, phone, email, password, face_filename)
            )
            db.commit()

            session['student_roll'] = roll
            session['student_name'] = name

            return redirect('/student-dashboard')

        except Exception as e:
            print(f"??? ERROR: {e}")
            return render_template('student_register.html', error=f'Registration failed: {str(e)}')

        finally:
            if db:
                db.close()

    return render_template('student_register.html')


# ==================== STUDENT LOGIN ====================
@app.route('/student-login', methods=['GET', 'POST'])
def student_login():
    if request.method == "POST":
        print(request.form)  # DEBUG

        email    = request.form.get('email', '')
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

    return render_template("student_login.html")


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
    percent = 100 if total > 0 else 0

    return render_template(
        'student_dashboard.html',
        student=student,
        attendance=attendance,
        total=total,
        present=total,
        percent=percent
    )


# ==================== FACULTY REGISTER ====================
@app.route('/faculty-register', methods=['GET', 'POST'])
def faculty_register():
    if request.method == 'POST':
        print("FORM DATA:", dict(request.form))  # DEBUG

        name       = request.form.get('name', '')
        faculty_id = request.form.get('faculty_id', '')
        department = request.form.get('department', '')
        email      = request.form.get('email', '')
        password   = hash_password(request.form.get('password', ''))

        # Validation
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
            db.execute(
                'INSERT INTO faculty (name, faculty_id, department, email, password) VALUES (?,?,?,?,?)',
                (name, faculty_id, department, email, password)
            )
            db.commit()
            db.close()

            session['faculty_id']   = faculty_id
            session['faculty_name'] = name

            return redirect('/faculty-dashboard')

        except Exception as e:
            print(f"❌ ERROR: {e}")
            return render_template('faculty_register.html', error=f'Error: {e}')

    return render_template('faculty_register.html')


# ==================== FACULTY LOGIN ====================
@app.route('/faculty-login', methods=['GET', 'POST'])
def faculty_login():
    if request.method == 'POST':
        print("FORM DATA:", dict(request.form))  # DEBUG

        fid      = request.form.get('fid', '')
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

    total_students = len(students)

    total_attendance = db.execute(
        'SELECT COUNT(*) as c FROM attendance'
    ).fetchone()['c']

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

    roll    = request.form.get('roll', '')
    subject = request.form.get('subject', '')
    now     = datetime.now()

    db = get_db()

    student = db.execute(
        'SELECT * FROM students WHERE roll=?',
        (roll,)
    ).fetchone()

    if student:
        db.execute(
            'INSERT INTO attendance (student_roll, student_name, subject, date, time, marked_by) VALUES (?,?,?,?,?,?)',
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


# ==================== LIVENESS DETECTION ====================
@app.route('/check-liveness', methods=['POST'])
def check_liveness():
    """Real-time liveness detection endpoint"""
    if 'student_roll' not in session and 'faculty_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    try:
        data = request.get_json()
        image_data = data.get('image', '')
        challenge_type = data.get('challenge', None)
        
        if not image_data:
            return jsonify({'success': False, 'error': 'No image data provided'})
        
        # Decode base64 image
        image_data = image_data.split(',')[1]  # Remove data:image/jpeg;base64, prefix
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        image_array = np.array(image)
        
        # Convert to OpenCV format
        if len(image_array.shape) == 3:
            image_cv = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        else:
            image_cv = image_array
        
        # Perform liveness detection
        detector = LivenessDetector()
        result = detector.detect_liveness(image_cv, challenge_type)
        
        return jsonify({
            'success': True,
            'is_live': result['is_live'],
            'confidence': result['confidence'],
            'checks': result['checks'],
            'challenge_completed': result.get('challenge_completed', False)
        })
        
    except Exception as e:
        print(f"Error in liveness detection: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== PROCESS ATTENDANCE ====================
@app.route('/process-attendance', methods=['POST'])
def process_attendance():
    if 'faculty_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    try:
        data = request.get_json()
        image_data = data.get('image', '')
        subject = data.get('subject', '')
        
        if not image_data or not subject:
            return jsonify({'success': False, 'error': 'Missing image or subject'})
        
        # Decode base64 image
        image_data = image_data.split(',')[1]  # Remove data:image/jpeg;base64, prefix
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        image_array = np.array(image)
        
        # Convert to OpenCV format
        if len(image_array.shape) == 3:
            image_cv = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        else:
            image_cv = image_array
        
        # Load face cascade classifier
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Detect faces in the image
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        # Get all students from database
        db = get_db()
        all_students = db.execute('SELECT * FROM students ORDER BY name').fetchall()
        db.close()
        
        present_students = []
        absent_students = []
        
        # For each detected face, try to match with student faces
        for (x, y, w, h) in faces:
            face_region = image_cv[y:y+h, x:x+w]
            
            # Simple face matching based on stored student images
            matched_student = None
            for student in all_students:
                if student['face_image']:
                    try:
                        # Load stored student face
                        student_face_path = os.path.join('static', student['face_image'])
                        if os.path.exists(student_face_path):
                            student_face = cv2.imread(student_face_path)
                            if student_face is not None:
                                # Simple comparison using histogram correlation
                                if compare_faces(face_region, student_face):
                                    matched_student = student
                                    break
                    except Exception as e:
                        print(f"Error comparing face for student {student['roll']}: {e}")
                        continue
            
            if matched_student and matched_student not in present_students:
                present_students.append({
                    'roll': matched_student['roll'],
                    'name': matched_student['name']
                })
        
        # Mark absent students (those not detected but have face images)
        detected_rolls = {s['roll'] for s in present_students}
        for student in all_students:
            if student['face_image'] and student['roll'] not in detected_rolls:
                absent_students.append({
                    'roll': student['roll'],
                    'name': student['name']
                })
        
        # Mark attendance in database
        db = get_db()
        now = datetime.now()
        
        # Mark present students
        for student in present_students:
            db.execute(
                'INSERT INTO attendance (student_roll, student_name, subject, date, time, marked_by) VALUES (?,?,?,?,?,?)',
                (student['roll'], student['name'], subject, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), session['faculty_id'])
            )
        
        # Mark absent students
        for student in absent_students:
            db.execute(
                'INSERT INTO attendance (student_roll, student_name, subject, date, time, marked_by) VALUES (?,?,?,?,?,?)',
                (student['roll'], student['name'], subject, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), session['faculty_id'])
            )
        
        db.commit()
        db.close()
        
        return jsonify({
            'success': True,
            'present_students': present_students,
            'absent_students': absent_students,
            'faces_detected': len(faces)
        })
        
    except Exception as e:
        print(f"Error processing attendance: {e}")
        return jsonify({'success': False, 'error': str(e)})

def compare_faces(face1, face2):
    """Simple face comparison using histogram correlation"""
    try:
        # Convert to grayscale
        gray1 = cv2.cvtColor(face1, cv2.COLOR_BGR2GRAY) if len(face1.shape) == 3 else face1
        gray2 = cv2.cvtColor(face2, cv2.COLOR_BGR2GRAY) if len(face2.shape) == 3 else face2
        
        # Resize to same dimensions
        gray1 = cv2.resize(gray1, (100, 100))
        gray2 = cv2.resize(gray2, (100, 100))
        
        # Calculate histogram correlation
        hist1 = cv2.calcHist([gray1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([gray2], [0], None, [256], [0, 256])
        
        correlation = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        
        # Threshold for matching (adjust as needed)
        return correlation > 0.7
        
    except Exception as e:
        print(f"Error in face comparison: {e}")
        return False

def check_face_duplicate(new_face_data, db):
    """Check if the uploaded face matches any existing faces in the database"""
    try:
        # Get all students with face images
        students_with_faces = db.execute(
            'SELECT roll, name, face_image FROM students WHERE face_image IS NOT NULL'
        ).fetchall()
        
        if not students_with_faces:
            return False
        
        # Convert new face data to image for comparison
        new_image = Image.open(io.BytesIO(new_face_data))
        new_array = np.array(new_image)
        
        # Convert to OpenCV format
        if len(new_array.shape) == 3:
            new_cv = cv2.cvtColor(new_array, cv2.COLOR_RGB2BGR)
        else:
            new_cv = new_array
        
        # Compare with each existing face
        for student in students_with_faces:
            try:
                existing_face_path = os.path.join('static', student['face_image'])
                if os.path.exists(existing_face_path):
                    existing_face = cv2.imread(existing_face_path)
                    if existing_face is not None:
                        # Compare faces using histogram correlation
                        if compare_faces(new_cv, existing_face):
                            print(f"Face match found with student: {student['name']} ({student['roll']})")
                            return True
            except Exception as e:
                print(f"Error comparing face with student {student['roll']}: {e}")
                continue
        
        return False
        
    except Exception as e:
        print(f"Error in face duplicate check: {e}")
        return False

# ==================== LOGOUT ====================
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    app.run(debug=True)