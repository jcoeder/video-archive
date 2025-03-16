import os
import logging
import subprocess
import hashlib
from datetime import datetime
import cv2
import threading
import time
import yt_dlp
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from forms import LoginForm, RegisterForm, ChangePasswordForm, AdminUserCreateForm, UploadForm
from flask_dropzone import Dropzone

# Initialize Flask app
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
dropzone = Dropzone(app)

# Configure Dropzone settings
app.config['DROPZONE_ALLOWED_FILE_TYPES'] = ['video']
app.config['DROPZONE_MAX_FILE_SIZE'] = 500  # MB
app.config['DROPZONE_UPLOAD_MULTIPLE'] = True
app.config['DROPZONE_PARALLEL_UPLOADS'] = 1
app.config['DROPZONE_UPLOAD_ON_CLICK'] = False
app.config['DROPZONE_IN_FORM'] = True
app.config['DROPZONE_UPLOAD_ACTION'] = 'upload_video'

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

def get_user_upload_folder(user):
    """Get user-specific upload folder path using UUID"""
    folder = os.path.join(UPLOAD_FOLDER, user.get_storage_path())
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

def get_user_thumbnail_folder(user):
    """Get user-specific thumbnail folder path using UUID"""
    folder = os.path.join(THUMBNAIL_FOLDER, user.get_storage_path())
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
    from forms import UploadForm
    # Remove admin override - all users only see their own videos
    videos = Video.query.filter_by(user_id=current_user.id).order_by(Video.date_archived.desc()).all()
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = UploadForm()
    return render_template('index.html', videos=videos, categories=categories, form=form)

