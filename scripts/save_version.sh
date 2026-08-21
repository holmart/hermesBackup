#!/bin/bash
cd /home/ubuntu/.hermes/hermes-agent
VERSION=$(git describe --tags --always 2>/dev/null)
BRANCH=$(git branch --show-current 2>/dev/null)
COMMIT=$(git rev-parse HEAD 2>/dev/null)
DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > /home/ubuntu/.hermes/backup/hermes_version.txt << EOF
version: $VERSION
branch: $BRANCH
commit: $COMMIT
snapshot_date: $DATE
repo: https://github.com/NousResearch/hermes-agent.git
install_method: git clone + uv pip install -e .
python: 3.11
EOF

echo "Version file updated"
cat /home/ubuntu/.hermes/backup/hermes_version.txt
