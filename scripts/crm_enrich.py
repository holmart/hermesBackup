#!/usr/bin/env python3
"""
CRM Enrichment — unified (internal + external)
==============================================
Single entry point that replaces internal_enrich.py (v3) and external_enrich.py.
One DynamoDB scan, shared validators, one write per lead, one Score recalc.

Modes (--mode / CRM_ENRICH_MODE):
  internal  — reshuffle data already in DynamoDB (fast, free, daily):
              RepresentanteLegal / Telefono / Email from internal fields.
  external  — go OUT to sources to fill high-value gaps (slower, weekly):
              (1) website revisit  -> RepresentanteLegal, Direccion, Instagram, WhatsApp
              (2) RUES datos.gov.co-> NIT, RazonSocial, RepresentanteLegal, FechaConstitucion
              (3) Google Places    -> Direccion, Website
  all       — run internal then external in a single pass over each lead.

Measured gap on 1000 real leads that motivates the external mode:
  Telefono 99% Email 87% Website 89%  ->  internal is near its ceiling
  RepresentanteLegal 12% NIT 11% RazonSocial 0% Direccion 16% Instagram 14%

Safe by design: DRY_RUN, per-source budgets, never overwrites a valid field,
Score recalculated once, Telegram summary. Score is written as a Number.

Suggested crons:
  internal: 0 4 * * *      (daily 4am UTC)   -> CRM_ENRICH_MODE=internal
  external: 0 6 * * 2,5    (Tue/Fri 6am UTC) -> CRM_ENRICH_MODE=external RUES_ENABLED=true
"""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# =============================================================================
# CONFIGURATION
# =============================================================================

TABLE_NAME = os.environ.get("CRM_TABLE", "sifagent-crm-clients")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
HERMES_HOME = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"

MODE = os.environ.get("CRM_ENRICH_MODE", "internal")  # overridden by --mode

MAX_LEADS_PER_RUN = int(os.environ.get("ENRICH_MAX_LEADS", "100"))
SKIP_IF_ENRICHED_WITHIN_DAYS = int(os.environ.get("ENRICH_SKIP_DAYS", "7"))
MAX_WORKERS = int(os.environ.get("ENRICH_WORKERS", "5"))

# LLM (internal name fallback)
LLM_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")

# External source 1: website revisit (free) — on by default in external/all.
WEB_REVISIT_ENABLED = os.environ.get("WEB_REVISIT_ENABLED", "true").lower() == "true"
MAX_WEB_REVISITS = int(os.environ.get("MAX_WEB_REVISITS", "80"))

# External source 2: RUES datos.gov.co (free, opt-in).
RUES_ENABLED = os.environ.get("RUES_ENABLED", "false").lower() == "true"
MAX_RUES_LOOKUPS = int(os.environ.get("MAX_RUES_LOOKUPS", "40"))
RUES_DATASET_ID = os.environ.get("RUES_DATASET_ID", "c82u-588k")
RUES_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN", "")

# External source 3: Google Places Details (paid, opt-in).
PLACES_ENABLED = os.environ.get("PLACES_ENABLED", "false").lower() == "true"
MAX_PLACES_LOOKUPS = int(os.environ.get("MAX_PLACES_LOOKUPS", "40"))
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")

# Legacy NIT scrape (informacolombia) — kept from v3, opt-in, capped.
NIT_LOOKUP_ENABLED = os.environ.get("NIT_LOOKUP_ENABLED", "false").lower() == "true"
MAX_NIT_LOOKUPS = int(os.environ.get("MAX_NIT_LOOKUPS", "20"))

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_dynamo_client = None


def get_dynamo():
    global _dynamo_client
    if _dynamo_client is None:
        import boto3
        _dynamo_client = boto3.client("dynamodb", region_name=REGION)
    return _dynamo_client


def want_internal() -> bool:
    return MODE in ("internal", "all")


def want_external() -> bool:
    return MODE in ("external", "all")


# =============================================================================
# SHARED VALIDATORS
# =============================================================================

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


CARGO_STOPWORDS = {
    "gerencia", "gerente", "dirección", "director", "presidente",
    "encargado", "jefe", "supervisor", "coordinador", "administrador",
    "administrativo", "asistente", "secretario", "tesorero", "vocero",
    "representante", "contacto", "servicio", "comercial", "ventas",
    "control", "operaciones", "producción", "calidad", "logística",
    "recursos", "talento", "humano", "finanzas", "contabilidad",
    "auditoría", "legal", "jurídico", "marketing", "publicidad",
    "soporte", "tecnico", "técnico", "ingeniero", "ingeniería",
    "secretaria", "directora", "coordinadora", "auxiliar",
    "recepcionista", "administrativa", "gerenta", "asesora", "asesor",
    "presidencia", "mercadeo", "recepcion", "recepción",
}

