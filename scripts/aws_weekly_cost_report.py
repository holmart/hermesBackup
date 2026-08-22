#!/usr/bin/env python3
"""
AWS Weekly Cost Report
- Obtiene costos por servicio via Cost Explorer
- Compara con semana anterior
- Detecta aumentos significativos
- Genera recomendaciones de optimizacion
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

HISTORY_FILE = "/home/ubuntu/.hermes/cron/aws_cost_history.json"
REPORT_FILE = "/home/ubuntu/.hermes/cron/aws_weekly_cost_report.md"


def run_aws_cmd(cmd):
    """Ejecuta comando AWS CLI y retorna JSON"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"AWS Error: {result.stderr}", file=sys.stderr)
            return None
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error ejecutando comando: {e}", file=sys.stderr)
        return None


def get_cost_by_service(start, end):
    """Obtiene costos agrupados por servicio"""
    cmd = (
        f"aws ce get-cost-and-usage "
        f"--time-period Start={start},End={end} "
        f"--granularity DAILY "
        f"--metrics BlendedCost "
        f"--group-by Type=DIMENSION,Key=SERVICE "
        f"--output json"
    )
    return run_aws_cmd(cmd)


def get_cost_by_usage_type(start, end, service):
    """Obtiene detalle de costos por usage type para un servicio"""
    cmd = (
        f"aws ce get-cost-and-usage "
        f"--time-period Start={start},End={end} "
        f"--granularity DAILY "
        f"--metrics BlendedCost "
        f"--group-by Type=DIMENSION,Key=USAGE_TYPE "
        f"--filter '{{\"Dimensions\":{{\"Key\":\"SERVICE\",\"Values\":[\"{service}\"]}}}}' "
        f"--output json"
    )
    return run_aws_cmd(cmd)


def parse_costs(data):
    """Extrae costos por servicio del resultado de AWS"""
    costs = {}
    if not data:
        return costs
    for result in data.get("ResultsByTime", []):
        for group in result.get("Groups", []):
            service = group["Keys"][0]
            amount = float(group["Metrics"]["BlendedCost"]["Amount"])
            if amount > 0.01:
                costs[service] = costs.get(service, 0) + amount
    return costs


