#!/usr/bin/env python3
"""
Unified Lead Generation Pipeline for SIF Agent — v3
=====================================================
Improvements over v2:
1. Cleans company names (removes SEO taglines, extracts real business name)
2. Deduplicates by root domain (not just full URL)
3. Visits /contacto and /nosotros subpages for more contact data
4. Extracts person names (gerente/dueño) from websites
5. Improved RUES search (uses domain-derived name, not page title)
6. Instagram bio scraping for WhatsApp/phone
7. Detects company size (# técnicos mentioned)

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
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse, urljoin
from typing import Optional, Dict, List, Tuple

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
    "infoisinfo.com.co", "cylex.com.co",  # directorios
    "aseoylimpiezabogota.com", "cleandelivery.com.co",  # aseo, no fumigación
    "initial.com",  # multinacional de servicios
    "moviaseo.com", "terserpro.com", "ecolimpiezabogota.com.co",  # empresas de aseo
    "industriaslyf.com",  # industrial, no fumigación
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


def load_state() -> Dict:
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"city_index": 0, "known_domains": [], "known_urls": []}


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
    """Search DuckDuckGo HTML, deduplicate by root domain."""
    known_domains = set(state.get("known_domains", []))
    candidate_urls = []
    seen_domains = set()

    templates = random.sample(QUERY_TEMPLATES, min(3, len(QUERY_TEMPLATES)))

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
# EXTRACTION PHASE (IMPROVED)
# =============================================================================

def validate_colombian_phone(raw: str) -> Optional[str]:
    """Validate and normalize a Colombian mobile phone number."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("57") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("3"):
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


def extract_emails(html: str) -> List[str]:
    """Extract email addresses from HTML, filtering junk."""
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    generic_prefixes = {"noreply", "no-reply", "mailer", "postmaster", "webmaster", "support", "test", "example"}
    emails = set()
    for match in re.finditer(pattern, html):
        email = match.group().lower().strip(".")
        prefix = email.split("@")[0]
        domain = email.split("@")[1] if "@" in email else ""
        if domain.endswith((".png", ".jpg", ".gif", ".css", ".js")):
            continue
        if prefix in generic_prefixes:
            continue
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
                return f"+{number}"
            # Try with country code added
            if len(number) == 10 and number.startswith("3"):
                return f"+57{number}"
    return None


def clean_company_name(raw_title: str, url: str) -> str:
    """
    Extract company name. Strategy:
    1. Use domain as primary name source (most reliable identifier)
    2. Check title for legal name (with SAS/LTDA suffix)
    3. Only use title if domain is too generic
    """
    domain = get_root_domain(url)
    domain_base = domain.split(".")[0].replace("-", " ").replace("_", " ")

    # Generic domain names that aren't useful as company names
    generic_names = {
        "control", "servicio", "empresa", "colombia", "bogota", "fumigacion",
        "plagas", "home", "www", "servicios", "fumigaciones", "desinfeccion",
        "controldeplagas", "controlplagas", "fumigacionesbogota",
    }

    # If domain is a real company name, use it
    if domain_base.lower().replace(" ", "") not in generic_names and len(domain_base) >= 4:
        name = domain_base.title()
        # Check if title has legal name (e.g., "Grupo Fumix SAS")
        if raw_title:
            legal_match = re.search(
                r"([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{2,30}(?:S\.?A\.?S\.?|LTDA\.?|S\.?A\.?|E\.?S\.?P\.?))",
                raw_title
            )
            if legal_match:
                return legal_match.group(1).strip()
        return name

    # Domain is generic — extract from title
    if raw_title:
        name = raw_title.strip()
        # Check for legal name in title first
        legal_match = re.search(
            r"([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{2,30}(?:S\.?A\.?S\.?|LTDA\.?|S\.?A\.?|E\.?S\.?P\.?))",
            name
        )
        if legal_match:
            return legal_match.group(1).strip()

        # Split on separators, take first part
        for sep in [" | ", " – ", " - ", " :: ", " » ", " — "]:
            if sep in name:
                name = name.split(sep)[0].strip()
                break

        # Remove SEO junk
        name = re.sub(r"\s*(?:en|de)\s+(?:Bogot[aá]|Medell[ií]n|Cali|Barranquilla|Colombia).*$", "", name, flags=re.IGNORECASE).strip()
        name = re.sub(r"\s*(?:2024|2025|2026|2027)\s*$", "", name).strip()
        name = re.sub(r"[^\w\s\-áéíóúñÁÉÍÓÚÑ]", "", name).strip()  # remove emojis/special chars

        if 3 < len(name) < 50:
            return name

    return domain_base.title()


