#!/usr/bin/env python3
"""
Query Leads CRM — Consulta conversacional de leads en DynamoDB.
================================================================
Script independiente para que Hermes consulte sus propios leads.
Diseñado para usarse como tool desde Telegram o CLI.

Uso:
  python3 query_leads.py --ciudad Bogota
  python3 query_leads.py --min-score 4
  python3 query_leads.py --estado nuevo
  python3 query_leads.py --vertical fumigacion
  python3 query_leads.py --buscar "restaurante"
  python3 query_leads.py --stats
  python3 query_leads.py --recientes 5
  python3 query_leads.py --top 10
  python3 query_leads.py --ciudad Medellin --min-score 4 --vertical hvac

Combinaciones válidas: todos los filtros se pueden combinar.
"""

import json
import os
import subprocess
import sys
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

# =============================================================================
# CONFIGURATION
# =============================================================================

TABLE = os.environ.get("CRM_TABLE", "sifagent-crm-clients")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
HERMES_HOME = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")


# =============================================================================
# DYNAMO HELPERS
# =============================================================================

# GSI definitions — used for efficient queries when available
GSI_CIUDAD_SCORE = "ciudad-score-index"
GSI_ESTADO_FECHA = "estado-fecha-index"
GSI_VERTICAL_SCORE = "vertical-score-index"


def _run_dynamo_cmd(cmd: List[str]) -> Optional[Dict]:
    """Run an AWS CLI DynamoDB command. Returns parsed JSON or None on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            # Check if it's a GSI not found error
            if "ValidationException" in (result.stderr or ""):
                return None
            print(f"Error DynamoDB: {result.stderr[:200]}", file=sys.stderr)
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print("Error: DynamoDB timeout", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def query_gsi(index_name: str, key_condition: str,
              expression_values: Dict,
              filter_expression: Optional[str] = None,
              extra_values: Optional[Dict] = None,
              scan_forward: bool = False) -> Optional[List[Dict]]:
    """Query a GSI. Returns None if GSI doesn't exist (caller should fallback to scan)."""
    cmd = [
        "aws", "dynamodb", "query",
        "--table-name", TABLE,
        "--region", REGION,
        "--index-name", index_name,
        "--key-condition-expression", key_condition,
    ]

    all_values = dict(expression_values)
    if extra_values:
        all_values.update(extra_values)
    cmd.extend(["--expression-attribute-values", json.dumps(all_values)])

    if filter_expression:
        cmd.extend(["--filter-expression", filter_expression])

    if not scan_forward:
        cmd.append("--no-scan-index-forward")  # Descending (highest score / newest first)

    items = []
    start_key = None

    while True:
        page_cmd = list(cmd)
        if start_key:
            page_cmd.extend(["--exclusive-start-key", json.dumps(start_key)])

        data = _run_dynamo_cmd(page_cmd)
        if data is None:
            return None  # GSI doesn't exist or error — signal fallback

        items.extend(data.get("Items", []))
        start_key = data.get("LastEvaluatedKey")
        if not start_key:
            break

    return items


def scan_all_leads(filter_expression: Optional[str] = None,
                   expression_values: Optional[Dict] = None,
                   expression_names: Optional[Dict] = None) -> List[Dict]:
    """Scan the CRM table with optional filter. Returns all matching items."""
    items = []
    start_key = None

    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", TABLE,
            "--region", REGION,
        ]

        if filter_expression:
            cmd.extend(["--filter-expression", filter_expression])
        if expression_values:
            cmd.extend(["--expression-attribute-values", json.dumps(expression_values)])
        if expression_names:
            cmd.extend(["--expression-attribute-names", json.dumps(expression_names)])
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                print(f"Error DynamoDB: {result.stderr[:200]}", file=sys.stderr)
                break
            data = json.loads(result.stdout)
            items.extend(data.get("Items", []))
            start_key = data.get("LastEvaluatedKey")
            if not start_key:
                break
        except subprocess.TimeoutExpired:
            print("Error: DynamoDB scan timeout", file=sys.stderr)
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            break

    return items


def parse_dynamo_item(item: Dict) -> Dict:
    """Convert DynamoDB item format to flat dict."""
    parsed = {}
    for key, value in item.items():
        if "S" in value:
            parsed[key] = value["S"]
        elif "N" in value:
            parsed[key] = int(float(value["N"]))
        elif "BOOL" in value:
            parsed[key] = value["BOOL"]
        elif "NULL" in value:
            parsed[key] = None
        else:
            parsed[key] = str(value)
    return parsed


