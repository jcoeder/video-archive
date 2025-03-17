import os
import logging
import subprocess
import hashlib
from datetime import datetime
import cv2
import threading
import time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from forms import LoginForm, RegisterForm, ChangePasswordForm, AdminUserCreateForm, UploadForm
from flask_dropzone import Dropzone
from database import db  # Import db from database.py

app = Flask(__name__)

# Configuration
DATABASE_URL = 'postgresql://videoarchive:Password123@localhost:5432/videoarchive'

app.config.update(
    DROPZONE_ALLOWED_FILE_TYPES='video',
    DROPZONE_MAX_FILE_SIZE=500,
    DROPZONE_UPLOAD_MULTIPLE=True,
    DROPZONE_PARALLEL_UPLOADS=10,
    DROPZONE_UPLOAD_ON_CLICK=True,
    DROPZONE_IN_FORM=True,
    DROPZONE_UPLOAD_ACTION='upload_video',
    DROPZONE_DEFAULT_MESSAGE="Drop video files here or click to upload",
    DROPZONE_TIMEOUT=300000,
    SECRET_KEY="dev-secret-key-change-in-production",
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_recycle": 300, "pool_pre_ping": True},
    SESSION_PROTECTION=None,
    UPLOAD_FOLDER='static/uploads',
    THUMBNAIL_FOLDER='static/thumbnails',
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)

