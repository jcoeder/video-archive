import os
import logging
import subprocess
from datetime import datetime
import cv2
import threading
import time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.utils import secure_filename
from pytube import YouTube
import urllib.parse
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from forms import LoginForm, RegisterForm

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask app
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
db.init_app(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configure upload settings
UPLOAD_FOLDER = 'static/uploads'
THUMBNAIL_FOLDER = 'static/thumbnails'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

# Create necessary directories
for folder in [UPLOAD_FOLDER, THUMBNAIL_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER

@login_manager.user_loader
def load_user(id):
    from models import User
    return User.query.get(int(id))

def scan_video_directory():
    """Scan upload directory and update database"""
    from models import Video
    while True:
        with app.app_context():
            # Check existing videos
            all_videos = Video.query.all()
            for video in all_videos:
                video_path = os.path.join('static', video.file_path)
                video.exists = os.path.exists(video_path)

            # Scan for new videos
            for filename in os.listdir(UPLOAD_FOLDER):
                if filename.endswith(tuple(ALLOWED_EXTENSIONS)):
                    filepath = os.path.join('uploads', filename)
                    existing_video = Video.query.filter_by(file_path=filepath).first()
                    if not existing_video:
                        # Create thumbnail
                        thumbnail_filename = f"{os.path.splitext(filename)[0]}_thumb.jpg"
                        thumbnail_path = os.path.join(THUMBNAIL_FOLDER, thumbnail_filename)
                        if generate_thumbnail(os.path.join(UPLOAD_FOLDER, filename), thumbnail_path):
                            video = Video(
                                title=os.path.splitext(filename)[0],
                                file_path=filepath,
                                thumbnail_path=f"thumbnails/{thumbnail_filename}",
                                date_archived=datetime.now()
                            )
                            db.session.add(video)

            db.session.commit()
        time.sleep(300)  # Check every 5 minutes

# Start scanning thread
scanning_thread = threading.Thread(target=scan_video_directory, daemon=True)
scanning_thread.start()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def transcode_video(input_path, output_path):
    """Transcode video to web-compatible format (MP4/H.264)"""
    try:
        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264',  # Video codec
            '-preset', 'medium',  # Encoding speed preset
            '-crf', '23',  # Quality (23 is a good balance)
            '-c:a', 'aac',  # Audio codec
            '-b:a', '128k',  # Audio bitrate
            '-movflags', '+faststart',  # Enable streaming
            '-y',  # Overwrite output file if exists
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logging.error(f"Transcoding failed: {result.stderr}")
            return False

        return True
    except Exception as e:
        logging.error(f"Error transcoding video: {str(e)}")
        return False

def generate_thumbnail(video_path, output_path):
    try:
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames < 10:
            frame_number = 0
        else:
            frame_number = 10

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()

        if ret:
            # Resize frame to a reasonable thumbnail size
            height = 360
            aspect_ratio = frame.shape[1] / frame.shape[0]
            width = int(height * aspect_ratio)
            frame = cv2.resize(frame, (width, height))

            cv2.imwrite(output_path, frame)
            success = True
        else:
            success = False

        cap.release()
        return success
    except Exception as e:
        logging.error(f"Error generating thumbnail: {str(e)}")
        return False

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        from models import User
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('index'))
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        from models import User
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/')
@login_required
def index():
    from models import Video, Category
    videos = Video.query.order_by(Video.date_archived.desc()).all()
    categories = Category.query.all()
    return render_template('index.html', videos=videos, categories=categories)

@app.route('/upload', methods=['POST'])
@login_required
def upload_video():
    from models import Video, Category

    if 'video' not in request.files and 'youtube_url' not in request.form:
        flash('No video file or YouTube URL provided', 'error')
        return redirect(url_for('index'))

    categories = request.form.getlist('categories')
    notes = request.form.get('notes', '')

    try:
        if 'video' in request.files:
            file = request.files['video']
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                original_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"original_{original_filename}")
                file.save(original_filepath)

                # Transcode to web-compatible format
                final_filename = f"web_{original_filename.rsplit('.', 1)[0]}.mp4"
                final_filepath = os.path.join(app.config['UPLOAD_FOLDER'], final_filename)

                if transcode_video(original_filepath, final_filepath):
                    # Generate thumbnail from transcoded video
                    thumbnail_filename = f"{os.path.splitext(final_filename)[0]}_thumb.jpg"
                    thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_filename)
                    generate_thumbnail(final_filepath, thumbnail_path)

                    video = Video(
                        title=os.path.splitext(original_filename)[0],
                        file_path=f"uploads/{final_filename}",  # Store relative path
                        thumbnail_path=f"thumbnails/{thumbnail_filename}",  # Store relative path
                        notes=notes,
                        date_archived=datetime.now()
                    )

                    # Clean up original file
                    os.remove(original_filepath)
                else:
                    flash('Error processing video file', 'error')
                    return redirect(url_for('index'))

        elif 'youtube_url' in request.form:
            url = request.form['youtube_url']
            yt = YouTube(url)
            stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
            original_filename = secure_filename(yt.title + '.mp4')
            original_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"original_{original_filename}")
            stream.download(output_path=app.config['UPLOAD_FOLDER'], filename=f"original_{original_filename}")

            # Transcode YouTube video
            final_filename = f"web_{original_filename}"
            final_filepath = os.path.join(app.config['UPLOAD_FOLDER'], final_filename)

            if transcode_video(original_filepath, final_filepath):
                # Generate thumbnail for YouTube video
                thumbnail_filename = f"{os.path.splitext(final_filename)[0]}_thumb.jpg"
                thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_filename)
                generate_thumbnail(final_filepath, thumbnail_path)

                video = Video(
                    title=yt.title,
                    file_path=f"uploads/{final_filename}",  # Store relative path
                    thumbnail_path=f"thumbnails/{thumbnail_filename}",  # Store relative path
                    notes=notes,
                    date_archived=datetime.now()
                )

                # Clean up original file
                os.remove(original_filepath)
            else:
                flash('Error processing YouTube video', 'error')
                return redirect(url_for('index'))

        # Add categories
        for category_id in categories:
            category = Category.query.get(category_id)
            if category:
                video.categories.append(category)

        db.session.add(video)
        db.session.commit()
        flash('Video successfully archived!', 'success')

    except Exception as e:
        logging.error(f"Error uploading video: {str(e)}")
        flash('Error uploading video. Please try again.', 'error')

    return redirect(url_for('index'))

