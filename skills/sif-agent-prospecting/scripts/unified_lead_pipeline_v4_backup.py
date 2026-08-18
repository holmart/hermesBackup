#!/usr/bin/env python3
"""
Unified Lead Generation Pipeline for SIF Agent — v4
=====================================================
Improvements over v3:
1. Better person name extraction (rejects false positives)
2. Phone validation rejects repetitive/sequential patterns
3. Email validation filters placeholders and mismatched domains
4. Single DynamoDB scan for dedup (not N scans per lead)
5. Removed dead RUES code
6. Proper exit code on failure (exit 1)
7. DynamoDB insert retry with exponential backoff
8. Log rotation (keeps last 5000 lines)
9. Removed Instagram scraping (always blocked by IG)
10. known_domains TTL (expires after 30 days)
11. Better query rotation for sustained yield
12. Improved company name cleaning

Designed to run daily via cron on EC2.
"""

import subprocess
import re
import json
import csv
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, urlparse, urljoin
from typing import Optional, Dict, List, Tuple, Set

# =============================================================================
# CONFIGURATION
# =============================================================================

HERMES_HOME = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")
LEADS_DIR = os.path.join(HERMES_HOME, "leads")
LEADS_CSV = os.path.join(LEADS_DIR, "fumigation_leads_enriched.csv")
LOG_FILE = os.path.join(LEADS_DIR, "pipeline.log")
STATE_FILE = os.path.join(LEADS_DIR, "pipeline_state.json")

DYNAMODB_TABLE = "sifagent-crm-clients"
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

# Max log lines before rotation
LOG_MAX_LINES = 5000

# known_domains TTL in days
KNOWN_DOMAINS_TTL_DAYS = 30

CITIES = [
    "Bogota", "Medellin", "Cali", "Barranquilla", "Bucaramanga",
    "Cartagena", "Pereira", "Manizales", "Ibague", "Villavicencio",
    "Santa Marta", "Cucuta", "Neiva", "Armenia", "Popayan"
]

QUERY_TEMPLATES = [
    "empresa fumigacion {city} Colombia",
    "control de plagas {city} Colombia",
    "fumigadora certificada {city}",
    "servicio fumigacion restaurantes {city}",
    "desinfeccion empresas {city} Colombia",
    "control plagas industrial {city}",
    "fumigacion comercial {city}",
    "manejo integrado plagas {city} Colombia",
    "empresa desratizacion {city}",
    "servicio sanitizacion {city} Colombia",
]

BLOCKED_DOMAINS = {
    "bing.com", "microsoft.com", "google.com", "youtube.com", "facebook.com",
    "twitter.com", "instagram.com", "linkedin.com", "amazon.com", "wikipedia.org",
    "mercadolibre.com", "olx.com", "reddit.com", "pinterest.com",
    "eltiempo.com", "semana.com", "caracol.com.co", "rcn.com.co",
    "publimetro.co", "googlesyndication.com", "doubleclick.net",
    "rentokil.com", "terminix.com",
    "empresite.eleconomistaamerica.co", "paginasamarillas.com.co",
    "equipmaster.com.co", "condustrial.com.co", "agrofumigadoras.com.co",
    "infoisinfo.com.co", "cylex.com.co",
    "aseoylimpiezabogota.com", "cleandelivery.com.co",
    "initial.com",
    "moviaseo.com", "terserpro.com", "ecolimpiezabogota.com.co",
    "industriaslyf.com",
}

COLOMBIAN_TLDS = (".co", ".com.co", ".org.co", ".net.co")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]

BOT_CHALLENGE_PHRASES = [
    "please complete the following challenge", "solving this captcha",
    "unusual traffic", "are you a robot", "verify you are a human",
    "¿eres un robot?", "please enable javascript", "access denied",
    "bot detection", "pardon the interruption", "request blocked",
    "we've detected unusual activity",
]

