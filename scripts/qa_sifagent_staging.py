#!/usr/bin/env python3
"""
QA Testing Script para SIF Agent Staging
Navega, hace login, y prueba funcionalidades clave.
Genera screenshots como evidencia.
"""

import asyncio
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright, expect

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

        # Capturar console logs y errores
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console_logs.append(f"[PAGE_ERROR] {err}"))

        # === PASO 1: LOGIN ===
        log("Navegando a login...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await screenshot(page, "01_login_page")

        # Llenar credenciales con selectores mas flexibles
        await page.fill("input[type='email']", EMAIL)
        await page.fill("input[type='password']", PASSWORD)
        await screenshot(page, "02_login_filled")

        # Click en boton Ingresar usando texto
        log("Haciendo click en Ingresar...")
        await page.click("button:has-text('Ingresar')")
        
        # Esperar a que la URL cambie o a que aparezca dashboard
        try:
            await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
            log("URL cambio despues del login")
        except:
            log("URL no cambio, esperando elementos de dashboard...")
            await asyncio.sleep(5)
        
        await screenshot(page, "03_post_login")

        # Verificar si hay error de login visible
        error_selectors = ["[role='alert']", ".error", ".text-red", ".text-red-500", ".MuiAlert-root"]
        error_found = None
        for sel in error_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    error_found = await el.inner_text()
                    break
            except:
                continue
        
        if error_found:
            log(f"ERROR DE LOGIN: {error_found}")
            await browser.close()
            sys.exit(1)

        current_url = page.url
        log(f"URL actual: {current_url}")

        if "/login" in current_url:
            log("ADVERTENCIA: Todavia en pagina de login. Revisando si hay contenido nuevo...")
            # Puede ser SPA que no cambio URL, revisar si aparecio contenido
            await asyncio.sleep(3)
            await screenshot(page, "03b_post_login_wait")

        log("Login procesado")

        # === PASO 2: DASHBOARD / NAVEGACION ===
        await screenshot(page, "04_dashboard")

        # Listar todos los links y botones visibles
        all_links = await page.query_selector_all("a, button, [role='button']")
        links_text = []
        for link in all_links:
            text = await link.inner_text()
            href = await link.get_attribute("href") or ""
            if text.strip():
                links_text.append((text.strip(), href))
        
        log(f"Elementos interactivos encontrados: {len(links_text)}")
        for text, href in links_text[:30]:  # Limitar output
            print(f"  - '{text}' -> {href}")

        # Guardar HTML para debug
        html = await page.content()
        with open(os.path.join(OUTPUT_DIR, "dashboard_html_snippet.txt"), "w") as f:
            f.write(html[:5000])
        log("HTML guardado para debug")

        # === PASO 3: ORDENES DE TRABAJO ===
        log("Buscando Ordenes de Trabajo...")
        orden_link = None
        for text, href in links_text:
            lower = text.lower()
            if any(k in lower for k in ["orden", "ordenes", "trabajo", "work order", "servicio", "tickets", "service"]):
                orden_link = href
                log(f"Link ordenes encontrado: '{text}' -> {href}")
                break

        if orden_link:
            full_url = orden_link if orden_link.startswith("http") else BASE_URL + orden_link.lstrip("/")
            await page.goto(full_url, wait_until="networkidle")
            await asyncio.sleep(3)
            await screenshot(page, "05_ordenes_list")
            log("Pagina de ordenes cargada")

            # Buscar boton crear orden
            buttons = await page.query_selector_all("button")
            for btn in buttons:
                btext = await btn.inner_text()
                if any(k in btext.lower() for k in ["crear", "nueva", "nuevo", "agregar", "+", "add", "new"]):
                    log(f"Boton crear encontrado: '{btext}'")
                    await btn.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(3)
                    await screenshot(page, "06_crear_orden_form")
                    log("Formulario crear orden abierto")

                    # Listar inputs del formulario
                    inputs = await page.query_selector_all("input, textarea, select")
                    log(f"Inputs en formulario: {len(inputs)}")
                    for inp in inputs:
                        itype = await inp.get_attribute("type") or "text"
                        iname = await inp.get_attribute("name") or ""
                        iplaceholder = await inp.get_attribute("placeholder") or ""
                        ilabel = await inp.get_attribute("aria-label") or ""
                        print(f"    Input: type={itype} name={iname} placeholder={iplaceholder} aria-label={ilabel}")
                    break
        else:
            log("No se encontro link a ordenes de trabajo")

        # === PASO 4: CONTRATOS ===
        log("Buscando Contratos...")
        contrato_link = None
        for text, href in links_text:
            lower = text.lower()
            if any(k in lower for k in ["contrato", "contratos", "recurrente", "suscripcion", "subscription", "recurring"]):
                contrato_link = href
                log(f"Link contratos encontrado: '{text}' -> {href}")
                break

        if contrato_link:
            full_url = contrato_link if contrato_link.startswith("http") else BASE_URL + contrato_link.lstrip("/")
            await page.goto(full_url, wait_until="networkidle")
            await asyncio.sleep(3)
            await screenshot(page, "08_contratos_list")
            log("Pagina de contratos cargada")
        else:
            log("No se encontro link a contratos")

        # === PASO 5: INVENTARIO ===
        log("Buscando Inventario...")
        inv_link = None
        for text, href in links_text:
            lower = text.lower()
            if any(k in lower for k in ["inventario", "stock", "producto", "material", "insumo", "inventory"]):
                inv_link = href
                log(f"Link inventario encontrado: '{text}' -> {href}")
                break

        if inv_link:
            full_url = inv_link if inv_link.startswith("http") else BASE_URL + inv_link.lstrip("/")
            await page.goto(full_url, wait_until="networkidle")
            await asyncio.sleep(3)
            await screenshot(page, "09_inventario")
            log("Pagina de inventario cargada")
        else:
            log("No se encontro link a inventario")

        # === PASO 6: MALETA VIRTUAL ===
        log("Buscando Maleta Virtual...")
        maleta_link = None
        for text, href in links_text:
            lower = text.lower()
            if any(k in lower for k in ["maleta", "kit", "herramienta", "equipo", "tecnico", "technician", "toolkit", "virtual bag"]):
                maleta_link = href
                log(f"Link maleta encontrado: '{text}' -> {href}")
                break

        if maleta_link:
            full_url = maleta_link if maleta_link.startswith("http") else BASE_URL + maleta_link.lstrip("/")
            await page.goto(full_url, wait_until="networkidle")
            await asyncio.sleep(3)
            await screenshot(page, "10_maleta_virtual")
            log("Pagina de maleta virtual cargada")
        else:
            log("No se encontro link a maleta virtual")

        # === PASO 7: TECNICOS ===
        log("Buscando Tecnicos...")
        tec_link = None
        for text, href in links_text:
            lower = text.lower()
            if any(k in lower for k in ["tecnico", "tecnicos", "empleado", "staff", "asignar", "technician", "employee", "team"]):
                tec_link = href
                log(f"Link tecnicos encontrado: '{text}' -> {href}")
                break

        if tec_link:
            full_url = tec_link if tec_link.startswith("http") else BASE_URL + tec_link.lstrip("/")
            await page.goto(full_url, wait_until="networkidle")
            await asyncio.sleep(3)
            await screenshot(page, "11_tecnicos")
            log("Pagina de tecnicos cargada")
        else:
            log("No se encontro link a tecnicos")

        # === CONSOLE LOGS ===
        log(f"Console logs capturados: {len(console_logs)}")
        for log_entry in console_logs[:20]:
            print(f"  {log_entry}")

        await browser.close()
        log(f"QA finalizado. Screenshots en: {OUTPUT_DIR}")
        return OUTPUT_DIR

if __name__ == "__main__":
    asyncio.run(main())
