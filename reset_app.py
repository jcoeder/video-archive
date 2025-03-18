# reset_app.py
from app import db, Video, Tag, app  # Import from app.py
import os
import shutil

def reset_app():
    with app.app_context():
        # Delete all database entries
        db.drop_all()
        db.create_all()
        print("Database emptied and tables recreated.")

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
        print("Reset complete.")
    else:
        print("Reset aborted.")
