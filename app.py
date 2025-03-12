import os
import logging
from datetime import datetime
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
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///videos.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# Configure upload settings
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                video = Video(
                    title=filename,
                    file_path=filepath,
                    notes=notes,
                    date_archived=datetime.now()
                )
                
        elif 'youtube_url' in request.form:
            url = request.form['youtube_url']
            yt = YouTube(url)
            stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
            filename = secure_filename(yt.title + '.mp4')
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            stream.download(output_path=app.config['UPLOAD_FOLDER'], filename=filename)
            
            video = Video(
                title=yt.title,
                file_path=filepath,
                notes=notes,
                date_archived=datetime.now()
            )

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
    from models import Video, Category
    db.create_all()