# =============================================================================
# QUERY FUNCTIONS (GSI-optimized with scan fallback)
# =============================================================================

def _query_via_ciudad_gsi(ciudad: str, min_score: Optional[int] = None,
                          estado: Optional[str] = None,
                          vertical: Optional[str] = None) -> Optional[List[Dict]]:
    """Query ciudad-score-index. Returns None if GSI unavailable."""
    key_condition = "Ciudad = :ciudad"
    values = {":ciudad": {"S": ciudad}}

    if min_score is not None:
        key_condition += " AND Score >= :min_score"
        values[":min_score"] = {"N": str(min_score)}

    # Additional filters beyond the key
    extra_filters = []
    extra_values = {}
    if estado:
        extra_filters.append("Estado = :estado")
        extra_values[":estado"] = {"S": estado}
    if vertical:
        extra_filters.append("Vertical = :vertical")
        extra_values[":vertical"] = {"S": vertical}

    filter_expr = " AND ".join(extra_filters) if extra_filters else None
    return query_gsi(GSI_CIUDAD_SCORE, key_condition, values,
                     filter_expression=filter_expr, extra_values=extra_values or None)


def _query_via_estado_gsi(estado: str, min_score: Optional[int] = None,
                          ciudad: Optional[str] = None,
                          vertical: Optional[str] = None) -> Optional[List[Dict]]:
    """Query estado-fecha-index. Returns None if GSI unavailable."""
    key_condition = "Estado = :estado"
    values = {":estado": {"S": estado}}

    extra_filters = []
    extra_values = {}
    if min_score is not None:
        extra_filters.append("Score >= :min_score")
        extra_values[":min_score"] = {"N": str(min_score)}
    if ciudad:
        extra_filters.append("contains(Ciudad, :ciudad)")
        extra_values[":ciudad"] = {"S": ciudad}
    if vertical:
        extra_filters.append("Vertical = :vertical")
        extra_values[":vertical"] = {"S": vertical}

    filter_expr = " AND ".join(extra_filters) if extra_filters else None
    return query_gsi(GSI_ESTADO_FECHA, key_condition, values,
                     filter_expression=filter_expr, extra_values=extra_values or None)


def _query_via_vertical_gsi(vertical: str, min_score: Optional[int] = None,
                            ciudad: Optional[str] = None,
                            estado: Optional[str] = None) -> Optional[List[Dict]]:
    """Query vertical-score-index. Returns None if GSI unavailable."""
    key_condition = "Vertical = :vertical"
    values = {":vertical": {"S": vertical}}

    if min_score is not None:
        key_condition += " AND Score >= :min_score"
        values[":min_score"] = {"N": str(min_score)}

    extra_filters = []
    extra_values = {}
    if ciudad:
        extra_filters.append("contains(Ciudad, :ciudad)")
        extra_values[":ciudad"] = {"S": ciudad}
    if estado:
        extra_filters.append("Estado = :estado")
        extra_values[":estado"] = {"S": estado}

    filter_expr = " AND ".join(extra_filters) if extra_filters else None
    return query_gsi(GSI_VERTICAL_SCORE, key_condition, values,
                     filter_expression=filter_expr, extra_values=extra_values or None)


