#!/usr/bin/env python3
"""
Exploracion exhaustiva de modulos en SIF Agent Staging
Documenta como llegar a cada funcionalidad
"""

import asyncio
import os
from datetime import datetime
from playwright.async_api import async_playwright

OUTPUT_DIR = "/home/ubuntu/.hermes/qa_output"
BASE_URL = "https://app-staging.sifagent.co/"
EMAIL = "Cliente1@sifagent.co"
PASSWORD = "History1*"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

async def screenshot(page, name):
    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    log(f"Screenshot: {path}")
    return path

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # Login
        log("Login...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.fill("input[type='email']", EMAIL)
        await page.fill("input[type='password']", PASSWORD)
        await page.click("button:has-text('Ingresar')")
        await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
        await asyncio.sleep(2)
        try:
            await page.click("button:has-text('Entendido')", timeout=2000)
        except:
            pass
        log("Login exitoso")

        # Obtener todos los links de navegacion del sidebar
        log("=== NAV PRINCIPAL ===")
        await page.goto(BASE_URL + "dashboard", wait_until="networkidle")
        await asyncio.sleep(2)
        
        nav_items = await page.query_selector_all("nav a, .sidebar a, aside a, [role='navigation'] a")
        routes = {}
        for item in nav_items:
            text = await item.inner_text()
            href = await item.get_attribute("href")
            if text.strip() and href:
                routes[text.strip()] = href
                log(f"Nav: '{text.strip()}' -> {href}")

        # Explorar cada ruta principal
        modules_to_test = {
            "Dashboard": "/dashboard",
            "Ordenes de Trabajo": "/work-orders",
            "Crear OT": "/work-orders/create",
            "Agenda": "/schedule",
            "Clientes": "/customers",
            "Crear Cliente": "/customers/create",
            "Activos": "/assets",
            "Crear Activo": "/assets/create",
            "Analytics": "/analytics",
            "Equipo": "/team",
            "Invitar miembro": "/team/invite",
            "Configuracion": "/settings",
            "Contratos": "/contracts",
            "Contratos por vencer": "/contracts/expiring",
            "Crear Contrato": "/contracts/create",
            "Perfil": "/profile",
        }

        for name, path in modules_to_test.items():
            try:
                url = BASE_URL + path.lstrip("/")
                log(f"\n=== {name}: {url} ===")
                await page.goto(url, wait_until="networkidle")
                await asyncio.sleep(2)
                
                title = await page.title()
                current = page.url
                
                # Contar elementos clave
                buttons = await page.query_selector_all("button")
                tables = await page.query_selector_all("table")
                forms = await page.query_selector_all("form")
                inputs = await page.query_selector_all("input, textarea, select")
                
                # Buscar CTAs principales
                cta_texts = []
                for btn in buttons[:10]:
                    btext = await btn.inner_text()
                    if btext.strip():
                        cta_texts.append(btext.strip()[:50])
                
                log(f"  Title: {title}")
                log(f"  URL: {current}")
                log(f"  Botones: {len(buttons)}, Tablas: {len(tables)}, Forms: {len(forms)}, Inputs: {len(inputs)}")
                log(f"  CTAs: {cta_texts[:5]}")
                
                await screenshot(page, f"mod_{name.lower().replace(' ', '_').replace('/', '_')}")
                
            except Exception as e:
                log(f"  ERROR en {name}: {e}")

        # Buscar Maleta Virtual en perfil de tecnico
        log("\n=== BUSCANDO MALETA VIRTUAL ===")
        await page.goto(BASE_URL + "team", wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Click en editar del primer tecnico (Andrea Lopez)
        edit_buttons = await page.query_selector_all("button")
        for btn in edit_buttons:
            btext = await btn.inner_text()
            if "editar" in btext.lower() or "edit" in btext.lower():
                log(f"Click en: {btext}")
                await btn.click()
                await asyncio.sleep(3)
                await screenshot(page, "mod_tecnico_editar")
                
                # Verificar si hay tabs o secciones
                tabs = await page.query_selector_all("[role='tab'], .tab, [aria-selected]")
                log(f"Tabs encontradas: {len(tabs)}")
                for tab in tabs:
                    ttext = await tab.inner_text()
                    log(f"  Tab: {ttext.strip()}")
                    if any(k in ttext.lower() for k in ["maleta", "kit", "herramienta", "toolkit", "insumos", "equipo"]):
                        log(f"  >>> MALETA VIRTUAL ENCONTRADA: {ttext.strip()}")
                break

        # Buscar en Settings
        log("\n=== BUSCANDO EN SETTINGS ===")
        await page.goto(BASE_URL + "settings", wait_until="networkidle")
        await asyncio.sleep(2)
        await screenshot(page, "mod_settings")
        
        settings_links = await page.query_selector_all("a, button")
        for link in settings_links:
            text = await link.inner_text()
            if any(k in text.lower() for k in ["maleta", "kit", "herramienta", "toolkit", "insumos", "equipo", "activos", "contratos", "plantilla"]):
                log(f"  Settings link: {text.strip()}")

        # Documentar rutas de API descubiertas
        log("\n=== RUTAS DESCUBIERTAS ===")
        all_routes = {
            **routes,
            **modules_to_test,
        }
        
        with open(os.path.join(OUTPUT_DIR, "rutas_sifagent.md"), "w") as f:
            f.write("# Rutas de SIF Agent Staging\n\n")
            f.write("| Modulo | Ruta | Como llegar |\n")
            f.write("|--------|------|-------------|\n")
            for name, route in sorted(all_routes.items()):
                f.write(f"| {name} | {route} | Sidebar nav o URL directa |\n")
        
        log("Rutas guardadas en rutas_sifagent.md")

        await browser.close()
        log("Exploracion completa")

if __name__ == "__main__":
    asyncio.run(main())