FORBIDDEN_NAME_TOKENS = {
    "lavado", "desinfeccion", "tanques", "agua", "potable", "control", "plagas",
    "servicio", "mantenimiento", "limpieza", "fumigacion", "electricidad",
    "fontaneria", "hidraulica", "construccion", "reparaciones",
    "instalaciones", "montaje", "cableado", "fumigaciones",
    "bogota", "medellin", "cali", "barranquilla", "cartagena", "colombia",
    "soluciones", "servicios", "grupo", "empresa", "asociados",
    "ink", "market", "marketing", "insumos", "insumo", "comercializadora",
    "distribuidora", "distribuciones", "importaciones", "exportaciones",
    "inversiones", "sas", "ltda", "eu", "sa", "cia", "compania", "corp",
    "corporacion", "industrias", "industrial", "tecno", "tecnologia",
    "medica", "medicas", "medico", "suministros", "provee", "proveedor",
    "dir", "gte", "adm", "gcia",
}

FORBIDDEN_NAME_SUBSTRINGS = (
    "market", "insumo", "comercial", "distribu", "importa", "exporta",
    "inversion", "industri", "tecnolog", "suministr", "proveedor",
    "solucion", "servicio",
)


def looks_like_person_name(val: str) -> bool:
    if not val or len(val.strip()) < 5:
        return False
    tokens = val.strip().split()
    if not (2 <= len(tokens) <= 4):
        return False
    for tok in tokens:
        core = tok.rstrip(".")
        if not core or core[0].isdigit():
            return False
        norm = strip_accents(core.lower())
        if norm in FORBIDDEN_NAME_TOKENS or norm in CARGO_STOPWORDS:
            return False
        if any(sub in norm for sub in FORBIDDEN_NAME_SUBSTRINGS):
            return False
        cleaned = re.sub(r"[.\-']", "", core)
        if cleaned and not cleaned.isalpha():
            return False
    return True


def _norm_for_compare(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_accents((s or "").lower()))


def name_matches_company(name: str, company: str) -> bool:
    n = _norm_for_compare(name)
    c = _norm_for_compare(company)
    if not n or not c:
        return False
    return n == c or n in c or c in n


def is_empty_or_generic(val: Optional[str]) -> bool:
    if val is None:
        return True
    val = str(val).strip()
    if not val or val.upper() in ("PENDIENTE", "N/A", "NULL", "0", "NONE", ""):
        return True
    generic = {
        "contacto", "gerencia", "servicio al cliente", "comercial", "ventas",
        "representante legal", "por determinar", "administracion", "encargado",
        "supervisor", "jefe", "director",
    }
    return val.lower() in generic


