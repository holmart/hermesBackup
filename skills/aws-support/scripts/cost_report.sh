#!/bin/bash
# =============================================================================
# AWS Cost Report v2 — Enhanced
# =============================================================================
# Genera reporte completo de costos con:
# - Costo total y comparación mes anterior (MoM)
# - Forecast de cierre de mes
# - Top servicios por costo
# - Costo diario (últimos 7 días con barras)
# - Desglose por tags (Project/Environment)
# - Alertas de anomalías (servicios con >50% de aumento)
# - Instancias EC2 infrautilizadas (CPU <5%)
# - Lambda con errores/throttles
# - DynamoDB capacity analysis
# - Recursos desperdiciados (EBS, EIPs)
# - Formato Telegram-friendly (--telegram)
# - Historial JSON (--json)
#
# Uso:
#   bash cost_report.sh [days_back] [--telegram] [--json]
#   bash cost_report.sh 30
#   bash cost_report.sh 30 --telegram
#   bash cost_report.sh --json
# =============================================================================

set -o pipefail

# --- Parse arguments ---
DAYS_BACK=30
TELEGRAM_MODE=false
JSON_MODE=false
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
HISTORY_DIR="${HERMES_HOME:-/home/ubuntu/.hermes}/leads"
HISTORY_FILE="$HISTORY_DIR/cost_history.json"

for arg in "$@"; do
  case "$arg" in
    --telegram) TELEGRAM_MODE=true ;;
    --json) JSON_MODE=true ;;
    [0-9]*) DAYS_BACK="$arg" ;;
  esac
done

# --- Cross-platform date helpers ---
_date_ago() {
  local days="$1"
  date -u -d "$days days ago" +%Y-%m-%d 2>/dev/null || date -u -v-${days}d +%Y-%m-%d
}

_date_format() {
  date -u +%Y-%m-%d
}

_month_start() {
  date -u +%Y-%m-01
}

_prev_month_start() {
  date -u -d "$(date +%Y-%m-01) -1 month" +%Y-%m-01 2>/dev/null || date -u -v-1m -v1d +%Y-%m-01
}

_prev_month_end() {
  date -u -d "$(date +%Y-%m-01) -1 day" +%Y-%m-%d 2>/dev/null || date -u -v1d -v-1d +%Y-%m-%d
}

# --- Dates ---
END_DATE=$(_date_format)
START_DATE=$(_date_ago "$DAYS_BACK")
WEEK_START=$(_date_ago 7)
MONTH_START=$(_month_start)
PREV_MONTH_START=$(_prev_month_start)
PREV_MONTH_END=$(_prev_month_end)

# --- Output buffer (for telegram/json modes) ---
OUTPUT=""
_print() {
  OUTPUT+="$1"$'\n'
  if [ "$JSON_MODE" != "true" ] && [ "$TELEGRAM_MODE" != "true" ]; then
    echo "$1"
  fi
}

# =============================================================================
# SECTION 1: HEADER
# =============================================================================

if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "💰 *AWS Cost Report*"
  _print "📅 Período: $START_DATE → $END_DATE ($DAYS_BACK días)"
  _print ""
else
  _print "=========================================="
  _print "  AWS Cost Report v2"
  _print "  Período: $START_DATE → $END_DATE ($DAYS_BACK días)"
  _print "  Región: $REGION"
  _print "=========================================="
fi

# =============================================================================
# SECTION 2: COSTO TOTAL + MoM COMPARISON
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "📊 *Costo Total*"
else
  _print "--- Costo Total + Comparación MoM ---"
fi

# Current period
CURRENT_COST=$(aws ce get-cost-and-usage \
  --time-period "Start=$START_DATE,End=$END_DATE" \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = 0
for r in data.get('ResultsByTime', []):
    amt = float(r['Total']['BlendedCost']['Amount'])
    period = r['TimePeriod']
    print(f\"  {period['Start']} → {period['End']}: \${amt:.2f}\")
    total += amt
print(f\"  TOTAL período: \${total:.2f}\")
print(f'__TOTAL__:{total:.2f}')
" 2>/dev/null)

if [ -n "$CURRENT_COST" ]; then
  # Print all lines except the __TOTAL__ marker
  echo "$CURRENT_COST" | grep -v "__TOTAL__" | while read -r line; do _print "$line"; done
  TOTAL_CURRENT=$(echo "$CURRENT_COST" | grep "__TOTAL__" | cut -d: -f2)
else
  _print "  ERROR: No se pudo obtener datos de costos"
  TOTAL_CURRENT="0"
fi

# Previous month for comparison
PREV_COST=$(aws ce get-cost-and-usage \
  --time-period "Start=$PREV_MONTH_START,End=$PREV_MONTH_END" \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = sum(float(r['Total']['BlendedCost']['Amount']) for r in data.get('ResultsByTime', []))
print(f'{total:.2f}')
" 2>/dev/null)

if [ -n "$PREV_COST" ] && [ "$PREV_COST" != "0.00" ] && [ -n "$TOTAL_CURRENT" ]; then
  python3 -c "
current = float('${TOTAL_CURRENT:-0}')
prev = float('${PREV_COST:-0}')
if prev > 0:
    change = ((current - prev) / prev) * 100
    arrow = '📈' if change > 0 else '📉'
    print(f'  {arrow} vs mes anterior (\${prev:.2f}): {change:+.1f}%')
else:
    print('  ℹ️ Sin datos del mes anterior para comparar')
" 2>/dev/null | while read -r line; do _print "$line"; done
fi

# =============================================================================
# SECTION 3: FORECAST
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🔮 *Forecast Fin de Mes*"
else
  _print "--- Forecast Cierre de Mes ---"
fi

# AWS GetCostForecast needs start in the future (tomorrow) and end = next month start
TOMORROW=$(date -u -d "+1 day" +%Y-%m-%d 2>/dev/null || date -u -v+1d +%Y-%m-%d)
NEXT_MONTH_START=$(date -u -d "$(date +%Y-%m-01) +1 month" +%Y-%m-01 2>/dev/null || date -u -v+1m -v1d +%Y-%m-01)

aws ce get-cost-forecast \
  --time-period "Start=$TOMORROW,End=$NEXT_MONTH_START" \
  --granularity MONTHLY \
  --metric BLENDED_COST \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = data.get('Total', {})
amt = float(total.get('Amount', 0))
lo = float(data.get('ForecastResultsByTime', [{}])[0].get('MeanValue', amt) if not total else amt)
print(f'  Estimado cierre de mes: \${amt:.2f}')
intervals = data.get('ForecastResultsByTime', [])
if intervals and 'PredictionIntervalLowerBound' in intervals[0]:
    lo = float(intervals[0]['PredictionIntervalLowerBound'])
    hi = float(intervals[0]['PredictionIntervalUpperBound'])
    print(f'  Rango: \${lo:.2f} — \${hi:.2f}')
" 2>/dev/null | while read -r line; do _print "$line"; done

if [ ${PIPESTATUS[0]} -ne 0 ] 2>/dev/null; then
  _print "  ℹ️ Forecast no disponible (necesita al menos 2 semanas de datos)"
fi

# =============================================================================
# SECTION 4: TOP SERVICIOS POR COSTO
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🏆 *Top 10 Servicios*"
else
  _print "--- Costo por Servicio (Top 10) ---"
fi

aws ce get-cost-and-usage \
  --time-period "Start=$START_DATE,End=$END_DATE" \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
services = {}
for r in data.get('ResultsByTime', []):
    for g in r.get('Groups', []):
        svc = g['Keys'][0]
        amt = float(g['Metrics']['BlendedCost']['Amount'])
        services[svc] = services.get(svc, 0) + amt

sorted_svcs = sorted(services.items(), key=lambda x: x[1], reverse=True)[:10]
for svc, amt in sorted_svcs:
    if amt > 0.01:
        # Shorten service names for readability
        short = svc.replace('Amazon ', '').replace('AWS ', '').replace(' - Compute', '')
        print(f'  {short:40s} \${amt:.2f}')
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 5: COSTO DIARIO (últimos 7 días)
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "📅 *Costo Diario (7 días)*"
else
  _print "--- Costo Diario (últimos 7 días) ---"
fi

aws ce get-cost-and-usage \
  --time-period "Start=$WEEK_START,End=$END_DATE" \
  --granularity DAILY \
  --metrics BlendedCost \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
days = data.get('ResultsByTime', [])
if not days:
    print('  Sin datos diarios disponibles')
else:
    amts = [float(r['Total']['BlendedCost']['Amount']) for r in days]
    max_amt = max(amts) if amts else 1
    for r in days:
        date = r['TimePeriod']['Start']
        amt = float(r['Total']['BlendedCost']['Amount'])
        bar_len = int((amt / max_amt) * 20) if max_amt > 0 else 0
        bar = '█' * bar_len
        print(f'  {date[5:]}  \${amt:.2f}  {bar}')
    avg = sum(amts) / len(amts) if amts else 0
    print(f'  Promedio diario: \${avg:.2f}')
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 6: DESGLOSE POR TAGS
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🏷️ *Costo por Proyecto (tags)*"
else
  _print "--- Costo por Tag: Project ---"
fi

aws ce get-cost-and-usage \
  --time-period "Start=$START_DATE,End=$END_DATE" \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=TAG,Key=Project \
  --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
tags = {}
for r in data.get('ResultsByTime', []):
    for g in r.get('Groups', []):
        tag = g['Keys'][0] or '(sin tag Project)'
        # Remove 'Project$' prefix if present
        tag = tag.replace('Project\$', '') if '\$' in tag else tag
        amt = float(g['Metrics']['BlendedCost']['Amount'])
        tags[tag] = tags.get(tag, 0) + amt

if not tags:
    print('  No hay recursos tagueados con \"Project\"')
else:
    sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:8]
    for tag, amt in sorted_tags:
        if amt > 0.01:
            print(f'  {tag:35s} \${amt:.2f}')
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 7: ALERTAS DE ANOMALÍAS
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "⚠️ *Alertas de Anomalías*"
else
  _print "--- Alertas de Anomalías (servicios con >50% aumento) ---"
fi

python3 -c "
import json, subprocess, sys

def get_costs(start, end):
    cmd = ['aws', 'ce', 'get-cost-and-usage',
           '--time-period', f'Start={start},End={end}',
           '--granularity', 'MONTHLY', '--metrics', 'BlendedCost',
           '--group-by', 'Type=DIMENSION,Key=SERVICE', '--output', 'json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return {}
    data = json.loads(r.stdout)
    services = {}
    for period in data.get('ResultsByTime', []):
        for g in period.get('Groups', []):
            svc = g['Keys'][0]
            amt = float(g['Metrics']['BlendedCost']['Amount'])
            services[svc] = services.get(svc, 0) + amt
    return services

current = get_costs('$MONTH_START', '$END_DATE')
previous = get_costs('$PREV_MONTH_START', '$PREV_MONTH_END')

if not current or not previous:
    print('  Sin datos suficientes para detectar anomalías')
    sys.exit(0)

anomalies = []
for svc, curr_amt in current.items():
    prev_amt = previous.get(svc, 0)
    if prev_amt > 0.50 and curr_amt > prev_amt * 1.5:
        pct = ((curr_amt - prev_amt) / prev_amt) * 100
        anomalies.append((svc, prev_amt, curr_amt, pct))

if not anomalies:
    print('  ✅ Sin anomalías detectadas')
else:
    anomalies.sort(key=lambda x: x[3], reverse=True)
    for svc, prev, curr, pct in anomalies[:5]:
        short = svc.replace('Amazon ', '').replace('AWS ', '')
        print(f'  🚨 {short}: \${prev:.2f} → \${curr:.2f} (+{pct:.0f}%)')
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 8: EC2 INFRAUTILIZADAS
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🖥️ *EC2 Infrautilizadas (CPU <5%)*"
else
  _print "--- EC2 Infrautilizadas (CPU promedio <5%, 7 días) ---"
fi

python3 -c "
import json, subprocess, sys
from datetime import datetime, timedelta, timezone

# Get running instances
cmd = ['aws', 'ec2', 'describe-instances', '--region', '$REGION',
       '--filters', 'Name=instance-state-name,Values=running',
       '--query', 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==\`Name\`].Value|[0]]',
       '--output', 'json']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    print('  ERROR: No se pudieron listar instancias')
    sys.exit(0)

instances = json.loads(r.stdout)
if not instances:
    print('  Sin instancias running')
    sys.exit(0)

now = datetime.now(timezone.utc)
start = (now - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S')
end = now.strftime('%Y-%m-%dT%H:%M:%S')

underutilized = []
for inst in instances:
    iid, itype, name = inst[0], inst[1], inst[2] or '(sin nombre)'
    cmd = ['aws', 'cloudwatch', 'get-metric-statistics',
           '--namespace', 'AWS/EC2', '--metric-name', 'CPUUtilization',
           '--dimensions', f'Name=InstanceId,Value={iid}',
           '--start-time', start, '--end-time', end,
           '--period', '86400', '--statistics', 'Average',
           '--region', '$REGION', '--output', 'json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        continue
    data = json.loads(r.stdout)
    points = data.get('Datapoints', [])
    if not points:
        continue
    avg_cpu = sum(p['Average'] for p in points) / len(points)
    if avg_cpu < 5.0:
        underutilized.append((name, iid, itype, avg_cpu))

if not underutilized:
    print('  ✅ Todas las instancias con uso >5% CPU')
else:
    for name, iid, itype, cpu in sorted(underutilized, key=lambda x: x[3]):
        print(f'  ⚠️ {name} ({itype}): CPU prom {cpu:.1f}% — considerar apagar/reducir')
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 9: LAMBDA ERRORES Y THROTTLES
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "⚡ *Lambda — Errores y Throttles*"
else
  _print "--- Lambda con Errores/Throttles (7 días) ---"
fi

python3 -c "
import json, subprocess, sys
from datetime import datetime, timedelta, timezone

# List all functions
cmd = ['aws', 'lambda', 'list-functions', '--region', '$REGION', '--output', 'json',
       '--query', 'Functions[].[FunctionName]']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    print('  ERROR: No se pudieron listar funciones Lambda')
    sys.exit(0)

functions = json.loads(r.stdout)
if not functions:
    print('  Sin funciones Lambda')
    sys.exit(0)

now = datetime.now(timezone.utc)
start = (now - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S')
end = now.strftime('%Y-%m-%dT%H:%M:%S')

problematic = []
for func in functions:
    fname = func[0]
    # Get errors
    cmd = ['aws', 'cloudwatch', 'get-metric-statistics',
           '--namespace', 'AWS/Lambda', '--metric-name', 'Errors',
           '--dimensions', f'Name=FunctionName,Value={fname}',
           '--start-time', start, '--end-time', end,
           '--period', '604800', '--statistics', 'Sum',
           '--region', '$REGION', '--output', 'json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        continue
    data = json.loads(r.stdout)
    errors = sum(p['Sum'] for p in data.get('Datapoints', []))

    # Get throttles
    cmd[5] = 'Throttles'
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    throttles = 0
    if r.returncode == 0:
        data = json.loads(r.stdout)
        throttles = sum(p['Sum'] for p in data.get('Datapoints', []))

    if errors > 0 or throttles > 0:
        problematic.append((fname, int(errors), int(throttles)))

if not problematic:
    print('  ✅ Sin errores ni throttles en Lambda')
else:
    problematic.sort(key=lambda x: x[1] + x[2], reverse=True)
    for fname, errs, throtts in problematic[:8]:
        parts = []
        if errs > 0: parts.append(f'{errs} errores')
        if throtts > 0: parts.append(f'{throtts} throttles')
        print(f'  ⚠️ {fname}: {\", \".join(parts)}')
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 10: DYNAMODB ANALYSIS
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🗄️ *DynamoDB — Capacidad*"
else
  _print "--- DynamoDB — Análisis de Capacidad ---"
fi

python3 -c "
import json, subprocess, sys

cmd = ['aws', 'dynamodb', 'list-tables', '--region', '$REGION', '--output', 'json']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    print('  ERROR: No se pudieron listar tablas')
    sys.exit(0)

tables = json.loads(r.stdout).get('TableNames', [])
if not tables:
    print('  Sin tablas DynamoDB')
    sys.exit(0)

for table in tables[:10]:
    cmd = ['aws', 'dynamodb', 'describe-table', '--table-name', table,
           '--region', '$REGION', '--output', 'json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        continue
    info = json.loads(r.stdout).get('Table', {})
    mode = info.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')
    items = info.get('ItemCount', 0)
    size_mb = info.get('TableSizeBytes', 0) / (1024*1024)
    gsi_count = len(info.get('GlobalSecondaryIndexes', []))

    mode_str = 'On-Demand' if mode == 'PAY_PER_REQUEST' else 'Provisioned'
    rcu = info.get('ProvisionedThroughput', {}).get('ReadCapacityUnits', 0)
    wcu = info.get('ProvisionedThroughput', {}).get('WriteCapacityUnits', 0)

    line = f'  {table}: {mode_str}'
    if mode != 'PAY_PER_REQUEST':
        line += f' (RCU:{rcu} WCU:{wcu})'
    line += f' | {items:,} items | {size_mb:.1f} MB'
    if gsi_count:
        line += f' | {gsi_count} GSIs'
    print(line)
" 2>/dev/null | while read -r line; do _print "$line"; done

# =============================================================================
# SECTION 11: RECURSOS DESPERDICIADOS
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🗑️ *Recursos Desperdiciados*"
else
  _print "--- Recursos Potencialmente Desperdiciados ---"
fi

# EBS Volumes no asociados
EBS_UNUSED=$(aws ec2 describe-volumes \
  --region "$REGION" \
  --filters "Name=status,Values=available" \
  --query "Volumes[].[VolumeId,Size,VolumeType]" \
  --output text 2>/dev/null)

if [ -n "$EBS_UNUSED" ]; then
  _print "  EBS no asociados:"
  echo "$EBS_UNUSED" | while read -r vol size vtype; do
    _print "    $vol — ${size}GB ($vtype)"
  done
else
  _print "  ✅ EBS: sin volúmenes no asociados"
fi

# Elastic IPs no asociadas
EIP_UNUSED=$(aws ec2 describe-addresses \
  --region "$REGION" \
  --query "Addresses[?!AssociationId].[PublicIp,AllocationId]" \
  --output text 2>/dev/null)

if [ -n "$EIP_UNUSED" ]; then
  _print "  EIPs no asociadas (costo: \$3.60/mes c/u):"
  echo "$EIP_UNUSED" | while read -r ip alloc; do
    _print "    $ip ($alloc)"
  done
else
  _print "  ✅ EIPs: todas asociadas"
fi

# Old snapshots (>90 days)
OLD_SNAPSHOTS=$(aws ec2 describe-snapshots \
  --region "$REGION" \
  --owner-ids self \
  --query "Snapshots[?StartTime<='$(date -u -d '90 days ago' +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -v-90d +%Y-%m-%dT%H:%M:%S)'].[SnapshotId,VolumeSize,StartTime]" \
  --output text 2>/dev/null | head -5)

if [ -n "$OLD_SNAPSHOTS" ]; then
  COUNT=$(echo "$OLD_SNAPSHOTS" | wc -l | tr -d ' ')
  _print "  Snapshots >90 días: $COUNT encontrados"
  echo "$OLD_SNAPSHOTS" | while read -r snap size stime; do
    _print "    $snap — ${size}GB (${stime:0:10})"
  done
else
  _print "  ✅ Snapshots: sin snapshots antiguos >90 días"
fi

# =============================================================================
# SECTION 12: LLM ANALYSIS (AI-powered insights)
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "🧠 *Análisis Inteligente*"
else
  _print "--- Análisis Inteligente (LLM) ---"
fi

# Use the collected OUTPUT as context for LLM analysis
LLM_API_KEY="${OPENROUTER_API_KEY:-}"
LLM_MODEL="${LLM_MODEL:-openai/gpt-4o-mini}"
LLM_API_BASE="${LLM_API_BASE:-https://openrouter.ai/api/v1}"

if [ -z "$LLM_API_KEY" ]; then
  # Try loading from .env
  ENV_FILE="${HERMES_HOME:-/home/ubuntu/.hermes}/.env"
  if [ -f "$ENV_FILE" ]; then
    LLM_API_KEY=$(grep "^OPENROUTER_API_KEY" "$ENV_FILE" | cut -d= -f2 | tr -d '"' | tr -d "'")
  fi
fi

if [ -n "$LLM_API_KEY" ]; then
  LLM_INSIGHTS=$(python3 -c "
import json, urllib.request, urllib.error, sys, os

api_key = '$LLM_API_KEY'
model = '$LLM_MODEL'
api_base = '$LLM_API_BASE'

# Build the report summary for LLM context
report_data = '''$OUTPUT'''

prompt = f'''Eres un experto en optimización de costos AWS. Analiza este reporte y genera exactamente 3-5 insights accionables.

REPORTE:
{report_data}

REGLAS:
- Responde SOLO con los insights, uno por línea
- Cada insight debe empezar con un emoji relevante
- Sé específico y accionable (no genérico)
- Si hay anomalías, explica posibles causas
- Si hay recursos infrautilizados, sugiere acción concreta
- Máximo 2 líneas por insight
- Responde en español

Insights:'''

payload = json.dumps({
    'model': model,
    'messages': [{'role': 'user', 'content': prompt}],
    'max_tokens': 400,
    'temperature': 0.3,
}).encode()

req = urllib.request.Request(
    f'{api_base}/chat/completions',
    data=payload,
    headers={
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
)

try:
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read())
        content = data['choices'][0]['message']['content'].strip()
        print(content)
except Exception as e:
    print(f'(LLM no disponible: {e})')
" 2>/dev/null)

  if [ -n "$LLM_INSIGHTS" ]; then
    echo "$LLM_INSIGHTS" | while IFS= read -r line; do
      if [ -n "$line" ]; then
        _print "  $line"
      fi
    done
  else
    _print "  (No se pudo generar análisis — LLM no respondió)"
  fi
else
  _print "  ℹ️ Análisis LLM no disponible (set OPENROUTER_API_KEY)"
fi

# =============================================================================
# SECTION 13: FOOTER
# =============================================================================

_print ""
if [ "$TELEGRAM_MODE" = "true" ]; then
  _print "_Generado: $(date -u +%Y-%m-%d\ %H:%M) UTC_"
else
  _print "=========================================="
  _print "  Cost Report completo — $(date -u +%Y-%m-%d\ %H:%M:%S) UTC"
  _print "=========================================="
fi

# =============================================================================
# JSON HISTORY (always save)
# =============================================================================

mkdir -p "$HISTORY_DIR" 2>/dev/null
python3 -c "
import json, os, sys
from datetime import datetime, timezone

history_file = '$HISTORY_FILE'
entry = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'period_start': '$START_DATE',
    'period_end': '$END_DATE',
    'days': $DAYS_BACK,
    'total_cost': float('${TOTAL_CURRENT:-0}'),
    'prev_month_cost': float('${PREV_COST:-0}'),
}

# Load existing history
history = []
if os.path.isfile(history_file):
    try:
        with open(history_file, 'r') as f:
            history = json.load(f)
    except (json.JSONDecodeError, IOError):
        history = []

# Keep last 90 entries
history.append(entry)
history = history[-90:]

with open(history_file, 'w') as f:
    json.dump(history, f, indent=2, ensure_ascii=False)
" 2>/dev/null

# =============================================================================
# OUTPUT MODES
# =============================================================================

if [ "$JSON_MODE" = "true" ]; then
  # Re-run just the key data and output as JSON
  python3 -c "
import json, subprocess, sys

def get_total(start, end):
    cmd = ['aws', 'ce', 'get-cost-and-usage',
           '--time-period', f'Start={start},End={end}',
           '--granularity', 'MONTHLY', '--metrics', 'BlendedCost', '--output', 'json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0: return 0
    data = json.loads(r.stdout)
    return sum(float(p['Total']['BlendedCost']['Amount']) for p in data.get('ResultsByTime', []))

result = {
    'period': {'start': '$START_DATE', 'end': '$END_DATE', 'days': $DAYS_BACK},
    'total_cost': float('${TOTAL_CURRENT:-0}'),
    'prev_month_cost': float('${PREV_COST:-0}'),
    'generated_at': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
}
print(json.dumps(result, indent=2))
" 2>/dev/null
elif [ "$TELEGRAM_MODE" = "true" ]; then
  echo "$OUTPUT"
fi
