#!/usr/bin/env python3
"""
QA Testing Script Deep Dive para SIF Agent Staging
Continua despues del login. Prueba crear OT, contratos, activos, equipo.
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

        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console_logs.append(f"[PAGE_ERROR] {err}"))

        # === LOGIN ===
        log("Login...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.fill("input[type='email']", EMAIL)
        await page.fill("input[type='password']", PASSWORD)
        await page.click("button:has-text('Ingresar')")
        await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
        await asyncio.sleep(3)
        log(f"Login exitoso. URL: {page.url}")

        # Cerrar modal de novedades si existe
        try:
            await page.click("button:has-text('Entendido')", timeout=3000)
            log("Modal de novedades cerrado")
            await asyncio.sleep(1)
        except:
            log("No habia modal de novedades")

        await screenshot(page, "04b_dashboard_sin_modal")

        # === 1. CREAR ORDEN DE TRABAJO ===
        log("=== CREAR ORDEN DE TRABAJO ===")
        await page.goto(BASE_URL + "work-orders/create", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "12_crear_ot_form")

        # Listar todos los inputs del formulario
        inputs = await page.query_selector_all("input, textarea, select")
        log(f"Inputs en formulario OT: {len(inputs)}")
        for inp in inputs:
            itype = await inp.get_attribute("type") or "text"
            iname = await inp.get_attribute("name") or ""
            iplaceholder = await inp.get_attribute("placeholder") or ""
            ilabel = await inp.get_attribute("aria-label") or ""
            required = await inp.get_attribute("required")
            req_str = " (required)" if required else ""
            print(f"    {iname or iplaceholder or ilabel or itype}{req_str}")

        # Intentar llenar el formulario
        try:
            # Buscar cliente
            await page.fill("input[placeholder*='cliente' i], input[name*='client' i], input[placeholder*='buscar' i]", "Cliente QA")
            await asyncio.sleep(1)
            # Si hay dropdown, seleccionar primera opcion
            try:
                await page.click("[role='option']:first-child, li:first-child", timeout=2000)
            except:
                pass
        except Exception as e:
            log(f"No se pudo llenar cliente: {e}")

        try:
            await page.fill("textarea[name*='description' i], textarea[placeholder*='descripcion' i], textarea[placeholder*='nota' i]", "Orden de prueba QA automatizado")
        except Exception as e:
            log(f"No se pudo llenar descripcion: {e}")

        try:
            await page.fill("input[placeholder*='direccion' i], input[name*='address' i], input[name*='location' i]", "Calle 123 #45-67, Bogota")
        except Exception as e:
            log(f"No se pudo llenar direccion: {e}")

        await screenshot(page, "13_ot_form_llenado")

        # Buscar boton Guardar/Crear
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            btext = await btn.inner_text()
            if any(k in btext.lower() for k in ["guardar", "crear", "salvar", "save", "create", "submit"]):
                log(f"Boton encontrado: '{btext}'")
                # No hacemos click para no crear datos basura en staging
                break

        # === 2. VER TECNICOS (Equipo) ===
        log("=== VER TECNICOS (Equipo) ===")
        await page.goto(BASE_URL + "team", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "14_team_tecnicos")

        # Listar tecnicos
        rows = await page.query_selector_all("table tr, [role='row']")
        log(f"Filas en equipo: {len(rows)}")
        for row in rows[:5]:
            text = await row.inner_text()
            if text.strip():
                print(f"    {text.strip()[:80]}")

        # === 3. VER CONTRATOS ===
        log("=== VER CONTRATOS ===")
        await page.goto(BASE_URL + "contracts", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "15_contratos")

        # Buscar boton crear contrato
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            btext = await btn.inner_text()
            if any(k in btext.lower() for k in ["contrato", "nuevo", "crear", "+", "new"]):
                log(f"Boton contratos: '{btext}'")
                break

        # === 4. VER ACTIVOS (Inventario) ===
        log("=== VER ACTIVOS (Inventario) ===")
        await page.goto(BASE_URL + "assets", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "16_activos_inventario")

        # Listar activos
        rows = await page.query_selector_all("table tr, [role='row']")
        log(f"Filas en activos: {len(rows)}")
        for row in rows[:5]:
            text = await row.inner_text()
            if text.strip():
                print(f"    {text.strip()[:80]}")

        # === 5. MALETA VIRTUAL ===
        log("=== MALETA VIRTUAL ===")
        # Buscar en la pagina de equipo o en settings
        await page.goto(BASE_URL + "team", wait_until="networkidle")
        await asyncio.sleep(3)
        
        # Buscar link o boton de maleta virtual / toolkit
        all_links = await page.query_selector_all("a, button")
        maleta_found = False
        for link in all_links:
            text = await link.inner_text()
            lower = text.lower()
            if any(k in lower for k in ["maleta", "kit", "herramienta", "toolkit", "virtual", "bag", "insumos"]):
                log(f"Link maleta: '{text}'")
                maleta_found = True
                break
        
        if not maleta_found:
            log("No se encontro link explicito a maleta virtual en /team")
        
        await screenshot(page, "17_maleta_virtual_check")

        # === 6. AGENDA ===
        log("=== AGENDA ===")
        await page.goto(BASE_URL + "schedule", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "18_agenda")

        # === 7. ANALYTICS ===
        log("=== ANALYTICS ===")
        await page.goto(BASE_URL + "analytics", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "19_analytics")

        # === CONSOLE LOGS ===
        log(f"Console logs totales: {len(console_logs)}")
        errors = [l for l in console_logs if l.startswith("[error]") or l.startswith("[PAGE_ERROR]")]
        if errors:
            log(f"ERRORES ENCONTRADOS: {len(errors)}")
            for e in errors[:10]:
                print(f"    {e}")
        else:
            log("Sin errores de consola")

        await browser.close()
        log(f"QA Deep Dive finalizado. Screenshots en: {OUTPUT_DIR}")

if __name__ == "__main__":
    asyncio.run(main())
