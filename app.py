# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import cv2
import hashlib
import threading
import whisper
from pydub import AudioSegment
from config import SECRET_KEY, SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS, UPLOAD_FOLDER, THUMBNAIL_FOLDER, LOG_FILE, LOG_LEVEL
from sqlalchemy import or_
import logging
from logging.handlers import RotatingFileHandler
import torch
import json

# Set up logging
log_level = os.getenv('LOG_LEVEL', LOG_LEVEL).upper()  # Use env var or config default
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)  # 10MB per file, 5 backups
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
logger = logging.getLogger(__name__)
logger.addHandler(handler)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024 * 1024  # 12GB limit

db = SQLAlchemy(app)

# Association table for many-to-many relationship between Video and Tag
video_tags = db.Table('video_tags',
    db.Column('video_id', db.Integer, db.ForeignKey('video.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    theme = db.Column(db.String(20), default='light')

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    thumbnail = db.Column(db.String(200))
    upload_date = db.Column(db.DateTime, default=lambda: datetime.utcnow().replace(second=0, microsecond=0))
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    checksum = db.Column(db.String(64), nullable=False)
    transcription = db.Column(db.Text, nullable=True)
    transcription_status = db.Column(db.String(20), default=None)  # running, completed, failed, or None
    tags = db.relationship('Tag', secondary=video_tags, backref=db.backref('videos', lazy='dynamic'))

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

# Function to generate thumbnail from video (10th frame)
def generate_thumbnail(video_path, output_path):
    logger.debug(f"Generating thumbnail for {video_path} to {output_path}")
    vidcap = cv2.VideoCapture(video_path)
    vidcap.set(cv2.CAP_PROP_POS_FRAMES, 9)
    success, image = vidcap.read()
    if success:
        image = cv2.resize(image, (250, 250), interpolation=cv2.INTER_AREA)
        cv2.imwrite(output_path, image)
        os.chmod(output_path, 0o775)  # Set rwxrwxr-x, group www-data inherited from service
        logger.debug(f"Thumbnail generated successfully for {video_path}")
    else:
        logger.error(f"Failed to generate thumbnail for {video_path}")
    vidcap.release()

# Helper to compute SHA-256 checksum of a file
def compute_checksum(file):
    logger.debug(f"Computing checksum for file")
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: file.read(4096), b""):
        sha256.update(chunk)
    file.seek(0)
    return sha256.hexdigest()

# Helper to transcribe video audio using Whisper
def transcribe_video(video_path, video_id):
    with app.app_context():
        video = db.session.get(Video, video_id)
        if not video:
            logger.error(f"Video {video_id} not found in database")
            return
        video.transcription_status = 'running'
        db.session.commit()
        logger.info(f"Transcription started for video {video_id}")

    try:
        logger.debug(f"Checking video file existence: {video_path}")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found at {video_path}")

        audio_path = video_path + ".wav"
        logger.debug(f"Attempting audio extraction to {audio_path}")
        try:
            video_audio = AudioSegment.from_file(video_path)
            audio = video_audio.set_channels(1).set_frame_rate(16000)
            audio.export(audio_path, format="wav")
            logger.info(f"Audio extracted for video {video_id}: duration={len(audio) / 1000.0}s, sample_rate={audio.frame_rate}, channels={audio.channels}")
        except Exception as e:
            logger.debug(f"Audio extraction failed: {str(e)}", exc_info=True)
            with app.app_context():
                video = db.session.get(Video, video_id)
                if video:
                    video.transcription_status = 'completed'
                    video.transcription = "No audio available in this video."
                    db.session.commit()
                    logger.info(f"Video {video_id} has no detectable audio; marked as completed")
            return

        model = whisper.load_model("tiny")
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"Transcribing video {video_id} using Whisper 'tiny' on {device}")
        result = model.transcribe(audio_path, language="en", word_timestamps=False)
        logger.debug(f"Transcription result: {len(result['segments'])} segments")
        segments = result["segments"]

        transcription_text = ""
        current_interval = 0
        current_paragraph = []
        interval_seconds = 60

        for segment in segments:
            start_time = segment["start"]
            interval = int(start_time // interval_seconds)
            if interval > current_interval:
                if current_paragraph:
                    transcription_text += " ".join(current_paragraph) + "\n\n"
                current_paragraph = []
                current_interval = interval
            current_paragraph.append(segment["text"].strip())

        if current_paragraph:
            transcription_text += " ".join(current_paragraph)

        with app.app_context():
            video = db.session.get(Video, video_id)
            if video:
                video.transcription = transcription_text
                video.transcription_status = 'completed'
                db.session.commit()
                logger.info(f"Transcription completed for video {video_id}: {transcription_text[:50]}...")

        if os.path.exists(audio_path):
            os.remove(audio_path)
            logger.debug(f"Temporary audio file removed: {audio_path}")

    except Exception as e:
        with app.app_context():
            video = db.session.get(Video, video_id)
            if video:
                video.transcription_status = 'failed'
                video.transcription = f"Failed: {str(e)}"
                db.session.commit()
        logger.error(f"Transcription failed for video {video_id}: {str(e)}", exc_info=True)

# Helper to get current user
def get_current_user():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:
            logger.debug(f"Current user retrieved: {user.username} (ID: {user.id})")
            return user
        else:
            logger.debug(f"User not found for user_id: {session['user_id']}")
            session.pop('user_id', None)
    return None

# Helper to clean up unused tags
def cleanup_unused_tags():
    tags = Tag.query.all()
    for tag in tags:
        if not tag.videos:
            logger.debug(f"Removing unused tag: {tag.name}")
            db.session.delete(tag)
    db.session.commit()

# Make get_current_user available in templates
app.jinja_env.globals['get_current_user'] = get_current_user

# Initialize database and create tables
with app.app_context():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['THUMBNAIL_FOLDER'], exist_ok=True)
    db.create_all()
    if not db.session.query(User).filter_by(username='admin').first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
            theme='light'
        )
        db.session.add(admin)
        db.session.commit()

# Routes
@app.route('/preferences', methods=['GET', 'POST'])
def preferences():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_current_user()
    if not current_user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        theme = request.form.get('theme', 'light')
        if theme not in ['light', 'dark']:
            flash('Invalid theme')
        else:
            current_user.theme = theme
            db.session.commit()
            flash(f'Theme set to {theme} mode')
        logger.info(f"User {current_user.username} updated preferences: theme={theme}")
        return redirect(url_for('preferences'))

    logger.debug(f"Rendering preferences page for user {current_user.username}")
    return render_template('preferences.html')

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    all_tags = Tag.query.filter(Tag.videos.any()).order_by(Tag.name).all()
    selected_tag = request.args.get('tag', None)
    search_query = request.args.get('search', None)

    query = Video.query.order_by(Video.upload_date.desc())
    videos = query.all()

    videos_json = [
        {
            'id': video.id,
            'title': video.title,
            'thumbnail': video.thumbnail,
            'upload_date': video.upload_date.strftime('%Y-%m-%d %H:%M'),
            'tags': [tag.name for tag in video.tags],
            'notes': video.notes or '',
            'transcription': video.transcription or '',
            'user_id': video.user_id
        } for video in videos
    ]

    logger.info(f"Rendering index page for user {get_current_user().username if get_current_user() else 'anonymous'}")
    return render_template('index.html', videos=videos, all_tags=all_tags, selected_tag=selected_tag, search_query=search_query, videos_json=json.dumps(videos_json))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = db.session.query(User).filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            logger.info(f"User logged in: {user.username} (ID: {user.id})")
            return redirect(url_for('index'))
        flash('Invalid credentials')
        logger.debug(f"Failed login attempt for username: {username}")
    logger.debug("Rendering login page")
    return render_template('login.html')

@app.route('/logout')
def logout():
    logger.info(f"Logging out user_id: {session.get('user_id')}")
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_current_user()
    if not current_user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'videos' not in request.files:
            logger.error("No video files selected in upload request")
            return jsonify({'error': 'No video files selected'}), 400

        videos = request.files.getlist('videos')
        tags_input = request.form.get('tags', '')
        notes = request.form.get('notes', '')
        status = {}
        logger.info(f"Upload attempt by user {current_user.username}: {len(videos)} files")

        for video in videos:
            if video and video.filename:
                try:
                    checksum = compute_checksum(video)
                    if db.session.query(Video).filter_by(checksum=checksum).first():
                        status[video.filename] = 'Duplicate detected'
                        logger.debug(f"Duplicate video detected: {video.filename}")
                        continue

                    # Sanitize filename: replace spaces and special characters
                    safe_filename = video.filename.replace(' ', '_').replace('[', '').replace(']', '')
                    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_filename}"
                    title = video.filename
                    video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    video.save(video_path)
                    os.chmod(video_path, 0o775)

                    thumbnail_filename = f"thumb_{filename}.jpg"
                    thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_filename)
                    generate_thumbnail(video_path, thumbnail_path)

                    new_video = Video(
                        title=title,
                        filename=filename,
                        thumbnail=thumbnail_filename,
                        notes=notes,
                        user_id=current_user.id,
                        checksum=checksum
                    )

                    if tags_input:
                        tag_names = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
                        for tag_name in tag_names:
                            tag = db.session.query(Tag).filter_by(name=tag_name).first()
                            if not tag:
                                tag = Tag(name=tag_name)
                                db.session.add(tag)
                            new_video.tags.append(tag)

                    db.session.add(new_video)
                    db.session.commit()
                    threading.Thread(target=transcribe_video, args=(video_path, new_video.id)).start()
                    status[video.filename] = 'Uploaded'
                    logger.debug(f"Video {new_video.id} uploaded: {filename}")

                except Exception as e:
                    status[video.filename] = f'Failed: {str(e)}'
                    logger.error(f"Upload failed for {video.filename}: {str(e)}", exc_info=True)

        db.session.commit()
        return jsonify(status), 200

    logger.debug("Rendering upload page")
    return render_template('upload.html')