def is_valid_email(val: str) -> bool:
    if not val or not isinstance(val, str):
        return False
    if not re.match(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$", val.strip()):
        return False
    domain = val.split("@")[1].lower()
    placeholders = {"empresa.com", "example.com", "test.com", "correo.com",
                    "mail.com", "domain.com", "tu-dominio.com"}
    return domain not in placeholders


def normalize_colombian_phone(raw: str) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    digits = re.sub(r"\D", "", raw.strip())
    if digits.startswith("57") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("3"):
        return None if len(set(digits)) <= 2 else f"+57{digits}"
    if len(digits) == 10 and digits.startswith("60"):
        return None if len(set(digits)) <= 2 else f"+57{digits}"
    # 7-digit landline without area code: cannot infer the city indicativo.
    return None


def clean_nit(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    return digits if 6 <= len(digits) <= 12 else None


def extract_name_from_email(email: str) -> Optional[str]:
    if not email or "@" not in email:
        return None
    local = re.sub(r"[._\-]", " ", email.split("@")[0])
    parts = [p for p in local.split() if p and len(p) >= 3]
    if len(parts) < 2:
        return None
    email_stopwords = {
        "info", "contacto", "admin", "ventas", "comercial", "gerencia",
        "soporte", "servicio", "empresa", "cliente", "clientes",
        "factura", "facturas", "contabilidad", "compras", "pedidos",
        "operaciones", "logistica", "calidad", "produccion",
        "rrhh", "talento", "humano", "legal", "juridico",
        "fumigaciones", "fumigacion", "fumiservi", "fumigar", "fumi",
        "extermi", "extermina", "plagas", "pest", "control",
        "lavado", "tanques", "desinfeccion", "saneamiento",
        "bogota", "medellin", "cali", "colombia", "tnbogota",
        "servicioalcliente", "atencion", "recepcion", "direccion",
        "notificaciones", "alertas", "noreply", "comunicaciones",
        "dir", "gte", "gcia", "adm", "coord", "jefe", "aux", "asist",
        "cxc", "cxp", "tesoreria", "cartera", "cobranza", "sst",
        "secretaria", "secretario", "asistente", "auxiliar", "recepcionista",
        "administracion", "administrativa", "administrativo", "gerente",
        "director", "directora", "coordinacion", "coordinador", "coordinadora",
        "presidencia", "presidente", "asesor", "asesora", "mercadeo",
        "sistemas", "almacen", "despachos", "facturacion",
    }
    if any(p.lower() in email_stopwords for p in parts):
        return None
    if any(any(sub in strip_accents(p.lower()) for sub in FORBIDDEN_NAME_SUBSTRINGS)
           for p in parts):
        return None
    service_patterns = re.compile(
        r"(fumi|pest|plaga|clean|sanit|hidro|electro|bomb|tanq|ambient|"
        r"servi|multi|ingeni|tecni|grupo|corp|sas$|ltda$|col$)", re.IGNORECASE)
    if any(service_patterns.search(p) for p in parts):
        return None
    candidate = " ".join(p.capitalize() for p in parts)
    return candidate if looks_like_person_name(candidate) else None


def extract_name_with_llm(responsable: str, cargo: str, company: str) -> Optional[str]:
    if not LLM_API_KEY:
        return None
    prompt = (f"De los siguientes datos de una empresa, extrae SOLO el nombre de la "
              f"persona (nombre y apellido). Si no hay un nombre de persona claro, "
              f'responde exactamente "NONE".\n\nEmpresa: {company}\n'
              f"Campo Responsable: {responsable}\nCampo Cargo: {cargo}\n\n"
              f'Responde SOLO con el nombre o "NONE":')
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50, "temperature": 0.1,
    }).encode()
    try:
        req = urllib.request.Request(
            f"{LLM_API_BASE}/chat/completions", data=payload,
            headers={"Authorization": f"Bearer {LLM_API_KEY}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            answer = json.loads(resp.read())["choices"][0]["message"]["content"].strip()
        if answer.upper() == "NONE" or len(answer) < 4:
            return None
        return answer if looks_like_person_name(answer) else None
    except Exception:
        return None


# =============================================================================
# PIPELINE HELPER IMPORT (for website revisit)
# =============================================================================

_pipe = None


def _load_pipeline_helpers():
    global _pipe
    if _pipe is not None:
        return _pipe
    candidate_dirs = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(HERMES_HOME, "skills", "sif-agent-prospecting", "scripts"),
        os.path.join(HERMES_HOME, "skills", "sales", "sif-agent-prospecting", "scripts"),
    ]
    for d in candidate_dirs:
        if d and os.path.isfile(os.path.join(d, "unified_lead_pipeline.py")):
            if d not in sys.path:
                sys.path.insert(0, d)
            break
    try:
        import unified_lead_pipeline as _p
        _pipe = _p
    except Exception as e:
        print(f"  WARN: could not import unified_lead_pipeline ({e}); "
              f"website revisit limited (no person-name / schema extraction)")
        _pipe = False
    return _pipe


def _fetch_url(url: str, timeout: int = 12) -> Optional[str]:
    p = _load_pipeline_helpers()
    if p:
        try:
            return p.fetch_url(url, max_attempts=2, timeout=timeout)
        except Exception:
            pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


# =============================================================================
# DYNAMO HELPERS
# =============================================================================

def get_attr(item: Dict, key: str) -> Optional[str]:
    d = item.get(key, {})
    if isinstance(d, dict):
        return d.get("S") or d.get("N")
    return None


def _iso_key(ts: str) -> str:
    if not ts:
        return ""
    t = ts.strip()
    if t.endswith("Z"):
        t = t[:-1]
    if t.endswith("+00:00"):
        t = t[:-6]
    return t


def needs_enrichment(item: Dict, cutoff: str) -> bool:
    """Candidate check that respects the active mode."""
    if want_internal():
        rep = get_attr(item, "RepresentanteLegal")
        tel = get_attr(item, "Telefono")
        email = get_attr(item, "Email")
        if is_empty_or_generic(rep) or not looks_like_person_name(rep or ""):
            return True
        if tel and not tel.startswith("+57"):
            return True
        if is_empty_or_generic(email) and get_attr(item, "EmailExtra"):
            return True
        if (NIT_LOOKUP_ENABLED and is_empty_or_generic(get_attr(item, "NIT"))
                and get_attr(item, "NombreComercial")):
            return True

    if want_external():
        last = get_attr(item, "UltimoEnrichExterno")
        if not (last and _iso_key(last) > _iso_key(cutoff)):
            for f in ("RepresentanteLegal", "NIT", "RazonSocial", "Direccion", "Instagram"):
                if is_empty_or_generic(get_attr(item, f)):
                    return True

    return False


def scan_candidates() -> List[Dict]:
    client = get_dynamo()
    items: List[Dict] = []
    start_key = None
    page = 0
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=SKIP_IF_ENRICHED_WITHIN_DAYS)).isoformat()
    proj = ("PK, SK, NombreComercial, RazonSocial, RepresentanteLegal, Responsable, "
            "CargoResponsable, NIT, Direccion, Instagram, WhatsApp, Telefono, "
            "TelefonosExtra, Email, EmailExtra, Website, Dominio, Ciudad, Servicios, "
            "TamanoEmpresa, FechaConstitucion, Score, UltimoEnrichExterno, FechaActualizacion")
    while True:
        params = {"TableName": TABLE_NAME, "ProjectionExpression": proj}
        if start_key:
            params["ExclusiveStartKey"] = start_key
        resp = client.scan(**params)
        for it in resp.get("Items", []):
            if needs_enrichment(it, cutoff):
                items.append(it)
        page += 1
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break
    print(f"  Scanned {page} page(s); {len(items)} candidates for mode '{MODE}'")
    if len(items) > MAX_LEADS_PER_RUN:
        print(f"  Capping to ENRICH_MAX_LEADS={MAX_LEADS_PER_RUN}")
        items = items[:MAX_LEADS_PER_RUN]
    return items


