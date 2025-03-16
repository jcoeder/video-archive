from app import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

content_categories = db.Table('content_categories',
    db.Column('content_id', db.Integer, db.ForeignKey('content.id'), primary_key=True),
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
    content = db.relationship('Content', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_storage_path(self):
        """Get the user's storage path using UUID"""
        return str(self.uuid if self.id != 1 else self.id)

class Content(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content_type = db.Column(db.String(10), nullable=False)  # 'video' or 'photo'
    file_path = db.Column(db.String(500), nullable=False)
    thumbnail_path = db.Column(db.String(500))
    notes = db.Column(db.Text)
    date_archived = db.Column(db.DateTime, default=datetime.utcnow)
    exists = db.Column(db.Boolean, default=True)  # Track if file exists
    file_hash = db.Column(db.String(64))  # Store SHA-256 hash of file
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_published = db.Column(db.Boolean, default=False)  # New: publishing status
    publish_date = db.Column(db.DateTime)  # New: when the content was published
    global_uri = db.Column(db.String(200), unique=True)  # New: URI for published content
    categories = db.relationship('Category', secondary=content_categories, lazy='subquery',
        backref=db.backref('content', lazy=True))

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('name', 'user_id', name='_user_category_uc'),)