from database import db  # Updated to import db from database.py
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

video_categories = db.Table('video_categories',
    db.Column('video_id', db.Integer, db.ForeignKey('public.videos.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('public.categories.id'), primary_key=True),
    schema='public'
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    categories = db.relationship('Category', backref='user', lazy=True)
    videos = db.relationship('Video', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_storage_path(self):
        return str(self.uuid if self.id != 1 else self.id)

class Video(db.Model):
    __tablename__ = 'videos'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    thumbnail_path = db.Column(db.String(500))
    notes = db.Column(db.Text)
    date_archived = db.Column(db.DateTime, default=datetime.utcnow)
    exists = db.Column(db.Boolean, default=True)
    file_hash = db.Column(db.String(64))
    user_id = db.Column(db.Integer, db.ForeignKey('public.users.id'), nullable=False)
    categories = db.relationship('Category', secondary=video_categories, lazy='subquery',
        backref=db.backref('videos', lazy=True))

class Category(db.Model):
    __tablename__ = 'categories'
    __table_args__ = (
        db.UniqueConstraint('name', 'user_id', name='_user_category_uc'),
        {'schema': 'public'}
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('public.users.id'), nullable=False)