@app.route('/video/<int:id>', methods=['GET', 'POST'])
def view_video(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_current_user()
    if not current_user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    video = db.session.get(Video, id)
    if not video:
        flash('Video not found.')
        logger.debug(f"Video {id} not found for user {current_user.username}")
        return redirect(url_for('index'))

    if request.method == 'POST':
        if 'notes' in request.form and 'tags' in request.form:
            notes = request.form['notes']
            tags_input = request.form['tags']
            video.notes = notes
            video.tags.clear()

            if tags_input:
                tag_names = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
                for tag_name in tag_names:
                    tag = db.session.query(Tag).filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.session.add(tag)
                    video.tags.append(tag)

            db.session.commit()
            cleanup_unused_tags()
            flash('Video metadata updated successfully')
            logger.info(f"Video {id} metadata updated by user {current_user.username}")

        elif 'save_manual_transcription' in request.form:
            manual_transcription = request.form.get('manual_transcription', '')
            if manual_transcription:
                video.transcription = manual_transcription
                video.transcription_status = 'completed'
                db.session.commit()
                flash('Manual transcription saved successfully.')
                logger.info(f"Manual transcription saved for video {id} by user {current_user.username}")
            else:
                flash('Manual transcription cannot be empty.')
                logger.debug(f"Empty manual transcription attempt for video {id}")

        elif 'start_transcription' in request.form:
            if video.transcription_status == 'running':
                flash('Transcription is already running for this video.')
            else:
                video_path = os.path.join(app.config['UPLOAD_FOLDER'], video.filename)
                threading.Thread(target=transcribe_video, args=(video_path, video.id)).start()
                flash('Transcription started in the background.')
                logger.info(f"Transcription restarted for video {id} by user {current_user.username}")

        return redirect(url_for('view_video', id=id))

    tags = ', '.join(tag.name for tag in video.tags)
    logger.debug(f"Rendering video page for video {id} by user {current_user.username}")
    return render_template('video.html', video=video, tags=tags)

@app.route('/video/<int:id>/transcription', methods=['GET'])
def view_transcription(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_current_user()
    if not current_user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    video = db.session.get(Video, id)
    if not video:
        flash('Video not found.')
        logger.debug(f"Transcription page: Video {id} not found")
        return redirect(url_for('index'))

    if video.transcription_status != 'completed' or not video.transcription:
        flash('Transcription is not available for this video.')
        logger.debug(f"No transcription available for video {id}")
        return redirect(url_for('view_video', id=id))

    interval = request.args.get('interval', 1, type=int)
    if interval not in range(1, 6):
        interval = 1

    one_minute_sections = video.transcription.split('\n\n')
    paragraphs = []
    current_paragraph = []
    sections_per_interval = interval

    for i, section in enumerate(one_minute_sections):
        current_paragraph.append(section)
        if (i + 1) % sections_per_interval == 0 or i == len(one_minute_sections) - 1:
            paragraphs.append(" ".join(current_paragraph))
            current_paragraph = []

    logger.debug(f"Rendering transcription page for video {id} with interval {interval}")
    return render_template('transcription.html', video=video, paragraphs=paragraphs, interval=interval)

@app.route('/delete/<int:id>', methods=['POST'])
def delete_video(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_current_user()
    if not current_user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    video = db.session.get(Video, id)
    if not video:
        flash('Video not found.')
        logger.debug(f"Delete attempt: Video {id} not found")
        return redirect(url_for('index'))

    if not current_user.is_admin and video.user_id != current_user.id:
        flash('You can only delete videos you uploaded')
        logger.debug(f"Unauthorized delete attempt for video {id} by user {current_user.username}")
        return redirect(url_for('index'))

    # Delete static files
    video_path = os.path.join(app.config['UPLOAD_FOLDER'], video.filename)
    thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], video.thumbnail)
    try:
        if os.path.exists(video_path):
            os.remove(video_path)
            logger.debug(f"Deleted video file: {video_path}")
        else:
            logger.debug(f"Video file not found for deletion: {video_path}")

        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
            logger.debug(f"Deleted thumbnail file: {thumbnail_path}")
        else:
            logger.debug(f"Thumbnail file not found for deletion: {thumbnail_path}")
    except Exception as e:
        logger.error(f"Failed to delete static files for video {id}: {str(e)}", exc_info=True)

    db.session.delete(video)
    db.session.commit()
    cleanup_unused_tags()
    flash('Video deleted successfully')
    logger.info(f"Video {id} deleted by user {current_user.username}")
    return redirect(url_for('index'))

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = get_current_user()
    if not user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if not check_password_hash(user.password_hash, current_password):
            flash('Current password is incorrect')
            logger.debug(f"Password change failed for {user.username}: incorrect current password")
        elif new_password != confirm_password:
            flash('New passwords do not match')
            logger.debug(f"Password change failed for {user.username}: passwords do not match")
        elif len(new_password) < 8:
            flash('New password must be at least 8 characters')
            logger.debug(f"Password change failed for {user.username}: password too short")
        else:
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Password changed successfully')
            logger.info(f"Password changed successfully for user {user.username}")
            return redirect(url_for('index'))

    logger.debug(f"Rendering change password page for {user.username}")
    return render_template('change_password.html')

@app.route('/admin/users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_current_user()
    if not current_user:
        flash('Session expired. Please log in again.')
        return redirect(url_for('login'))

    if not current_user.is_admin:
        flash('Admin access required')
        logger.debug(f"Non-admin {current_user.username} attempted to access manage_users")
        return redirect(url_for('index'))

    if request.method == 'POST':
        if 'add_user' in request.form:
            username = request.form['username']
            password = request.form['password']
            if db.session.query(User).filter_by(username=username).first():
                flash('Username already exists')
                logger.debug(f"Add user failed: {username} already exists")
            elif len(password) < 8:
                flash('Password must be at least 8 characters')
                logger.debug(f"Add user failed: password too short for {username}")
            else:
                new_user = User(
                    username=username,
                    password_hash=generate_password_hash(password),
                    is_admin=False,
                    theme='light'
                )
                db.session.add(new_user)
                db.session.commit()
                flash(f'User {username} added successfully')
                logger.info(f"User {username} added by admin {current_user.username}")

        elif 'delete_user' in request.form:
            user_id = request.form['user_id']
            user_to_delete = db.session.get(User, user_id)
            if not user_to_delete:
                flash('User not found.')
                logger.debug(f"Delete user failed: ID {user_id} not found")
                return redirect(url_for('manage_users'))
            if user_to_delete.is_admin:
                flash('Cannot delete admin user')
                logger.debug(f"Delete user failed: {user_to_delete.username} is admin")
            else:
                db.session.delete(user_to_delete)
                db.session.commit()
                flash(f'User {user_to_delete.username} deleted successfully')
                logger.info(f"User {user_to_delete.username} deleted by admin {current_user.username}")

        elif 'toggle_admin' in request.form:
            user_id = request.form['user_id']
            user_to_toggle = db.session.get(User, user_id)
            if not user_to_toggle:
                flash('User not found.')
                logger.debug(f"Toggle admin failed: ID {user_id} not found")
                return redirect(url_for('manage_users'))
            if user_to_toggle.username == 'admin':
                flash('Cannot change admin status of the primary admin user')
                logger.debug(f"Toggle admin failed: {user_to_toggle.username} is primary admin")
            else:
                user_to_toggle.is_admin = not user_to_toggle.is_admin
                db.session.commit()
                flash(f'Admin status for {user_to_toggle.username} updated')
                logger.info(f"Admin status toggled for {user_to_toggle.username} by {current_user.username}")

    users = db.session.query(User).all()
    logger.debug(f"Rendering manage_users page for admin {current_user.username}")
    return render_template('manage_users.html', users=users)

# Custom 404 error handler
@app.errorhandler(404)
def page_not_found(e):
    logger.debug(f"404 error detected, redirecting to index: {request.url}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