# =============================================================================
# BUDGETS (thread-safe)
# =============================================================================

_budget_lock = threading.Lock()
_budget_used = {"web": 0, "rues": 0, "places": 0, "nit": 0}


def _take_budget(source: str, cap: int) -> bool:
    with _budget_lock:
        if _budget_used[source] >= cap:
            return False
        _budget_used[source] += 1
        return True


# =============================================================================
# INTERNAL ENRICHMENT
# =============================================================================

def enrich_internal(item: Dict, company: str) -> Dict[str, str]:
    changes: Dict[str, str] = {}
    rep = get_attr(item, "RepresentanteLegal")
    resp = get_attr(item, "Responsable")
    cargo = get_attr(item, "CargoResponsable")
    tel = get_attr(item, "Telefono")
    tel_extra = get_attr(item, "TelefonosExtra")
    email = get_attr(item, "Email")
    email_extra = get_attr(item, "EmailExtra")

    # RepresentanteLegal
    if is_empty_or_generic(rep) or not looks_like_person_name(rep or ""):
        candidate = None
        if not is_empty_or_generic(resp) and looks_like_person_name(resp):
            candidate = resp.strip()
        else:
            candidate = (extract_name_from_email(email)
                         or extract_name_from_email(email_extra))
            if not candidate and resp and not is_empty_or_generic(resp) and LLM_API_KEY:
                candidate = extract_name_with_llm(resp, cargo or "", company)
        if candidate and not name_matches_company(candidate, company):
            changes["RepresentanteLegal"] = candidate

    # Phone normalization
    if tel:
        norm = normalize_colombian_phone(tel)
        if norm and norm != tel.strip():
            changes["Telefono"] = norm
        elif not norm and tel_extra:
            for cand in re.split(r"[,;|\s/]+", tel_extra):
                n = normalize_colombian_phone(cand.strip())
                if n:
                    changes["Telefono"] = n
                    break
    elif tel_extra:
        for cand in re.split(r"[,;|\s/]+", tel_extra):
            n = normalize_colombian_phone(cand.strip())
            if n:
                changes["Telefono"] = n
                break

    # Email promotion
    if not is_valid_email(email or "") and is_valid_email(email_extra or ""):
        changes["Email"] = email_extra.strip().lower()

    # Legacy NIT scrape (opt-in)
    if (NIT_LOOKUP_ENABLED and is_empty_or_generic(get_attr(item, "NIT"))
            and company and len(company) > 4 and _take_budget("nit", MAX_NIT_LOOKUPS)):
        time.sleep(random.uniform(0.5, 1.5))
        nit_data = _lookup_nit_informacolombia(company)
        if nit_data:
            if "NIT" in nit_data:
                changes["NIT"] = nit_data["NIT"]
            if ("RazonSocial" in nit_data
                    and is_empty_or_generic(get_attr(item, "RazonSocial"))):
                changes["RazonSocial"] = nit_data["RazonSocial"]

    return changes


