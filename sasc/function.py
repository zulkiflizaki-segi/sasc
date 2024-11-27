import cv2
import numpy as np
from flask import flash
import os


# Initialize the Haar Cascade
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Preprocessing helper function
def preprocess_face(image):
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Normalize lighting
    gray = cv2.equalizeHist(gray)
    # Resize to a consistent size (e.g., 100x100)
    resized_face = cv2.resize(gray, (100, 100))
    return resized_face

# Function to capture face images for training
def capture_face(user_id):
    cap = cv2.VideoCapture(0)
    face_count = 0
    user_dir = f'faces/{user_id}'

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)

    while face_count < 25:  # Capture up to 25 images per student
        ret, frame = cap.read()
        if not ret:
            flash('Error: Unable to access the camera.', 'error')
            break

        faces = face_cascade.detectMultiScale(frame, scaleFactor=1.3, minNeighbors=5)

        for (x, y, w, h) in faces:
            face_count += 1
            face_img = frame[y:y+h, x:x+w]
            processed_face = preprocess_face(face_img)
            face_filename = f'{user_dir}/{user_id}_{face_count}.jpg'
            cv2.imwrite(face_filename, processed_face)

            # Feedback on the frame
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f'Capturing {face_count}/25', (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.imshow('Capturing Faces', frame)

        if cv2.waitKey(1) & 0xFF == ord('q') or face_count >= 25:
            break

    cap.release()
    cv2.destroyAllWindows()
    flash(f'{face_count} face images captured successfully for user {user_id}', 'success')

# Load and train LBPH recognizer
def load_student_faces():
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    faces, labels = [], []
    student_ids = {}

    for student_id in os.listdir('faces'):
        user_dir = f'faces/{student_id}'
        for img_file in os.listdir(user_dir):
            img_path = f'{user_dir}/{img_file}'
            img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            faces.append(preprocess_face(img))  # Preprocess image before training
            labels.append(int(student_id))
        student_ids[int(student_id)] = student_id

    if faces:
        recognizer.train(faces, np.array(labels))
    else:
        flash('No faces available for training.', 'warning')

    return recognizer, student_ids

# Real-time recognition with enhanced feedback
def recognize_student_with_details(recognizer, student_ids):
    cap = cv2.VideoCapture(0)
    recognized_id = None

    while True:
        ret, frame = cap.read()
        if not ret:
            flash('Error: Unable to capture video from camera.', 'error')
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

        for (x, y, w, h) in faces:
            face_img = preprocess_face(gray[y:y + h, x:x + w])

            try:
                label, confidence = recognizer.predict(face_img)
                if confidence < 50:  # Confidence threshold
                    recognized_id = student_ids.get(label)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(frame, f'ID: {recognized_id}, Conf: {int(confidence)}',
                                (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                else:
                    cv2.putText(frame, 'Unknown', (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            except cv2.error:
                cv2.putText(frame, 'Error', (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        cv2.imshow('Recognition', frame)

        if cv2.waitKey(1) & 0xFF == ord('q') or recognized_id:
            break

    cap.release()
    cv2.destroyAllWindows()
    return recognized_id