def extract_person_name(html: str) -> Optional[str]:
    """
    IMPROVEMENT #4: Extract name of owner/manager from HTML.
    Looks for common patterns in Spanish company pages.
    """
    # Patterns ordered by reliability
    patterns = [
        # "Representante Legal: Nombre Apellido"
        r"(?:representante\s+legal|gerente\s+general|director\s+general|fundador|propietario|gerente)\s*[:\-]\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})",
        # "Ing./Dr./Sr. Nombre Apellido"
        r"(?:Ing\.|Dr\.|Dra\.|Sr\.|Sra\.)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})",
        # Near "quienes somos" or "nuestro equipo" sections
        r"(?:nuestro\s+equipo|quienes\s+somos|nuestra\s+empresa).*?([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2})",
    ]

    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if match:
            name = match.group(1).strip()
            # Validate: 2-4 words, each capitalized, reasonable length
            words = name.split()
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words) and 5 < len(name) < 45:
                # Filter out false positives
                false_pos = ["control plagas", "servicio tecnico", "colombia bogota", "bucaramanga cali"]
                if name.lower() not in false_pos and not any(fp in name.lower() for fp in false_pos):
                    return name
    return None


def detect_company_size(html: str) -> Optional[str]:
    """
    IMPROVEMENT #7: Detect approximate company size from content.
    Returns: 'micro' (1-3), 'pequeña' (4-10), 'mediana' (11-50), or None.
    """
    html_lower = html.lower()

    # Look for explicit mentions of team size
    size_patterns = [
        (r"(\d+)\s*(?:técnicos|tecnicos|operarios|empleados|colaboradores)", None),
        (r"equipo\s+de\s+(\d+)", None),
        (r"más\s+de\s+(\d+)\s+(?:años|técnicos|clientes)", None),
        (r"(\d+)\s+(?:años|years)\s+(?:de\s+)?experiencia", "experience"),
    ]

    technician_count = 0
    for pat, pat_type in size_patterns:
        match = re.search(pat, html_lower)
        if match:
            num = int(match.group(1))
            if pat_type == "experience":
                continue  # Years of experience != size
            if 1 <= num <= 200:
                technician_count = num
                break

    if technician_count > 0:
        if technician_count <= 3:
            return "micro"
        elif technician_count <= 10:
            return "pequeña"
        elif technician_count <= 50:
            return "mediana"
        else:
            return "grande"

    # Infer from signals
    signals_large = 0
    if "sedes" in html_lower or "sucursales" in html_lower:
        signals_large += 1
    if re.search(r"cobertura\s+nacional", html_lower):
        signals_large += 1
    if len(re.findall(r"\+57\s*3\d{2}", html)) > 3:  # Multiple phone numbers
        signals_large += 1
    if "certificado iso" in html_lower or "iso 9001" in html_lower:
        signals_large += 1

    if signals_large >= 3:
        return "mediana"
    elif signals_large >= 1:
        return "pequeña"

    return None


def extract_instagram_handle(html: str) -> Optional[str]:
    """Extract Instagram handle from page."""
    patterns = [
        r"instagram\.com/([a-zA-Z0-9_.]+)",
        r"@([a-zA-Z0-9_.]+)\s*(?:en\s+)?(?:instagram|insta)",
    ]
    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            handle = match.group(1).strip("./")
            if handle and len(handle) > 2 and handle not in ("p", "reel", "stories", "explore"):
                return handle
    return None


