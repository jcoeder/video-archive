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
from forms import LoginForm, RegisterForm, ChangePasswordForm, AdminUserCreateForm  # Added AdminUserCreateForm import


# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET") or "dev-secret-key-change-in-production"

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

def get_user_upload_folder(user_id):
    """Get user-specific upload folder path"""
    folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

def get_user_thumbnail_folder(user_id):
    """Get user-specific thumbnail folder path"""
    folder = os.path.join(THUMBNAIL_FOLDER, str(user_id))
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

# Create base directories
for folder in [UPLOAD_FOLDER, THUMBNAIL_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER

@login_manager.user_loader
def load_user(id):
    from models import User
    return User.query.get(int(id))

def cleanup_unused_thumbnails():
    """Clean up thumbnails that don't have corresponding video entries"""
    try:
        from models import Video
        with app.app_context():
            # Get all thumbnail paths from the database
            db_thumbnails = set(v.thumbnail_path for v in Video.query.all() if v.thumbnail_path)

            # Scan thumbnail directory
            for user_dir in os.listdir(THUMBNAIL_FOLDER):
                user_thumb_dir = os.path.join(THUMBNAIL_FOLDER, user_dir)
                if os.path.isdir(user_thumb_dir):
                    for thumb in os.listdir(user_thumb_dir):
                        thumb_path = f"thumbnails/{user_dir}/{thumb}"
                        if thumb_path not in db_thumbnails:
                            try:
                                os.remove(os.path.join('static', thumb_path))
                                logging.info(f"Removed unused thumbnail: {thumb_path}")
                            except Exception as e:
                                logging.error(f"Error removing thumbnail {thumb_path}: {str(e)}")
    except Exception as e:
        logging.error(f"Error in cleanup_unused_thumbnails: {str(e)}")

def scan_video_directory():
    """Scan upload directory and update database"""
    from models import Video, User
    while True:
        with app.app_context():
            try:
                # Check existing videos
                all_videos = Video.query.all()
                for video in all_videos:
                    video_path = os.path.join('static', video.file_path)
                    video.exists = os.path.exists(video_path)

                # Scan for new videos - per user directory
                users = User.query.all()
                for user in users:
                    user_upload_dir = get_user_upload_folder(user.id)
                    if os.path.exists(user_upload_dir):
                        for filename in os.listdir(user_upload_dir):
                            if filename.endswith(tuple(ALLOWED_EXTENSIONS)):
                                filepath = os.path.join('uploads', str(user.id), filename)
                                existing_video = Video.query.filter_by(file_path=filepath).first()
                                if not existing_video:
                                    try:
                                        # Create thumbnail with timestamp to ensure uniqueness
                                        thumbnail_filename = f"{os.path.splitext(filename)[0]}_{int(time.time())}_thumb.jpg"
                                        thumbnail_path = os.path.join(get_user_thumbnail_folder(user.id), thumbnail_filename)

                                        if generate_thumbnail(os.path.join(user_upload_dir, filename), thumbnail_path):
                                            video = Video(
                                                title=os.path.splitext(filename)[0],
                                                file_path=filepath,
                                                thumbnail_path=f"thumbnails/{user.id}/{thumbnail_filename}",
                                                date_archived=datetime.now(),
                                                user_id=user.id
                                            )
                                            db.session.add(video)
                                            logging.info(f"Added new video: {filepath}")
                                        else:
                                            logging.error(f"Failed to generate thumbnail for {filepath}")
                                    except Exception as e:
                                        logging.error(f"Error processing new video {filepath}: {str(e)}")
                                        continue

                db.session.commit()

                # Clean up unused thumbnails
                cleanup_unused_thumbnails()

            except Exception as e:
                logging.error(f"Error in scan_video_directory: {str(e)}")
                try:
                    db.session.rollback()
                except:
                    pass

        time.sleep(300)  # Check every 5 minutes

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def transcode_video(input_path, output_path):
    """Transcode video to web-compatible format (MP4/H.264)"""
    try:
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

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
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

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
    try:
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
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        flash('An error occurred during login', 'danger')
        return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    try:
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
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        flash('An error occurred during registration', 'danger')
        return redirect(url_for('register'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/')
@login_required
def index():
    from models import Video, Category
    if current_user.is_admin:
        videos = Video.query.order_by(Video.date_archived.desc()).all()
        categories = Category.query.all()
    else:
        videos = Video.query.filter_by(user_id=current_user.id).order_by(Video.date_archived.desc()).all()
        categories = Category.query.filter_by(user_id=current_user.id).all()
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
                user_upload_folder = get_user_upload_folder(current_user.id)
                original_filepath = os.path.join(user_upload_folder, f"original_{original_filename}")

                # Ensure directory exists
                os.makedirs(os.path.dirname(original_filepath), exist_ok=True)
                file.save(original_filepath)

                # Transcode to web-compatible format
                final_filename = f"web_{original_filename.rsplit('.', 1)[0]}.mp4"
                final_filepath = os.path.join(user_upload_folder, final_filename)

                if transcode_video(original_filepath, final_filepath):
                    # Generate thumbnail with timestamp
                    thumbnail_filename = f"{os.path.splitext(final_filename)[0]}_{int(time.time())}_thumb.jpg"
                    thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user.id), thumbnail_filename)

                    if generate_thumbnail(final_filepath, thumbnail_path):
                        video = Video(
                            title=os.path.splitext(original_filename)[0],
                            file_path=f"uploads/{current_user.id}/{final_filename}",
                            thumbnail_path=f"thumbnails/{current_user.id}/{thumbnail_filename}",
                            notes=notes,
                            date_archived=datetime.now(),
                            user_id=current_user.id
                        )

                        # Add categories
                        for category_id in categories:
                            category = Category.query.get(category_id)
                            if category and category.user_id == current_user.id:
                                video.categories.append(category)

                        db.session.add(video)
                        db.session.commit()

                        # Clean up original file
                        try:
                            os.remove(original_filepath)
                        except Exception as e:
                            logging.error(f"Error removing original file: {str(e)}")

                        flash('Video successfully archived!', 'success')
                    else:
                        flash('Error generating thumbnail', 'error')
                        return redirect(url_for('index'))
                else:
                    flash('Error processing video file', 'error')
                    return redirect(url_for('index'))

        elif 'youtube_url' in request.form:
            url = request.form['youtube_url']
            try:
                yt = YouTube(url)
                stream = yt.streams.filter(progressive=True, file_extension='mp4').first()

                original_filename = secure_filename(yt.title + '.mp4')
                user_upload_folder = get_user_upload_folder(current_user.id)
                original_filepath = os.path.join(user_upload_folder, f"original_{original_filename}")

                # Ensure directory exists
                os.makedirs(os.path.dirname(original_filepath), exist_ok=True)
                stream.download(filename=original_filepath)

                # Transcode YouTube video
                final_filename = f"web_{original_filename}"
                final_filepath = os.path.join(user_upload_folder, final_filename)

                if transcode_video(original_filepath, final_filepath):
                    # Generate thumbnail with timestamp
                    thumbnail_filename = f"{os.path.splitext(final_filename)[0]}_{int(time.time())}_thumb.jpg"
                    thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user.id), thumbnail_filename)

                    if generate_thumbnail(final_filepath, thumbnail_path):
                        video = Video(
                            title=yt.title,
                            file_path=f"uploads/{current_user.id}/{final_filename}",
                            thumbnail_path=f"thumbnails/{current_user.id}/{thumbnail_filename}",
                            notes=notes,
                            date_archived=datetime.now(),
                            user_id=current_user.id
                        )

                        # Add categories
                        for category_id in categories:
                            category = Category.query.get(category_id)
                            if category and category.user_id == current_user.id:
                                video.categories.append(category)

                        db.session.add(video)
                        db.session.commit()

                        # Clean up original file
                        try:
                            os.remove(original_filepath)
                        except Exception as e:
                            logging.error(f"Error removing original file: {str(e)}")

                        flash('Video successfully archived!', 'success')
                    else:
                        flash('Error generating thumbnail', 'error')
                        return redirect(url_for('index'))
                else:
                    flash('Error processing YouTube video', 'error')
                    return redirect(url_for('index'))
            except Exception as e:
                logging.error(f"Error downloading YouTube video: {str(e)}")
                flash('Error downloading YouTube video. Please try again.', 'error')
                return redirect(url_for('index'))

    except Exception as e:
        logging.error(f"Error uploading video: {str(e)}")
        flash('Error uploading video. Please try again.', 'error')
        db.session.rollback()

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

    # Ensure user owns the video or is admin
    if video.user_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

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
        logger.error(f"Error deleting video: {str(e)}")
        flash(f'Error deleting video: {str(e)}', 'danger')
    return redirect(url_for('index'))


