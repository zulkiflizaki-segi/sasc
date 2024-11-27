from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import os
import uuid
import datetime
from flask_mail import Mail, Message
from db import connect_db
from function import capture_face, load_student_faces, recognize_student_with_details
import base64
import cv2
import numpy as np


app = Flask(__name__)
app.jinja_env.globals.update(enumerate=enumerate)
app.secret_key = 'your_secret_key'

# Ensure faces directory exists
if not os.path.exists('faces'):
    os.makedirs('faces')

# Flask-Mail configuration for sending emails
app.config['MAIL_SERVER'] = 'smtp.example.com'  # Replace with your SMTP server
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = ''
app.config['MAIL_PASSWORD'] = ''

mail = Mail(app)

# Admin Dashboard to manage classrooms and enrollments
@app.route('/admin/dashboard')
def admin_dashboard():
    db = connect_db()
    cursor = db.cursor()

    # Get all classrooms
    cursor.execute("""
        SELECT classrooms.id, classrooms.room_number, classrooms.subject, classrooms.start_time,classrooms.end_time, classrooms.end_date, classrooms.start_date, teachers.name AS teacher_name
        FROM classrooms LEFT JOIN teachers ON classrooms.teacher_id = teachers.id
    """)
    classrooms = cursor.fetchall()

    # Get all teachers for assignment
    cursor.execute("SELECT id, name FROM teachers")
    teachers = cursor.fetchall()

    # Get all students for enrollment
    cursor.execute("SELECT id, name FROM students")
    students = cursor.fetchall()

    return render_template('admin_dashboard.html', classrooms=classrooms, teachers=teachers, students=students)

# Enroll a student into a classroom
@app.route('/admin/enroll_student', methods=['POST'])
def enroll_student():
    student_id = request.form['student_id']
    classroom_id = request.form['classroom_id']

    db = connect_db()
    cursor = db.cursor()

    # Check if the student is already enrolled
    cursor.execute("SELECT * FROM enrollments WHERE student_id = %s AND classroom_id = %s", (student_id, classroom_id))
    if cursor.fetchone():
        flash('Student is already enrolled in this classroom.', 'warning')
    else:
        cursor.execute("INSERT INTO enrollments (student_id, classroom_id) VALUES (%s, %s)", (student_id, classroom_id))
        db.commit()
        flash('Student enrolled successfully!', 'success')

    return redirect(url_for('admin_dashboard'))