def scrape_instagram_bio(handle: str) -> Dict:
    """
    IMPROVEMENT #6: Scrape Instagram bio for contact info.
    Uses the public page (no login required for public profiles).
    """
    result = {"phone": None, "email": None, "whatsapp": None}
    url = f"https://www.instagram.com/{handle}/"
    html = fetch_url(url, max_attempts=1, timeout=10)
    if not html or len(html) < 500:
        return result

    # Extract phone from bio
    phones = extract_phones(html)
    if phones:
        result["phone"] = phones[0]
        result["whatsapp"] = phones[0]

    # Extract email from bio
    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    # WhatsApp links in bio
    wa = extract_whatsapp(html)
    if wa:
        result["whatsapp"] = wa

    return result


def scrape_company(url: str) -> Optional[Dict]:
    """
    Visit a company website and subpages to extract all available data.
    IMPROVEMENT #3: Also visits /contacto and /nosotros.
    """
    html = fetch_url(url, max_attempts=2, timeout=12)
    if not html or len(html) < 200:
        return None

    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    all_html = html  # Accumulate HTML from multiple pages

    # IMPROVEMENT #3: Visit subpages for more contact data
    subpages = ["/contacto", "/contactanos", "/contact", "/nosotros", "/quienes-somos", "/about"]
    for subpage in subpages:
        sub_url = urljoin(base_url, subpage)
        sub_html = fetch_url(sub_url, max_attempts=1, timeout=8)
        if sub_html and len(sub_html) > 200:
            all_html += "\n" + sub_html
        time.sleep(random.uniform(0.5, 1.5))

    # Extract data from combined HTML
    raw_title = ""
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if title_match:
        raw_title = title_match.group(1).strip()

    # IMPROVEMENT #1: Clean company name
    company_name = clean_company_name(raw_title, url)

    phones = extract_phones(all_html)
    emails = extract_emails(all_html)
    whatsapp = extract_whatsapp(all_html)
    services = extract_services(all_html)
    city = extract_address_city(all_html)

    # IMPROVEMENT #4: Extract person name
    contact_person = extract_person_name(all_html)

    # IMPROVEMENT #7: Detect company size
    company_size = detect_company_size(all_html)

    # IMPROVEMENT #6: Check Instagram
    ig_handle = extract_instagram_handle(all_html)
    ig_data = {}
    if ig_handle:
        ig_data = scrape_instagram_bio(ig_handle)
        # Merge Instagram data (only if we don't have it from the website)
        if ig_data.get("phone") and not phones:
            phones = [ig_data["phone"]]
        if ig_data.get("email") and not emails:
            emails = [ig_data["email"]]
        if ig_data.get("whatsapp") and not whatsapp:
            whatsapp = ig_data["whatsapp"]

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
        "url": base_url + "/",  # Normalize to root
        "domain": get_root_domain(url),
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
# RUES ENRICHMENT (IMPROVED)
# =============================================================================

def query_rues(company_name: str, domain: str) -> Optional[Dict]:
    """
    IMPROVEMENT #5: Query RUES using domain-derived name instead of page title.
    Falls back to cleaned company name if domain name is too short.
    """
    # Try domain-derived name first (e.g., fumycontrol.co -> "fumycontrol")
    domain_name = domain.split(".")[0] if domain else ""
    # Clean domain name: remove hyphens, add spaces for camelCase
    domain_name = re.sub(r"[-_]", " ", domain_name)

    # Decide search term: use domain if it's meaningful, else use company name
    if len(domain_name) >= 5:
        search_term = domain_name
    else:
        search_term = company_name

    # Clean for RUES search
    search_term = re.sub(r"\s*(S\.?A\.?S\.?|LTDA\.?|S\.?A\.?|E\.?S\.?P\.?).*$", "", search_term, flags=re.IGNORECASE).strip()
    search_term = re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ\s]", "", search_term).strip()

    if len(search_term) < 4:
        return None

    url = f"https://www.rues.org.co/api/Registros?razonSocial={quote_plus(search_term)}&tipoDocumento=NIT"
    html = fetch_url(url, max_attempts=2, timeout=20)

    if not html:
        return None

    # Try parsing as JSON
    try:
        data = json.loads(html)
        if isinstance(data, list) and len(data) > 0:
            # Try to find the best match (compare with domain or company name)
            best = None
            for entry in data[:5]:  # Check first 5 results
                razon = (entry.get("razonSocial", "") or entry.get("RazonSocial", "")).lower()
                # Match if domain name appears in razon social
                if domain_name.lower() in razon or search_term.lower() in razon:
                    best = entry
                    break
            if not best:
                best = data[0]  # Fallback to first result

            nit = best.get("nit", best.get("NIT", ""))
            razon_social = best.get("razonSocial", best.get("RazonSocial", ""))
            rep_legal = best.get("representanteLegal", best.get("RepresentanteLegal", ""))
            estado = best.get("estado", best.get("Estado", ""))
            if nit:
                return {
                    "nit": str(nit),
                    "razon_social": razon_social,
                    "representante_legal": rep_legal,
                    "estado": estado,
                }
    except (json.JSONDecodeError, ValueError):
        pass

    # HTML fallback
    nit_match = re.search(r"(\d{9,})-?\d?", html)
    rep_match = re.search(r"[Rr]epresentante\s*[Ll]egal[:\s]+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})", html)

    if nit_match:
        return {
            "nit": nit_match.group(1),
            "razon_social": "",
            "representante_legal": rep_match.group(1) if rep_match else "",
            "estado": "",
        }

    return None


