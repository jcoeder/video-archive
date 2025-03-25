# config.py
SECRET_KEY = 'x7k9p2m4q8r5t3v6w1z0'  # Generated secret key for testing
SQLALCHEMY_DATABASE_URI = 'postgresql://videoarchive:Password123@localhost/videoarchive'
SQLALCHEMY_TRACK_MODIFICATIONS = False
UPLOAD_FOLDER = 'static/uploads'
THUMBNAIL_FOLDER = 'static/thumbnails'
LOG_FILE = '/var/log/videoarchive'  # Log file path
LOG_LEVEL = 'DEBUG'  # Default log level (INFO or DEBUG)