# Initialize extensions
dropzone = Dropzone(app)
db.init_app(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = None

@login_manager.user_loader
def load_user(id):
    from models import User
    return db.session.get(User, int(id))

# Constants
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

# Utility functions
def get_user_upload_folder(user):
    folder = os.path.join(app.config['UPLOAD_FOLDER'], user.get_storage_path())
    os.makedirs(folder, exist_ok=True)
    return folder

def get_user_thumbnail_folder(user):
    folder = os.path.join(app.config['THUMBNAIL_FOLDER'], user.get_storage_path())
    os.makedirs(folder, exist_ok=True)
    return folder

for folder in [app.config['UPLOAD_FOLDER'], app.config['THUMBNAIL_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

def transcode_video(input_path, output_path):
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
            '-y', output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logging.error(f"Transcoding failed: {result.stderr}")
            return False
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
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        logging.info(f"Generating thumbnail from video: {video_path}")
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {video_path}")
            return False
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            logging.error(f"Video has no frames: {video_path}")
            return False
        cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
        if ret:
            height, aspect_ratio = 360, frame.shape[1] / frame.shape[0]
            width = int(height * aspect_ratio)
            frame = cv2.resize(frame, (width, height))
            if not cv2.imwrite(output_path, frame):
                logging.error(f"Failed to write thumbnail to: {output_path}")
                return False
            logging.info(f"Successfully generated thumbnail: {output_path}")
            return True
        logging.error(f"Failed to read frame from video: {video_path}")
        return False
    except Exception as e:
        logging.error(f"Error generating thumbnail: {str(e)}")
        return False
    finally:
        if 'cap' in locals():
            cap.release()

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = LoginForm()
        if form.validate_on_submit():
            from models import User
            user = User.query.filter_by(username=form.username.data).first()
            if user and user.check_password(form.password.data):
                login_user(user, remember=False)
                return redirect(url_for('index'))
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))
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
            elif User.query.filter_by(email=form.email.data).first():
                flash('Email already registered', 'danger')
            else:
                user = User(username=form.username.data, email=form.email.data)
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.commit()
                flash('Registration successful!', 'success')
                return redirect(url_for('login'))
            return redirect(url_for('register'))
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
    videos = Video.query.filter_by(user_id=current_user.id).order_by(Video.date_archived.desc()).all()
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = UploadForm()
    return render_template('index.html', videos=videos, categories=categories, form=form)

@app.route('/upload', methods=['POST'])
@login_required
def upload_video():
    from models import Video, Category
    try:
        categories = request.form.getlist('categories')
        notes = request.form.get('notes', '')
        if request.files:
            for key, file in request.files.items():
                if file and allowed_file(file.filename):
                    original_filename = secure_filename(file.filename)
                    user_upload_folder = get_user_upload_folder(current_user)
                    original_filepath = os.path.join(user_upload_folder, f"original_{original_filename}")
                    web_filename = f"web_{os.path.splitext(original_filename)[0]}.mp4"
                    web_filepath = os.path.join(user_upload_folder, web_filename)
                    file.save(original_filepath)
                    file_hash = calculate_file_hash(original_filepath)
                    if file_hash and check_duplicate_video(file_hash, current_user.id):
                        cleanup_files([original_filepath])
                        continue
                    if not transcode_video(original_filepath, web_filepath):
                        cleanup_files([original_filepath])
                        flash(f'Error processing {original_filename}', 'error')
                        continue
                    thumbnail_filename = f"video_{int(time.time())}_thumb.jpg"
                    thumbnail_path = os.path.join(get_user_thumbnail_folder(current_user), thumbnail_filename)
                    if not generate_thumbnail(web_filepath, thumbnail_path):
                        cleanup_files([original_filepath, web_filepath])
                        flash(f'Error generating thumbnail for {original_filename}', 'error')
                        continue
                    video = Video(
                        title=os.path.splitext(original_filename)[0],
                        file_path=f"uploads/{current_user.get_storage_path()}/{web_filename}",
                        thumbnail_path=f"thumbnails/{current_user.get_storage_path()}/{thumbnail_filename}",
                        notes=notes,
                        date_archived=datetime.now(),
                        user_id=current_user.id,
                        file_hash=file_hash
                    )
                    for category_id in categories:
                        if category := Category.query.get(category_id):
                            if category.user_id == current_user.id:
                                video.categories.append(category)
                    db.session.add(video)
                    db.session.commit()
        return redirect(url_for('index'))
    except Exception as e:
        logging.error(f"Error uploading video: {str(e)}")
        flash('Error uploading video. Please try again.', 'error')
        db.session.rollback()
        return redirect(url_for('index'))

def cleanup_files(file_paths):
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logging.error(f"Error removing file {path}: {str(e)}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_file_hash(file_path):
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        logging.error(f"Error calculating file hash: {str(e)}")
        return None

def check_duplicate_video(file_hash, user_id):
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
    if video.user_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    categories = Category.query.filter_by(user_id=video.user_id).order_by(Category.name).all()
    if request.method == 'POST':
        video.notes = request.form.get('notes', '')
        video.categories = [category for category_id in request.form.getlist('categories')
                           if (category := Category.query.get(category_id)) and category.user_id == video.user_id]
        db.session.commit()
        if request.headers.get('Content-Type') == 'application/x-www-form-urlencoded':
            return jsonify({'success': True})
        flash('Video details updated successfully!', 'success')
        return redirect(url_for('video_detail', video_id=video_id))
    return render_template('video.html', video=video, categories=categories)

@app.route('/video/delete/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    from models import Video
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    try:
        user_upload_dir = os.path.join('static/uploads', str(video.user_id))
        filename = os.path.basename(video.file_path)
        base_filename = filename[4:] if filename.startswith('web_') else filename
        for file_path in [
            os.path.join(user_upload_dir, f"original_{base_filename}"),
            os.path.join(user_upload_dir, f"web_{base_filename}"),
            os.path.join('static', video.thumbnail_path) if video.thumbnail_path else None
        ]:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"Deleted file: {file_path}")
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
        elif form.email.data and User.query.filter_by(email=form.email.data).first():
            flash('Email already registered', 'danger')
        else:
            user = User(username=form.username.data, email=form.email.data or None, is_admin=form.is_admin.data)
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
    from models import User
    return render_template('admin.html', users=User.query.all(), form=AdminUserCreateForm())

@app.route('/admin/toggle/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('admin'))
    try:
        from models import User
        user = db.session.get(User, user_id)
        if not user:
            flash('User not found.', 'danger')
        elif user.username == 'admin':
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
        flash('Invalid current password', 'danger')
    return render_template('change_password.html', form=form)

@app.route('/category/add', methods=['POST'])
@login_required
def add_category():
    from models import Category
    name = request.form.get('category_name')
    if not name:
        return jsonify({'success': False, 'error': 'Category name is required'})
    try:
        if existing := Category.query.filter_by(name=name, user_id=current_user.id).first():
            return jsonify({'success': True, 'category': {'id': existing.id, 'name': existing.name}})
        category = Category(name=name, user_id=current_user.id)
        db.session.add(category)
        db.session.commit()
        return jsonify({'success': True, 'category': {'id': category.id, 'name': category.name}})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Category already exists or invalid name'})

@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('admin'))
    from models import User
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin'))
    if user.username == 'admin':
        flash('Cannot delete default admin user.', 'danger')
        return redirect(url_for('admin'))
    try:
        for folder in [
            os.path.join('static/uploads', user.get_storage_path()),
            os.path.join('static/thumbnails', user.get_storage_path())
        ]:
            if os.path.exists(folder):
                import shutil
                shutil.rmtree(folder)
        for video in user.videos:
            db.session.delete(video)
        for category in user.categories:
            db.session.delete(category)
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} deleted successfully!', 'success')
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        db.session.rollback()
        flash('Error deleting user', 'danger')
    return redirect(url_for('admin'))

@app.route('/account_management')
@login_required
def account_management():
    return render_template('account_management.html', form=ChangePasswordForm())

@app.route('/download_content')
@login_required
def download_content():
    import os
    import zipfile
    from io import BytesIO
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        user_upload_folder = get_user_upload_folder(current_user)
        for root, _, files in os.walk(user_upload_folder):
            for file in files:
                if file.startswith('original_'):
                    file_path = os.path.join(root, file)
                    try:
                        zf.write(file_path, os.path.basename(file_path))
                    except Exception as e:
                        logging.error(f"Error adding file to zip: {str(e)}")
    memory_file.seek(0)
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
    from models import Video
    logging.info("Running periodic video file check...")
    try:
        for video in Video.query.all():
            web_file = os.path.join('static', video.file_path)
            original_file = os.path.join('static/uploads', video.user.get_storage_path(),
                                       f"original_{os.path.basename(video.file_path)[4:] if video.file_path.startswith('web_') else os.path.basename(video.file_path)}")
            thumbnail_file = os.path.join('static', video.thumbnail_path) if video.thumbnail_path else None
            if not os.path.exists(web_file) and not os.path.exists(original_file):
                video.exists = False
                if thumbnail_file and os.path.exists(thumbnail_file):
                    os.remove(thumbnail_file)
                    video.thumbnail_path = None
                    logging.info(f"Removed thumbnail for missing video {video.id}")
            elif os.path.exists(original_file) and not os.path.exists(web_file):
                logging.info(f"Regenerating web version for video {video.id}")
                if transcode_video(original_file, web_file):
                    video.exists = True
            elif os.path.exists(web_file) and not os.path.exists(original_file):
                logging.info(f"Copying web version to original for video {video.id}")
                os.makedirs(os.path.dirname(original_file), exist_ok=True)
                import shutil
                shutil.copy2(web_file, original_file)
        db.session.commit()
    except Exception as e:
        logging.error(f"Error in check_and_sync_video_files: {str(e)}")
        db.session.rollback()

def start_background_sync():
    def run_periodic_check():
        while True:
            with app.app_context():
                check_and_sync_video_files()
            time.sleep(60)
    threading.Thread(target=run_periodic_check, daemon=True).start()

def init_app():
    """Initialize database and start background sync"""
    with app.app_context():
        from models import Video, Category, User
        logging.info("Testing database connection...")
        result = db.session.execute(text("SELECT current_database()")).scalar()
        logging.info(f"Connected to database: {result}")
        db.session.execute(text("SET search_path TO public"))
        db.session.commit()

        # Debug metadata contents
        logging.info("Registered tables in Base.metadata: %s", list(db.metadata.tables.keys()))

        logging.info("Creating all database tables...")
        db.metadata.create_all(bind=db.engine)
        db.session.commit()
        logging.info("Tables created successfully.")

        # Verify table existence
        inspector = inspect(db.engine)
        tables = inspector.get_table_names(schema='public')
        logging.info(f"Tables in database: {tables}")
        if 'users' not in tables:
            logging.error("Table 'users' was not created!")
            raise RuntimeError("Table creation failed: 'users' not found")

        if not db.session.get(User, 1):
            logging.info("Creating default admin user...")
            admin_user = User(id=1, username='admin', email='admin@example.com', is_admin=True)
            admin_user.set_password('admin')
            db.session.add(admin_user)
            db.session.commit()
            logging.info("Default admin user created.")
        else:
            logging.info("Admin user already exists.")
        start_background_sync()

if __name__ == '__main__':
    init_app()
    app.run(debug=True)