@app.route('/video/<int:video_id>', methods=['GET', 'POST'])
@login_required
def video_detail(video_id):
    from models import Video, Category
    video = Video.query.get_or_404(video_id)
    categories = Category.query.all()

    if request.method == 'POST':
        video.notes = request.form.get('notes', '')
        video.categories = []
        for category_id in request.form.getlist('categories'):
            category = Category.query.get(category_id)
            if category:
                video.categories.append(category)
        db.session.commit()
        flash('Video details updated successfully!', 'success')
        return redirect(url_for('video_detail', video_id=video_id))

    return render_template('video.html', video=video, categories=categories)

@app.route('/video/delete/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    from models import Video
    video = Video.query.get_or_404(video_id)
    try:
        # Delete files
        if video.file_path:
            file_path = os.path.join('static', video.file_path)
            if os.path.exists(file_path):
                os.remove(file_path)
        if video.thumbnail_path:
            thumb_path = os.path.join('static', video.thumbnail_path)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
        # Delete database entry
        db.session.delete(video)
        db.session.commit()
        flash('Video deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting video: {str(e)}', 'danger')
    return redirect(url_for('index'))


@app.route('/category/add', methods=['POST'])
@login_required
def add_category():
    from models import Category
    name = request.form.get('category_name')
    if name:
        try:
            category = Category(name=name)
            db.session.add(category)
            db.session.commit()
            return jsonify({
                'success': True,
                'category': {'id': category.id, 'name': category.name}
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'Category already exists or invalid name'
            })
    return jsonify({
        'success': False,
        'error': 'Category name is required'
    })

with app.app_context():
    # Import models so they can be created
    from models import Video, Category, User
    # Create all tables
    db.drop_all()  # Drop all tables to ensure clean state
    db.create_all()  # Recreate all tables with proper schema