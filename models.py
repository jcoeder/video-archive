from app import db
from datetime import datetime

video_categories = db.Table('video_categories',
    db.Column('video_id', db.Integer, db.ForeignKey('video.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True)
)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    notes = db.Column(db.Text)
    date_archived = db.Column(db.DateTime, default=datetime.utcnow)
    categories = db.relationship('Category', secondary=video_categories, lazy='subquery',
        backref=db.backref('videos', lazy=True))

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
