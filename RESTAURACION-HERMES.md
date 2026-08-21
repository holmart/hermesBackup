# Restauracion Completa de Hermes Agent

Guia paso a paso para restaurar Hermes Agent desde cero en caso de perdida total de la instancia EC2.

---

## Prerequisitos

- Acceso a la cuenta AWS `768296856192` (us-east-1)
- Acceso al repo GitHub `holmart/hermesBackup` (backup diario de archivos)
- Los secrets estan en AWS Secrets Manager: `hermes-agent/env`

---

## Fuentes de Restauracion

| Fuente | Que contiene | Como acceder |
|--------|-------------|--------------|
| **GitHub `NousResearch/hermes-agent`** | Codigo fuente del agente (el motor) | `git clone` |
| **GitHub `holmart/hermesBackup`** | Skills, scripts, config, memories, cron jobs, SOUL.md, estado, plugins | `git clone` |
| **AWS Secrets Manager** | `.env` con todas las API keys y tokens | `aws secretsmanager get-secret-value` |
| **AWS DynamoDB** | CRM de leads (`sifagent-crm-clients`) — **no se pierde con la EC2** | Tabla persistente en AWS |
| **Este documento** | Systemd service, crontab, estructura, pasos de recuperacion | Lo estas leyendo |

---

## Hermes Agent Source Code

El codigo fuente de Hermes Agent es open source y se instala desde GitHub:

| Campo | Valor |
|-------|-------|
| **Repositorio** | `https://github.com/NousResearch/hermes-agent.git` |
| **Branch** | `main` |
| **Version estable actual** | `v0.20.1` (2026.8.13) |
| **Commit estable** | `9cb456a9b` |
| **Metodo de instalacion** | `git clone` + `uv venv` + `uv pip install -e .` |
| **Python requerido** | `>=3.11, <3.14` |
| **Licencia** | MIT |
| **Autor** | Nous Research |

### Para instalar una version especifica:

```bash
cd ~/.hermes
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
git checkout 9cb456a9b   # v0.20.1
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
```

### Para actualizar a la ultima version:

```bash
cd ~/.hermes/hermes-agent
git pull origin main
source .venv/bin/activate
uv pip install -e .
sudo systemctl restart hermes-gateway
```

> **IMPORTANTE:** El source no tiene modificaciones locales. Se usa tal cual del repo upstream.

### Version tracking automatico

El backup diario guarda un archivo `hermes_version.txt` con el commit exacto que esta corriendo.
Para restaurar a ese commit:

```bash
cd ~/.hermes/hermes-agent
git checkout $(grep "^commit:" ~/.hermes/backup/hermes_version.txt | cut -d' ' -f2)
```
---

## Paso 1: Provisionar la Instancia EC2

| Campo | Valor |
|-------|-------|
| **AMI** | Ubuntu 22.04 LTS (x86_64) |
| **Tipo** | t3.small (2 vCPU, 2 GB RAM) |
| **Region** | us-east-1 |
| **Tag Name** | `Hermes-Agent-Server` |
| **IAM Role** | `OpenClaw-Server-Role` |
| **Security Group** | Permitir salida a internet (HTTPS). No necesita puertos de entrada. |
| **Storage** | 30 GB gp3 (minimo) |

### Politicas IAM del rol

- `AmazonSSMManagedInstanceCore` (acceso SSM)
- Inline `HermesSecretsManagerAccess`: GetSecretValue, PutSecretValue, DescribeSecret en `hermes-agent/*`
- `AmazonDynamoDBFullAccess` o scoped a `sifagent-crm-clients`

---

## Paso 2: Instalar Dependencias del Sistema

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget unzip jq
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install && rm -rf aws awscliv2.zip
```

---

## Paso 3: Crear Estructura de Directorios

```bash
mkdir -p ~/.hermes/{bin,scripts,memories,skills,cron,leads,logs,sessions,hooks,plugins,gateway,state}
```

---

## Paso 4: Instalar Hermes Agent

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
mkdir -p ~/.hermes/bin
cp ~/.local/bin/uv ~/.hermes/bin/
cp ~/.local/bin/uvx ~/.hermes/bin/
cd ~/.hermes
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
git checkout 9cb456a9b
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
hermes --version
```

---

## Paso 5: Restaurar Archivos desde GitHub Backup

```bash
cd ~/.hermes
git clone https://github.com/holmart/hermesBackup.git backup
cp backup/config.yaml .
cp backup/SOUL.md .
cp backup/memories/*.md memories/
cp -r backup/skills/* skills/
cp -r backup/scripts/* scripts/
chmod +x scripts/*.sh
cp backup/cron/jobs.json cron/
cp backup/leads/pipeline_state.json leads/ 2>/dev/null || true
cp -r backup/plugins/* plugins/ 2>/dev/null || true
cp backup/state/gateway_state.json . 2>/dev/null || true
cp backup/state/channel_directory.json . 2>/dev/null || true
# auth.json se regenera al autenticar; el backup tiene version sanitizada solo de referencia
```

---

## Paso 6: Restaurar Secrets desde AWS Secrets Manager

```bash
# Opcion A: Script automatico
~/.hermes/scripts/restore_env.sh

# Opcion B: Manual
aws secretsmanager get-secret-value --secret-id "hermes-agent/env" --region us-east-1 --query SecretString --output text > ~/.hermes/.env
chmod 600 ~/.hermes/.env
```

### Variables en el secret (19 keys)

