#!/bin/bash
# Daily backup of Hermes custom files to GitHub
# Runs at 12:00 UTC (7 AM Colombia) via cron

HERMES_HOME="/home/ubuntu/.hermes"
BACKUP_DIR="$HERMES_HOME/backup"
DATE=$(date -u +"%Y-%m-%d %H:%M UTC")

# Ensure backup dir exists and is a git repo
if [ ! -d "$BACKUP_DIR/.git" ]; then
    echo "ERROR: Backup dir is not a git repo"
    exit 1
fi

cd "$BACKUP_DIR"

# Pull latest (in case of manual edits)
git pull --rebase origin main 2>/dev/null || git pull --rebase origin master 2>/dev/null || true

# Clear old content (except .git)
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' ! -name '.gitignore' -exec rm -rf {} \;

# Copy custom files (NOT the hermes-agent source code)
echo "Copying custom files..."

# Config and personality
cp -f "$HERMES_HOME/config.yaml" "$BACKUP_DIR/" 2>/dev/null || true
    sed -i "s/api_key: .*/api_key: REDACTED/g" "$BACKUP_DIR/config.yaml" 2>/dev/null || true
cp -f "$HERMES_HOME/SOUL.md" "$BACKUP_DIR/" 2>/dev/null || true

# Memories
mkdir -p "$BACKUP_DIR/memories"
cp -f "$HERMES_HOME/memories/"*.md "$BACKUP_DIR/memories/" 2>/dev/null || true

# Skills (custom, not the hermes-agent built-in ones)
mkdir -p "$BACKUP_DIR/skills"
cp -rf "$HERMES_HOME/skills/sif-agent-prospecting" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/crm-data-enrichment" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/crm-internal-field-enrichment" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/aws-support" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/competencia-fumigacion" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/configuration" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/crm-query" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/fsm-saas-platform" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/hermes" "$BACKUP_DIR/skills/" 2>/dev/null || true
cp -rf "$HERMES_HOME/skills/rues-data-enrichment" "$BACKUP_DIR/skills/" 2>/dev/null || true

# Cron jobs config
mkdir -p "$BACKUP_DIR/cron"
cp -f "$HERMES_HOME/cron/jobs.json" "$BACKUP_DIR/cron/" 2>/dev/null || true

# Leads state (not the full CSV, just state)
mkdir -p "$BACKUP_DIR/leads"
cp -f "$HERMES_HOME/leads/pipeline_state.json" "$BACKUP_DIR/leads/" 2>/dev/null || true

# Custom scripts
mkdir -p "$BACKUP_DIR/scripts"
cp -f "$HERMES_HOME/scripts/"*.py "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp -f "$HERMES_HOME/scripts/"*.sh "$BACKUP_DIR/scripts/" 2>/dev/null || true

# .env (without secrets - create sanitized version)
if [ -f "$HERMES_HOME/.env" ]; then
    grep -v "TOKEN\|KEY\|SECRET\|PASSWORD" "$HERMES_HOME/.env" > "$BACKUP_DIR/.env.example" 2>/dev/null || true
fi

# Plugins
if [ -d "$HERMES_HOME/plugins" ]; then
    mkdir -p "$BACKUP_DIR/plugins"
    cp -rf "$HERMES_HOME/plugins/"* "$BACKUP_DIR/plugins/" 2>/dev/null || true
fi

# Auth & gateway state
mkdir -p "$BACKUP_DIR/state"
if [ -f "$HERMES_HOME/auth.json" ]; then
    python3 -c "
import json
with open('$HERMES_HOME/auth.json') as f:
    d = json.load(f)
for provider, cfg in d.get('providers', {}).items():
    for key in list(cfg.keys()):
        if any(s in key.lower() for s in ['token', 'key', 'secret', 'password', 'credential']):
            cfg[key] = 'REDACTED'
for provider, creds in d.get('credential_pool', {}).items():
    for cred in creds:
        for key in list(cred.keys()):
            if any(s in key.lower() for s in ['token', 'key', 'secret', 'password', 'credential', 'access']):
                cred[key] = 'REDACTED'
with open('$BACKUP_DIR/state/auth.json', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null || true
fi
cp -f "$HERMES_HOME/gateway_state.json" "$BACKUP_DIR/state/" 2>/dev/null || true
cp -f "$HERMES_HOME/channel_directory.json" "$BACKUP_DIR/state/" 2>/dev/null || true

# Create .gitignore if not exists
cat > "$BACKUP_DIR/.gitignore" << 'GITIGNORE'
*.pyc
__pycache__/
.env
*.log
*.csv
GITIGNORE

# Commit and push
cd "$BACKUP_DIR"
git add -A
if git diff --cached --quiet; then
    echo "No changes to backup"
else
    git commit -m "backup: $DATE"
    git push origin main 2>/dev/null || git push origin master 2>/dev/null
    echo "Backup pushed successfully: $DATE"
fi
