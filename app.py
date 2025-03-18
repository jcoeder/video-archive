# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import cv2
from config import SECRET_KEY, SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS, UPLOAD_FOLDER, THUMBNAIL_FOLDER  # Import from config

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER

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

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    thumbnail = db.Column(db.String(200))
    upload_date = db.Column(db.DateTime, default=lambda: datetime.utcnow().replace(second=0, microsecond=0))
    notes = db.Column(db.Text)
    tags = db.relationship('Tag', secondary=video_tags, backref=db.backref('videos', lazy='dynamic'))

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

# Function to generate thumbnail from video (10th frame)
def generate_thumbnail(video_path, output_path):
    vidcap = cv2.VideoCapture(video_path)
    vidcap.set(cv2.CAP_PROP_POS_FRAMES, 9)  # 10th frame (0-based index)
    success, image = vidcap.read()
    if success:
        cv2.imwrite(output_path, image)
    vidcap.release()

# Initialize database and create tables
with app.app_context():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['THUMBNAIL_FOLDER'], exist_ok=True)
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123')
        )
        db.session.add(admin)
        db.session.commit()

# Routes
@app.route('/')
def index():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    videos = Video.query.order_by(Video.upload_date.desc()).all()
    return render_template('index.html', videos=videos)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['logged_in'] = True
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'video' not in request.files:
            flash('No video file')
            return redirect(request.url)
        
        video = request.files['video']
        if video.filename == '':
            flash('No selected file')
            return redirect(request.url)
            
        title = request.form['title']
        tags_input = request.form['tags']
        notes = request.form['notes']
        
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{video.filename}"
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        video.save(video_path)
        
        thumbnail_filename = f"thumb_{filename}.jpg"
        thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_filename)
        generate_thumbnail(video_path, thumbnail_path)
        
        new_video = Video(
            title=title,
            filename=filename,
            thumbnail=thumbnail_filename,
            notes=notes
        )
        
        if tags_input:
            tag_names = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
            for tag_name in tag_names:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                new_video.tags.append(tag)
        
        db.session.add(new_video)
        db.session.commit()
        flash('Video uploaded successfully')
        return redirect(url_for('index'))
    
    return render_template('upload.html')

@app.route('/video/<int:id>')
def view_video(id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    video = Video.query.get_or_404(id)
    return render_template('video.html', video=video)

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        user = User.query.filter_by(username='admin').first()  # Single user system
        if not check_password_hash(user.password_hash, current_password):
            flash('Current password is incorrect')
        elif new_password != confirm_password:
            flash('New passwords do not match')
        elif len(new_password) < 8:
            flash('New password must be at least 8 characters')
        else:
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Password changed successfully')
            return redirect(url_for('index'))
    
    return render_template('change_password.html')

if __name__ == '__main__':
    app.run(debug=True)
