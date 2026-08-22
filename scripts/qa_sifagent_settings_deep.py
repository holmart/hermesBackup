#!/usr/bin/env python3
"""
Exploracion profunda del modulo Configuracion de SIF Agent Staging
Documenta cada tab, campo y funcionalidad
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

async def extract_form_fields(page):
    """Extrae todos los inputs, labels y valores de un formulario"""
    fields = []
    
    # Buscar inputs con labels
    labels = await page.query_selector_all("label")
    for label in labels:
        text = await label.inner_text()
        text = text.strip().replace('\n', ' ')
        
        # Buscar el input asociado
        for_attr = await label.get_attribute("for")
        input_el = None
        
        if for_attr:
            input_el = await page.query_selector(f"#{for_attr}, [name='{for_attr}']")
        else:
            # Buscar input dentro del label
            input_el = await label.query_selector("input, select, textarea")
        
        if input_el:
            itype = await input_el.get_attribute("type") or "text"
            iname = await input_el.get_attribute("name") or ""
            ivalue = await input_el.input_value() if itype != "file" else ""
            iplaceholder = await input_el.get_attribute("placeholder") or ""
            irequired = await input_el.get_attribute("required")
            disabled = await input_el.is_disabled()
            
            fields.append({
                "label": text,
                "type": itype,
                "name": iname,
                "value": ivalue,
                "placeholder": iplaceholder,
                "required": "Si" if irequired else "No",
                "disabled": "Si" if disabled else "No"
            })
    
    return fields

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
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

        # Ir a Configuracion
        await page.goto(BASE_URL + "settings", wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Obtener todos los tabs
        tabs = await page.query_selector_all("[role='tab'], button[class*='tab'], .tabs button, nav[aria-label] button")
        log(f"Tabs encontrados: {len(tabs)}")
        
        tab_info = []
        for i, tab in enumerate(tabs):
            text = await tab.inner_text()
            is_selected = await tab.get_attribute("aria-selected")
            tab_info.append({
                "index": i,
                "text": text.strip(),
                "selected": is_selected == "true"
            })
            log(f"  Tab {i}: '{text.strip()}' (selected={is_selected})")

        # Explorar cada tab
        report_data = {}
        
        for tab_data in tab_info:
            tab_name = tab_data["text"]
            tab_idx = tab_data["index"]
            
            log(f"\n{'='*60}")
            log(f"EXPLORANDO TAB: {tab_name}")
            log(f"{'='*60}")
            
            # Click en el tab
            tabs = await page.query_selector_all("[role='tab'], button[class*='tab'], .tabs button, nav[aria-label] button")
            if tab_idx < len(tabs):
                await tabs[tab_idx].click()
                await asyncio.sleep(2)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(1)
            
            await screenshot(page, f"cfg_{tab_name.lower().replace(' ', '_').replace('/', '_')}")
            
            # Extraer contenido del tab
            content = {
                "title": await page.title(),
                "url": page.url,
                "fields": [],
                "buttons": [],
                "texts": [],
                "cards": []
            }
            
            # Campos del formulario
            content["fields"] = await extract_form_fields(page)
            
            # Botones
            buttons = await page.query_selector_all("button")
            for btn in buttons:
                btext = await btn.inner_text()
                if btext.strip() and len(btext.strip()) < 100:
                    content["buttons"].append(btext.strip())
            
            # Textos principales (headings, descripciones)
            headings = await page.query_selector_all("h1, h2, h3, h4, p")
            for h in headings:
                htext = await h.inner_text()
                htext = htext.strip().replace('\n', ' ')
                if htext and len(htext) < 200 and htext not in content["texts"]:
                    content["texts"].append(htext)
            
            # Cards/contenedores
            cards = await page.query_selector_all("[class*='card'], section, fieldset")
            content["card_count"] = len(cards)
            
            report_data[tab_name] = content
            
            # Log resumen
            log(f"  Campos: {len(content['fields'])}")
            log(f"  Botones: {len(content['buttons'])}")
            for field in content['fields'][:10]:
                req = " *" if field['required'] == "Si" else ""
                log(f"    - {field['label']}{req} ({field['type']})")

        # Guardar reporte
        with open(os.path.join(OUTPUT_DIR, "configuracion_detallado.md"), "w") as f:
            f.write("# Documentacion del Modulo Configuracion - SIF Agent Staging\n\n")
            f.write(f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")
            
            f.write("## Indice de Tabs\n\n")
            for tab_name in report_data.keys():
                f.write(f"- [{tab_name}](#{tab_name.lower().replace(' ', '-').replace('/', '')})\n")
            f.write("\n---\n\n")
            
            for tab_name, data in report_data.items():
                anchor = tab_name.lower().replace(' ', '-').replace('/', '')
                f.write(f"## {tab_name}\n\n")
                f.write(f"**URL:** {data['url']}\n\n")
                
                if data['texts']:
                    f.write("**Descripcion:**\n")
                    for t in data['texts'][:5]:
                        if t:
                            f.write(f"> {t}\n")
                    f.write("\n")
                
                if data['fields']:
                    f.write("### Campos\n\n")
                    f.write("| Campo | Tipo | Requerido | Valor Actual | Placeholder |\n")
                    f.write("|-------|------|-----------|--------------|-------------|\n")
                    for field in data['fields']:
                        val = field['value'][:30] if field['value'] else '-'
                        placeholder = field['placeholder'][:30] if field['placeholder'] else '-'
                        f.write(f"| {field['label']} | {field['type']} | {field['required']} | {val} | {placeholder} |\n")
                    f.write("\n")
                
                if data['buttons']:
                    f.write("### Botones/Acciones\n\n")
                    seen = set()
                    for btn in data['buttons']:
                        if btn not in seen and len(btn) < 80:
                            f.write(f"- `{btn}`\n")
                            seen.add(btn)
                    f.write("\n")
                
                f.write("---\n\n")
        
        log(f"\nReporte guardado en: {OUTPUT_DIR}/configuracion_detallado.md")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
