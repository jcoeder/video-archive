Install deps
```
sudo apt install postgresql-16 build-essential libpq-dev python3 python3-dev python3-venv python3-pip libopencv-dev ffmpeg postgresql-contrib -y
```

Enable Postgres
```
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

Create DB
```
CREATE DATABASE videoarchive;
CREATE USER videoarchive WITH PASSWORD 'Password123';
GRANT ALL PRIVILEGES ON DATABASE videoarchive TO videoarchive;
\q
```

Create user and set permissions
```
sudo adduser --system --group --no-create-home videoarchive
sudo usermod -s /bin/bash videoarchive
cd /opt/
sudo git clone https://github.com/jcoeder/videoarchive.git
sudo mkdir -p /opt/videoarchive/static/uploads /opt/videoarchive/static/thumbnails
sudo chown -r videoarchive:videoarchive /opt/videoarchive
sudo touch /var/log/videoarchive.log
sudo chown videoarchive:videoarchive /var/log/videoarchive.log
sudo chmod 660 /var/log/videoarchive.log
```

Setup venv
```
sudo su - videoarchive
python3.11 -m venv venv
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
sudo cp /opt/videoarchive/setup/videoarchive.nginx /etc/nginx/sites-available/videoarchive
sudo ln -s /etc/nginx/sites-available/videoarchive /etc/nginx/sites-enabled/
sudo systemctl enable nginx
sudo systemctl restart nginx
sudo systemctl status nginx
```