# Add a new classroom
@app.route('/admin/add_classroom', methods=['POST'])
def add_classroom():
    """Add a new classroom with schedule validation."""
    room_number = request.form['room_number']
    subject = request.form['subject']
    teacher_id = request.form['teacher_id']
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    start_time = request.form['start_time']
    end_time = request.form['end_time']

    # Check for schedule conflicts
    if check_schedule_conflict(room_number, start_date, end_date, start_time, end_time):
        flash('Error: Schedule conflict detected. Please choose a different time or room.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = connect_db()
    cursor = db.cursor()

    # Insert the new classroom
    cursor.execute("""
        INSERT INTO classrooms (room_number, subject, teacher_id, start_date, end_date, start_time, end_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (room_number, subject, teacher_id, start_date, end_date, start_time, end_time))
    db.commit()

    db.close()
    flash('Classroom added successfully!', 'success')
    return redirect(url_for('admin_dashboard'))



# Route for registering a new user
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        user_id = request.form['id']
        role = request.form['role']
        password = request.form['password']
        hashed_password = generate_password_hash(password)
        face_image_data = request.form['face_image']

        # Decode the face image from Base64
        if face_image_data:
            face_data = base64.b64decode(face_image_data.split(',')[1])
            face_image = np.frombuffer(face_data, dtype=np.uint8)
            face_image = cv2.imdecode(face_image, cv2.IMREAD_COLOR)

            # Save the image (adjust the path as needed)
            face_directory = f'faces/{user_id}'
            if not os.path.exists(face_directory):
                os.makedirs(face_directory)
            cv2.imwrite(f'{face_directory}/{user_id}_1.jpg', face_image)

        # Save user details and hashed password in the database (example)
        db = connect_db()
        cursor = db.cursor()
        if role == 'student':
            cursor.execute("INSERT INTO students (student_id, name, email, password) VALUES (%s, %s, %s, %s)",
                           (user_id, name, email, hashed_password))
        elif role == 'teacher':
            cursor.execute("INSERT INTO teachers (teacher_id, name, email, password) VALUES (%s, %s, %s, %s)",
                           (user_id, name, email, hashed_password))
        db.commit()
        db.close()

        flash('Registration successful and face captured!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# Classroom dashboard route
@app.route('/classroom/dashboard/<int:classroom_id>')
def classroom_dashboard(classroom_id):
    """Display details and attendance records for a specific classroom."""
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch classroom details
    cursor.execute("""
        SELECT classrooms.room_number, classrooms.subject, teachers.name AS teacher_name,
               classrooms.start_date, classrooms.end_date, classrooms.start_time, classrooms.end_time
        FROM classrooms
        JOIN teachers ON classrooms.teacher_id = teachers.id
        WHERE classrooms.id = %s
    """, (classroom_id,))
    classroom = cursor.fetchone()

    # Fetch attendance records for the classroom
    cursor.execute("""
        SELECT attendance.student_id, attendance.role, attendance.face_image_path, attendance.timestamp
        FROM attendance
        WHERE attendance.classroom_id = %s
        ORDER BY attendance.timestamp DESC
    """, (classroom_id,))
    attendance_records = cursor.fetchall()

    db.close()
    return render_template('classroom_dashboard.html', classroom=classroom, attendance_records=attendance_records)

# Attendance capture route with live face detection
@app.route('/classroom/capture', methods=['POST'])
def capture_attendance():
    user_id = request.form['user_id']
    role = request.form['role']
    db = connect_db()
    cursor = db.cursor()

    # Use OpenCV for live face capture and recognition
    recognizer, student_ids = load_student_faces()  # Load trained face recognizer and student IDs

    # Recognize student in real-time using webcam
    recognized_id = recognize_student_with_details(recognizer, student_ids)

    # Validate recognized ID
    if recognized_id is not None and recognized_id == user_id:
        timestamp = datetime.datetime.now()

        # Update attendance record in the database based on role
        if role == 'student':
            cursor.execute("INSERT INTO attendance (classroom_id, student_id, timestamp, role) VALUES (%s, %s, %s, %s)",
                           (1, user_id, timestamp, role))  # Use the correct classroom_id dynamically
        elif role == 'teacher':
            cursor.execute("INSERT INTO attendance (classroom_id, teacher_id, timestamp, role) VALUES (%s, %s, %s, %s)",
                           (1, user_id, timestamp, role))

        db.commit()
        flash(f'Attendance captured for {role} ID: {user_id}', 'success')
    else:
        flash('Face recognition failed or ID mismatch. Please try again.', 'error')

    db.close()
    return redirect(url_for('classroom_dashboard', classroom_id=1))  # Adjust classroom_id as needed


# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        db = connect_db()
        cursor = db.cursor(dictionary=True)

        # Debugging Step: Check Input Email
        print(f"Login attempt for email: {email}")

        # Check if the user is a student
        cursor.execute("SELECT id, name, password FROM students WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            print(f"Student found: {user}")  # Debugging Step
            if check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['name']
                session['role'] = 'student'
                flash('Login successful!', 'success')
                return redirect(url_for('student_dashboard'))  # Redirect to student dashboard

        # Check if the user is a teacher
        cursor.execute("SELECT id, name, password FROM teachers WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            print(f"Teacher found: {user}")  # Debugging Step
            if check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['name']
                session['role'] = 'teacher'
                flash('Login successful!', 'success')
                return redirect(url_for('teacher_dashboard'))  # Redirect to teacher dashboard

        # If no match found
        flash('Invalid email or password. Please try again.', 'error')
        print("Login failed: Invalid credentials")  # Debugging Step

    return render_template('login.html')


# Request password reset page (render the forgot password form)
@app.route('/forgot_password', methods=['GET', 'POST'])
def reset_password_request():
    if request.method == 'POST':
        email = request.form['email']

        db = connect_db()
        cursor = db.cursor()

        # Check if the email is in the students table
        cursor.execute("SELECT email FROM students WHERE email = %s", (email,))
        student = cursor.fetchone()

        # Check if the email is in the teachers table if not found in students
        if not student:
            cursor.execute("SELECT email FROM teachers WHERE email = %s", (email,))
            teacher = cursor.fetchone()

        if student or teacher:
            # Generate a unique reset token and set expiration time
            token = str(uuid.uuid4())  # Generate unique token
            expires_at = datetime.datetime.now() + datetime.timedelta(hours=1)  # Token expires in 1 hour

            # Store token in password_resets table
            cursor.execute("INSERT INTO password_resets (email, token, expires_at) VALUES (%s, %s, %s)",
                           (email, token, expires_at))
            db.commit()

            # Send password reset email with the reset link
            reset_link = url_for('reset_password', token=token, _external=True)
            send_reset_email(email, reset_link)

            flash('A password reset link has been sent to your email.', 'success')
            return redirect(url_for('login'))
        else:
            flash('This email is not registered in the system.', 'error')
            return redirect(url_for('reset_password_request'))

    return render_template('forgot_password.html')


# Function to send password reset email
def send_reset_email(email, reset_link):
    msg = Message('Password Reset Request', sender='your_email@example.com', recipients=[email])
    msg.body = f'Please click the link to reset your password: {reset_link}'
    mail.send(msg)


# Password reset form and logic
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    db = connect_db()
    cursor = db.cursor()

    # Validate the reset token
    cursor.execute("SELECT email, expires_at FROM password_resets WHERE token = %s", (token,))
    reset_request = cursor.fetchone()

    if reset_request:
        email, expires_at = reset_request
        if datetime.datetime.now() > expires_at:
            flash('The reset link has expired. Please request a new one.', 'error')
            return redirect(url_for('reset_password_request'))

        if request.method == 'POST':
            new_password = request.form['password']
            hashed_password = generate_password_hash(new_password)

            # Check if the email belongs to a student
            cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
            student = cursor.fetchone()

            # Check if the email belongs to a teacher
            cursor.execute("SELECT * FROM teachers WHERE email = %s", (email,))
            teacher = cursor.fetchone()

            if student:
                # Update student's password
                cursor.execute("UPDATE students SET password = %s WHERE email = %s", (hashed_password, email))
            elif teacher:
                # Update teacher's password
                cursor.execute("UPDATE teachers SET password = %s WHERE email = %s", (hashed_password, email))

            db.commit()

            # Invalidate the token
            cursor.execute("DELETE FROM password_resets WHERE token = %s", (token,))
            db.commit()

            flash('Your password has been reset successfully.', 'success')
            return redirect(url_for('login'))

        return render_template('reset_password.html', token=token)

    else:
        flash('Invalid or expired reset token.', 'error')
        return redirect(url_for('reset_password_request'))

@app.route('/teacher/dashboard')
def teacher_dashboard():
    teacher_id = session.get('user_id')  # Assuming the teacher is logged in and their ID is stored in the session
    db = connect_db()
    cursor = db.cursor()

    # Get all classrooms assigned to the teacher
    cursor.execute("""
        SELECT classrooms.id, classrooms.room_number, classrooms.subject, classrooms.start_time,classrooms.end_time, classrooms.end_date, classrooms.start_time ,COUNT(enrollments.student_id) AS student_count
        FROM classrooms
        LEFT JOIN enrollments ON classrooms.id = enrollments.classroom_id
        WHERE classrooms.teacher_id = %s
        GROUP BY classrooms.id
    """, (teacher_id,))
    classrooms = cursor.fetchall()

    return render_template('teacher_dashboard.html', classrooms=classrooms)

# View students enrolled in a specific class
@app.route('/teacher/classroom/<int:classroom_id>')
def view_classroom(classroom_id):
    db = connect_db()
    cursor = db.cursor()

    # Get students enrolled in the classroom
    cursor.execute("""
        SELECT students.id, students.name, students.email,
               COUNT(attendance.id) AS total_classes,
               SUM(CASE WHEN attendance.status = 'present' THEN 1 ELSE 0 END) AS attended_classes
        FROM students
        JOIN enrollments ON students.id = enrollments.student_id
        LEFT JOIN attendance ON students.id = attendance.student_id AND attendance.classroom_id = %s
        WHERE enrollments.classroom_id = %s
        GROUP BY students.id
    """, (classroom_id, classroom_id))
    students = cursor.fetchall()

    # Calculate the overall class attendance rate
    cursor.execute("""
        SELECT COUNT(attendance.id) AS total_classes,
               SUM(CASE WHEN attendance.status = 'present' THEN 1 ELSE 0 END) AS attended_classes
        FROM attendance
        WHERE classroom_id = %s
    """, (classroom_id,))
    class_attendance = cursor.fetchone()

    return render_template('view_classroom.html', students=students, class_attendance=class_attendance)

# Update absent reason for a student
@app.route('/teacher/update_absent_reason/<int:attendance_id>', methods=['POST'])
def update_absent_reason(attendance_id):
    absent_reason = request.form['absent_reason']
    evidence_type = request.form['evidence_type']
    db = connect_db()
    cursor = db.cursor()

    # Update the absent reason in the attendance table
    cursor.execute("UPDATE attendance SET absent_reason = %s WHERE id = %s", (absent_reason, attendance_id))

    # Optionally, save evidence in the absent_evidence table
    cursor.execute("""
        INSERT INTO absent_evidence (student_id, evidence_type, evidence_message, submission_date)
        SELECT student_id, %s, %s, NOW() FROM attendance WHERE id = %s
    """, (evidence_type, absent_reason, attendance_id))

    db.commit()
    flash('Absent reason updated successfully!', 'success')
    return redirect(url_for('view_classroom', classroom_id=request.form['classroom_id']))

# Student Dashboard to view enrolled subjects, classrooms, and attendance
@app.route('/student/dashboard')
def student_dashboard():
    """Render the student dashboard with attendance details and submission options."""


    student_id = session.get('user_id')  # Assuming the student is logged in
    db = connect_db()
    cursor = db.cursor()

    # Fetch gamification data
    cursor.execute("""
          SELECT total_points, badges
          FROM gamification
          WHERE student_id = %s
      """, (student_id,))
    gamification_data = cursor.fetchone()

    if not gamification_data:
        gamification_data = {"total_points": 0, "badges": []}

    # Fetch leaderboard
    cursor.execute("""
          SELECT students.name, gamification.total_points
          FROM gamification
          JOIN students ON gamification.student_id = students.id
          ORDER BY gamification.total_points DESC
          LIMIT 10
      """)
    leaderboard = cursor.fetchall()

    # Get all the subjects and classrooms the student is enrolled in
    cursor.execute("""
        SELECT classrooms.id, classrooms.room_number, classrooms.subject,
           COUNT(attendance.id) AS total_classes,
           SUM(CASE WHEN attendance.status = 'present' THEN 1 ELSE 0 END) AS attended_classes
            FROM classrooms
            JOIN enrollments ON classrooms.id = enrollments.classroom_id
            LEFT JOIN attendance ON classrooms.id = attendance.classroom_id
            WHERE enrollments.student_id = %s
            GROUP BY classrooms.id, classrooms.room_number, classrooms.subject
    """, (student_id, student_id))
    enrolled_classes = cursor.fetchall()

    # Get attendance notifications for the student
    cursor.execute("""
        SELECT classrooms.room_number, classrooms.subject, attendance.attendance_date, attendance.status
        FROM attendance
        JOIN classrooms ON attendance.classroom_id = classrooms.id
        WHERE attendance.student_id = %s
        ORDER BY attendance.attendance_date DESC
    """, (student_id,))
    attendance_notifications = cursor.fetchall()

    # Check if any class has an attendance rate below 80%
    classes_below_80 = []
    for classroom in enrolled_classes:
        total_classes = classroom[3] or 0  # Index for total_classes
        attended_classes = classroom[4] or 0  # Index for attended_classes
        attendance_rate = (attended_classes / total_classes) * 100 if total_classes > 0 else 0
        if attendance_rate < 80:
            classes_below_80.append(classroom)

    return render_template('student_dashboard.html', enrolled_classes=enrolled_classes,
                           attendance_notifications=attendance_notifications,
                           classes_below_80=classes_below_80, gamification_data=gamification_data, leaderboard=leaderboard)

# Submit absent evidence
@app.route('/student/upload_evidence', methods=['POST'])
def upload_evidence():
    """Handle the submission of absent evidence."""
    if 'user_id' not in session:
        flash('Please log in to submit evidence.', 'error')
        return redirect(url_for('login'))

    student_id = session['user_id']
    classroom_id = request.form.get('classroom_id')  # Classroom ID selected by the student
    evidence_type = request.form['evidence_type']
    evidence_message = request.form['evidence_message']

    db = connect_db()
    cursor = db.cursor()

    # Insert evidence into the database
    cursor.execute("""
        INSERT INTO absent_evidence (student_id, classroom_id, evidence_type, evidence_message)
        VALUES (%s, %s, %s, %s)
    """, (student_id, classroom_id, evidence_type, evidence_message))
    db.commit()

    db.close()
    flash('Absent evidence submitted successfully!', 'success')
    return redirect(url_for('student_dashboard'))


@app.route('/teacher/classrooms')
def teacher_classrooms():
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch all classrooms assigned to the logged-in teacher
    teacher_id = session.get('user_id')  # Assuming teacher's ID is stored in the session upon login

    # Ensure only classrooms related to the teacher are retrieved
    cursor.execute("SELECT id, room_number FROM classrooms WHERE teacher_id = %s", (teacher_id,))
    classrooms = cursor.fetchall()

    db.close()
    return render_template('manage_classrooms.html', classrooms=classrooms)

# Route to display the "Manage Classrooms" page
@app.route('/teacher/classrooms')
def manage_classrooms():
    """Display classrooms for the logged-in teacher."""
    teacher_id = session.get('user_id')  # Ensure the teacher is logged in
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch classrooms assigned to the teacher
    cursor.execute("""
        SELECT id, room_number, subject, start_date, start_time , end_date, end_time
        FROM classrooms
        WHERE teacher_id = %s
    """, (teacher_id,))
    classrooms = cursor.fetchall()

    db.close()
    return render_template('teacher_dashboard.html', classrooms=classrooms)


@app.route('/admin/edit_classroom/<int:classroom_id>', methods=['POST'])
def edit_classroom(classroom_id):
    """Edit an existing classroom with schedule validation."""
    room_number = request.form['room_number']
    subject = request.form['subject']
    teacher_id = request.form['teacher_id']
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    start_time = request.form['start_time']
    end_time = request.form['end_time']

    # Check for schedule conflicts excluding the current classroom
    if check_schedule_conflict(room_number, start_date, end_date, start_time, end_time, exclude_classroom_id=classroom_id):
        flash('Error: Schedule conflict detected. Please choose a different time or room.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = connect_db()
    cursor = db.cursor()

    # Update classroom details
    cursor.execute("""
        UPDATE classrooms
        SET room_number = %s, subject = %s, teacher_id = %s, start_date = %s, end_date = %s, start_time = %s, end_time = %s
        WHERE id = %s
    """, (room_number, subject, teacher_id, start_date, end_date, start_time, end_time, classroom_id))
    db.commit()

    db.close()
    flash('Classroom updated successfully!', 'success')
    return redirect(url_for('admin_dashboard'))


# Route to delete a classroom
@app.route('/delete_classroom/<int:classroom_id>', methods=['POST'])
def delete_classroom(classroom_id):
    db = connect_db()
    cursor = db.cursor()

    # Delete classroom record from database
    cursor.execute("DELETE FROM classrooms WHERE id = %s", (classroom_id,))
    db.commit()

    db.close()
    flash('Classroom deleted successfully!', 'success')
    return redirect(url_for('manage_classrooms'))

@app.route('/teacher/attendance')
def teacher_attendance():
    """View attendance records for the teacher's classrooms."""
    teacher_id = session.get('user_id')  # Ensure the teacher is logged in
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch all classrooms for the logged-in teacher
    cursor.execute("""
        SELECT classrooms.id, classrooms.room_number, classrooms.subject
        FROM classrooms
        WHERE classrooms.teacher_id = %s
    """, (teacher_id,))
    classrooms = cursor.fetchall()

    # Fetch attendance records for all classrooms of the teacher
    cursor.execute("""
        SELECT attendance.id AS attendance_id, students.name AS student_name, classrooms.room_number,
               classrooms.subject, attendance.attendance_date, attendance.status, attendance.student_id
        FROM attendance
        JOIN students ON attendance.student_id = students.id
        JOIN classrooms ON attendance.classroom_id = classrooms.id
        WHERE classrooms.teacher_id = %s
        ORDER BY attendance.attendance_date DESC
    """, (teacher_id,))
    attendance_records = cursor.fetchall()

    db.close()
    return render_template('teacher_dashboard.html', classrooms=classrooms, attendance_records=attendance_records)


@app.route('/teacher/update_attendance', methods=['POST'])
def update_attendance():
    """Update attendance for a specific student."""
    attendance_id = request.form.get('attendance_id')
    new_status = request.form.get('status')

    db = connect_db()
    cursor = db.cursor()

    # Update attendance status
    cursor.execute("""
        UPDATE attendance
        SET status = %s
        WHERE id = %s
    """, (new_status, attendance_id))
    db.commit()

    db.close()
    flash('Attendance updated successfully!', 'success')
    return redirect(url_for('teacher_attendance'))

@app.route('/teacher/reports')
def teacher_reports():
    """Fetch data for Reports and Exam Results tabs."""
    teacher_id = session.get('user_id')
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch classrooms
    cursor.execute("""
        SELECT classrooms.id, classrooms.room_number, classrooms.subject
        FROM classrooms
        WHERE classrooms.teacher_id = %s
    """, (teacher_id,))
    classrooms = cursor.fetchall()

    # Fetch attendance summary (if needed)
    cursor.execute("""
        SELECT students.id AS student_id, students.name AS student_name, classrooms.room_number,
               classrooms.subject, COUNT(attendance.id) AS total_classes,
               SUM(CASE WHEN attendance.status = 'present' THEN 1 ELSE 0 END) AS attended_classes
        FROM students
        JOIN enrollments ON students.id = enrollments.student_id
        JOIN classrooms ON enrollments.classroom_id = classrooms.id
        LEFT JOIN attendance ON students.id = attendance.student_id AND classrooms.id = attendance.classroom_id
        WHERE classrooms.teacher_id = %s
        GROUP BY students.id, classrooms.id
    """, (teacher_id,))
    attendance_summary = cursor.fetchall()

    # Fetch exam results
    cursor.execute("""
        SELECT exam_results.id AS result_id, students.name AS student_name, classrooms.room_number,
               classrooms.subject, exam_results.exam_type, exam_results.score
        FROM exam_results
        JOIN students ON exam_results.student_id = students.id
        JOIN classrooms ON exam_results.classroom_id = classrooms.id
        WHERE classrooms.teacher_id = %s
        ORDER BY classrooms.id, students.id
    """, (teacher_id,))
    exam_results = cursor.fetchall()

    db.close()
    return render_template('teacher_dashboard.html', classrooms=classrooms,
                           attendance_summary=attendance_summary, exam_results=exam_results)


@app.route('/teacher/upload_score', methods=['POST'])
def upload_score():
    """Upload or update exam scores for a student."""
    student_id = request.form['student_id']
    classroom_id = request.form['classroom_id']
    exam_type = request.form['exam_type']
    score = request.form['score']

    db = connect_db()
    cursor = db.cursor()

    # Insert or update the exam result
    cursor.execute("""
        INSERT INTO exam_results (student_id, classroom_id, exam_type, score)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE score = VALUES(score)
    """, (student_id, classroom_id, exam_type, score))
    db.commit()

    db.close()
    flash('Score uploaded successfully!', 'success')
    return redirect(url_for('teacher_reports'))

@app.route('/student/attendance')
def attendance_notifications():
    """Render attendance notifications and rates for the student."""
    if 'user_id' not in session:
        flash('Please log in to view your attendance.', 'error')
        return redirect(url_for('login'))

    student_id = session['user_id']
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch attendance summary for each class
    cursor.execute("""
        SELECT classrooms.room_number, classrooms.subject,
               COUNT(attendance.id) AS total_classes,
               SUM(CASE WHEN attendance.status = 'present' THEN 1 ELSE 0 END) AS attended_classes,
               SUM(CASE WHEN attendance.status = 'absent' THEN 1 ELSE 0 END) AS absent_classes
        FROM classrooms
        JOIN enrollments ON classrooms.id = enrollments.classroom_id
        LEFT JOIN attendance ON classrooms.id = attendance.classroom_id AND attendance.student_id = %s
        WHERE enrollments.student_id = %s
        GROUP BY classrooms.id
    """, (student_id, student_id))
    attendance_summary = cursor.fetchall()

    # Fetch detailed attendance notifications (dates)
    cursor.execute("""
        SELECT classrooms.room_number, classrooms.subject, attendance.attendance_date, attendance.status
        FROM attendance
        JOIN classrooms ON attendance.classroom_id = classrooms.id
        WHERE attendance.student_id = %s
        ORDER BY attendance.attendance_date DESC
    """, (student_id,))
    attendance_notifications = cursor.fetchall()

    db.close()
    return render_template('student_dashboard.html', attendance_summary=attendance_summary,
                           attendance_notifications=attendance_notifications)

@app.route('/student/gamification')
def gamification():
    """Render the Gamification module."""
    if 'user_id' not in session:
        flash('Please log in to view gamification details.', 'error')
        return redirect(url_for('login'))

    student_id = session['user_id']
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch total points and badges
    cursor.execute("""
        SELECT total_points, badges
        FROM gamification
        WHERE student_id = %s
    """, (student_id,))
    gamification_data = cursor.fetchone()

    # If no gamification data exists, initialize it for the student
    if not gamification_data:
        gamification_data = {"total_points": 0, "badges": []}
        cursor.execute("""
            INSERT INTO gamification (student_id, total_points, badges)
            VALUES (%s, %s, %s)
        """, (student_id, 0, '[]'))
        db.commit()

    # Fetch leaderboard
    cursor.execute("""
        SELECT students.name, gamification.total_points
        FROM gamification
        JOIN students ON gamification.student_id = students.id
        ORDER BY gamification.total_points DESC
        LIMIT 10
    """)
    leaderboard = cursor.fetchall()

    db.close()
    return render_template('student_dashboard.html', gamification_data=gamification_data, leaderboard=leaderboard)


@app.route('/student/exam_results')
def exam_results():
    """Render Exam Results for the student."""
    if 'user_id' not in session:
        flash('Please log in to view your exam results.', 'error')
        return redirect(url_for('login'))

    student_id = session['user_id']
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    # Fetch exam results
    cursor.execute("""
        SELECT classrooms.subject, exam_results.exam_type, exam_results.score, attendance_rate.attendance_rate
        FROM exam_results
        JOIN classrooms ON exam_results.classroom_id = classrooms.id
        JOIN (
            SELECT classrooms.id AS classroom_id,
                   (SUM(CASE WHEN attendance.status = 'present' THEN 1 ELSE 0 END) /
                    COUNT(attendance.id)) * 100 AS attendance_rate
            FROM attendance
            JOIN classrooms ON attendance.classroom_id = classrooms.id
            WHERE attendance.student_id = %s
            GROUP BY classrooms.id
        ) AS attendance_rate
        ON exam_results.classroom_id = attendance_rate.classroom_id
        WHERE exam_results.student_id = %s
    """, (student_id, student_id))
    results = cursor.fetchall()

    db.close()
    return render_template('student_dashboard.html', exam_results=results)

def check_schedule_conflict(room_number, start_date, end_date, start_time, end_time, exclude_classroom_id=None):
    """
    Check if the given classroom schedule conflicts with existing schedules.
    :param room_number: Room number to check.
    :param start_date: Start date of the new schedule.
    :param end_date: End date of the new schedule.
    :param start_time: Start time of the new schedule.
    :param end_time: End time of the new schedule.
    :param exclude_classroom_id: Optional classroom ID to exclude from the check (for updates).
    :return: True if a conflict exists, False otherwise.
    """
    db = connect_db()
    cursor = db.cursor()

    # SQL query to check for schedule conflicts
    query = """
        SELECT id FROM classrooms
        WHERE room_number = %s
        AND (
            (start_date <= %s AND end_date >= %s) -- Date ranges overlap
            AND (
                (start_time <= %s AND end_time > %s) -- Time ranges overlap
                OR (start_time < %s AND end_time >= %s)
                OR (%s <= start_time AND %s >= end_time)
            )
        )
    """
    params = (room_number, end_date, start_date, end_time, start_time, end_time, start_time, start_time, end_time)

    if exclude_classroom_id:
        query += " AND id != %s"
        params += (exclude_classroom_id,)

    cursor.execute(query, params)
    conflict = cursor.fetchone()

    db.close()
    return conflict is not None


# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=False)
