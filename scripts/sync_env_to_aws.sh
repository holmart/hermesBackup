#!/bin/bash
# Sync .env to AWS Secrets Manager
# Called from daily_backup.sh or manually

HERMES_HOME="/home/ubuntu/.hermes"
SECRET_NAME="hermes-agent/env"
REGION="us-east-1"

if [ ! -f "$HERMES_HOME/.env" ]; then
    echo "ERROR: .env not found"
    exit 1
fi

ENV_CONTENT=$(cat "$HERMES_HOME/.env")

aws secretsmanager put-secret-value \
    --secret-id "$SECRET_NAME" \
    --secret-string "$ENV_CONTENT" \
    --region "$REGION" 2>&1

if [ $? -eq 0 ]; then
    echo "Secrets synced to AWS Secrets Manager: $SECRET_NAME"
else
    echo "ERROR: Failed to sync secrets"
    exit 1
fi
