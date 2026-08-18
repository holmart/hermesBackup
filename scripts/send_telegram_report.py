# Script para enviar reportes automáticos a Telegram
import requests
import json
import time

# Configurar Telegram Bot Info
TELEGRAM_BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
TELEGRAM_CHAT_ID = 'YOUR_TELEGRAM_CHAT_ID'

# Función para enviar mensaje a Telegram

def send_telegram_message(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    response = requests.post(url, data=payload)
    return response.json()

# Leer el log de ejecución
log_file_path = '/home/ubuntu/.hermes/leads/cron_output.log'

# Generar el mensaje a enviar
with open(log_file_path, 'r') as log_file:
    lines = log_file.readlines()
    report_data = []
    for line in lines:
        if 'Found' in line or 'Inserted' in line or 'Error' in line:
            report_data.append(line.strip())

# Crear el mensaje final
message = '*Reporte de Ejecución del Pipeline:*\n' + '\n'.join(report_data)

# Enviar el mensaje a Telegram
if report_data:
    send_telegram_message(message)
    print('Telegram report sent successfully')
else:
    print('No relevant data to report.')