| Categoria | Variables |
|-----------|-----------|
| **LLM** | `OPENROUTER_API_KEY`, `KIMI_API_KEY`, `KIMI_BASE_URL` |
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_HOME_CHANNEL_THREAD_ID` |
| **APIs** | `GOOGLE_PLACES_API_KEY` |
| **Browser** | `BROWSERBASE_PROXIES`, `BROWSERBASE_ADVANCED_STEALTH`, `BROWSER_SESSION_TIMEOUT`, `BROWSER_INACTIVITY_TIMEOUT` |
| **Config** | `TERMINAL_MODAL_IMAGE`, `TERMINAL_TIMEOUT`, `TERMINAL_LIFETIME_SECONDS` |
| **Debug** | `WEB_TOOLS_DEBUG`, `VISION_TOOLS_DEBUG`, `MOA_TOOLS_DEBUG`, `IMAGE_TOOLS_DEBUG` |

---

## Paso 7: Configurar Servicio Systemd

```bash
sudo tee /etc/systemd/system/hermes-gateway.service << 'EOF'
[Unit]
Description=Hermes Agent Gateway (Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/.hermes/hermes-agent
Environment=HOME=/home/ubuntu
Environment=PATH=/home/ubuntu/.hermes/hermes-agent/.venv/bin:/home/ubuntu/.hermes/bin:/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/ubuntu/.hermes/hermes-agent/.venv/bin/python3 hermes gateway run --replace
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable hermes-gateway
sudo systemctl start hermes-gateway
```

---

## Paso 8: Configurar Crontab

```bash
crontab -e
```

```cron
0 13 * * * /home/ubuntu/.hermes/skills/sif-agent-prospecting/scripts/run_pipeline.sh --vertical fumigacion
30 13 * * * /home/ubuntu/.hermes/skills/sif-agent-prospecting/scripts/run_pipeline.sh --vertical hvac
0 14 * * * /home/ubuntu/.hermes/skills/sif-agent-prospecting/scripts/run_pipeline.sh --vertical electrico
0 12 * * * /home/ubuntu/.hermes/scripts/daily_backup.sh >> /home/ubuntu/.hermes/leads/backup.log 2>&1
```

---

## Paso 9: Verificar

```bash
sudo systemctl status hermes-gateway
hermes status
hermes skills list
hermes cron list
hermes send "Restauracion completa. Hermes operativo." --platform telegram
```

---

## Paso 10: Validar Integraciones

| Integracion | Como verificar |
|-------------|----------------|
| **Telegram** | Enviar mensaje al bot |
| **OpenRouter (LLM)** | `hermes send "hola" --platform telegram` |
| **CRM Enrichment** | `hermes cron run weekly_crm_enrichment` |
| **FSM Tenant Alert** | `hermes cron run fsm_new_tenant_alert` |
| **Lead Pipeline** | `run_pipeline.sh --vertical fumigacion` |
| **DynamoDB CRM** | `aws dynamodb scan --table-name sifagent-crm-clients --max-items 5` |

---

## Paso 11: Reautenticar Proveedores (si aplica)

El archivo `auth.json` contiene tokens OAuth de sesion. Se regenera automaticamente al usar `hermes` con el provider correspondiente.

```bash
# Si usas Nous Research como provider principal, el OAuth se renueva al interactuar
hermes send "Test auth" --platform telegram
```

---

## Troubleshooting

### Bot no responde en Telegram
1. Verificar `TELEGRAM_BOT_TOKEN` en `.env`
2. `sudo systemctl status hermes-gateway`
3. `sudo journalctl -u hermes-gateway --since "5 min ago"`

### Error de modelo/LLM
1. Verificar `OPENROUTER_API_KEY` en `.env`
2. `hermes config get model`

### Secrets Manager access denied
1. Verificar IAM role tiene `OpenClaw-Server-Role`
2. Verificar policy inline `HermesSecretsManagerAccess`

### DynamoDB access denied
1. Verificar IAM role tiene acceso a `sifagent-crm-clients`
2. `aws dynamodb describe-table --table-name sifagent-crm-clients`

---

## Tiempos Estimados

| Paso | Tiempo |
|------|--------|
| Provisionar EC2 | 5 min |
| Instalar dependencias | 10 min |
| Instalar Hermes Agent | 5 min |
| Restaurar archivos + secrets | 3 min |
| Configurar systemd + cron | 3 min |
| Verificar | 5 min |
| **Total** | **~30 minutos** |

---

## Mantenimiento del Backup

| Componente | Frecuencia | Destino |
|------------|-----------|---------|
| Archivos (config, skills, scripts, estado) | Diario 12:00 UTC | GitHub `holmart/hermesBackup` |
| Secrets (`.env`) | Diario 12:00 UTC | AWS Secrets Manager `hermes-agent/env` |
| Version source | Diario 12:00 UTC | `hermes_version.txt` en GitHub backup |
| CRM DynamoDB | **NO TIENE BACKUP AUTOMATICO** | Tabla persistente en AWS (no se pierde con EC2) |

> **ADVERTENCIA:** La tabla DynamoDB `sifagent-crm-clients` no tiene backup configurado. Si alguien borra la tabla o sus items, no hay forma de recuperarlos. Considerar activar **Point-in-Time Recovery (PITR)** o exportaciones periodicas a S3.

---

*Ultima actualizacion: 2026-08-21*
*Version de Hermes: v0.20.1*