def query_by_filters(ciudad: Optional[str] = None,
                     min_score: Optional[int] = None,
                     estado: Optional[str] = None,
                     vertical: Optional[str] = None,
                     buscar: Optional[str] = None) -> List[Dict]:
    """Query leads with combined filters. Uses GSIs when possible, falls back to scan."""

    # Text search always requires a full scan (no GSI can help)
    if not buscar:
        # Try GSI-optimized queries in priority order
        items = None

        if ciudad and items is None:
            items = _query_via_ciudad_gsi(ciudad, min_score, estado, vertical)
            if items is not None:
                leads = [parse_dynamo_item(item) for item in items]
                leads.sort(key=lambda x: (x.get("Score", 0), x.get("FechaIngreso", "")), reverse=True)
                return leads

        if estado and items is None:
            items = _query_via_estado_gsi(estado, min_score, ciudad, vertical)
            if items is not None:
                leads = [parse_dynamo_item(item) for item in items]
                leads.sort(key=lambda x: (x.get("Score", 0), x.get("FechaIngreso", "")), reverse=True)
                return leads

        if vertical and items is None:
            items = _query_via_vertical_gsi(vertical, min_score, ciudad, estado)
            if items is not None:
                leads = [parse_dynamo_item(item) for item in items]
                leads.sort(key=lambda x: (x.get("Score", 0), x.get("FechaIngreso", "")), reverse=True)
                return leads

    # Fallback: full scan with filter expressions
    filters = []
    values = {}
    names = {}

    if ciudad:
        filters.append("contains(Ciudad, :ciudad)")
        values[":ciudad"] = {"S": ciudad}

    if min_score is not None:
        filters.append("Score >= :min_score")
        values[":min_score"] = {"N": str(min_score)}

    if estado:
        filters.append("Estado = :estado")
        values[":estado"] = {"S": estado}

    if vertical:
        filters.append("Vertical = :vertical")
        values[":vertical"] = {"S": vertical}

    if buscar:
        # Search in multiple text fields
        search_conditions = []
        for i, field in enumerate(["NombreComercial", "Servicios", "ContactoPrincipal", "Ciudad", "Dominio"]):
            placeholder_name = f"#field{i}"
            placeholder_val = f":buscar{i}"
            names[placeholder_name] = field
            values[placeholder_val] = {"S": buscar.lower()}
            search_conditions.append(f"contains({placeholder_name}, {placeholder_val})")
        filters.append(f"({' OR '.join(search_conditions)})")

    filter_expr = " AND ".join(filters) if filters else None
    expr_values = values if values else None
    expr_names = names if names else None

    items = scan_all_leads(filter_expr, expr_values, expr_names)
    leads = [parse_dynamo_item(item) for item in items]

    # Sort by score desc, then date desc
    leads.sort(key=lambda x: (x.get("Score", 0), x.get("FechaIngreso", "")), reverse=True)
    return leads


def get_stats() -> Dict:
    """Get aggregated statistics of the CRM."""
    items = scan_all_leads()
    leads = [parse_dynamo_item(item) for item in items]

    if not leads:
        return {"total": 0, "message": "No hay leads en el CRM"}

    # Aggregate by different dimensions
    by_estado = {}
    by_ciudad = {}
    by_vertical = {}
    by_score = {}
    total = len(leads)

    for lead in leads:
        estado = lead.get("Estado", "sin_estado")
        by_estado[estado] = by_estado.get(estado, 0) + 1

        ciudad = lead.get("Ciudad", "sin_ciudad")
        if ciudad:
            by_ciudad[ciudad] = by_ciudad.get(ciudad, 0) + 1

        vert = lead.get("Vertical", "sin_vertical")
        if vert:
            by_vertical[vert] = by_vertical.get(vert, 0) + 1

        score = lead.get("Score", 0)
        by_score[score] = by_score.get(score, 0) + 1

    # Recent leads (last 7 days)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent = sum(1 for l in leads if l.get("FechaIngreso", "") >= week_ago)

    return {
        "total": total,
        "recientes_7d": recent,
        "por_estado": dict(sorted(by_estado.items(), key=lambda x: x[1], reverse=True)),
        "por_ciudad": dict(sorted(by_ciudad.items(), key=lambda x: x[1], reverse=True)[:10]),
        "por_vertical": dict(sorted(by_vertical.items(), key=lambda x: x[1], reverse=True)),
        "por_score": dict(sorted(by_score.items(), key=lambda x: x[0], reverse=True)),
    }


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_lead_short(lead: Dict, index: int = 0) -> str:
    """Format a single lead for display (compact)."""
    stars = "⭐" * lead.get("Score", 0)
    lines = [f"{index}. **{lead.get('NombreComercial', lead.get('PK', '???'))}** {stars}"]

    if lead.get("Ciudad"):
        lines.append(f"   📍 {lead['Ciudad']}")
    if lead.get("ContactoPrincipal"):
        lines.append(f"   👤 {lead['ContactoPrincipal']}")
    if lead.get("Telefono"):
        lines.append(f"   📞 {lead['Telefono']}")
    if lead.get("WhatsApp"):
        wa_num = lead['WhatsApp'].replace('+', '')
        lines.append(f"   💬 wa.me/{wa_num}")
    if lead.get("Email"):
        lines.append(f"   📧 {lead['Email']}")
    if lead.get("Servicios"):
        services = lead['Servicios'][:80]
        lines.append(f"   🔧 {services}")
    if lead.get("Website"):
        lines.append(f"   🌐 {lead['Website']}")
    if lead.get("Estado"):
        lines.append(f"   📋 Estado: {lead['Estado']}")
    if lead.get("Vertical"):
        lines.append(f"   🏷️ Vertical: {lead['Vertical']}")

    return "\n".join(lines)