# =============================================================================
# DYNAMODB PHASE
# =============================================================================

def check_exists_in_dynamodb(domain: str) -> bool:
    """Check if a company with this domain already exists in DynamoDB."""
    # Search by website containing the domain
    cmd = [
        "aws", "dynamodb", "scan",
        "--table-name", DYNAMODB_TABLE,
        "--region", AWS_REGION,
        "--filter-expression", "contains(Website, :domain)",
        "--expression-attribute-values", json.dumps({":domain": {"S": domain}}),
        "--projection-expression", "PK",
        "--select", "COUNT",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("Count", 0) > 0
    except Exception:
        pass
    return False


def insert_lead_to_dynamodb(lead: Dict) -> bool:
    """Insert a new lead into DynamoDB CRM table."""
    pk = lead["company_name"].upper().strip()
    sk = lead.get("nit", "") or f"LEAD-{int(time.time())}"
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
        "NIT": {"S": lead.get("nit", "")},
        "RepresentanteLegal": {"S": lead.get("representante_legal", "")},
        "RazonSocial": {"S": lead.get("razon_social", "")},
        "ContactoPrincipal": {"S": lead.get("contact_person", "")},
        "TamanoEmpresa": {"S": lead.get("company_size", "")},
        "Instagram": {"S": lead.get("instagram", "")},
        "FuenteRepLegal": {"S": lead.get("fuente_rep_legal", "pipeline_v3")},
        "FechaIngreso": {"S": now},
        "FuenteLead": {"S": "pipeline_unified_v3"},
        "Estado": {"S": "nuevo"},
        "Score": {"N": str(lead.get("score", 3))},
        "Vertical": {"S": "fumigacion"},
    }

    # Remove empty string values
    item = {k: v for k, v in item.items() if v.get("S", "x") != "" or v.get("N")}

    cmd = [
        "aws", "dynamodb", "put-item",
        "--table-name", DYNAMODB_TABLE,
        "--region", AWS_REGION,
        "--item", json.dumps(item),
        "--condition-expression", "attribute_not_exists(PK)",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True
        elif "ConditionalCheckFailed" in (result.stderr or ""):
            log(f"  Already exists in CRM: {pk}")
            return False
        else:
            log(f"  DynamoDB put error: {result.stderr[:200]}")
            return False
    except Exception as e:
        log(f"  DynamoDB exception: {e}")
        return False


# =============================================================================
# SCORING (IMPROVED)
# =============================================================================

def score_lead(lead: Dict) -> int:
    """Score a lead 1-5. Higher = more actionable (has real contact data)."""
    score = 1.0  # Base: found a company website

    # Contact data quality (most important)
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

    # Business signals
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
        if lead.get("representante_legal"):
            body += f"   🏛 Rep. Legal: {lead['representante_legal']}\n"
        if lead.get("nit"):
            body += f"   🏢 NIT: {lead['nit']}\n"
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
    log("UNIFIED LEAD PIPELINE v3 — Starting")
    log("=" * 60)

    state = load_state()
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
    for url in candidate_urls[:12]:  # Limit to 12 (each visits subpages too)
        log(f"  Scraping: {get_root_domain(url)}...")
        lead_data = scrape_company(url)
        if lead_data:
            enriched_leads.append(lead_data)
            log(f"    ✓ {lead_data['company_name']} | Ph: {lead_data.get('phone', '-')} | Em: {lead_data.get('email', '-')} | Person: {lead_data.get('contact_person', '-')}")
        else:
            log(f"    ✗ No useful data")
        time.sleep(random.uniform(1, 2))

    log(f"Leads with contact data: {len(enriched_leads)}")

    # PHASE 3: Enrich from extracted data (RUES API unreliable — always returns same NIT)
    log("\n--- PHASE 3: DATA CONSOLIDATION ---")
    for lead in enriched_leads:
        lead["nit"] = ""
        lead["razon_social"] = ""
        lead["representante_legal"] = lead.get("contact_person", "")
        lead["fuente_rep_legal"] = "website" if lead.get("contact_person") else ""
        if lead.get("contact_person"):
            log(f"  ✓ {lead.get('domain', '')} → Contacto: {lead['contact_person']}")

    # PHASE 4: Score and filter
    log("\n--- PHASE 4: SCORE & FILTER ---")
    for lead in enriched_leads:
        lead["score"] = score_lead(lead)

    enriched_leads.sort(key=lambda x: x["score"], reverse=True)
    qualified_leads = [l for l in enriched_leads if l["score"] >= 3]
    log(f"Qualified leads (score >= 3): {len(qualified_leads)}")

    # PHASE 5: Insert to DynamoDB (check by domain)
    log("\n--- PHASE 5: INSERT TO CRM ---")
    inserted = 0
    duplicates = 0
    for lead in qualified_leads:
        if check_exists_in_dynamodb(lead.get("domain", "")):
            log(f"  Skip (exists): {lead['company_name']}")
            duplicates += 1
            continue
        if insert_lead_to_dynamodb(lead):
            inserted += 1
            log(f"  ✓ Inserted: {lead['company_name']} (score {lead['score']})")
        else:
            duplicates += 1
        time.sleep(0.5)

    # PHASE 6: Save to CSV
    log("\n--- PHASE 6: SAVE CSV ---")
    csv_exists = os.path.isfile(LEADS_CSV)
    with open(LEADS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not csv_exists:
            writer.writerow([
                "timestamp", "company_name", "domain", "phone", "email", "whatsapp",
                "city", "contact_person", "company_size", "instagram",
                "services", "nit", "representante_legal", "score"
            ])
        for lead in qualified_leads:
            writer.writerow([
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                lead["company_name"], lead.get("domain", ""),
                lead.get("phone", ""), lead.get("email", ""), lead.get("whatsapp", ""),
                lead.get("city", city), lead.get("contact_person", ""),
                lead.get("company_size", ""), lead.get("instagram", ""),
                "|".join(lead.get("services", [])),
                lead.get("nit", ""), lead.get("representante_legal", ""),
                lead.get("score", 3),
            ])

    # PHASE 7: Telegram report
    log("\n--- PHASE 7: TELEGRAM REPORT ---")
    stats = {
        "found": len(enriched_leads),
        "inserted": inserted,
        "duplicates": duplicates,
        "next_city": next_city,
    }
    send_telegram_report(qualified_leads, city, stats)

    # Update state (track domains, not just URLs)
    state["city_index"] = (city_index + 1) % len(CITIES)
    known_domains = state.get("known_domains", [])
    for lead in enriched_leads:
        if lead.get("domain"):
            known_domains.append(lead["domain"])
    state["known_domains"] = known_domains[-300:]
    known_urls = state.get("known_urls", [])
    known_urls.extend(candidate_urls)
    state["known_urls"] = known_urls[-500:]
    save_state(state)

    log("\n" + "=" * 60)
    log(f"PIPELINE v3 COMPLETE — City: {city} | Found: {len(enriched_leads)} | Inserted: {inserted} | Score>=3: {len(qualified_leads)}")
    log("=" * 60)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        log(f"FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(0)
