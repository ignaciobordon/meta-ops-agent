# Meta Ops Agent - Rollback & Disaster Recovery Plan

## Table of Contents
1. [Quick Rollback Commands](#quick-rollback-commands)
2. [Rollback Scenarios](#rollback-scenarios)
3. [Database Recovery](#database-recovery)
4. [Application Rollback](#application-rollback)
5. [Infrastructure Recovery](#infrastructure-recovery)
6. [Data Recovery](#data-recovery)
7. [Incident Response Playbook](#incident-response-playbook)
8. [Post-Incident Review](#post-incident-review)

---

## Quick Rollback Commands

### Emergency: Roll back to previous release (< 2 minutes)

```bash
# 1. Identify the previous working version
git log --oneline --tags -5

# 2. Switch to previous release tag
cd /opt/meta-ops-agent
git checkout <previous-tag>

# 3. Reinstall dependencies (if changed)
source venv/bin/activate
pip install -r requirements.txt

# 4. Run database downgrade if migrations changed
alembic downgrade -1

# 5. Restart the application
sudo systemctl restart meta-ops-agent

# 6. Verify health
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

### Emergency: Restart without code changes (< 30 seconds)

```bash
sudo systemctl restart meta-ops-agent
sleep 3
curl -f http://localhost:8000/api/health/live && echo "OK" || echo "FAILED"
```

---

## Rollback Scenarios

### Scenario 1: Bad Deployment (Application Error)

**Symptoms**: 500 errors, health check failing, error spike in logs

**Steps**:
```bash
# 1. Check current status
sudo systemctl status meta-ops-agent
curl -s http://localhost:8000/api/health

# 2. Check recent logs for error details
sudo journalctl -u meta-ops-agent --since "10 minutes ago" --no-pager | tail -50

# 3. Roll back to last known good version
cd /opt/meta-ops-agent
git stash  # Save any local changes
git checkout $(git describe --tags --abbrev=0 HEAD~1)  # Previous tag

# 4. Restore dependencies
source venv/bin/activate
pip install -r requirements.txt

# 5. Downgrade database if needed
alembic downgrade -1

# 6. Restart
sudo systemctl restart meta-ops-agent

# 7. Verify
sleep 3
curl -s http://localhost:8000/api/health
```

**Recovery Time**: 2-5 minutes

### Scenario 2: Database Migration Failure

**Symptoms**: Application won't start, SQLAlchemy errors, migration errors

**Steps**:
```bash
# 1. Check current migration state
cd /opt/meta-ops-agent
source venv/bin/activate
alembic current

# 2. Check migration history
alembic history --verbose

# 3. Downgrade to previous migration
alembic downgrade -1

# 4. If downgrade fails, restore from backup
sudo -u postgres pg_restore \
  --clean --if-exists \
  -d meta_ops_agent \
  /var/backups/meta-ops/db/meta_ops_agent_$(date +%Y%m%d).dump

# 5. Restart application
sudo systemctl restart meta-ops-agent
```

**Recovery Time**: 5-15 minutes

### Scenario 3: Database Corruption

**Symptoms**: Data inconsistencies, integrity errors, missing records

**Steps**:
```bash
# 1. Stop the application immediately
sudo systemctl stop meta-ops-agent

# 2. Assess the damage
sudo -u postgres psql meta_ops_agent -c "
  SELECT schemaname, tablename, n_live_tup, n_dead_tup
  FROM pg_stat_user_tables
  ORDER BY n_dead_tup DESC;
"

# 3. Find the most recent backup
ls -lt /var/backups/meta-ops/db/ | head -5

# 4. Restore from latest backup
sudo -u postgres dropdb meta_ops_agent
sudo -u postgres createdb -O meta_ops_user meta_ops_agent
sudo -u postgres pg_restore \
  -d meta_ops_agent \
  /var/backups/meta-ops/db/meta_ops_agent_YYYYMMDD.dump

# 5. Verify data integrity
sudo -u postgres psql meta_ops_agent -c "
  SELECT 'organizations' as tbl, count(*) FROM organizations
  UNION ALL
  SELECT 'users', count(*) FROM users
  UNION ALL
  SELECT 'decision_packs', count(*) FROM decision_packs
  UNION ALL
  SELECT 'ad_accounts', count(*) FROM ad_accounts;
"

# 6. Restart application
sudo systemctl start meta-ops-agent

# 7. Verify health
curl -s http://localhost:8000/api/health
```

**Recovery Time**: 15-30 minutes

### Scenario 4: ChromaDB Vector Store Corruption

**Symptoms**: Creative scoring fails, tagger returns errors, embedding lookups fail

**Steps**:
```bash
# 1. Stop application
sudo systemctl stop meta-ops-agent

# 2. Check ChromaDB status
ls -la /opt/meta-ops-agent/data/chromadb/

# 3. Restore from backup
rm -rf /opt/meta-ops-agent/data/chromadb/
cp -r /var/backups/meta-ops/chromadb/chromadb_YYYYMMDD/ \
  /opt/meta-ops-agent/data/chromadb/

# 4. If no backup available, reinitialize
cd /opt/meta-ops-agent
source venv/bin/activate
python -c "
from src.core.vector_store import VectorStore
vs = VectorStore()
vs.initialize()
print('ChromaDB reinitialized successfully')
"

# 5. Restart
sudo systemctl start meta-ops-agent
```

**Recovery Time**: 5-20 minutes

### Scenario 5: API Rate Limiting / DDoS

**Symptoms**: Legitimate users blocked, 429 errors everywhere, high CPU

**Steps**:
```bash
# 1. Check current rate limit status
sudo journalctl -u meta-ops-agent --since "5 minutes ago" | grep "RATE_LIMIT"

# 2. Block offending IPs at nginx level
sudo nano /etc/nginx/conf.d/blocklist.conf
# Add: deny <offending-ip>;
sudo nginx -t && sudo systemctl reload nginx

# 3. Temporarily increase rate limits if needed
# Edit .env file
# RATE_LIMIT_PER_MINUTE=200

# 4. Restart to apply
sudo systemctl restart meta-ops-agent
```

**Recovery Time**: 2-5 minutes

### Scenario 6: Meta API Credentials Expired

**Symptoms**: 401 errors from Meta API, ad data not refreshing, campaign operations fail

**Steps**:
```bash
# 1. Verify the issue
curl -s "https://graph.facebook.com/v21.0/me?access_token=$(grep META_ACCESS_TOKEN /opt/meta-ops-agent/.env | cut -d= -f2)"

# 2. Generate new long-lived token
# Go to: https://developers.facebook.com/tools/explorer/
# Generate new token with required permissions:
# - ads_management, ads_read, business_management

# 3. Update the token
sudo nano /opt/meta-ops-agent/.env
# Update META_ACCESS_TOKEN=new_token_here

# 4. Restart
sudo systemctl restart meta-ops-agent

# 5. Verify Meta API connectivity
curl -s http://localhost:8000/api/health | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('Meta API:', data.get('dependencies', {}).get('meta_api', {}).get('status', 'unknown'))
"
```

**Recovery Time**: 5-10 minutes

### Scenario 7: Anthropic API Outage

**Symptoms**: Decision engine timeouts, creative generation fails, 503 from Claude

**Steps**:
```bash
# 1. Check Anthropic API status
# Visit: https://status.anthropic.com

# 2. Check error logs
sudo journalctl -u meta-ops-agent --since "10 minutes ago" | grep -i "anthropic\|claude\|ENGINE_ERROR"

# 3. The system should gracefully degrade:
# - Decisions queue and retry automatically
# - Health check will show "degraded" status
# - Existing cached responses continue to work

# 4. If extended outage, enable fallback mode
# Edit .env:
# AI_FALLBACK_MODE=true  (uses rule-based decisions instead of AI)

# 5. Restart
sudo systemctl restart meta-ops-agent
```

**Recovery Time**: Depends on Anthropic (system degrades gracefully)

---

## Database Recovery

### Automated Backup Verification

```bash
#!/bin/bash
# /opt/meta-ops-agent/scripts/verify_backup.sh
# Run daily after backup completes

BACKUP_DIR="/var/backups/meta-ops/db"
LATEST_BACKUP=$(ls -t $BACKUP_DIR/*.dump 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "CRITICAL: No backup files found!"
    exit 1
fi

# Check backup age (should be < 25 hours old)
BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_BACKUP")) / 3600 ))
if [ $BACKUP_AGE -gt 25 ]; then
    echo "WARNING: Latest backup is ${BACKUP_AGE}h old"
    exit 1
fi

# Check backup size (should be > 1KB, indicating non-empty)
BACKUP_SIZE=$(stat -c %s "$LATEST_BACKUP")
if [ $BACKUP_SIZE -lt 1024 ]; then
    echo "WARNING: Backup file suspiciously small: ${BACKUP_SIZE} bytes"
    exit 1
fi

# Test restore to temporary database
sudo -u postgres createdb meta_ops_verify_temp 2>/dev/null
sudo -u postgres pg_restore -d meta_ops_verify_temp "$LATEST_BACKUP" 2>/dev/null
RESTORE_EXIT=$?
sudo -u postgres dropdb meta_ops_verify_temp 2>/dev/null

if [ $RESTORE_EXIT -ne 0 ]; then
    echo "CRITICAL: Backup restore verification FAILED"
    exit 1
fi

echo "OK: Backup verified (${BACKUP_AGE}h old, ${BACKUP_SIZE} bytes)"
```

### Point-in-Time Recovery (PITR)

If WAL archiving is enabled:

```bash
# 1. Stop PostgreSQL
sudo systemctl stop postgresql

# 2. Move current data directory
sudo mv /var/lib/postgresql/16/main /var/lib/postgresql/16/main.broken

# 3. Restore base backup
sudo -u postgres pg_basebackup -D /var/lib/postgresql/16/main

# 4. Create recovery configuration
cat << 'EOF' | sudo tee /var/lib/postgresql/16/main/recovery.conf
restore_command = 'cp /var/backups/meta-ops/wal/%f %p'
recovery_target_time = '2026-02-16 10:00:00'
recovery_target_action = 'promote'
EOF

# 5. Start PostgreSQL (will replay WAL to target time)
sudo systemctl start postgresql

# 6. Verify
sudo -u postgres psql meta_ops_agent -c "SELECT count(*) FROM decision_packs;"
```

---

## Application Rollback

### Git Tag-Based Rollback

Every deployment should be tagged:

```bash
# During deployment (automated in CI/CD):
git tag -a "release-$(date +%Y%m%d-%H%M)" -m "Production release"
git push origin --tags

# To rollback:
# List recent tags
git tag -l "release-*" --sort=-creatordate | head -5

# Checkout previous release
git checkout release-YYYYMMDD-HHMM

# Reinstall dependencies (in case they changed)
source venv/bin/activate
pip install -r requirements.txt

# Run migrations if needed
alembic current  # Check current state
alembic downgrade -1  # If migration was part of release

# Restart
sudo systemctl restart meta-ops-agent
```

### Blue-Green Deployment Rollback

If using blue-green deployment:

```bash
# Nginx points to current (blue) on port 8000
# New version runs on green port 8001

# To rollback (switch nginx back to blue):
sudo sed -i 's/proxy_pass http:\/\/127.0.0.1:8001/proxy_pass http:\/\/127.0.0.1:8000/' \
  /etc/nginx/sites-available/meta-ops-agent

sudo nginx -t && sudo systemctl reload nginx

# Stop the failed green deployment
sudo systemctl stop meta-ops-agent-green
```

---

## Infrastructure Recovery

### Server Recovery Checklist

If the entire server needs to be rebuilt:

```
1. [ ] Provision new Ubuntu 22.04 LTS server
2. [ ] Install system packages (Python 3.11, PostgreSQL 16, Nginx)
3. [ ] Restore PostgreSQL from latest backup
4. [ ] Clone repository and checkout latest release tag
5. [ ] Create virtual environment and install dependencies
6. [ ] Restore .env from secure backup (1Password / Vault)
7. [ ] Restore ChromaDB data from backup
8. [ ] Configure Nginx with SSL certificates
9. [ ] Configure systemd service
10. [ ] Start application and verify health
11. [ ] Update DNS if IP changed
12. [ ] Run smoke tests
13. [ ] Monitor for 30 minutes
```

### SSL Certificate Recovery

```bash
# If Let's Encrypt cert expired:
sudo certbot renew --force-renewal
sudo systemctl reload nginx

# If cert files are missing:
sudo certbot certonly --nginx -d meta-ops.yourdomain.com
sudo systemctl reload nginx
```

---

## Data Recovery

### Decision Data Recovery

If decision records are lost but the database is intact:

```bash
# Re-sync from Meta API
curl -X POST http://localhost:8000/api/decisions/sync \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force_resync": true}'
```

### Audit Log Recovery

Audit logs are append-only and stored in the database:

```bash
# Check audit log integrity
sudo -u postgres psql meta_ops_agent -c "
  SELECT date_trunc('hour', created_at) as hour,
         count(*) as entries,
         count(DISTINCT user_id) as users
  FROM audit_logs
  WHERE created_at > now() - interval '24 hours'
  GROUP BY 1
  ORDER BY 1;
"
```

---

## Incident Response Playbook

### Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| **SEV1** | System down, all users affected | < 15 min | App won't start, DB down |
| **SEV2** | Major feature broken | < 30 min | Decision engine failing, Meta API down |
| **SEV3** | Minor feature degraded | < 2 hours | Slow responses, partial data |
| **SEV4** | Cosmetic / non-urgent | Next business day | UI glitch, log formatting |

### SEV1 Response Protocol

```
1. ACKNOWLEDGE
   - Confirm the incident within 5 minutes
   - Assign incident commander

2. ASSESS
   - Check health endpoint: curl http://localhost:8000/api/health
   - Check logs: journalctl -u meta-ops-agent --since "15 min ago"
   - Check database: pg_isready -h localhost
   - Check disk space: df -h

3. MITIGATE
   - If bad deploy: rollback (see Scenario 1)
   - If DB issue: restore (see Scenario 3)
   - If resource exhaustion: restart + scale

4. COMMUNICATE
   - Update status page
   - Notify affected users if applicable

5. RESOLVE
   - Confirm health check is green
   - Monitor for 30 minutes
   - Document the incident
```

### Monitoring Checks

```bash
#!/bin/bash
# /opt/meta-ops-agent/scripts/health_monitor.sh
# Run every minute via cron

HEALTH_URL="http://localhost:8000/api/health"
TIMEOUT=10

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "$HEALTH_URL")

if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "207" ]; then
    echo "$(date): ALERT - Health check returned $HTTP_CODE" >> /var/log/meta-ops-alerts.log

    # Auto-restart on failure (with cooldown)
    LAST_RESTART=$(stat -c %Y /tmp/meta-ops-last-restart 2>/dev/null || echo 0)
    NOW=$(date +%s)
    COOLDOWN=300  # 5 minutes

    if [ $((NOW - LAST_RESTART)) -gt $COOLDOWN ]; then
        sudo systemctl restart meta-ops-agent
        touch /tmp/meta-ops-last-restart
        echo "$(date): Auto-restarted meta-ops-agent" >> /var/log/meta-ops-alerts.log
    fi
fi
```

Crontab entry:
```
* * * * * /opt/meta-ops-agent/scripts/health_monitor.sh
```

---

## Post-Incident Review

### Template

After every SEV1 or SEV2 incident, create a post-mortem:

```markdown
# Incident Report: [Title]

**Date**: YYYY-MM-DD
**Duration**: X hours Y minutes
**Severity**: SEV1/SEV2
**Commander**: [Name]

## Timeline
- HH:MM - Issue detected by [monitoring/user report]
- HH:MM - Investigation started
- HH:MM - Root cause identified
- HH:MM - Fix deployed / rollback executed
- HH:MM - Service restored
- HH:MM - All-clear confirmed

## Root Cause
[Detailed explanation of what caused the incident]

## Impact
- Users affected: X
- Revenue impact: $X
- Data loss: Yes/No

## What Went Well
- [List positives]

## What Went Wrong
- [List issues]

## Action Items
- [ ] [Preventive measure 1] - Owner: [Name] - Due: [Date]
- [ ] [Preventive measure 2] - Owner: [Name] - Due: [Date]
```

---

## Backup Schedule Summary

| What | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| PostgreSQL full dump | Daily 2 AM | 30 days | `/var/backups/meta-ops/db/` |
| ChromaDB snapshot | Daily 3 AM | 14 days | `/var/backups/meta-ops/chromadb/` |
| Application code | Every deploy (git tag) | Forever | Git repository |
| .env secrets | On change | Current | 1Password / Vault |
| Nginx config | On change | 5 versions | `/var/backups/meta-ops/nginx/` |
| SSL certificates | Auto-renewed | N/A | Let's Encrypt |

---

## Emergency Contacts

| Role | Contact | When to Engage |
|------|---------|----------------|
| On-call engineer | [Configure in PagerDuty] | SEV1/SEV2 auto-paged |
| Database admin | [Contact] | Database corruption, PITR needed |
| Infrastructure | [Contact] | Server down, DNS issues |
| Meta API support | developers.facebook.com/support | Platform-level API issues |
| Anthropic support | support.anthropic.com | Claude API outage |