@app.route('/admin/create_user', methods=['POST'])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('index'))

    form = AdminUserCreateForm()
    if form.validate_on_submit():
        from models import User
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('admin'))

        if form.email.data and User.query.filter_by(email=form.email.data).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('admin'))

        user = User(
            username=form.username.data,
            email=form.email.data,
            is_admin=form.is_admin.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'User {form.username.data} created successfully!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('index'))

    form = AdminUserCreateForm()
    from models import User
    users = User.query.all()
    return render_template('admin.html', users=users, form=form)

@app.route('/admin/toggle/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('index'))

    from models import User
    user = User.query.get_or_404(user_id)
    if user.username == 'admin':
        flash('Cannot modify admin status of default admin user.', 'danger')
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f"Admin status {'granted to' if user.is_admin else 'removed from'} {user.username}", 'success')
    return redirect(url_for('admin'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if current_user.check_password(form.current_password.data):
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash('Your password has been updated!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid current password', 'danger')
    return render_template('change_password.html', form=form)


@app.route('/category/add', methods=['POST'])
@login_required
def add_category():
    from models import Category
    name = request.form.get('category_name')
    if name:
        try:
            category = Category(name=name, user_id=current_user.id)
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

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {str(error)}")
    db.session.rollback()
    return "Internal Server Error", 500

# Initialize database and create admin user
with app.app_context():
    # Import models
    from models import Video, Category, User

    # Drop all tables to reset
    db.drop_all()
    # Create all tables with proper schema
    db.create_all()

    # Create default admin user with ID 1
    admin_user = User(
        id=1,
        username='admin',
        email='admin@example.com',
        is_admin=True
    )
    admin_user.set_password('admin')
    db.session.add(admin_user)
    db.session.commit()

# Start scanning thread
scanning_thread = threading.Thread(target=scan_video_directory, daemon=True)
scanning_thread.start()