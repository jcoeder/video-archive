# Video Archive Setup Guide

This guide explains how to set up the Video Archive Flask application on CentOS 9 and Ubuntu 22+. It includes instructions for installing system dependencies (Python 3.11, PostgreSQL 16), setting up a virtual environment, and configuring PostgreSQL.

## Prerequisites

- A clean installation of CentOS 9 or Ubuntu 22+.
- Root or sudo access to install packages.
- Basic familiarity with the terminal.

## Setup Instructions

### CentOS 9

#### 1. Install System Dependencies

Update the system and install required packages:

```bash
sudo dnf update -y
sudo dnf install -y epel-release
sudo dnf install -y gcc make libpq-devel python3.11 python3.11-devel python3-pip

sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf -qy module disable postgresql
sudo dnf install -y postgresql16 postgresql16-server postgresql16-contrib
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable postgresql-16
sudo systemctl start postgresql-16

sudo dnf install -y opencv opencv-devel


sudo -u postgres psql
CREATE ROLE videoarchive WITH LOGIN PASSWORD 'Password123';
CREATE DATABASE videoarchive;
GRANT ALL PRIVILEGES ON DATABASE videoarchive TO videoarchive;
\q

python3.11 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install flask flask-sqlalchemy psycopg2-binary werkzeug opencv-python










sudo apt update -y
sudo apt install -y build-essential libpq-dev python3.11 python3.11-dev python3.11-venv python3-pip

sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt update -y
sudo apt install -y postgresql-16
sudo systemctl enable postgresql
sudo systemctl start postgresql

sudo apt install -y libopencv-dev python3-opencv

sudo touch /var/log/videoarchive
sudo chown videoarchive:videoarchive /var/log/videoarchive
sudo chmod 664 /var/log/videoarchive

sudo -u postgres psql
CREATE ROLE videoarchive WITH LOGIN PASSWORD 'Password123';
CREATE DATABASE videoarchive;
GRANT ALL PRIVILEGES ON DATABASE videoarchive TO videoarchive;
\q


sudo adduser --home /home/videoarchive --shell /bin/bash videoarchive

su - videoarchive

git clone

cd /home/videoarchive/videoarchive
cd videoarchive
mkdir -p static/uploads static/thumbnails

sudo su - justin cp setup/videoarchive.service /etc/systemd/system/
sudo su - justin systemctl daemon-reload
sudo su - justin systemctl start videoarchive
sudo su - justin systemctl enable videoarchive 


python3.11 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install flask flask-sqlalchemy psycopg2-binary werkzeug opencv-python









python reset_app.py

python app.py
