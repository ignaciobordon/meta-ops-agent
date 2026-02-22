# Meta Ops Agent - Production Deployment Guide

Complete step-by-step guide for deploying Meta Ops Agent to production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Server Setup](#server-setup)
3. [Environment Configuration](#environment-configuration)
4. [Database Setup](#database-setup)
5. [Application Deployment](#application-deployment)
6. [Web Server Configuration](#web-server-configuration)
7. [Process Management](#process-management)
8. [Monitoring Setup](#monitoring-setup)
9. [Backup Strategy](#backup-strategy)
10. [Post-Deployment Checklist](#post-deployment-checklist)

---

## Prerequisites

### System Requirements
- **OS**: Ubuntu 22.04 LTS (recommended) or Debian 11+
- **CPU**: 2+ cores (4+ recommended)
- **RAM**: 4GB minimum (8GB+ recommended)
- **Storage**: 20GB+ SSD
- **Network**: Static IP or domain name with SSL certificate

### Required Software
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install system dependencies
sudo apt install -y git nginx certbot python3-certbot-nginx postgresql redis-server

# Install Node.js (for frontend)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### Access Requirements
- SSH access to production server
- Domain name (e.g., `meta-ops.yourdomain.com`)
- SSL certificate (Let's Encrypt or commercial)
- Meta App credentials (App ID + Secret)
- Anthropic API key

---

## Server Setup

### 1. Create Application User
```bash
# Create dedicated user (security best practice)
sudo useradd -m -s /bin/bash meta-ops
sudo usermod -aG sudo meta-ops

# Switch to application user
sudo su - meta-ops
```

### 2. Clone Repository
```bash
cd /home/meta-ops
git clone https://github.com/yourusername/meta-ops-agent.git
cd meta-ops-agent

# Checkout production branch
git checkout main  # or production branch
```

### 3. Create Directory Structure
```bash
# Create required directories
mkdir -p /home/meta-ops/meta-ops-agent/{logs,backups,chroma_data}

# Set permissions
chmod 750 /home/meta-ops/meta-ops-agent
chmod 700 /home/meta-ops/meta-ops-agent/chroma_data
```

---

## Environment Configuration

### 1. Create Production .env File
```bash
cd /home/meta-ops/meta-ops-agent
cp .env.template .env
chmod 600 .env  # Restrict access to owner only
```

### 2. Configure Environment Variables
Edit `.env` with production values:

```bash
# .env - Production Configuration

# ===== CRITICAL SECRETS (REQUIRED) =====
ANTHROPIC_API_KEY=sk-ant-api03-xxx...
META_APP_ID=your_meta_app_id
META_APP_SECRET=your_meta_app_secret
JWT_SECRET_KEY=your_secure_random_key_min_32_chars

# ===== Database =====
DATABASE_URL=postgresql://meta_ops_user:secure_password@localhost/meta_ops_db

# ===== Application =====
ENVIRONMENT=production
DEBUG=false

# ===== Security =====
RATE_LIMIT_PER_MINUTE=100
OPERATOR_ARMED=false  # Set true only after thorough testing

# ===== ChromaDB =====
CHROMA_PERSIST_DIRECTORY=/home/meta-ops/meta-ops-agent/chroma_data

# ===== Embedding Model =====
EMBEDDING_MODEL=all-MiniLM-L6-v2

# ===== Logging =====
LOG_LEVEL=INFO
LOG_FILE=/home/meta-ops/meta-ops-agent/logs/app.log

# ===== CORS (Update with your frontend domains) =====
CORS_ORIGINS=https://meta-ops.yourdomain.com,https://app.yourdomain.com
```

### 3. Generate Secure JWT Secret
```bash
# Generate strong random key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Copy output to JWT_SECRET_KEY in .env
```

---

## Database Setup

### 1. Install and Configure PostgreSQL
```bash
# PostgreSQL should already be installed
sudo systemctl status postgresql

# Create database and user
sudo -u postgres psql <<EOF
CREATE DATABASE meta_ops_db;
CREATE USER meta_ops_user WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE meta_ops_db TO meta_ops_user;
ALTER DATABASE meta_ops_db OWNER TO meta_ops_user;
\q
EOF
```

### 2. Run Database Migrations
```bash
cd /home/meta-ops/meta-ops-agent

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Run migrations (using Alembic)
cd backend
alembic upgrade head
```

### 3. Verify Database Connection
```bash
# Test connection
python3 -c "
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
conn = engine.connect()
print('✓ Database connection successful!')
conn.close()
"
```

---

## Application Deployment

### 1. Install Python Dependencies
```bash
cd /home/meta-ops/meta-ops-agent
source venv/bin/activate
pip install -r requirements.txt

# Install production WSGI server
pip install gunicorn uvicorn[standard]
```

### 2. Initialize ChromaDB
```bash
# Create ChromaDB collections
python3 -c "
from src.database.vector.db_client import VectorDBClient
client = VectorDBClient()
print('✓ ChromaDB initialized successfully!')
"
```

### 3. Test Application Startup
```bash
# Test FastAPI backend
cd /home/meta-ops/meta-ops-agent/backend
uvicorn main:app --host 127.0.0.1 --port 8000

# Should see: "Application startup complete"
# Press Ctrl+C to stop
```

### 4. Build Frontend (if applicable)
```bash
cd /home/meta-ops/meta-ops-agent/frontend
npm install
npm run build

# Output will be in frontend/dist/
```

---

## Web Server Configuration

### 1. Configure Nginx as Reverse Proxy
```bash
sudo nano /etc/nginx/sites-available/meta-ops
```

Add configuration:
```nginx
# /etc/nginx/sites-available/meta-ops

upstream backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name meta-ops.yourdomain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name meta-ops.yourdomain.com;

    # SSL Configuration (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/meta-ops.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/meta-ops.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req zone=api_limit burst=20 nodelay;

    # API Endpoints
    location /api/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Frontend (if serving static files)
    location / {
        root /home/meta-ops/meta-ops-agent/frontend/dist;
        try_files $uri $uri/ /index.html;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    # Health Check Endpoint (no rate limit)
    location /api/health {
        proxy_pass http://backend;
        access_log off;
    }

    # API Documentation
    location /docs {
        proxy_pass http://backend;
    }

    # Logs
    access_log /var/log/nginx/meta-ops-access.log;
    error_log /var/log/nginx/meta-ops-error.log;
}
```

### 2. Enable Site and Obtain SSL Certificate
```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/meta-ops /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl reload nginx

# Obtain Let's Encrypt SSL certificate
sudo certbot --nginx -d meta-ops.yourdomain.com

# Test automatic renewal
sudo certbot renew --dry-run
```

---

## Process Management

### 1. Create Systemd Service
```bash
sudo nano /etc/systemd/system/meta-ops-backend.service
```

Add service configuration:
```ini
# /etc/systemd/system/meta-ops-backend.service

[Unit]
Description=Meta Ops Agent Backend API
After=network.target postgresql.service

[Service]
Type=notify
User=meta-ops
Group=meta-ops
WorkingDirectory=/home/meta-ops/meta-ops-agent/backend
Environment="PATH=/home/meta-ops/meta-ops-agent/venv/bin"
EnvironmentFile=/home/meta-ops/meta-ops-agent/.env

ExecStart=/home/meta-ops/meta-ops-agent/venv/bin/gunicorn \
    --bind 127.0.0.1:8000 \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 120 \
    --access-logfile /home/meta-ops/meta-ops-agent/logs/access.log \
    --error-logfile /home/meta-ops/meta-ops-agent/logs/error.log \
    --log-level info \
    main:app

# Restart policy
Restart=always
RestartSec=10s

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 2. Enable and Start Service
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable meta-ops-backend

# Start service
sudo systemctl start meta-ops-backend

# Check status
sudo systemctl status meta-ops-backend

# View logs
sudo journalctl -u meta-ops-backend -f
```

### 3. Service Management Commands
```bash
# Start
sudo systemctl start meta-ops-backend

# Stop
sudo systemctl stop meta-ops-backend

# Restart
sudo systemctl restart meta-ops-backend

# Reload (graceful)
sudo systemctl reload meta-ops-backend

# Status
sudo systemctl status meta-ops-backend

# Logs
sudo journalctl -u meta-ops-backend --since "1 hour ago"
```

---

## Monitoring Setup

### 1. Application Health Checks
```bash
# Test health endpoint
curl https://meta-ops.yourdomain.com/api/health

# Expected response:
# {"status": "healthy", "database": "connected", "chromadb": "ok"}
```

### 2. Setup Prometheus Metrics (Optional)
```bash
# Install Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-*.tar.gz
cd prometheus-*

# Configure Prometheus to scrape metrics
nano prometheus.yml
```

Add scrape config:
```yaml
scrape_configs:
  - job_name: 'meta-ops-backend'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### 3. Setup Log Rotation
```bash
sudo nano /etc/logrotate.d/meta-ops
```

Add configuration:
```
/home/meta-ops/meta-ops-agent/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 meta-ops meta-ops
    sharedscripts
    postrotate
        systemctl reload meta-ops-backend > /dev/null 2>&1 || true
    endscript
}
```

---

## Backup Strategy

### 1. Database Backups
```bash
# Create backup script
nano /home/meta-ops/backup-database.sh
```

```bash
#!/bin/bash
# Database backup script

BACKUP_DIR="/home/meta-ops/meta-ops-agent/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/meta_ops_db_$TIMESTAMP.sql.gz"

# Create backup
pg_dump -U meta_ops_user meta_ops_db | gzip > "$BACKUP_FILE"

# Keep only last 30 days
find "$BACKUP_DIR" -name "meta_ops_db_*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE"
```

```bash
chmod +x /home/meta-ops/backup-database.sh

# Setup daily cron job
crontab -e
# Add: 0 2 * * * /home/meta-ops/backup-database.sh
```

### 2. ChromaDB Backups
```bash
# Backup ChromaDB data
tar -czf /home/meta-ops/meta-ops-agent/backups/chroma_$(date +%Y%m%d).tar.gz \
    /home/meta-ops/meta-ops-agent/chroma_data/

# Keep last 7 days
find /home/meta-ops/meta-ops-agent/backups -name "chroma_*.tar.gz" -mtime +7 -delete
```

### 3. Application Code Backups
```bash
# Git-based: Tag releases
git tag -a v1.0.0 -m "Production release v1.0.0"
git push origin v1.0.0
```

---

## Post-Deployment Checklist

### Security Verification
- [ ] All secrets in .env, not in code
- [ ] .env file has 600 permissions (owner read/write only)
- [ ] HTTPS enabled with valid SSL certificate
- [ ] Rate limiting active (test by exceeding 100 req/min)
- [ ] RBAC enforced on decision approval/execution endpoints
- [ ] OPERATOR_ARMED=false until tested
- [ ] Firewall configured (UFW: allow 22, 80, 443 only)
- [ ] PostgreSQL not exposed to internet (127.0.0.1 only)
- [ ] Regular security updates scheduled

### Functionality Verification
- [ ] `/api/health` returns healthy status
- [ ] `/docs` shows API documentation
- [ ] Can create decision (POST /api/decisions)
- [ ] Can view saturation analysis (GET /api/saturation/analyze)
- [ ] Can view opportunities (GET /api/opportunities)
- [ ] BrandMapBuilder generates from brand text
- [ ] SaturationEngine analyzes CSV data
- [ ] All 6 API routers registered and responding

### Performance Verification
- [ ] API response time < 500ms (p95)
- [ ] Database queries optimized (no N+1)
- [ ] ChromaDB vector search < 200ms
- [ ] Gunicorn workers = 2-4x CPU cores
- [ ] Memory usage stable under load

### Monitoring Verification
- [ ] Health checks working
- [ ] Logs rotating properly
- [ ] Metrics endpoint accessible (/metrics)
- [ ] Systemd service auto-restarts on failure
- [ ] Database backups running daily
- [ ] ChromaDB backups scheduled

### Rollback Preparedness
- [ ] Previous version tagged in git
- [ ] Database backup recent (< 24 hours)
- [ ] ChromaDB backup recent (< 24 hours)
- [ ] ROLLBACK.md documented and tested
- [ ] Emergency contact list updated

---

## Quick Start Commands

### Deploy Latest Code
```bash
cd /home/meta-ops/meta-ops-agent
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart meta-ops-backend
```

### Check Application Status
```bash
# Service status
sudo systemctl status meta-ops-backend

# Recent logs
sudo journalctl -u meta-ops-backend --since "10 minutes ago"

# Health check
curl https://meta-ops.yourdomain.com/api/health
```

### Emergency Stop
```bash
sudo systemctl stop meta-ops-backend
```

---

## Common Issues & Solutions

### Issue: Service won't start
```bash
# Check logs
sudo journalctl -u meta-ops-backend -n 50

# Common causes:
# - Missing .env file → Create from .env.template
# - Database not running → sudo systemctl start postgresql
# - Port 8000 in use → sudo lsof -i :8000
```

### Issue: Database connection failed
```bash
# Test PostgreSQL
sudo systemctl status postgresql

# Test connection string
psql postgresql://meta_ops_user:password@localhost/meta_ops_db
```

### Issue: High memory usage
```bash
# Reduce Gunicorn workers
# Edit /etc/systemd/system/meta-ops-backend.service
# Change --workers 4 to --workers 2
sudo systemctl daemon-reload
sudo systemctl restart meta-ops-backend
```

---

## Production Deployment Timeline

**Day 1: Server Preparation**
- Provision server
- Install dependencies
- Configure firewall
- Setup domain + SSL

**Day 2: Application Deployment**
- Clone repository
- Configure .env
- Setup database
- Deploy backend
- Configure Nginx

**Day 3: Testing & Monitoring**
- Run E2E tests
- Load testing
- Setup monitoring
- Configure backups

**Day 4: Go Live**
- Final security audit
- Enable OPERATOR_ARMED (after validation)
- Monitor for 24 hours
- Adjust resources as needed

---

## Support & Maintenance

### Regular Maintenance Tasks
- **Daily**: Check logs for errors
- **Weekly**: Review metrics and performance
- **Monthly**: Security updates, backup verification
- **Quarterly**: Dependency updates, security audit

### Emergency Contacts
- **DevOps**: [your-email@company.com]
- **Database**: [dba@company.com]
- **Security**: [security@company.com]

---

**Deployment Status**: Ready for Production ✅

**Last Updated**: 2026-02-16
**Version**: 1.0.0