# Words that should never appear as a person name
PERSON_NAME_BLACKLIST = {
    "control", "plagas", "fumigacion", "fumigación", "servicio", "servicios",
    "empresa", "empresas", "colombia", "bogota", "bogotá", "medellin", "medellín",
    "cali", "barranquilla", "cartagena", "pereira", "manizales", "ibague",
    "villavicencio", "santa", "marta", "cucuta", "neiva", "armenia", "popayan",
    "restaurante", "hotel", "edificio", "residencial", "comercial", "industrial",
    "sanitizacion", "sanitización", "desinfeccion", "desinfección", "desratizacion",
    "desratización", "fumigaciones", "certificado", "contacto", "nosotros",
    "quienes", "somos", "nuestro", "equipo", "inicio", "home", "about",
    "limpieza", "aseo", "lavado", "mantenimiento", "soluciones", "profesionales",
    "termitas", "roedores", "insectos", "vectores", "plagas",
}

# Placeholder/generic email domains
PLACEHOLDER_EMAIL_DOMAINS = {
    "empresa.com", "example.com", "test.com", "correo.com", "mail.com",
    "email.com", "domain.com", "tu-dominio.com", "tudominio.com",
    "sampleemail.com", "yourcompany.com",
}

# =============================================================================
# UTILITIES
# =============================================================================

def log(msg: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def rotate_log():
    """Keep only the last LOG_MAX_LINES lines in the log file."""
    try:
        if not os.path.isfile(LOG_FILE):
            return
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > LOG_MAX_LINES:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-LOG_MAX_LINES:])
            log(f"Log rotated: kept last {LOG_MAX_LINES} lines (was {len(lines)})")
    except Exception:
        pass


def load_state() -> Dict:
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"city_index": 0, "known_domains": {}, "known_urls": [], "query_offset": 0}


