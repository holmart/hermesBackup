#!/bin/bash
# Restore .env from AWS Secrets Manager
# Usage: ./restore_env.sh [--dry-run]

HERMES_HOME="/home/ubuntu/.hermes"
SECRET_NAME="hermes-agent/env"
REGION="us-east-1"
DRY_RUN=false

if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
fi

echo "Fetching secrets from AWS Secrets Manager..."
SECRET_VALUE=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --region "$REGION" \
    --query 'SecretString' \
    --output text 2>&1)

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to fetch secret: $SECRET_VALUE"
    exit 1
fi

if [ "$DRY_RUN" = true ]; then
    echo "--- DRY RUN - Would write these keys: ---"
    echo "$SECRET_VALUE" | grep -oP '^[A-Z_]+(?==)'
    echo "--- End DRY RUN ---"
    exit 0
fi

# Backup current .env if exists
if [ -f "$HERMES_HOME/.env" ]; then
    cp "$HERMES_HOME/.env" "$HERMES_HOME/.env.bak.$(date +%Y%m%d_%H%M%S)"
    echo "Current .env backed up"
fi

# Write new .env
echo "$SECRET_VALUE" > "$HERMES_HOME/.env"
chmod 600 "$HERMES_HOME/.env"
echo "Restored .env from Secrets Manager ($(echo "$SECRET_VALUE" | wc -l) lines)"
echo "Restart hermes-gateway to apply: sudo systemctl restart hermes-gateway"
