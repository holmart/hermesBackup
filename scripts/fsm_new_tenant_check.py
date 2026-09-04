#!/usr/bin/env python3
"""
FSM New Tenant Detector
Scans fsm-tenants-prod for tenants created in the last 60 minutes.
Reports new tenants not previously notified.
Uses AWS CLI (subprocess) — no boto3 dependency needed.
"""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

STATE_FILE = os.path.expanduser("~/.hermes/cron/fsm_tenants_notified.json")
TABLE_NAME = "fsm-tenants-prod"
REGION = "us-east-1"
CHECK_WINDOW_MINUTES = 60


def load_notified():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("notified_ids", []))
    return set()


def save_notified(ids):
    with open(STATE_FILE, "w") as f:
        json.dump({"notified_ids": sorted(ids), "last_check": datetime.now(timezone.utc).isoformat()}, f, indent=2)


def scan_recent_tenants():
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CHECK_WINDOW_MINUTES)).isoformat()

    cmd = [
        "aws", "dynamodb", "scan",
        "--table-name", TABLE_NAME,
        "--region", REGION,
        "--filter-expression", "begins_with(PK, :pk) AND SK = :sk AND createdAt > :cutoff",
        "--expression-attribute-values", json.dumps({
            ":pk": {"S": "TENANT#"},
            ":sk": {"S": "CONFIG"},
            ":cutoff": {"S": cutoff},
        }),
        "--output", "json"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"❌ Error al consultar DynamoDB: {result.stderr.strip()}")
        return []

    data = json.loads(result.stdout)
    return data.get("Items", [])


def format_tenant(item):
    name = item.get("name", {}).get("S", "(sin nombre)")
    email = item.get("email", {}).get("S", "(sin email)")
    phone = item.get("phone", {}).get("S", "")
    vertical = item.get("vertical", {}).get("S", "(sin vertical)")
    plan = item.get("plan", {}).get("S", "trial")
    service_mode = item.get("serviceMode", {}).get("S", "field")
    created = item.get("createdAt", {}).get("S", "")
    tenant_id = item.get("tenantId", {}).get("S", "")
    country = item.get("country", {}).get("S", "")
    utm = item.get("registrationUtm", {}).get("M", {})
    utm_source = utm.get("utm_source", {}).get("S", "")
    utm_medium = utm.get("utm_medium", {}).get("S", "")

    mode_label = "Campo" if service_mode == "field" else "Local (In-House)"
    utm_str = f"{utm_source}/{utm_medium}" if utm_source else "directo"
    phone_str = phone if phone else "(no registrado)"

    lines = [
        "🆕 **Nuevo Tenant Registrado**",
        "",
        f"📋 **Empresa:** {name or '(pendiente onboarding)'}",
        f"📧 **Email:** {email}",
        f"📱 **Teléfono:** {phone_str}",
        f"🏢 **Vertical:** {vertical or '(pendiente)'}",
        f"🔧 **Modo:** {mode_label}",
        f"💳 **Plan:** {plan}",
        f"🌍 **País:** {country}",
        f"📈 **Fuente:** {utm_str}",
        f"🕐 **Registrado:** {created[:19].replace('T', ' ')} UTC",
        f"🆔 `{tenant_id}`",
    ]
    return "\n".join(lines)


def main():
    notified = load_notified()
    recent = scan_recent_tenants()

    new_tenants = []
    for item in recent:
        tid = item.get("tenantId", {}).get("S", "")
        if tid and tid not in notified:
            new_tenants.append(item)
            notified.add(tid)

    if not new_tenants:
        # Silent — no output means no delivery in no-agent mode
        save_notified(notified)
        return

    output_parts = [f"🎉 **{len(new_tenants)} nuevo(s) tenant(s) detectado(s):**\n"]
    for t in new_tenants:
        output_parts.append(format_tenant(t))
        output_parts.append("---")

    print("\n".join(output_parts))
    save_notified(notified)


if __name__ == "__main__":
    main()
