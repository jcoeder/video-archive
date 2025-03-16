import os
import logging
import subprocess
import hashlib
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

def allowed_file(filename):
    """Check if a filename has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_file_hash(file_path):
    """Calculate SHA-256 hash of a file"""
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read the file in chunks to handle large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        logging.error(f"Error calculating file hash: {str(e)}")
        return None

def check_duplicate_video(file_hash, user_id):
    """Check if a video with the same hash exists for the user"""
    from models import Video
    return Video.query.filter_by(file_hash=file_hash, user_id=user_id).first()

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


def transcode_video(input_path, output_path):
    """Transcode video to web-compatible format (MP4/H.264)"""
    try:
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264',  # Video codec
            '-preset', 'ultrafast',  # Fastest encoding speed
            '-crf', '28',  # Lower quality for faster encoding
            '-c:a', 'aac',  # Audio codec
            '-b:a', '128k',  # Audio bitrate
            '-movflags', '+faststart',  # Enable streaming
            '-y',  # Overwrite output file if exists
            output_path
        ]

        # Run FFmpeg with timeout
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # 10 minute timeout

        if result.returncode != 0:
            logging.error(f"Transcoding failed: {result.stderr}")
            return False

        # Verify the output file exists and has size
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logging.error("Transcoding failed: Output file is missing or empty")
            return False

        logging.info("Video transcoding completed successfully")
        return True
    except subprocess.TimeoutExpired:
        logging.error("Transcoding timed out after 10 minutes")
        return False
    except Exception as e:
        logging.error(f"Error transcoding video: {str(e)}")
        return False

def generate_thumbnail(video_path, output_path):
    """Generate thumbnail from video"""
    try:
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        logging.info(f"Generating thumbnail from video: {video_path}")

        # Try to open video file
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {video_path}")
            return False

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            logging.error(f"Video has no frames: {video_path}")
            return False

        # Try to read frame at 1 second mark
        cap.set(cv2.CAP_PROP_POS_MSEC, 1000)  # 1 second in
        ret, frame = cap.read()

        if not ret:
            # If failed, try first frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        if ret:
            # Resize frame to a reasonable thumbnail size
            height = 360
            aspect_ratio = frame.shape[1] / frame.shape[0]
            width = int(height * aspect_ratio)
            frame = cv2.resize(frame, (width, height))

            # Write thumbnail
            success = cv2.imwrite(output_path, frame)
            if not success:
                logging.error(f"Failed to write thumbnail to: {output_path}")
                return False

            logging.info(f"Successfully generated thumbnail: {output_path}")
            success = True
        else:
            logging.error(f"Failed to read frame from video: {video_path}")
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
        categories = Category.query.order_by(Category.name).all()
    else:
        videos = Video.query.filter_by(user_id=current_user.id).order_by(Video.date_archived.desc()).all()
        categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
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

                # Save original file
                original_filepath = os.path.join(user_upload_folder, f"original_{original_filename}")
                web_filename = f"web_{os.path.splitext(original_filename)[0]}.mp4"
                web_filepath = os.path.join(user_upload_folder, web_filename)

                os.makedirs(os.path.dirname(original_filepath), exist_ok=True)
                file.save(original_filepath)

                # Calculate file hash
                file_hash = calculate_file_hash(original_filepath)
                if file_hash:
                    # Check for duplicates
                    duplicate = check_duplicate_video(file_hash, current_user.id)
                    if duplicate:
                        try:
                            os.remove(original_filepath)
                        except Exception as e:
                            logging.error(f"Error removing duplicate file: {str(e)}")
                        flash('This video has already been uploaded.', 'warning')
                        return redirect(url_for('video_detail', video_id=duplicate.id))

                # Create web-optimized version
                if transcode_video(original_filepath, web_filepath):
                    # Generate thumbnail
                    thumbnail_filename = f"video_{int(time.time())}_thumb.jpg"
                    thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user.id), thumbnail_filename)

                    if generate_thumbnail(web_filepath, thumbnail_path):
                        # Create database record
                        video = Video(
                            title=os.path.splitext(original_filename)[0],
                            file_path=f"uploads/{current_user.id}/{web_filename}",
                            thumbnail_path=f"thumbnails/{current_user.id}/{thumbnail_filename}",
                            notes=notes,
                            date_archived=datetime.now(),
                            user_id=current_user.id,
                            file_hash=file_hash,
                            exists=True
                        )

                        # Add categories
                        for category_id in categories:
                            category = Category.query.get(category_id)
                            if category and category.user_id == current_user.id:
                                video.categories.append(category)

                        db.session.add(video)
                        db.session.commit()
                        flash('Video successfully uploaded!', 'success')
                    else:
                        try:
                            os.remove(original_filepath)
                            os.remove(web_filepath)
                        except Exception as e:
                            logging.error(f"Error cleaning up files: {str(e)}")
                        flash('Error generating thumbnail', 'error')
                else:
                    try:
                        os.remove(original_filepath)
                    except Exception as e:
                        logging.error(f"Error cleaning up original file: {str(e)}")
                    flash('Error processing video file', 'error')

        elif 'youtube_url' in request.form:
            url = request.form['youtube_url']
            try:
                yt = YouTube(url)
                stream = yt.streams.filter(progressive=True, file_extension='mp4').first()

                original_filename = secure_filename(yt.title + '.mp4')
                user_upload_folder = get_user_upload_folder(current_user.id)

                # Save original file
                original_filepath = os.path.join(user_upload_folder, f"original_{original_filename}")
                os.makedirs(os.path.dirname(original_filepath), exist_ok=True)
                stream.download(filename=original_filepath)

                # Calculate file hash
                file_hash = calculate_file_hash(original_filepath)
                if file_hash:
                    # Check for duplicates
                    duplicate = check_duplicate_video(file_hash, current_user.id)
                    if duplicate:
                        # Clean up the uploaded file
                        try:
                            os.remove(original_filepath)
                        except Exception as e:
                            logging.error(f"Error removing duplicate file: {str(e)}")
                        flash('This video has already been uploaded.', 'warning')
                        return redirect(url_for('video_detail', video_id=duplicate.id))

                # Create web-optimized version
                web_filename = f"web_{os.path.splitext(original_filename)[0]}.mp4"
                web_filepath = os.path.join(user_upload_folder, web_filename)

                if transcode_video(original_filepath, web_filepath):
                    # Generate thumbnail with timestamp
                    thumbnail_filename = f"{os.path.splitext(web_filename)[0]}_{int(time.time())}_thumb.jpg"
                    thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user.id), thumbnail_filename)

                    if generate_thumbnail(web_filepath, thumbnail_path):
                        video = Video(
                            title=yt.title,
                            file_path=f"uploads/{current_user.id}/{web_filename}",  # Store web version path
                            thumbnail_path=f"thumbnails/{current_user.id}/{thumbnail_filename}",
                            notes=notes,
                            date_archived=datetime.now(),
                            user_id=current_user.id,
                            file_hash=file_hash
                        )

                        # Add categories
                        for category_id in categories:
                            category = Category.query.get(category_id)
                            if category and category.user_id == current_user.id:
                                video.categories.append(category)

                        db.session.add(video)
                        db.session.commit()

                        flash('Video successfully archived!', 'success')
                    else:
                        # Clean up files on thumbnail generation failure
                        try:
                            os.remove(original_filepath)
                            os.remove(web_filepath)
                        except Exception as e:
                            logging.error(f"Error cleaning up files: {str(e)}")
                        flash('Error generating thumbnail', 'error')
                        return redirect(url_for('index'))
                else:
                    # Clean up original file on transcoding failure
                    try:
                        os.remove(original_filepath)
                    except Exception as e:
                        logging.error(f"Error cleaning up original file: {str(e)}")
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
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()

    if request.method == 'POST':
        video.notes = request.form.get('notes', '')
        video.categories = []
        for category_id in request.form.getlist('categories'):
            category = Category.query.get(category_id)
            if category and category.user_id == current_user.id:
                video.categories.append(category)
        db.session.commit()
        if request.headers.get('Content-Type') == 'application/x-www-form-urlencoded':
            # AJAX request
            return jsonify({'success': True})
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
        # Get base file paths
        user_upload_dir = os.path.join('static/uploads', str(video.user_id))
        filename = os.path.basename(video.file_path)

        # Handle different possible filename patterns
        if filename.startswith('web_'):
            base_filename = filename[4:]  # Remove 'web_' prefix
        else:
            base_filename = filename

        original_file = os.path.join(user_upload_dir, f"original_{base_filename}")
        web_file = os.path.join(user_upload_dir, f"web_{base_filename}")

        # Delete original file if it exists
        if os.path.exists(original_file):
            try:
                os.remove(original_file)
                logging.info(f"Deleted original file: {original_file}")
            except Exception as e:
                logging.error(f"Error deleting original file {original_file}: {str(e)}")

        # Delete web-optimized file if it exists
        if os.path.exists(web_file):
            try:
                os.remove(web_file)
                logging.info(f"Deleted web file: {web_file}")
            except Exception as e:
                logging.error(f"Error deleting web file {web_file}: {str(e)}")

        # Delete thumbnail if it exists
        if video.thumbnail_path:
            thumb_path = os.path.join('static', video.thumbnail_path)
            if os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                    logging.info(f"Deleted thumbnail: {thumb_path}")
                except Exception as e:
                    logging.error(f"Error deleting thumbnail {thumb_path}: {str(e)}")

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
        return redirect(url_for('admin'))

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
            # Check if category already exists for this user
            existing = Category.query.filter_by(name=name, user_id=current_user.id).first()
            if existing:
                return jsonify({
                    'success': True,
                    'category': {'id': existing.id, 'name': existing.name}
                })

            # Create new category
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

@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('admin'))

    from models import User
    user = User.query.get_or_404(user_id)

    if user.username == 'admin':
        flash('Cannot delete default admin user.', 'danger')
        return redirect(url_for('admin'))

    try:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    return redirect(url_for('admin'))

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {str(error)}")
    db.session.rollback()
    return "Internal Server Error", 500

def sync_video_files():
    """Synchronize video files with database records"""
    from models import Video
    logging.info("Starting video file synchronization...")

    try:
        videos = Video.query.all()
        for video in videos:
            user_upload_folder = get_user_upload_folder(video.user_id)
            user_thumbnail_folder = get_user_thumbnail_folder(video.user_id)

            # Get file paths
            web_file = os.path.join('static', video.file_path)
            web_filename = os.path.basename(video.file_path)

            # Handle original filename (remove 'web_' if present)
            original_filename = web_filename
            if original_filename.startswith('web_'):
                original_filename = original_filename[4:]  # Remove 'web_' prefix

            original_file = os.path.join('static/uploads', str(video.user_id), f"original_{original_filename}")
            thumbnail_file = os.path.join('static', video.thumbnail_path) if video.thumbnail_path else None

            # Check and fix missing files
            if not os.path.exists(web_file):
                if os.path.exists(original_file):
                    logging.info(f"Regenerating web version for video {video.id}")
                    if transcode_video(original_file, web_file):
                        video.exists = True
                    else:
                        video.exists = False
                        logging.error(f"Failed to generate web version for video {video.id}")
                else:
                    video.exists = False
                    logging.warning(f"Video file missing for record {video.id}")

            # Handle missing original file
            if not os.path.exists(original_file) and os.path.exists(web_file):
                logging.info(f"Copying web version to original for video {video.id}")
                try:
                    os.makedirs(os.path.dirname(original_file), exist_ok=True)
                    import shutil
                    shutil.copy2(web_file, original_file)
                    # Update the original file path in case web_ prefix was removed
                    logging.info(f"Successfully restored original file from web version: {original_file}")
                except Exception as e:
                    logging.error(f"Error copying web to original for video {video.id}: {str(e)}")

            # Handle missing thumbnail
            if not thumbnail_file or not os.path.exists(thumbnail_file):
                source_file = None
                # Try web version first, then original
                if os.path.exists(web_file):
                    source_file = web_file
                    logging.info(f"Using web version to generate thumbnail for video {video.id}")
                elif os.path.exists(original_file):
                    source_file = original_file
                    logging.info(f"Using original version to generate thumbnail for video {video.id}")

                if source_file:
                    logging.info(f"Generating missing thumbnail for video {video.id}")
                    thumbnail_filename = f"video_{video.id}_{int(time.time())}_thumb.jpg"
                    thumbnail_path = os.path.join(user_thumbnail_folder, thumbnail_filename)
                    if generate_thumbnail(source_file, thumbnail_path):
                        video.thumbnail_path = f"thumbnails/{video.user_id}/{thumbnail_filename}"
                        logging.info(f"Successfully generated thumbnail: {thumbnail_path}")
                    else:
                        logging.error(f"Failed to generate thumbnail for video {video.id}")

            db.session.commit()

    except Exception as e:
        logging.error(f"Error in sync_video_files: {str(e)}")
        db.session.rollback()

def check_and_sync_video_files():
    """Check video files and sync status in database"""
    from models import Video
    logging.info("Running periodic video file check...")

    try:
        videos = Video.query.all()
        for video in videos:
            user_upload_folder = get_user_upload_folder(video.user_id)
            user_thumbnail_folder = get_user_thumbnail_folder(video.user_id)

            # Get file paths
            web_file = os.path.join('static', video.file_path)
            web_filename = os.path.basename(video.file_path)

            # Handle original filename (remove 'web_' if present)
            original_filename = web_filename
            if original_filename.startswith('web_'):
                original_filename = original_filename[4:]  # Remove 'web_' prefix

            original_file = os.path.join('static/uploads', str(video.user_id), f"original_{original_filename}")
            thumbnail_file = os.path.join('static', video.thumbnail_path) if video.thumbnail_path else None

            # Check if both video files are missing
            if not os.path.exists(web_file) and not os.path.exists(original_file):
                video.exists = False
                # Remove thumbnail if it exists
                if thumbnail_file and os.path.exists(thumbnail_file):
                    try:
                        os.remove(thumbnail_file)
                        video.thumbnail_path = None
                        logging.info(f"Removed thumbnail for missing video {video.id}")
                    except Exception as e:
                        logging.error(f"Error removing thumbnail for video {video.id}: {str(e)}")
            else:
                # If original exists but web version is missing, create it
                if os.path.exists(original_file) and not os.path.exists(web_file):
                    logging.info(f"Regenerating web version for video {video.id}")
                    if transcode_video(original_file, web_file):
                        video.exists = True
                    else:
                        logging.error(f"Failed to generate web version for video {video.id}")

                # If web exists but original is missing, restore it
                if os.path.exists(web_file) and not os.path.exists(original_file):
                    logging.info(f"Copying web version to original for video {video.id}")
                    try:
                        os.makedirs(os.path.dirname(original_file), exist_ok=True)
                        import shutil
                        shutil.copy2(web_file, original_file)
                        logging.info(f"Successfully restored original file: {original_file}")
                    except Exception as e:
                        logging.error(f"Error copying web to original for video {video.id}: {str(e)}")

            db.session.commit()

    except Exception as e:
        logging.error(f"Error in check_and_sync_video_files: {str(e)}")
        db.session.rollback()

def start_background_sync():
    """Start background thread for periodic file checks"""
    def run_periodic_check():
        while True:
            with app.app_context():
                check_and_sync_video_files()
            time.sleep(60)  # Wait for 1 minute

    sync_thread = threading.Thread(target=run_periodic_check, daemon=True)
    sync_thread.start()

# Initialize database and start background sync
with app.app_context():
    # Import models
    from models import Video, Category, User

    # Create all tables with proper schema
    db.create_all()

    # Create default admin user with ID 1 if it doesn't exist
    admin_user = User.query.get(1)
    if not admin_user:
        admin_user = User(
            id=1,
            username='admin',
            email='admin@example.com',
            is_admin=True
        )
        admin_user.set_password('admin')
        db.session.add(admin_user)
        db.session.commit()

    # Run initial sync
    sync_video_files()
    # Start background sync thread
    start_background_sync()