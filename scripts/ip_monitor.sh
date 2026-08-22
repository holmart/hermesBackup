#!/bin/bash
# Monitor IP change and notify via Telegram
# Stores last known IP in ~/.hermes/state/last_known_ip.txt

HERMES_HOME="/home/ubuntu/.hermes"
STATE_FILE="$HERMES_HOME/state/last_known_ip.txt"
source "$HERMES_HOME/.env"

mkdir -p "$HERMES_HOME/state"

# Get current public IP
CURRENT_IP=$(curl -s --max-time 10 https://checkip.amazonaws.com)

if [ -z "$CURRENT_IP" ]; then
    echo "ERROR: Could not determine current IP"
    exit 1
fi

# Get last known IP
if [ -f "$STATE_FILE" ]; then
    LAST_IP=$(cat "$STATE_FILE")
else
    LAST_IP=""
fi

# Compare
if [ "$CURRENT_IP" != "$LAST_IP" ]; then
    echo "$CURRENT_IP" > "$STATE_FILE"
    
    if [ -z "$LAST_IP" ]; then
        MSG="🌐 *IP Monitor Initialized*%0AIP actual: \`$CURRENT_IP\`"
    else
        MSG="⚠️ *IP Publica Cambio!*%0A%0AAnterior: \`$LAST_IP\`%0ANueva: \`$CURRENT_IP\`%0A%0A*Accion requerida:* Actualizar IP en Google Cloud Console (API key restrictions) o quitar restriccion de IP."
    fi
    
    # Send Telegram notification
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"         -d "chat_id=${TELEGRAM_ALLOWED_USERS}"         -d "text=${MSG}"         -d "parse_mode=Markdown" > /dev/null 2>&1
    
    echo "IP changed: $LAST_IP -> $CURRENT_IP (notification sent)"
else
    echo "IP unchanged: $CURRENT_IP"
fi
