Install deps
```
sudo apt install postgresql-16 libpq-dev python3 python3-dev python3-venv python3-pip libopencv-dev ffmpeg nginx -y
```
```
sudo apt install postgresql-16 build-essential libpq-dev python3 python3-dev python3-venv python3-pip libopencv-dev ffmpeg postgresql-contrib nginx -y
```

Enable Postgres
```
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

Create DB
```
CREATE DATABASE videoarchive;
CREATE ROLE videoarchive WITH LOGIN PASSWORD 'Password123';
ALTER DATABASE videoarchive OWNER TO videoarchive;
\c videoarchive
GRANT USAGE, CREATE ON SCHEMA public TO videoarchive;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO videoarchive;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO videoarchive;
\q
```

Create user and set permissions
```
sudo adduser --system --group --home /home/videoarchive videoarchive
sudo usermod -s /bin/bash videoarchive
cd /opt/
sudo git clone https://github.com/jcoeder/videoarchive.git
sudo mkdir -p /opt/videoarchive/static/uploads /opt/videoarchive/static/thumbnails
sudo chown -R videoarchive:videoarchive /opt/videoarchive
sudo touch /var/log/videoarchive.log
sudo chown videoarchive:videoarchive /var/log/videoarchive.log
sudo chmod 660 /var/log/videoarchive.log
```

Setup venv
```
sudo su - videoarchive
cd /opt/videoarchive
python3 -m venv venv
source venv/bin/activate
pip install -r requirements
exit
```

Test the app
```
sudo -u videoarchive /opt/videoarchive/venv/bin/python /opt/videoarchive/app.py
```

Create run app as a service
```
sudo cp /opt/videoarchive/setup/videoarchive.service /etc/systemd/system/videoarchive.service
sudo systemctl daemon-reload
sudo systemctl enable videoarchive.service
sudo systemctl restart videoarchive.service
sudo systemctl status videoarchive.service
```

Setup nginx
```
sudo rm /etc/nginx/sites-available/default
sudo rm /etc/nginx/sites-enabled/default
sudo cp /opt/videoarchive/setup/videoarchive.nginx /etc/nginx/sites-available/videoarchive
sudo ln -s /etc/nginx/sites-available/videoarchive /etc/nginx/sites-enabled/
sudo systemctl enable nginx
sudo systemctl restart nginx
sudo systemctl status nginx
```