@app.route('/upload', methods=['POST'])
@login_required
def upload_video():
    from models import Video, Category

    try:
        # Get shared metadata for all uploads
        categories = request.form.getlist('categories')
        notes = request.form.get('notes', '')

        if 'youtube_url' in request.form:
            url = request.form['youtube_url']
            try:
                # Configure yt-dlp options
                ydl_opts = {
                    'format': 'best[ext=mp4]',
                    'outtmpl': 'temp_%(title)s.%(ext)s'
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # Download video info first
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', '')
                    original_filename = secure_filename(f"{title}.mp4")
                    user_upload_folder = get_user_upload_folder(current_user)

                    # Set the output path
                    original_filepath = os.path.join(user_upload_folder, f"original_{original_filename}")
                    ydl_opts['outtmpl'] = original_filepath

                    # Download the video
                    ydl.download([url])

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
                    web_filename = f"web_{os.path.splitext(original_filename)[0]}.mp4"
                    web_filepath = os.path.join(user_upload_folder, web_filename)

                    if transcode_video(original_filepath, web_filepath):
                        # Generate thumbnail
                        thumbnail_filename = f"video_{int(time.time())}_thumb.jpg"
                        thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user), thumbnail_filename)

                        if generate_thumbnail(web_filepath, thumbnail_path):
                            video = Video(
                                title=title,
                                file_path=f"uploads/{current_user.get_storage_path()}/{web_filename}",
                                thumbnail_path=f"thumbnails/{current_user.get_storage_path()}/{thumbnail_filename}",
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
                            cleanup_files([original_filepath, web_filepath])
                            flash('Error generating thumbnail', 'error')
                    else:
                        cleanup_files([original_filepath])
                        flash('Error processing YouTube video', 'error')

            except Exception as e:
                logging.error(f"Error downloading YouTube video: {str(e)}")
                flash('Error downloading YouTube video. Please try again.', 'error')
                return redirect(url_for('index'))

        elif request.files:
            # Handle multiple file uploads
            for key, file in request.files.items():
                if file and allowed_file(file.filename):
                    original_filename = secure_filename(file.filename)
                    user_upload_folder = get_user_upload_folder(current_user)

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
                            cleanup_files([original_filepath])
                            continue  # Skip this file and process the next one

                    # Create web-optimized version
                    if transcode_video(original_filepath, web_filepath):
                        # Generate thumbnail
                        thumbnail_filename = f"video_{int(time.time())}_thumb.jpg"
                        thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user), thumbnail_filename)

                        if generate_thumbnail(web_filepath, thumbnail_path):
                            video = Video(
                                title=os.path.splitext(original_filename)[0],
                                file_path=f"uploads/{current_user.get_storage_path()}/{web_filename}",
                                thumbnail_path=f"thumbnails/{current_user.get_storage_path()}/{thumbnail_filename}",
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
                        else:
                            cleanup_files([original_filepath, web_filepath])
                            flash(f'Error generating thumbnail for {original_filename}', 'error')
                    else:
                        cleanup_files([original_filepath])
                        flash(f'Error processing {original_filename}', 'error')

        return redirect(url_for('index'))

    except Exception as e:
        logging.error(f"Error uploading video: {str(e)}")
        flash('Error uploading video. Please try again.', 'error')
        db.session.rollback()
        return redirect(url_for('index'))

def cleanup_files(file_paths):
    """Helper function to clean up files"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logging.error(f"Error removing file {path}: {str(e)}")

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


@app.route('/video/<int:video_id>', methods=['GET', 'POST'])
@login_required
def video_detail(video_id):
    from models import Video, Category
    video = Video.query.get_or_404(video_id)

    # Ensure user owns the video or is admin
    if video.user_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    # Only show categories belonging to the video owner
    categories = Category.query.filter_by(user_id=video.user_id).order_by(Category.name).all()

    if request.method == 'POST':
        if video.user_id != current_user.id and not current_user.is_admin:
            flash('Access denied.', 'danger')
            return redirect(url_for('index'))

        video.notes = request.form.get('notes', '')
        video.categories = []
        for category_id in request.form.getlist('categories'):
            category = Category.query.get(category_id)
            if category and category.user_id == video.user_id:
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
            email=form.email.data or None,  # Convert empty string to None
            is_admin=form.is_admin.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
            flash(f'User {form.username.data} created successfully!', 'success')
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            db.session.rollback()
            flash('Error creating user. Please try again.', 'danger')
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

    try:
        from models import User
        user = User.query.get_or_404(user_id)

        if user.username == 'admin':
            flash('Cannot modify admin status of default admin user.', 'danger')
        else:
            user.is_admin = not user.is_admin
            db.session.commit()
            flash(f"Admin status {'granted to' if user.is_admin else 'removed from'} {user.username}", 'success')
    except Exception as e:
        logger.error(f"Error toggling admin status: {str(e)}")
        db.session.rollback()
        flash('Error updating admin status', 'danger')

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
        # Get user's storage paths
        user_upload_folder = os.path.join('static/uploads', user.get_storage_path())
        user_thumbnail_folder = os.path.join('static/thumbnails', user.get_storage_path())

        # Delete all user's videos and categories
        for video in user.videos:
            db.session.delete(video)
        for category in user.categories:
            db.session.delete(category)

        # Delete the user's folders
        try:
            import shutil
            if os.path.exists(user_upload_folder):
                shutil.rmtree(user_upload_folder)
            if os.path.exists(user_thumbnail_folder):
                shutil.rmtree(user_thumbnail_folder)
        except Exception as e:
            logging.error(f"Error deleting user folders: {str(e)}")

        # Delete the user
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} deleted successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting user: {str(e)}")
        flash('Error deleting user', 'danger')

    return redirect(url_for('admin'))

@app.route('/account_management')
@login_required
def account_management():
    form = ChangePasswordForm()
    return render_template('account_management.html', form=form)

@app.route('/download_content')
@login_required
def download_content():
    import os
    import zipfile
    from io import BytesIO
    from datetime import datetime

    # Create a BytesIO object to store the zip file
    memory_file = BytesIO()

    # Create the zip file
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        user_upload_folder = get_user_upload_folder(current_user)

        # Walk through the user's upload directory
        for root, dirs, files in os.walk(user_upload_folder):
            for file in files:
                # Only include original files
                if file.startswith('original_'):
                    file_path = os.path.join(root, file)
                    # Add file to zip without the full path structure
                    arcname = os.path.basename(file_path)
                    try:
                        zf.write(file_path, arcname)
                    except Exception as e:
                        logging.error(f"Error adding file to zip: {str(e)}")
                        continue

    # Reset the file pointer
    memory_file.seek(0)

    # Generate the response
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'video_archive_{timestamp}.zip'
    )

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {str(error)}")
    db.session.rollback()
    return "Internal Server Error", 500

def check_and_sync_video_files():
    """Check video files and sync status in database"""
    from models import Video
    logging.info("Running periodic video file check...")

    try:
        videos = Video.query.all()
        for video in videos:
            user_upload_folder = get_user_upload_folder(video.user)
            user_thumbnail_folder = get_user_thumbnail_folder(video.user)

            # Get file paths
            web_file = os.path.join('static', video.file_path)
            web_filename = os.path.basename(video.file_path)

            # Handle original filename (remove 'web_' if present)
            original_filename = web_filename
            if original_filename.startswith('web_'):
                original_filename = original_filename[4:]  # Remove 'web_' prefix

            original_file = os.path.join('static/uploads', video.user.get_storage_path(), f"original_{original_filename}")
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
                        logging.error(f"Errorremoving thumbnail for video {video.id}: {str(e)}")
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

    # Start background sync thread
    start_background_sync()

if __name__ == '__main__':
    app.run(debug=True)