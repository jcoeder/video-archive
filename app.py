import os
import logging
import subprocess
from datetime import datetime
import cv2
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.utils import secure_filename
from pytube import YouTube
import urllib.parse

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask app
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Configure SQLite database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///videos.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

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

@app.route('/')
def index():
    from models import Video, Category
    videos = Video.query.order_by(Video.date_archived.desc()).all()
    categories = Category.query.all()
    return render_template('index.html', videos=videos, categories=categories)

@app.route('/upload', methods=['POST'])
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

@app.route('/category/add', methods=['POST'])
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
    from models import Video, Category
    # Drop all tables and recreate them with the new schema
    db.drop_all()
    db.create_all()