def _lookup_nit_informacolombia(company_name: str) -> Optional[Dict[str, str]]:
    clean = re.sub(r"\b(s\.?a\.?s\.?|ltda\.?|s\.?a\.?|e\.?u\.?)\b", "",
                   company_name, flags=re.IGNORECASE)
    clean = re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ\s]", "", clean).strip()
    if len(clean) < 4:
        return None
    url = ("https://www.informacolombia.com/directorio-empresas/buscar?q="
           + clean.replace(" ", "+"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    # Only accept NIT in explicit context (avoid capturing random numbers).
    nit_match = re.search(r"NIT[:\s]*(\d{3}\.?\d{3}\.?\d{3}[\-\s]?\d?)", html)
    if not nit_match:
        return None
    result = {"NIT": re.sub(r"[.\-\s]", "", nit_match.group(1))}
    razon = re.search(r'<h[12][^>]*>([^<]+)</h[12]>', html[:3000])
    if razon:
        r = razon.group(1).strip()
        if len(r) > 5 and r.upper() != "INFORMACOLOMBIA":
            result["RazonSocial"] = r
    return result


# =============================================================================
# EXTERNAL ENRICHMENT — source 1: website revisit
# =============================================================================

def enrich_from_website(item: Dict, company: str) -> Dict[str, str]:
    changes: Dict[str, str] = {}
    if not WEB_REVISIT_ENABLED:
        return changes
    website = get_attr(item, "Website") or ""
    dominio = get_attr(item, "Dominio") or ""
    url = website or (f"https://{dominio}" if dominio else "")
    if not url:
        return changes
    if not _take_budget("web", MAX_WEB_REVISITS):
        return changes
    if not url.startswith("http"):
        url = "https://" + url

    html = _fetch_url(url, timeout=12)
    if not html or len(html) < 200:
        return changes
    all_html = html
    try:
        base = f"{urllib.parse.urlparse(url).scheme}://{urllib.parse.urlparse(url).netloc}"
        for sub in ("/contacto", "/contactanos", "/nosotros", "/quienes-somos"):
            sub_html = _fetch_url(urllib.parse.urljoin(base, sub), timeout=8)
            if sub_html and len(sub_html) > 200:
                all_html += "\n" + sub_html
            time.sleep(random.uniform(0.3, 0.8))
    except Exception:
        pass

    p = _load_pipeline_helpers()

    if is_empty_or_generic(get_attr(item, "RepresentanteLegal")) and p:
        try:
            person = p.extract_person_name(all_html)
        except Exception:
            person = None
        if (person and looks_like_person_name(person)
                and not name_matches_company(person, company)):
            changes["RepresentanteLegal"] = person

    structured = {}
    if p:
        try:
            structured = p.extract_structured_data(all_html) or {}
        except Exception:
            structured = {}

    if is_empty_or_generic(get_attr(item, "Instagram")):
        insta = structured.get("instagram") or _find_instagram(all_html)
        if insta:
            changes["Instagram"] = insta[:200]

    if is_empty_or_generic(get_attr(item, "Direccion")):
        addr = _find_address(all_html)
        if addr:
            changes["Direccion"] = addr[:200]

    if is_empty_or_generic(get_attr(item, "WhatsApp")) and p:
        try:
            wa = p.extract_whatsapp(all_html)
        except Exception:
            wa = None
        if wa:
            changes["WhatsApp"] = wa

    return changes


def _find_instagram(html: str) -> Optional[str]:
    m = re.search(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{2,40})", html)
    if m:
        handle = m.group(1)
        if handle.lower() not in ("p", "explore", "accounts", "reel", "reels"):
            return f"https://instagram.com/{handle}"
    return None


def _find_address(html: str) -> Optional[str]:
    pat = re.compile(
        r"((?:calle|carrera|cra\.?|kra\.?|cll\.?|av(?:enida)?\.?|diagonal|dg\.?|"
        r"transversal|tv\.?|autopista)\s*\d{1,3}[a-zA-Z]?\s*"
        r"(?:#|no\.?|nro\.?|n°)?\s*\d{1,3}[a-zA-Z]?\s*[-–]\s*\d{1,3})",
        re.IGNORECASE)
    m = pat.search(html)
    if m:
        addr = re.sub(r"\s+", " ", m.group(1)).strip()
        if 8 <= len(addr) <= 120:
            return addr
    return None


# =============================================================================
# EXTERNAL ENRICHMENT — source 2: RUES datos.gov.co
# =============================================================================

def enrich_from_rues(item: Dict, company: str, city: str) -> Dict[str, str]:
    changes: Dict[str, str] = {}
    if not RUES_ENABLED or not company or len(company) < 4:
        return changes
    if not _take_budget("rues", MAX_RUES_LOOKUPS):
        return changes
    row = _rues_query(company, city)
    if not row:
        return changes

    def pick(*keys):
        for k in keys:
            for rk, rv in row.items():
                if rk.lower() == k and rv and str(rv).strip():
                    return str(rv).strip()
        return None

    if is_empty_or_generic(get_attr(item, "NIT")):
        nit = clean_nit(pick("nit", "numero_identificacion", "identificacion"))
        if nit:
            changes["NIT"] = nit
    if is_empty_or_generic(get_attr(item, "RazonSocial")):
        razon = pick("razon_social", "razonsocial", "nombre", "nombre_empresa")
        if razon and len(razon) > 4:
            changes["RazonSocial"] = razon[:200]
    if is_empty_or_generic(get_attr(item, "RepresentanteLegal")):
        rep = pick("representante_legal", "representantelegal",
                   "nombre_representante_legal")
        if rep and looks_like_person_name(rep) and not name_matches_company(rep, company):
            changes["RepresentanteLegal"] = rep[:120]
    if is_empty_or_generic(get_attr(item, "FechaConstitucion")):
        fecha = pick("fecha_matricula", "fecha_constitucion", "fecha_registro")
        if fecha:
            changes["FechaConstitucion"] = fecha[:32]
    if is_empty_or_generic(get_attr(item, "Direccion")):
        dire = pick("direccion", "direccion_comercial", "domicilio")
        if dire and 8 <= len(dire) <= 120:
            changes["Direccion"] = dire.strip()[:120]
    return changes


def _rues_query(company: str, city: str) -> Optional[Dict]:
    clean = re.sub(r"\b(s\.?a\.?s\.?|ltda\.?|s\.?a\.?|e\.?u\.?)\b", "",
                   company, flags=re.IGNORECASE).strip()
    if len(clean) < 4:
        return None
    url = (f"https://www.datos.gov.co/resource/{RUES_DATASET_ID}.json?"
           + urllib.parse.urlencode({"$q": clean, "$limit": "5"}))
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if RUES_APP_TOKEN:
        headers["X-App-Token"] = RUES_APP_TOKEN
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            rows = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    target = _norm_for_compare(company)
    for r in rows:
        if not isinstance(r, dict):
            continue
        name_val = ""
        for k, v in r.items():
            if "razon" in k.lower() or k.lower() in ("nombre", "nombre_empresa"):
                name_val = str(v)
                break
        rn = _norm_for_compare(name_val)
        if rn and (rn in target or target in rn):
            return r
    return rows[0]


# =============================================================================
# EXTERNAL ENRICHMENT — source 3: Google Places
# =============================================================================

def enrich_from_places(item: Dict, company: str, city: str) -> Dict[str, str]:
    changes: Dict[str, str] = {}
    if not PLACES_ENABLED or not GOOGLE_PLACES_API_KEY or not company:
        return changes
    if not _take_budget("places", MAX_PLACES_LOOKUPS):
        return changes
    place = _places_search(company, city)
    if not place:
        return changes
    if is_empty_or_generic(get_attr(item, "Direccion")):
        addr = place.get("formattedAddress", "")
        if addr and 8 <= len(addr) <= 200:
            changes["Direccion"] = addr
    if is_empty_or_generic(get_attr(item, "Website")):
        web = place.get("websiteUri", "")
        if web:
            changes["Website"] = web[:300]
    return changes


def _places_search(company: str, city: str) -> Optional[Dict]:
    query = f"{company} {city} Colombia".strip()
    payload = json.dumps({"textQuery": query, "languageCode": "es",
                          "regionCode": "CO", "maxResultCount": 1}).encode()
    try:
        req = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchText", data=payload,
            headers={"Content-Type": "application/json",
                     "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                     "X-Goog-FieldMask": ("places.displayName,places.websiteUri,"
                                          "places.formattedAddress,places.rating")},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    places = data.get("places", [])
    return places[0] if places else None


# =============================================================================
# SCORE
# =============================================================================

def calculate_score(item: Dict, changes: Dict[str, str]) -> int:
    def has(field):
        val = changes.get(field) or get_attr(item, field)
        return bool(val and str(val).strip()
                    and str(val).strip() not in ("None", "null", "N/A"))
    score = 0
    if has("Telefono"):
        score += 1
    if has("Email"):
        score += 1
    if has("Website") or has("Dominio"):
        score += 1
    if has("NIT"):
        score += 1
    for f in ("Ciudad", "Servicios", "WhatsApp", "NombreComercial",
              "RepresentanteLegal", "TamanoEmpresa"):
        if has(f):
            score += 0.5
    return min(int(score) + 1, 5)


# =============================================================================
# WRITE
# =============================================================================

def update_item(pk: str, sk: str, changes: Dict[str, str], sources: List[str]) -> bool:
    if not changes:
        return False
    if DRY_RUN:
        preview = ", ".join(f"{k}={str(v)[:28]}" for k, v in changes.items()
                            if k not in ("FechaActualizacion", "UltimoEnrichExterno",
                                         "FuenteEnriquecimiento"))
        print(f"    [DRY RUN] {pk[:30]} <- {preview}  (src: {'+'.join(sources)})")
        return True

    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    changes = dict(changes)
    changes["FechaActualizacion"] = now
    if any(s in ("web", "rues", "places") for s in sources):
        changes["UltimoEnrichExterno"] = now
    changes["FuenteEnriquecimiento"] = "+".join(sources) or "internal"

    set_clauses, expr_names, expr_vals = [], {}, {}
    for i, (field, new_val) in enumerate(changes.items()):
        an, vp = f"#f{i}", f":v{i}"
        set_clauses.append(f"{an} = {vp}")
        expr_names[an] = field
        expr_vals[vp] = {"N": str(new_val)} if field == "Score" else {"S": str(new_val)}

    client = get_dynamo()
    for attempt in range(1, 4):
        try:
            client.update_item(
                TableName=TABLE_NAME,
                Key={"PK": {"S": pk}, "SK": {"S": sk}},
                UpdateExpression="SET " + ", ".join(set_clauses),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_vals)
            return True
        except client.exceptions.ProvisionedThroughputExceededException:
            time.sleep(2 ** attempt + random.uniform(0, 1))
        except Exception as e:
            if attempt < 3:
                time.sleep(1)
                continue
            print(f"    ERROR updating {pk[:30]}: {e}")
            return False
    return False


# =============================================================================
# PROCESS ONE LEAD
# =============================================================================

def process_lead(item: Dict) -> Tuple[str, str, Dict[str, str], List[str]]:
    pk = get_attr(item, "PK") or ""
    sk = get_attr(item, "SK") or ""
    company = get_attr(item, "NombreComercial") or get_attr(item, "RazonSocial") or pk
    city = get_attr(item, "Ciudad") or ""
    changes: Dict[str, str] = {}
    sources: List[str] = []

    if want_internal():
        internal_changes = enrich_internal(item, company)
        if internal_changes:
            changes.update(internal_changes)
            sources.append("internal")

    if want_external():
        for fn, tag in ((enrich_from_website, "web"),
                        (enrich_from_rues, "rues"),
                        (enrich_from_places, "places")):
            if tag == "web":
                new = fn(item, company)
            else:
                new = fn(item, company, city)
            added = False
            for k, v in new.items():
                if k not in changes:  # never overwrite an earlier fill
                    changes[k] = v
                    added = True
            if added:
                sources.append(tag)

    if changes:
        new_score = calculate_score(item, changes)
        try:
            current = int(float(get_attr(item, "Score") or "0"))
        except (ValueError, TypeError):
            current = 0
        if new_score > current:
            changes["Score"] = str(new_score)

    return pk, sk, changes, sources


# =============================================================================
# TELEGRAM
# =============================================================================

def send_telegram_summary(candidates: int, updated: int, by_field: Dict[str, int],
                          by_source: Dict[str, int], examples: List[str]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = (f"🔄 *CRM Enrichment [{MODE}] — "
           f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC*\n\n")
    msg += f"📊 Candidatos: {candidates} | Actualizados: {updated}\n"
    if by_field:
        msg += "\n📝 Campos:\n" + "".join(
            f"  • {f}: {c}\n" for f, c in sorted(by_field.items(), key=lambda x: -x[1]))
    if by_source:
        msg += "\n🔎 Fuente:\n" + "".join(
            f"  • {s}: {c}\n" for s, c in sorted(by_source.items(), key=lambda x: -x[1]))
    if examples:
        msg += "\n🏢 Ejemplos:\n" + "".join(f"  • {e}\n" for e in examples[:5])
    if DRY_RUN:
        msg += "\n⚠️ _Modo DRY RUN — sin cambios reales_"
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                             "parse_mode": "Markdown"}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


# =============================================================================
# MAIN
# =============================================================================

def _load_env():
    env_file = os.path.join(HERMES_HOME, ".env")
    if not os.path.isfile(env_file):
        return
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


def _apply_mode(cli_mode: Optional[str]):
    global MODE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GOOGLE_PLACES_API_KEY, LLM_API_KEY
    if cli_mode:
        MODE = cli_mode
    if MODE not in ("internal", "external", "all"):
        MODE = "internal"
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS",
                                      TELEGRAM_CHAT_ID).split(",")[0].strip()
    GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", GOOGLE_PLACES_API_KEY)
    LLM_API_KEY = os.environ.get("OPENROUTER_API_KEY", LLM_API_KEY)


def main():
    parser = argparse.ArgumentParser(description="Unified CRM enrichment")
    parser.add_argument("--mode", choices=["internal", "external", "all"],
                        default=None, help="Which enrichment phases to run")
    args = parser.parse_args()

    _load_env()
    _apply_mode(args.mode)

    print("=" * 60)
    print(f"CRM Enrichment (unified) — mode: {MODE}")
    print(f"Table: {TABLE_NAME} | Region: {REGION} | Mode run: "
          f"{'DRY RUN' if DRY_RUN else 'LIVE'}")
    if want_internal():
        print(f"  internal: on (NIT scrape: {'on' if NIT_LOOKUP_ENABLED else 'off'}, "
              f"LLM: {'on' if LLM_API_KEY else 'off'})")
    if want_external():
        print(f"  external: web={WEB_REVISIT_ENABLED} rues={RUES_ENABLED} "
              f"places={PLACES_ENABLED and bool(GOOGLE_PLACES_API_KEY)}")
    print(f"  caps: leads={MAX_LEADS_PER_RUN} web={MAX_WEB_REVISITS} "
          f"rues={MAX_RUES_LOOKUPS} places={MAX_PLACES_LOOKUPS} nit={MAX_NIT_LOOKUPS}")
    print("=" * 60)
    print()

    print("--- Phase 1: Scan candidates ---")
    items = scan_candidates()
    if not items:
        print("  No candidates. Done!")
        send_telegram_summary(0, 0, {}, {}, [])
        return 0

    print(f"\n--- Phase 2: Enriching {len(items)} leads ---")
    to_update = []
    # Internal-only work is CPU-light; external does network I/O. Process
    # sequentially so per-source budgets and rate-limits stay honest.
    for it in items:
        pk, sk, changes, sources = process_lead(it)
        if changes:
            to_update.append((pk, sk, changes, sources))
    print(f"  Leads with new data: {len(to_update)} / {len(items)}")

    print(f"\n--- Phase 3: Writing updates ---")
    updated = 0
    by_field: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    examples: List[str] = []

    def _do(args):
        pk, sk, changes, sources = args
        return pk, changes, sources, update_item(pk, sk, changes, sources)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_do, u): u for u in to_update}
        for fut in as_completed(futures):
            try:
                pk, changes, sources, ok = fut.result()
            except Exception:
                ok = False
            if not ok:
                continue
            updated += 1
            for k in changes:
                if k not in ("FechaActualizacion", "UltimoEnrichExterno",
                             "FuenteEnriquecimiento", "Score"):
                    by_field[k] = by_field.get(k, 0) + 1
            for s in sources:
                by_source[s] = by_source.get(s, 0) + 1
            if len(examples) < 5:
                fields = [k for k in changes if k not in (
                    "FechaActualizacion", "UltimoEnrichExterno",
                    "FuenteEnriquecimiento", "Score")]
                examples.append(f"{pk[:28]}: {', '.join(fields)}")

    print("\n" + "=" * 60)
    print(f"Enrichment [{MODE}] completed!")
    print(f"  Candidates: {len(items)}")
    print(f"  Updated:    {updated}")
    print(f"  By field:   {by_field}")
    print(f"  By source:  {by_source}")
    if DRY_RUN:
        print("\n  ⚠️ DRY RUN — no database changes were made")
    print("=" * 60)

    send_telegram_summary(len(items), updated, by_field, by_source, examples)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
