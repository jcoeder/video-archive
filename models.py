from app import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

video_categories = db.Table('video_categories',
    db.Column('video_id', db.Integer, db.ForeignKey('video.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)  # Made email optional
    password_hash = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    categories = db.relationship('Category', backref='user', lazy=True)
    videos = db.relationship('Video', backref='user', lazy=True)
    jobs = db.relationship('Job', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_storage_path(self):
        """Get the user's storage path using UUID"""
        return str(self.uuid if self.id != 1 else self.id)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    thumbnail_path = db.Column(db.String(500))
    notes = db.Column(db.Text)
    date_archived = db.Column(db.DateTime, default=datetime.utcnow)
    exists = db.Column(db.Boolean, default=True)  # Track if video file exists
    file_hash = db.Column(db.String(64))  # Store SHA-256 hash of file
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    categories = db.relationship('Category', secondary=video_categories, lazy='subquery',
        backref=db.backref('videos', lazy=True))

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('name', 'user_id', name='_user_category_uc'),)

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_type = db.Column(db.String(50), nullable=False)  # e.g., 'youtube_download'
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending, processing, completed, failed
    youtube_url = db.Column(db.String(500))
    result = db.Column(db.Text)  # File path or error message
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'job_type': self.job_type,
            'status': self.status,
            'youtube_url': self.youtube_url,
            'result': self.result,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }