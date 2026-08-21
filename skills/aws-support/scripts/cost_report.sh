#!/bin/bash
# AWS Cost Report
# Uso: bash cost_report.sh [days_back]

DAYS_BACK="${1:-30}"
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -u -d "$DAYS_BACK days ago" +%Y-%m-%d 2>/dev/null || date -u -v-${DAYS_BACK}d +%Y-%m-%d)

echo "=========================================="
echo "  AWS Cost Report"
echo "  Periodo: $START_DATE -> $END_DATE ($DAYS_BACK dias)"
echo "=========================================="

echo ""
echo "--- Costo Total ---"
aws ce get-cost-and-usage --time-period "Start=$START_DATE,End=$END_DATE" --granularity MONTHLY --metrics BlendedCost --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = 0
for r in data.get('ResultsByTime', []):
    amt = float(r['Total']['BlendedCost']['Amount'])
    period = r['TimePeriod']
    print(f\"  {period['Start']} -> {period['End']}: USD {amt:.2f}\")
    total += amt
print(f'\n  TOTAL: USD {total:.2f}')
" || echo "ERROR: No se pudo obtener costos"

echo ""
echo "--- Top 10 Servicios por Costo ---"
aws ce get-cost-and-usage --time-period "Start=$START_DATE,End=$END_DATE" --granularity MONTHLY --metrics BlendedCost --group-by Type=DIMENSION,Key=SERVICE --output json 2>/dev/null | python3 -c "
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
        print(f'  {svc:45s} USD {amt:.2f}')
" || echo "ERROR: No se pudo obtener desglose"

echo ""
echo "--- Recursos Desperdiciados ---"
echo "  EBS no asociados:"
aws ec2 describe-volumes --region us-east-1 --filters "Name=status,Values=available" --query "Volumes[].[VolumeId,Size]" --output text 2>/dev/null || echo "    Ninguno"
echo "  EIPs no asociadas:"
aws ec2 describe-addresses --region us-east-1 --query "Addresses[?!AssociationId].[PublicIp,AllocationId]" --output text 2>/dev/null || echo "    Ninguna"

echo ""
echo "=========================================="
echo "  Cost Report completo"
echo "=========================================="