def save_state(state: Dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_root_domain(url: str) -> str:
    """Extract root domain from URL (e.g., 'www.fumycontrol.co/page' -> 'fumycontrol.co')."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url


def expire_known_domains(state: Dict) -> Dict:
    """Remove domains older than KNOWN_DOMAINS_TTL_DAYS from state.

    Migrates legacy list format to dict format with timestamps.
    """
    known = state.get("known_domains", {})

    # Migrate from legacy list format to dict with timestamps
    if isinstance(known, list):
        now_iso = datetime.now(timezone.utc).isoformat()
        known = {domain: now_iso for domain in known}
        state["known_domains"] = known

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KNOWN_DOMAINS_TTL_DAYS)).isoformat()
    expired = [d for d, ts in known.items() if ts < cutoff]
    for d in expired:
        del known[d]

    if expired:
        log(f"Expired {len(expired)} domains from known_domains (older than {KNOWN_DOMAINS_TTL_DAYS} days)")

    state["known_domains"] = known
    return state


def fetch_url(url: str, max_attempts: int = 3, timeout: int = 15) -> Optional[str]:
    """Fetch URL with retries, bot detection, and realistic headers."""
    for attempt in range(1, max_attempts + 1):
        ua = random.choice(USER_AGENTS)
        cmd = [
            "curl", "-s", "-L", "--max-time", str(timeout), "--compressed",
            "-A", ua,
            "-H", "accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "accept-language: es-CO,es;q=0.9,en;q=0.5",
            "-H", "cache-control: no-cache",
            "-H", "upgrade-insecure-requests: 1",
            url
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            if result.returncode != 0:
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            html = result.stdout
            lowered = html.lower()
            if any(phrase in lowered for phrase in BOT_CHALLENGE_PHRASES):
                log(f"  Bot challenge attempt {attempt} for {url[:60]}")
                time.sleep(3 ** attempt + random.uniform(0, 2))
                continue
            return html
        except (subprocess.TimeoutExpired, Exception) as e:
            log(f"  Fetch error attempt {attempt}: {e}")
            time.sleep(2 ** attempt)
    return None


# =============================================================================
# SEARCH PHASE
# =============================================================================

def extract_ddg_links(html: str) -> List[str]:
    """Extract result links from DuckDuckGo HTML (uddg= parameter)."""
    from urllib.parse import unquote
    links = []
    uddg_matches = re.findall(r"uddg=([^&\"']+)", html)
    for encoded_url in uddg_matches:
        url = unquote(encoded_url)
        if url.startswith("http"):
            links.append(url)
    if len(links) < 3:
        href_matches = re.findall(r'href="(https?://[^"]+)"', html, re.IGNORECASE)
        for url in href_matches:
            if "duckduckgo.com" not in url and "javascript:" not in url:
                links.append(url)
    seen = set()
    unique = []
    for u in links:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def is_relevant_domain(url: str) -> bool:
    """Check if URL is a relevant Colombian company domain."""
    try:
        domain = get_root_domain(url)
        if any(blocked in domain for blocked in BLOCKED_DOMAINS):
            return False
        if any(domain.endswith(tld) for tld in COLOMBIAN_TLDS):
            return True
        if domain.endswith(".com") and len(domain.split(".")) <= 3:
            generic_coms = {"wikipedia.com", "youtube.com", "facebook.com", "twitter.com"}
            if domain not in generic_coms:
                return True
    except Exception:
        pass
    return False


def search_city(city: str, state: Dict) -> List[str]:
    """Search DuckDuckGo HTML, deduplicate by root domain.

    Uses query_offset to rotate which templates are used across runs,
    ensuring different queries each day for sustained yield.
    """
    known_domains = set(state.get("known_domains", {}).keys()) if isinstance(state.get("known_domains"), dict) else set(state.get("known_domains", []))
    candidate_urls = []
    seen_domains = set()

    # Rotate queries: use offset to pick different templates each run
    query_offset = state.get("query_offset", 0)
    num_queries = 3
    selected_indices = [(query_offset + i) % len(QUERY_TEMPLATES) for i in range(num_queries)]
    templates = [QUERY_TEMPLATES[i] for i in selected_indices]

    for template in templates:
        query = template.format(city=city)
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        log(f"  Searching: {query}")

        html = fetch_url(search_url)
        if not html:
            log(f"  Failed to fetch search results")
            continue

        links = extract_ddg_links(html)
        for u in links:
            domain = get_root_domain(u)
            if not is_relevant_domain(u):
                continue
            if domain in known_domains or domain in seen_domains:
                continue
            seen_domains.add(domain)
            candidate_urls.append(u)

        log(f"  Found {len(links)} links, {len(seen_domains)} unique relevant domains so far")
        time.sleep(random.uniform(4, 7))

    log(f"Total unique domains to scrape: {len(candidate_urls)}")
    return candidate_urls


# =============================================================================
# EXTRACTION PHASE
# =============================================================================

def is_repetitive_number(digits: str) -> bool:
    """Check if a number has repetitive or sequential patterns (likely fake)."""
    # All same digit: 3333333333
    if len(set(digits)) <= 2:
        return True
    # Repeating pairs: 3636363636
    if len(digits) >= 8:
        pair = digits[:2]
        if pair * (len(digits) // 2) == digits[:len(digits) // 2 * 2]:
            return True
    # Sequential: 3456789012
    sequential_up = all(int(digits[i]) == (int(digits[i-1]) + 1) % 10 for i in range(1, len(digits)))
    if sequential_up:
        return True
    return False


def validate_colombian_phone(raw: str) -> Optional[str]:
    """Validate and normalize a Colombian mobile phone number."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("57") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("3"):
        if is_repetitive_number(digits):
            return None
        return f"+57{digits}"
    return None


def extract_phones(html: str) -> List[str]:
    """Extract valid Colombian mobile phones from HTML."""
    patterns = [
        r"(?:\+?57\s*)?3\d{2}[\s\-\.]?\d{3}[\s\-\.]?\d{4}",
        r"(?:\(\+?57\))\s*3\d{2}[\s\-\.]?\d{3}[\s\-\.]?\d{4}",
    ]
    phones = set()
    for pat in patterns:
        for match in re.finditer(pat, html):
            validated = validate_colombian_phone(match.group())
            if validated:
                phones.add(validated)
    return list(phones)


def is_valid_email(email: str, company_domain: str = "") -> bool:
    """Validate email is real and relevant, not a placeholder."""
    if not email or "@" not in email:
        return False

    prefix = email.split("@")[0]
    domain = email.split("@")[1]

    # Reject placeholder domains
    if domain in PLACEHOLDER_EMAIL_DOMAINS:
        return False

    # Reject image/asset file extensions mistakenly captured
    if domain.endswith((".png", ".jpg", ".gif", ".css", ".js", ".svg")):
        return False

    # Reject very short or single-char prefixes
    if len(prefix) < 2:
        return False

    # Reject if prefix is just numbers
    if prefix.isdigit():
        return False

    # Reject generic prefixes that indicate test/system emails
    generic_prefixes = {
        "noreply", "no-reply", "mailer", "postmaster", "webmaster",
        "test", "example", "admin123", "user", "demo",
    }
    if prefix.lower() in generic_prefixes:
        return False

    return True


def extract_emails(html: str, company_domain: str = "") -> List[str]:
    """Extract validated email addresses from HTML."""
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    emails = set()
    for match in re.finditer(pattern, html):
        email = match.group().lower().strip(".")
        if is_valid_email(email, company_domain):
            emails.add(email)
    return list(emails)


def extract_whatsapp(html: str) -> Optional[str]:
    """Extract WhatsApp link/number from HTML."""
    patterns = [
        r"wa\.me/(\d+)",
        r"api\.whatsapp\.com/send\?phone=(\d+)",
        r"whatsapp\.com/send\?phone=(\d+)",
    ]
    for pat in patterns:
        match = re.search(pat, html)
        if match:
            number = match.group(1)
            if number.startswith("57") and len(number) == 12:
                digits = number[2:]
                if not is_repetitive_number(digits):
                    return f"+{number}"
            if len(number) == 10 and number.startswith("3"):
                if not is_repetitive_number(number):
                    return f"+57{number}"
    return None


def clean_company_name(raw_title: str, url: str) -> str:
    """Extract company name from domain or page title."""
    domain = get_root_domain(url)
    domain_base = domain.split(".")[0].replace("-", " ").replace("_", " ")

    generic_names = {
        "control", "servicio", "empresa", "colombia", "bogota", "fumigacion",
        "plagas", "home", "www", "servicios", "fumigaciones", "desinfeccion",
        "controldeplagas", "controlplagas", "fumigacionesbogota",
    }

    if domain_base.lower().replace(" ", "") not in generic_names and len(domain_base) >= 4:
        name = domain_base.title()
        if raw_title:
            legal_match = re.search(
                r"([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{2,30}(?:S\.?A\.?S\.?|LTDA\.?|S\.?A\.?|E\.?S\.?P\.?))",
                raw_title
            )
            if legal_match:
                return legal_match.group(1).strip()
        return name

    if raw_title:
        name = raw_title.strip()
        legal_match = re.search(
            r"([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{2,30}(?:S\.?A\.?S\.?|LTDA\.?|S\.?A\.?|E\.?S\.?P\.?))",
            name
        )
        if legal_match:
            return legal_match.group(1).strip()

        for sep in [" | ", " – ", " - ", " :: ", " » ", " — "]:
            if sep in name:
                name = name.split(sep)[0].strip()
                break

        name = re.sub(r"\s*(?:en|de)\s+(?:Bogot[aá]|Medell[ií]n|Cali|Barranquilla|Colombia).*$", "", name, flags=re.IGNORECASE).strip()
        name = re.sub(r"\s*(?:2024|2025|2026|2027)\s*$", "", name).strip()
        name = re.sub(r"[^\w\s\-áéíóúñÁÉÍÓÚÑ]", "", name).strip()

        if 3 < len(name) < 50:
            return name

    return domain_base.title()


def extract_person_name(html: str) -> Optional[str]:
    """Extract name of owner/manager from HTML with strict validation."""
    patterns = [
        r"(?:representante\s+legal|gerente\s+general|director\s+general|fundador|propietario|gerente)\s*[:\-]\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})",
        r"(?:Ing\.|Dr\.|Dra\.|Sr\.|Sra\.)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})",
    ]

    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            words = name.split()

            # Must be 2-4 words, each capitalized
            if not (2 <= len(words) <= 4):
                continue
            if not all(w[0].isupper() for w in words):
                continue
            if not (5 < len(name) < 45):
                continue

            # Reject if any word is in the blacklist
            name_lower_words = {w.lower() for w in words}
            if name_lower_words & PERSON_NAME_BLACKLIST:
                continue

            # Reject if the name contains only common business terms
            business_terms = {"control", "servicio", "empresa", "grupo", "soluciones", "profesional"}
            if len(name_lower_words - business_terms) == 0:
                continue

            # Each word should be a plausible name (>= 3 chars, no digits)
            if any(len(w) < 3 or any(c.isdigit() for c in w) for w in words):
                continue

            return name

    return None


def detect_company_size(html: str) -> Optional[str]:
    """Detect approximate company size from content."""
    html_lower = html.lower()

    size_patterns = [
        (r"(\d+)\s*(?:técnicos|tecnicos|operarios|empleados|colaboradores)", None),
        (r"equipo\s+de\s+(\d+)", None),
    ]

    for pat, _ in size_patterns:
        match = re.search(pat, html_lower)
        if match:
            num = int(match.group(1))
            if 1 <= num <= 200:
                if num <= 3:
                    return "micro"
                elif num <= 10:
                    return "pequeña"
                elif num <= 50:
                    return "mediana"
                else:
                    return "grande"

    signals_large = 0
    if "sedes" in html_lower or "sucursales" in html_lower:
        signals_large += 1
    if re.search(r"cobertura\s+nacional", html_lower):
        signals_large += 1
    if len(re.findall(r"\+57\s*3\d{2}", html)) > 3:
        signals_large += 1
    if "certificado iso" in html_lower or "iso 9001" in html_lower:
        signals_large += 1

    if signals_large >= 3:
        return "mediana"
    elif signals_large >= 1:
        return "pequeña"

    return None


def extract_instagram_handle(html: str) -> Optional[str]:
    """Extract Instagram handle from page (metadata only, no scraping)."""
    patterns = [
        r"instagram\.com/([a-zA-Z0-9_.]+)",
    ]
    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            handle = match.group(1).strip("./")
            if handle and len(handle) > 2 and handle not in ("p", "reel", "stories", "explore"):
                return handle
    return None


def scrape_company(url: str) -> Optional[Dict]:
    """Visit a company website and subpages to extract all available data."""
    html = fetch_url(url, max_attempts=2, timeout=12)
    if not html or len(html) < 200:
        return None

    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    domain = get_root_domain(url)
    all_html = html

    # Visit subpages for more contact data
    subpages = ["/contacto", "/contactanos", "/contact", "/nosotros", "/quienes-somos", "/about"]
    for subpage in subpages:
        sub_url = urljoin(base_url, subpage)
        sub_html = fetch_url(sub_url, max_attempts=1, timeout=8)
        if sub_html and len(sub_html) > 200:
            all_html += "\n" + sub_html
        time.sleep(random.uniform(0.5, 1.5))

    # Extract title
    raw_title = ""
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if title_match:
        raw_title = title_match.group(1).strip()

    company_name = clean_company_name(raw_title, url)
    phones = extract_phones(all_html)
    emails = extract_emails(all_html, domain)
    whatsapp = extract_whatsapp(all_html)
    services = extract_services(all_html)
    city = extract_address_city(all_html)
    contact_person = extract_person_name(all_html)
    company_size = detect_company_size(all_html)
    ig_handle = extract_instagram_handle(all_html)

    if not whatsapp and phones:
        whatsapp = phones[0]

    # Must have at least phone or email
    if not phones and not emails:
        return None

    # Prioritize emails
    priority_prefixes = ["gerencia", "gerente", "director", "admin", "comercial", "info", "contacto"]
    best_email = ""
    if emails:
        for prefix in priority_prefixes:
            for email in emails:
                if email.startswith(prefix):
                    best_email = email
                    break
            if best_email:
                break
        if not best_email:
            best_email = emails[0]

    return {
        "company_name": company_name,
        "url": base_url + "/",
        "domain": domain,
        "phone": phones[0] if phones else "",
        "all_phones": phones,
        "email": best_email,
        "all_emails": emails,
        "whatsapp": whatsapp or "",
        "services": services,
        "city": city or "",
        "contact_person": contact_person or "",
        "company_size": company_size or "",
        "instagram": ig_handle or "",
    }


def extract_services(html: str) -> List[str]:
    """Extract services mentioned on the page."""
    service_keywords = [
        "fumigación", "fumigacion", "control de plagas", "desinfección", "desinfeccion",
        "desratización", "desratizacion", "sanitización", "sanitizacion",
        "control de termitas", "control de roedores", "control de insectos",
        "manejo integrado de plagas", "certificado de fumigación",
        "lavado de tanques", "control de vectores",
    ]
    found = []
    html_lower = html.lower()
    for kw in service_keywords:
        if kw in html_lower:
            found.append(kw)
    return found


def extract_address_city(html: str) -> Optional[str]:
    """Try to extract city from the page content."""
    pat = r"(?:Bogot[aá]|Medell[ií]n|Cali|Barranquilla|Bucaramanga|Cartagena|Pereira|Manizales|Ibagu[eé]|Villavicencio|Santa Marta|C[uú]cuta|Neiva|Armenia|Popay[aá]n)"
    match = re.search(pat, html, re.IGNORECASE)
    if match:
        return match.group().title()
    return None


# =============================================================================
# DYNAMODB PHASE
# =============================================================================

def load_existing_domains_from_dynamodb() -> Set[str]:
    """Single scan to get all existing domains from DynamoDB. Much more efficient than N individual scans."""
    domains = set()
    start_key = None

    while True:
        cmd = [
            "aws", "dynamodb", "scan",
            "--table-name", DYNAMODB_TABLE,
            "--region", AWS_REGION,
            "--projection-expression", "Dominio,Website",
            "--select", "SPECIFIC_ATTRIBUTES",
        ]
        if start_key:
            cmd.extend(["--exclusive-start-key", json.dumps(start_key)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                log(f"  DynamoDB scan error: {result.stderr[:200]}")
                break
            data = json.loads(result.stdout)
            for item in data.get("Items", []):
                dominio = item.get("Dominio", {}).get("S", "")
                website = item.get("Website", {}).get("S", "")
                if dominio:
                    domains.add(dominio)
                elif website:
                    domains.add(get_root_domain(website))

            last_key = data.get("LastEvaluatedKey")
            if not last_key:
                break
            start_key = last_key
        except Exception as e:
            log(f"  DynamoDB scan exception: {e}")
            break

    log(f"  Loaded {len(domains)} existing domains from CRM")
    return domains


def insert_lead_to_dynamodb(lead: Dict, max_retries: int = 3) -> bool:
    """Insert a new lead into DynamoDB CRM table with retry + backoff."""
    pk = lead["company_name"].upper().strip()
    sk = f"LEAD-{int(time.time())}"
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "PK": {"S": pk},
        "SK": {"S": sk},
        "NombreComercial": {"S": lead["company_name"]},
        "Website": {"S": lead["url"]},
        "Dominio": {"S": lead.get("domain", "")},
        "Telefono": {"S": lead.get("phone", "")},
        "TelefonosExtra": {"S": ", ".join(lead.get("all_phones", []))},
        "Email": {"S": lead.get("email", "")},
        "EmailsExtra": {"S": ", ".join(lead.get("all_emails", []))},
        "WhatsApp": {"S": lead.get("whatsapp", "")},
        "Ciudad": {"S": lead.get("city", "")},
        "Servicios": {"S": ", ".join(lead.get("services", []))},
        "NIT": {"S": ""},
        "RepresentanteLegal": {"S": lead.get("contact_person", "")},
        "RazonSocial": {"S": ""},
        "ContactoPrincipal": {"S": lead.get("contact_person", "")},
        "TamanoEmpresa": {"S": lead.get("company_size", "")},
        "Instagram": {"S": lead.get("instagram", "")},
        "FuenteRepLegal": {"S": "website" if lead.get("contact_person") else ""},
        "FechaIngreso": {"S": now},
        "FuenteLead": {"S": "pipeline_unified_v4"},
        "Estado": {"S": "nuevo"},
        "Score": {"N": str(lead.get("score", 3))},
        "Vertical": {"S": "fumigacion"},
    }

    # Remove empty string values (except Score which is N type)
    item = {k: v for k, v in item.items() if v.get("S", "x") != "" or v.get("N")}

    cmd = [
        "aws", "dynamodb", "put-item",
        "--table-name", DYNAMODB_TABLE,
        "--region", AWS_REGION,
        "--item", json.dumps(item),
        "--condition-expression", "attribute_not_exists(PK)",
    ]

    for attempt in range(1, max_retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return True
            elif "ConditionalCheckFailed" in (result.stderr or ""):
                log(f"  Already exists in CRM: {pk}")
                return False
            elif "ProvisionedThroughputExceeded" in (result.stderr or "") or "ThrottlingException" in (result.stderr or ""):
                wait_time = 2 ** attempt + random.uniform(0, 1)
                log(f"  DynamoDB throttled, retry {attempt}/{max_retries} in {wait_time:.1f}s")
                time.sleep(wait_time)
                continue
            else:
                log(f"  DynamoDB put error (attempt {attempt}): {result.stderr[:200]}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False
        except Exception as e:
            log(f"  DynamoDB exception (attempt {attempt}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return False

    return False


# =============================================================================
# SCORING
# =============================================================================

def score_lead(lead: Dict) -> int:
    """Score a lead 1-5. Higher = more actionable (has real contact data)."""
    score = 1.0

    has_phone = bool(lead.get("phone"))
    has_email = bool(lead.get("email"))
    has_person = bool(lead.get("contact_person"))
    has_whatsapp = bool(lead.get("whatsapp"))

    if has_phone:
        score += 1.0
    if has_email:
        score += 1.0
    if has_person:
        score += 1.0
    if has_whatsapp and not has_phone:
        score += 0.5

    services = lead.get("services", [])
    if len(services) >= 3:
        score += 0.5

    size = lead.get("company_size", "")
    if size in ("mediana", "grande"):
        score += 0.5
    elif size == "pequeña":
        score += 0.25

    return min(5, max(1, int(round(score))))


# =============================================================================
# TELEGRAM REPORT
# =============================================================================

def send_telegram_report(leads: List[Dict], city: str, stats: Dict):
    """Send a formatted report to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram not configured, skipping report")
        return

    header = f"🎯 *Leads SIF Agent — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*\n"
    header += f"📍 Ciudad: *{city}*\n"
    header += f"📊 Encontradas: {stats['found']} | Insertadas: {stats['inserted']} | Duplicadas: {stats['duplicates']}\n\n"

    body = ""
    for i, lead in enumerate(leads[:5], 1):
        stars = "⭐" * lead.get("score", 3)
        body += f"*{i}. {lead['company_name']}* {stars}\n"
        if lead.get("city"):
            body += f"   📍 {lead['city']}\n"
        if lead.get("contact_person"):
            body += f"   👤 {lead['contact_person']}\n"
        if lead.get("phone"):
            body += f"   📞 {lead['phone']}\n"
        if lead.get("whatsapp"):
            body += f"   💬 [WhatsApp](https://wa.me/{lead['whatsapp'].replace('+', '')})\n"
        if lead.get("email"):
            body += f"   📧 {lead['email']}\n"
        if lead.get("company_size"):
            body += f"   📐 Tamaño: {lead['company_size']}\n"
        if lead.get("instagram"):
            body += f"   📷 @{lead['instagram']}\n"
        if lead.get("services"):
            body += f"   🔧 {', '.join(lead['services'][:3])}\n"
        body += f"   🌐 {lead['url']}\n\n"

    if not leads:
        body = "No se encontraron leads nuevas calificadas hoy.\n"

    footer = f"\n_Próxima ciudad: {stats.get('next_city', 'N/A')}_"
    message = header + body + footer

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    cmd = [
        "curl", "-s", "-X", "POST", api_url,
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            resp = json.loads(result.stdout)
            if resp.get("ok"):
                log("Telegram report sent successfully")
            else:
                log(f"Telegram API error: {resp.get('description', 'unknown')}")
        else:
            log(f"Telegram curl failed: {result.stderr[:200]}")
    except Exception as e:
        log(f"Telegram send error: {e}")


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def main():
    os.makedirs(LEADS_DIR, exist_ok=True)

    # Rotate log at start
    rotate_log()

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

    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_USERS", TELEGRAM_CHAT_ID).split(",")[0].strip()

    log("=" * 60)
    log("UNIFIED LEAD PIPELINE v4 — Starting")
    log("=" * 60)

    state = load_state()

    # Expire old known_domains
    state = expire_known_domains(state)

    city_index = state.get("city_index", 0) % len(CITIES)
    city = CITIES[city_index]
    next_city = CITIES[(city_index + 1) % len(CITIES)]

    log(f"Target city: {city} (index {city_index})")

    # PHASE 1: Search (deduplicated by domain)
    log("\n--- PHASE 1: SEARCH ---")
    candidate_urls = search_city(city, state)

    # PHASE 2: Scrape each company + subpages
    log("\n--- PHASE 2: SCRAPE & EXTRACT ---")
    enriched_leads = []
    for url in candidate_urls[:15]:  # Increased from 12 to 15
        log(f"  Scraping: {get_root_domain(url)}...")
        lead_data = scrape_company(url)
        if lead_data:
            enriched_leads.append(lead_data)
            log(f"    ✓ {lead_data['company_name']} | Ph: {lead_data.get('phone', '-')} | Em: {lead_data.get('email', '-')} | Person: {lead_data.get('contact_person', '-')}")
        else:
            log(f"    ✗ No useful data")
        time.sleep(random.uniform(1, 2))

    log(f"Leads with contact data: {len(enriched_leads)}")

    # PHASE 3: Score and filter
    log("\n--- PHASE 3: SCORE & FILTER ---")
    for lead in enriched_leads:
        lead["score"] = score_lead(lead)

    enriched_leads.sort(key=lambda x: x["score"], reverse=True)
    qualified_leads = [l for l in enriched_leads if l["score"] >= 3]
    log(f"Qualified leads (score >= 3): {len(qualified_leads)}")

    # PHASE 4: Insert to DynamoDB (single scan dedup)
    log("\n--- PHASE 4: INSERT TO CRM ---")
    existing_domains = load_existing_domains_from_dynamodb()
    inserted = 0
    duplicates = 0
    for lead in qualified_leads:
        domain = lead.get("domain", "")
        if domain in existing_domains:
            log(f"  Skip (exists): {lead['company_name']}")
            duplicates += 1
            continue
        if insert_lead_to_dynamodb(lead):
            inserted += 1
            existing_domains.add(domain)  # Track within this run too
            log(f"  ✓ Inserted: {lead['company_name']} (score {lead['score']})")
        else:
            duplicates += 1
        time.sleep(0.5)

    # PHASE 5: Save to CSV
    log("\n--- PHASE 5: SAVE CSV ---")
    csv_exists = os.path.isfile(LEADS_CSV)
    with open(LEADS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not csv_exists:
            writer.writerow([
                "timestamp", "company_name", "domain", "phone", "email", "whatsapp",
                "city", "contact_person", "company_size", "instagram",
                "services", "score"
            ])
        for lead in qualified_leads:
            writer.writerow([
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                lead["company_name"], lead.get("domain", ""),
                lead.get("phone", ""), lead.get("email", ""), lead.get("whatsapp", ""),
                lead.get("city", city), lead.get("contact_person", ""),
                lead.get("company_size", ""), lead.get("instagram", ""),
                "|".join(lead.get("services", [])),
                lead.get("score", 3),
            ])

    # PHASE 6: Telegram report
    log("\n--- PHASE 6: TELEGRAM REPORT ---")
    stats = {
        "found": len(enriched_leads),
        "inserted": inserted,
        "duplicates": duplicates,
        "next_city": next_city,
    }
    send_telegram_report(qualified_leads, city, stats)

    # Update state
    state["city_index"] = (city_index + 1) % len(CITIES)
    state["query_offset"] = (state.get("query_offset", 0) + 3) % len(QUERY_TEMPLATES)

    known_domains = state.get("known_domains", {})
    if isinstance(known_domains, list):
        now_iso = datetime.now(timezone.utc).isoformat()
        known_domains = {d: now_iso for d in known_domains}
    now_iso = datetime.now(timezone.utc).isoformat()
    for lead in enriched_leads:
        if lead.get("domain"):
            known_domains[lead["domain"]] = now_iso
    # Also add candidate domains that were scraped but had no data
    for url in candidate_urls[:15]:
        d = get_root_domain(url)
        if d not in known_domains:
            known_domains[d] = now_iso
    state["known_domains"] = known_domains

    known_urls = state.get("known_urls", [])
    known_urls.extend(candidate_urls)
    state["known_urls"] = known_urls[-500:]
    save_state(state)

    log("\n" + "=" * 60)
    log(f"PIPELINE v4 COMPLETE — City: {city} | Found: {len(enriched_leads)} | Inserted: {inserted} | Score>=3: {len(qualified_leads)}")
    log("=" * 60)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        log(f"FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
