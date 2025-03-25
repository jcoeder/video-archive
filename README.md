sudo apt install postgresql-16 build-essential libpq-dev python3.11 python3.11-dev python3.11-venv python3-pip libopencv-dev ffmpeg postgresql-contrib -y

sudo systemctl enable --now postgresql
sudo -u postgres psql

CREATE DATABASE videoarchive;
CREATE USER videoarchive WITH PASSWORD 'Password123';
GRANT ALL PRIVILEGES ON DATABASE videoarchive TO videoarchive;
\q

sudo adduser --system --group --no-create-home videoarchive
sudo usermod -s /bin/bash videoarchive
cd /opt/
sudo git clone https://github.com/jcoeder/videoarchive.git
sudo mkdir -p /opt/videoarchive/static/uploads /opt/videoarchive/static/thumbnails
sudo chown -r videoarchive:videoarchive /opt/videoarchive
sudo touch /var/log/videoarchive.log
sudo chown videoarchive:videoarchive /var/log/videoarchive.log
sudo chmod 660 /var/log/videoarchive.log

sudo su - videoarchive
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements
exit


sudo -u videoarchive /opt/videoarchive/venv/bin/python /opt/videoarchive/app.py


sudo vi /etc/systemd/system/videoarchive.service

[Unit]
Description=Video Archive Flask Application
After=network.target

[Service]
User=videoarchive
Group=videoarchive
WorkingDirectory=/opt/videoarchive
Environment="PATH=/opt/videoarchive/venv/bin:/usr/bin:/bin"
ExecStart=/opt/videoarchive/venv/bin/gunicorn --workers 4 --timeout 600 --bind 0.0.0.0:5000 app:app
Restart=always
StandardOutput=append:/var/log/videoarchive.log
StandardError=append:/var/log/videoarchive.log

[Install]
WantedBy=multi-user.target


sudo systemctl daemon-reload
sudo systemctl enable videoarchive.service
sudo systemctl restart videoarchive.service
sudo systemctl status videoarchive.service




sudo vi /etc/nginx/sites-available/videoarchive

server {
    listen 80;
    server_name 172.21.41.52;  # Your server's IP

    # Allow large file uploads (12GB)
    client_max_body_size 12G;

    # Increase timeout and buffer settings for large uploads
    proxy_headers_hash_max_size 1024;
    proxy_headers_hash_bucket_size 128;
    proxy_read_timeout 600;         # 10 minutes
    proxy_connect_timeout 600;      # 10 minutes
    proxy_send_timeout 600;         # 10 minutes
    proxy_buffer_size 128k;         # Increase buffer size
    proxy_buffers 4 256k;           # Number and size of buffers
    proxy_busy_buffers_size 256k;   # Buffer size for busy responses

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/videoarchive/static/;
        expires 30d;
        access_log off;
    }
}

sudo systemctl enable nginx
sudo systemctl restart nginx
sudo systemctl status nginx
