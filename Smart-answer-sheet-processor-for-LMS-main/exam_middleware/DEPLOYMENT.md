# Smart Answer Sheet Processor - Deployment Guide

**Version**: 1.0.0  
**Last Updated**: 2026-04-07  
**Status**: Production Ready

> This guide provides complete instructions for deploying the Smart Answer Sheet Processor for LMS (Exam Middleware) to production environments.

## Table of Contents

1. [Overview](#overview)
2. [System Requirements](#system-requirements)
3. [Pre-Deployment Checklist](#pre-deployment-checklist)
4. [Local Development Setup](#local-development-setup)
5. [Production Deployment](#production-deployment)
6. [Initial Configuration](#initial-configuration)
7. [Monitoring & Maintenance](#monitoring--maintenance)
8. [Troubleshooting](#troubleshooting)

---

## Overview

**Smart Answer Sheet Processor** is a FastAPI-based middleware that securely bridges physical examination papers to Moodle LMS through a three-step workflow:

1. **Upload**: Administrative staff upload scanned exam papers in bulk
2. **Verify**: System automatically extracts student ID and subject code from filenames
3. **Submit**: Students authenticate and choose which papers to submit to Moodle

### Key Capabilities

- ✅ Bulk file upload with automatic parsing
- ✅ Secure JWT-based staff authentication
- ✅ Moodle OAuth integration for student login
- ✅ Complete audit trail for compliance
- ✅ Encrypted token storage
- ✅ Docker containerization ready
- ✅ PostgreSQL backend with async support
- ✅ Redis session management

---

## System Requirements

### Minimum

- **CPU**: 2 cores
- **Memory**: 4 GB RAM
- **Storage**: 50 GB (adjust based on expected exam volumes)
- **OS**: Ubuntu 20.04 LTS or similar

### Services

- **PostgreSQL**: 14+ (production database)
- **Redis**: 7+ (session/cache management)
- **Python**: 3.10+
- **Docker**: 20.10+ (recommended for deployment)

### Network

- HTTPS/SSL certificates for production domain
- Outbound access to Moodle instance
- Firewall rules for PostgreSQL/Redis access
- CDN or reverse proxy (optional, for high availability)

---

## Pre-Deployment Checklist

Complete these items **before** deploying to production:

### Security

- [ ] Generate strong `SECRET_KEY` (32+ characters)
- [ ] Set unique PostgreSQL password (16+ characters)
- [ ] Set Redis password if exposed to network
- [ ] Obtain SSL certificates for domain
- [ ] Configure CORS origins (exact domain, not wildcard)
- [ ] Set `DEBUG=False` in all environments
- [ ] Update admin password immediately after first login
- [ ] Configure firewall rules

### Configuration

- [ ] Moodle instance accessible and Web Services enabled
- [ ] Obtain Moodle admin token from admin panel
- [ ] Confirm Moodle base URL (https://...)
- [ ] Verify PostgreSQL connection details
- [ ] Confirm Redis connectivity
- [ ] Update upload directory paths (absolute paths recommended)
- [ ] Configure log file location and rotation

### Files & Storage

- [ ] Create `/uploads` directory with proper permissions
- [ ] Create `/logs` directory with proper permissions
- [ ] Ensure disk space for uploads (minimum 50GB recommended)
- [ ] Configure backup plan for PostgreSQL
- [ ] Test backup restore procedure

### Moodle Preparation

- [ ] Create course and assignments
- [ ] Create service account with limited permissions
- [ ] Generate Web Services token
- [ ] Note assignment IDs (visible in URL: `view.php?id=4`)
- [ ] Test token with API call (see MOODLE.md)
- [ ] Ensure students have Moodle accounts

---

## Local Development Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd Smart-answer-sheet-processor-for-LMS-main/exam_middleware
```

### 2. Create Virtual Environment

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Development Environment

```bash
# Copy example environment
cp .env.example .env

# Edit .env for local development
nano .env
```

Dev `.env` should have:

```env
DEBUG=True
DATABASE_MODE=sqlite
MOCK_LMS_ENABLED=True
RELOAD=True
```

### 5. Initialize Database

```bash
python init_db.py --include-samples
```

### 6. Run Development Server

```bash
python run.py
```

Server will be available at `http://localhost:8000`

**Default Credentials (Development Only)**:
- Staff: `admin` / `ChangeMe@123`
- Mock Student: `test_user` / (configured in mock LMS)

---

## Production Deployment

### Option A: Docker Deployment (Recommended)

#### 1. Prepare Production Environment File

Create `.env` in exam_middleware directory:

```env
# Required Production Settings
DEBUG=False
ENVIRONMENT=production
SECRET_KEY=<generate-with-secrets.token_urlsafe(32)>

# Database
DATABASE_MODE=postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=exam_middleware

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=<strong-password-if-exposed>

# Moodle
MOODLE_BASE_URL=https://moodle.yourinstitution.edu
MOODLE_ADMIN_TOKEN=<obtained-from-moodle-admin>
MOCK_LMS_ENABLED=False

# Server
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=["https://yourdomain.com"]

# File Upload
UPLOAD_DIR=/app/uploads
MAX_FILE_SIZE_MB=50

# Logging
LOG_LEVEL=WARNING
LOG_FILE=/app/logs/app.log
```

#### 2. Build Docker Image

```bash
# Production build
docker build -f Dockerfile.prod -t exam-middleware:latest .

# Or use docker-compose
docker-compose -f docker-compose.yml build
```

#### 3. Deploy with Docker Compose

```bash
# Create directory for volumes
mkdir -p /data/postgres /data/redis /app/uploads /app/logs

# Set permissions
chmod 700 /data/postgres /data/redis
chmod 755 /app/uploads /app/logs

# Start services
docker-compose -f docker-compose.yml up -d

# Check status
docker-compose ps
docker-compose logs -f app
```

#### 4. Run Database Initialization

```bash
docker-compose exec app python init_db.py
```

### Option B: Traditional Deployment

#### 1. System Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Install Redis
sudo apt install redis-server -y

# Install Python
sudo apt install python3.10 python3.10-venv python3-pip -y
```

#### 2. Configure PostgreSQL

```bash
sudo systemctl start postgresql
sudo -u postgres psql

# In PostgreSQL shell:
CREATE DATABASE exam_middleware;
CREATE USER exam_user WITH PASSWORD 'strong_password_here';
ALTER ROLE exam_user SET client_encoding TO 'utf8';
ALTER ROLE exam_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE exam_user SET default_transaction_deferrable TO on;
ALTER ROLE exam_user SET default_transaction_read_committed TO off;
GRANT ALL PRIVILEGES ON DATABASE exam_middleware TO exam_user;
\q
```

#### 3. Setup Application

```bash
# Create app directory
sudo mkdir -p /opt/exam_middleware
sudo chown $USER:$USER /opt/exam_middleware
cd /opt/exam_middleware

# Clone and setup
git clone <repo> .
python3 -m venv venv
source venv/bin/activate
pip install -r exam_middleware/requirements.txt

# Create directories
mkdir -p uploads logs
chmod 755 uploads logs
```

#### 4. Configure Environment

```bash
cd exam_middleware
cp .env.example .env
nano .env
# Update all production values
```

#### 5. Initialize Database

```bash
python init_db.py
```

#### 6. Setup Systemd Service

Create `/etc/systemd/system/exam-middleware.service`:

```ini
[Unit]
Description=Smart Answer Sheet Processor
After=network.target postgresql.service redis-server.service

[Service]
Type=notify
User=www-data
WorkingDirectory=/opt/exam_middleware/exam_middleware
Environment="PATH=/opt/exam_middleware/venv/bin"
EnvironmentFile=/opt/exam_middleware/exam_middleware/.env
ExecStart=/opt/exam_middleware/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable exam-middleware
sudo systemctl start exam-middleware
sudo systemctl status exam-middleware
```

#### 7. Setup Nginx Reverse Proxy

Create `/etc/nginx/sites-available/exam-middleware`:

```nginx
upstream exam_middleware_app {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    listen [::]:80;
    server_name yourdomain.com;

    location / {
        return 301 https://$server_name$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 50M;

    location / {
        proxy_pass http://exam_middleware_app;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host $host;
        proxy_redirect off;
    }
}
```

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/exam-middleware /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## Initial Configuration

### 1. Access Staff Portal

Navigate to `https://yourdomain.com`

Login with credentials created during `init_db.py`

### 2. Configure Subject Mappings

Subject mappings link exam subjects to Moodle assignments.

```bash
python setup_subject_mapping.py
```

This interactive script will:
- Help you find assignment IDs from Moodle
- Create subject-to-assignment mappings
- Validate configuration

Example mapping:
- Subject: `19AI405` → Assignment ID: `4`
- Subject: `19AI411` → Assignment ID: `6`

### 3. Setup Student Mappings (if needed)

To link student register numbers to Moodle usernames:

```bash
python setup_username_reg.py
```

### 4. Test Integration

```bash
# Test API health
curl https://yourdomain.com/health

# Test database
curl https://yourdomain.com/api/health
```

---

## Monitoring & Maintenance

### Logs

```bash
# Docker
docker-compose logs -f app

# Traditional
tail -f logs/app.log

# Check specific errors
grep ERROR logs/app.log | tail -20
```

### Database Maintenance

```bash
# Backup
docker-compose exec postgres pg_dump -U postgres exam_middleware > backup.sql

# Restore
docker-compose exec -T postgres psql -U postgres exam_middleware < backup.sql

# Cleanup old audit logs (optional)
docker-compose exec postgres psql -U postgres exam_middleware -c \
  "DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '1 year';"
```

### PostgreSQL Monitoring

```bash
# Connect to database
docker-compose exec postgres psql -U postgres exam_middleware

# Useful queries
\dt                           # List tables
SELECT COUNT(*) FROM examination_artifacts;
SELECT COUNT(*) FROM audit_logs;
\q
```

### Health Checks

```bash
# API endpoint
curl https://yourdomain.com/health

# Database connectivity
docker-compose exec app python -c "from app.db.database import engine; print('DB OK')"

# Redis connectivity
docker-compose exec redis redis-cli ping
```

### Alerts to Monitor

- [ ] Disk space for uploads
- [ ] Database growth (audit logs)
- [ ] Failed Moodle API calls
- [ ] Student submission failures
- [ ] High memory usage

### Automatic Backups

```bash
# Create backup script at /opt/backup_exam_middleware.sh
#!/bin/bash
BACKUP_DIR="/backups/exam_middleware"
DATE=$(date +%Y%m%d_%H%M%S)
docker-compose -f /opt/exam_middleware/exam_middleware/docker-compose.yml \
  exec -T postgres pg_dump -U postgres exam_middleware | \
  gzip > "$BACKUP_DIR/exam_middleware_$DATE.sql.gz"
# Keep only last 30 days
find $BACKUP_DIR -mtime +30 -delete

# Add to crontab
# 0 2 * * * /opt/backup_exam_middleware.sh
```

---

## Troubleshooting

### Cannot Connect to Moodle

```bash
# Check Moodle URL
curl -v https://moodle.yourinstitution.edu

# Verify token in Moodle admin panel
# Check web service is enabled: Admin > Advanced Features > Web Services

# Test token (requires jq)
curl -d "token=YOUR_TOKEN&wsfunction=core_user_get_users&moodlewsrestformat=json" \
  "https://moodle.yourinstitution.edu/webservice/rest/server.php"
```

### Database Connection Failed

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Test connection
docker-compose exec postgres pg_isready -U postgres

# Check credentials in .env
grep POSTGRES .env
```

### Students Cannot Login

1. Verify student has Moodle account
2. Check CORS origins in `.env`
3. Verify student login endpoint is accessible
4. Check browser console for CORS errors

### Files Not Processing

1. Check filename format: `[register_number]_[subject_code].[ext]`
2. Verify file extensions are allowed
3. Check file size doesn't exceed `MAX_FILE_SIZE_MB`
4. View audit logs for specific errors

### Memory Usage High

```bash
# Check which process
docker stats

# Increase limits in docker-compose.yml
# Restart service
docker-compose restart app
```

### SSL Certificate Issues

```bash
# Renew Let's Encrypt certificate
sudo certbot renew

# Check expiration
echo | openssl s_client -servername yourdomain.com -connect yourdomain.com:443 2>/dev/null | openssl x509 -noout -dates
```

---

## Support & Maintenance

### Database Migrations

If schema changes are needed in the future:

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migration
alembic upgrade head
```

### Updating Application

```bash
# Stop service
docker-compose down

# Pull updates
git pull origin main

# Rebuild image
docker-compose build

# Restart
docker-compose up -d
```

### Performance Tuning

Adjust docker-compose resource limits based on:
- Number of concurrent users
- File upload frequency
- Moodle response times

See `docker-compose.yml` deploy section for CPU/memory settings.

---

## Security Considerations

1. **Keep secrets in .env** (never in .env.example or git)
2. **Use HTTPS only** in production
3. **Rotate SECRET_KEY** regularly
4. **Audit logs** for compliance
5. **Regular backups** (encrypted, off-site)
6. **Monitor failed logins**
7. **Update dependencies** regularly
8. **Restrict network access** to admin ports

---

For additional help, refer to:
- [API Documentation](./API.md)
- [Architecture Overview](../readme.md)
- [Moodle Integration Guide](./MOODLE.md)