def load_history():
    """Carga historial de costos previos"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_history(history):
    """Guarda historial de costos"""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def get_recommendations(service, cost, details=None):
    """Genera recomendaciones especificas por servicio"""
    recs = []
    
    if "CloudFront" in service:
        recs.append("Reducir invalidaciones: usar versionado de assets, invalidar solo rutas cambiadas")
        recs.append("Consolidar distribuciones staging en una sola")
        if details and any("Invalidations" in k for k in details.keys()):
            recs.append("**URGENTE**: Invalidaciones exceden limite gratuito (1,000/mes). Costo ~$0.005 por URL invalidada.")
    
    elif "EC2" in service:
        recs.append("Revisar instancias subutilizadas (CPU < 10%)")
        recs.append("Considerar Reserved Instances si uso es estable")
        recs.append("Revisar EBS no asociados y snapshots viejos")
    
    elif "S3" in service:
        recs.append("Activar lifecycle policies para mover a Glacier/IA")
        recs.append("Revisar multipart uploads fallidos")
        recs.append("Habilitar compresion en CloudFront para reducir transferencia")
    
    elif "DynamoDB" in service:
        recs.append("Revisar capacidad provisionada vs on-demand")
        recs.append("Activar TTL para datos temporales")
        recs.append("Considerar DAX si hay lecturas frecuentes")
    
    elif "Lambda" in service:
        recs.append("Revisar funciones con alto cold start time")
        recs.append("Optimizar memory allocation (no sobreprovisionar)")
        recs.append("Usar provisioned concurrency si es critico")
    
    elif "API Gateway" in service:
        recs.append("Considerar HTTP API en vez de REST API (70% mas barato)")
        recs.append("Cachear respuestas frecuentes")
    
    elif "Route 53" in service:
        recs.append("Costo fijo bajo, normal para dominios gestionados")
    
    elif "CloudWatch" in service:
        recs.append("Revisar custom metrics y logs retention")
        recs.append("Reducir granularidad de metricas si no es critico")
    
    elif "Secrets Manager" in service:
        recs.append("Costo fijo bajo por secretos almacenados")
    
    else:
        recs.append("Revisar uso y considerar eliminar si no es necesario")
    
    return recs


def generate_report(current_costs, previous_costs, week_label):
    """Genera reporte Markdown"""
    lines = []
    lines.append(f"# Reporte Semanal de Costos AWS\n")
    lines.append(f"**Periodo:** {week_label}\n")
    lines.append(f"**Generado:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")
    lines.append(f"**Cuenta:** 768296856192 (us-east-1)\n\n")
    
    total_current = sum(current_costs.values())
    total_previous = sum(previous_costs.values()) if previous_costs else 0
    
    lines.append(f"## Resumen Ejecutivo\n\n")
    lines.append(f"| Metrica | Valor |\n")
    lines.append(f"|---------|-------|\n")
    lines.append(f"| Costo total esta semana | **${total_current:.2f}** |\n")
    if total_previous > 0:
        delta = total_current - total_previous
        pct = (delta / total_previous) * 100 if total_previous else 0
        trend = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        lines.append(f"| Semana anterior | ${total_previous:.2f} |\n")
        lines.append(f"| Variacion | {trend} ${abs(delta):.2f} ({abs(pct):.1f}%) |\n")
    lines.append(f"| Servicios activos | {len(current_costs)} |\n\n")
    
    # Servicios ordenados por costo
    lines.append(f"## Costos por Servicio\n\n")
    lines.append(f"| Servicio | Costo | % Total | Variacion vs Semana Ant |\n")
    lines.append(f"|----------|-------|---------|------------------------|\n")
    
    alerts = []
    for service, cost in sorted(current_costs.items(), key=lambda x: -x[1]):
        pct = (cost / total_current) * 100 if total_current else 0
        prev = previous_costs.get(service, 0)
        
        if prev > 0:
            delta = cost - prev
            delta_pct = (delta / prev) * 100
            if delta > 5 or delta_pct > 50:
                alerts.append((service, cost, prev, delta, delta_pct))
            delta_str = f"+${delta:.2f} ({delta_pct:+.1f}%)" if delta >= 0 else f"-${abs(delta):.2f} ({delta_pct:.1f}%)"
        else:
            delta_str = "Nuevo"
            if cost > 1:
                alerts.append((service, cost, 0, cost, 100))
        
        lines.append(f"| {service} | ${cost:.2f} | {pct:.1f}% | {delta_str} |\n")
    
    lines.append("\n")
    
    # Alertas
    if alerts:
        lines.append(f"## ⚠️ Alertas de Aumento\n\n")
        lines.append(f"Se detectaron **{len(alerts)}** servicios con aumento significativo:\n\n")
        
        for service, cost, prev, delta, delta_pct in sorted(alerts, key=lambda x: -x[3]):
            lines.append(f"### {service}\n\n")
            lines.append(f"- Costo actual: **${cost:.2f}**\n")
            lines.append(f"- Costo anterior: ${prev:.2f}\n")
            lines.append(f"- Aumento: **+${delta:.2f} ({delta_pct:+.1f}%)**\n\n")
            
            # Obtener detalle por usage type
            details = None
            today = datetime.utcnow()
            start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
            end = today.strftime('%Y-%m-%d')
            detail_data = get_cost_by_usage_type(start, end, service)
            if detail_data:
                details = parse_costs(detail_data)
                top_usage = sorted(details.items(), key=lambda x: -x[1])[:3]
                lines.append(f"**Top conceptos de costo:**\n")
                for usage, amt in top_usage:
                    lines.append(f"- {usage}: ${amt:.4f}\n")
                lines.append("\n")
            
            recs = get_recommendations(service, cost, details)
            lines.append(f"**Recomendaciones:**\n")
            for rec in recs:
                lines.append(f"- {rec}\n")
            lines.append("\n")
    else:
        lines.append(f"## ✅ Sin Alertas\n\n")
        lines.append(f"Ningun servicio mostro aumento significativo esta semana.\n\n")
    
    # Recomendaciones generales
    lines.append(f"## Recomendaciones Generales\n\n")
    
    if "Amazon Elastic Compute Cloud" in current_costs and current_costs["Amazon Elastic Compute Cloud"] > 5:
        lines.append(f"- **EC2**: ${current_costs['Amazon Elastic Compute Cloud']:.2f}/semana. Revisar instancias subutilizadas.\n")
    
    if "Amazon CloudFront" in current_costs and current_costs["Amazon CloudFront"] > 2:
        lines.append(f"- **CloudFront**: ${current_costs['Amazon CloudFront']:.2f}/semana. Invalidaciones probablemente exceden limite gratuito. Usar versionado de assets.\n")
    
    if "Amazon Simple Storage Service" in current_costs and current_costs["Amazon Simple Storage Service"] > 1:
        lines.append(f"- **S3**: ${current_costs['Amazon Simple Storage Service']:.2f}/semana. Revisar lifecycle policies y versionamiento.\n")
    
    lines.append(f"- Usar `--dry-run` antes de eliminar cualquier recurso.\n")
    lines.append(f"- Activar AWS Budgets para alertas de costo automaticas.\n\n")
    
    lines.append(f"---\n*Reporte generado automaticamente por Hermes Agent*\n")
    
    return "\n".join(lines)


def main():
    today = datetime.utcnow()
    
    # Periodo actual: ultimos 7 dias
    current_start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    current_end = today.strftime('%Y-%m-%d')
    
    # Periodo anterior: 7-14 dias atras
    prev_start = (today - timedelta(days=14)).strftime('%Y-%m-%d')
    prev_end = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    
    week_label = f"{current_start} al {current_end}"
    
    print(f"Obteniendo costos: {current_start} a {current_end}")
    current_data = get_cost_by_service(current_start, current_end)
    current_costs = parse_costs(current_data)
    
    print(f"Obteniendo costos semana anterior: {prev_start} a {prev_end}")
    prev_data = get_cost_by_service(prev_start, prev_end)
    previous_costs = parse_costs(prev_data)
    
    # Guardar en historial
    history = load_history()
    history[week_label] = current_costs
    # Mantener solo ultimas 8 semanas
    keys = sorted(history.keys())[-8:]
    history = {k: history[k] for k in keys}
    save_history(history)
    
    # Generar reporte
    report = generate_report(current_costs, previous_costs, week_label)
    
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    
    print(report)
    return report


if __name__ == "__main__":
    main()
