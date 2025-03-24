# reset_app.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import shutil
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS, UPLOAD_FOLDER, THUMBNAIL_FOLDER

# Set up a minimal Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER

# Initialize SQLAlchemy
db = SQLAlchemy(app)

def reset_app():
    with app.app_context():
        # Reflect current database state and drop all tables
        db.reflect()
        db.drop_all()
        print("All existing tables dropped.")

        # Clear the MetaData to avoid conflicts
        db.metadata.clear()

        # Define models inline with extend_existing=True
        class User(db.Model):
            __tablename__ = 'user'
            __table_args__ = {'extend_existing': True}
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(80), unique=True, nullable=False)
            password_hash = db.Column(db.String(255), nullable=False)
            is_admin = db.Column(db.Boolean, default=False)
            theme = db.Column(db.String(20), default='light')

        class Video(db.Model):
            __tablename__ = 'video'
            __table_args__ = {'extend_existing': True}
            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(200), nullable=False)
            filename = db.Column(db.String(200), nullable=False)
            thumbnail = db.Column(db.String(200))
            upload_date = db.Column(db.DateTime, default=lambda: datetime.utcnow().replace(second=0, microsecond=0))
            notes = db.Column(db.Text)
            user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
            checksum = db.Column(db.String(64), nullable=False)
            transcription = db.Column(db.Text, nullable=True)
            transcription_status = db.Column(db.String(20), default=None)
            tags = db.relationship('Tag', secondary='video_tags', backref=db.backref('videos', lazy='dynamic'))

        class Tag(db.Model):
            __tablename__ = 'tag'
            __table_args__ = {'extend_existing': True}
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(50), unique=True, nullable=False)

        # Define the association table
        db.Table('video_tags',
            db.Column('video_id', db.Integer, db.ForeignKey('video.id'), primary_key=True),
            db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True),
            extend_existing=True
        )

        # Create all tables with the new schema
        db.create_all()
        print("New tables created with updated schema.")

    # Delete all files in uploads and thumbnails folders
    upload_folder = app.config['UPLOAD_FOLDER']
    thumbnail_folder = app.config['THUMBNAIL_FOLDER']
    
    if os.path.exists(upload_folder):
        shutil.rmtree(upload_folder)
        os.makedirs(upload_folder)
        print(f"Cleared {upload_folder}")
    
    if os.path.exists(thumbnail_folder):
        shutil.rmtree(thumbnail_folder)
        os.makedirs(thumbnail_folder)
        print(f"Cleared {thumbnail_folder}")

if __name__ == '__main__':
    confirm = input("Are you sure you want to empty the database and delete all uploaded content? (yes/no): ")
    if confirm.lower() == 'yes':
        reset_app()
        print("Reset complete. Run app.py to recreate the admin user.")
    else:
        print("Reset aborted.")