def format_stats(stats: Dict) -> str:
    """Format stats for display."""
    if stats.get("total", 0) == 0:
        return "📊 CRM vacío — no hay leads registradas."

    lines = [
        f"📊 **Estadísticas del CRM**",
        f"",
        f"Total leads: **{stats['total']}**",
        f"Nuevas (últimos 7 días): **{stats['recientes_7d']}**",
        f"",
        f"**Por estado:**",
    ]
    for estado, count in stats["por_estado"].items():
        lines.append(f"  • {estado}: {count}")

    lines.append(f"\n**Por ciudad (top 10):**")
    for ciudad, count in stats["por_ciudad"].items():
        lines.append(f"  • {ciudad}: {count}")

    lines.append(f"\n**Por vertical:**")
    for vert, count in stats["por_vertical"].items():
        lines.append(f"  • {vert}: {count}")

    lines.append(f"\n**Por score:**")
    for score, count in stats["por_score"].items():
        lines.append(f"  • {'⭐' * int(score)} ({score}): {count}")

    return "\n".join(lines)


def format_leads_list(leads: List[Dict], limit: int = 10) -> str:
    """Format a list of leads for display."""
    if not leads:
        return "No se encontraron leads con esos criterios."

    total = len(leads)
    display = leads[:limit]

    lines = [f"🎯 **{total} leads encontradas** (mostrando {len(display)}):\n"]
    for i, lead in enumerate(display, 1):
        lines.append(format_lead_short(lead, i))
        lines.append("")

    if total > limit:
        lines.append(f"\n... y {total - limit} más. Usa --top {total} para ver todas.")

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Load .env
    env_file = os.path.join(HERMES_HOME, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value and key not in os.environ:
                            os.environ[key] = value
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Consulta leads del CRM (DynamoDB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s --stats                          # Estadísticas generales
  %(prog)s --ciudad Bogota                  # Leads en Bogotá
  %(prog)s --min-score 4                    # Leads score 4+
  %(prog)s --estado nuevo --top 5           # Top 5 leads nuevas
  %(prog)s --vertical fumigacion --ciudad Medellin
  %(prog)s --buscar "restaurante"           # Búsqueda en texto
  %(prog)s --recientes 7                    # Leads de los últimos 7 días
        """
    )
    parser.add_argument("--ciudad", "-c", help="Filtrar por ciudad (búsqueda parcial)")
    parser.add_argument("--min-score", "-s", type=int, help="Score mínimo (1-5)")
    parser.add_argument("--estado", "-e", help="Filtrar por estado (nuevo/contactada/demo/trial/cerrada/descartada)")
    parser.add_argument("--vertical", "-v", help="Filtrar por vertical (fumigacion/hvac/electrico)")
    parser.add_argument("--buscar", "-b", help="Búsqueda de texto libre en nombre, servicios, contacto, ciudad")
    parser.add_argument("--stats", action="store_true", help="Mostrar estadísticas del CRM")
    parser.add_argument("--recientes", "-r", type=int, metavar="DIAS", help="Leads de los últimos N días")
    parser.add_argument("--top", "-t", type=int, default=10, help="Cantidad de resultados a mostrar (default: 10)")
    parser.add_argument("--json", action="store_true", help="Output en formato JSON (para integración)")

    args = parser.parse_args()

    # Stats mode
    if args.stats:
        stats = get_stats()
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            print(format_stats(stats))
        return 0

    # Query mode
    leads = query_by_filters(
        ciudad=args.ciudad,
        min_score=args.min_score,
        estado=args.estado,
        vertical=args.vertical,
        buscar=args.buscar,
    )

    # Filter by recency if requested
    if args.recientes:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.recientes)).isoformat()
        leads = [l for l in leads if l.get("FechaIngreso", "") >= cutoff]

    # Output
    if args.json:
        output = {
            "total": len(leads),
            "leads": leads[:args.top],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(format_leads_list(leads, limit=args.top))

    return 0


if __name__ == "__main__":
    sys.exit(main())
