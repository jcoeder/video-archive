sudo apt upgrade -y

sudo apt update -y

sudo apt install git python3-pip python3.11-dev build-essential libssl-dev libffi-dev python3-setuptools python3.11-venv nginx postgresql ffmpeg openssl libgl-dev libglu-dev -y

git clone https://github.com/jcoeder/video-archive.git

cd video-archive

python3.11 -m venv venv

source venv/bin/activate

pip install -r requirements.txt

sudo systemctl enable --now nginx

sudo systemctl enable --now postgresql

sudo -u postgres psql

CREATE ROLE videoarchive WITH LOGIN PASSWORD 'Password123';

CREATE DATABASE videoarchive;

GRANT ALL PRIVILEGES ON DATABASE videoarchive TO videoarchive;

ALTER DATABASE videoarchive OWNER TO videoarchive;

\q

run and test

gunicorn -c gunicorn_config.py app:app
