# config.py
# Application settings
SECRET_KEY = 'x7k9p2m4q8r5t3v6w1z0'
SQLALCHEMY_TRACK_MODIFICATIONS = False
UPLOAD_FOLDER = '/opt/videoarchive/static/uploads'  # Absolute path
THUMBNAIL_FOLDER = '/opt/videoarchive/static/thumbnails'
LOG_FILE = '/var/log/videoarchive.log'
LOG_LEVEL = 'INFO'

# Database configuration (hardcoded)
DB_PROVIDER = 'postgresql'
DB_USER = 'videoarchive'
DB_PASSWORD = 'Password123'
DB_HOST = 'localhost'
DB_NAME = 'videoarchive'

# Construct SQLALCHEMY_DATABASE_URI based on provider
if DB_PROVIDER.lower() == 'sqlite':
    SQLALCHEMY_DATABASE_URI = 'sqlite:////opt/videoarchive/instance/videoarchive.db'
else:
    SQLALCHEMY_DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'
