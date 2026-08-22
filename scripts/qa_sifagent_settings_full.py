#!/usr/bin/env python3
"""
Documentacion completa del modulo Configuracion de SIF Agent Staging
Explora cada tab y documenta campos, botones y funcionalidades
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
        page = await browser.new_page(viewport={"width": 1280, "height": 900})

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
        await asyncio.sleep(3)

        # Los tabs son botones dentro del nav con clase especifica
        # Excluimos los del sidebar principal (los primeros 9)
        all_nav_buttons = await page.query_selector_all("nav button")
        # Los tabs de config estan al final del nav
        tab_buttons = all_nav_buttons[9:]  # Skip sidebar items
        
        tabs = []
        for btn in tab_buttons:
            text = await btn.inner_text()
            text = text.strip()
            if text and text != '<<' and len(text) < 30:
                tabs.append(btn)
                log(f"Tab encontrado: '{text}'")

        report = {}

        for tab_btn in tabs:
            tab_name = await tab_btn.inner_text()
            tab_name = tab_name.strip()
            
            log(f"\n{'='*60}")
            log(f"TAB: {tab_name}")
            log(f"{'='*60}")
            
            await tab_btn.click()
            await asyncio.sleep(2)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)
            
            await screenshot(page, f"cfg_{tab_name.lower().replace(' ', '_').replace('/', '_')}")
            
            # Extraer contenido
            content = await page.evaluate("""
                () => {
                    const data = {
                        headings: [],
                        paragraphs: [],
                        fields: [],
                        buttons: [],
                        lists: [],
                        tables: []
                    };
                    
                    // Headings
                    document.querySelectorAll('h1, h2, h3, h4').forEach(el => {
                        const text = el.innerText.trim();
                        if (text && text.length < 100) data.headings.push(text);
                    });
                    
                    // Parrafos descriptivos
                    document.querySelectorAll('p, [class*="description"], [class*="text-sm"]').forEach(el => {
                        const text = el.innerText.trim();
                        if (text && text.length > 10 && text.length < 300 && !data.paragraphs.includes(text)) {
                            data.paragraphs.push(text);
                        }
                    });
                    
                    // Inputs, selects, textareas (solo dentro del main content, no sidebar)
                    const main = document.querySelector('main') || document.body;
                    main.querySelectorAll('input, select, textarea').forEach(el => {
                        const label = document.querySelector(`label[for="${el.id}"]`);
                        const labelText = label ? label.innerText.trim() : '';
                        const placeholder = el.placeholder || '';
                        const type = el.type || el.tagName.toLowerCase();
                        const value = el.value || '';
                        const required = el.required;
                        const name = el.name || '';
                        
                        // Buscar label cercano
                        let nearbyLabel = labelText;
                        if (!nearbyLabel) {
                            const parent = el.closest('label');
                            if (parent) nearbyLabel = parent.innerText.trim().substring(0, 50);
                        }
                        if (!nearbyLabel) {
                            const prev = el.previousElementSibling;
                            if (prev && prev.tagName === 'LABEL') nearbyLabel = prev.innerText.trim();
                        }
                        
                        data.fields.push({
                            label: nearbyLabel || placeholder || name || type,
                            type: type,
                            required: required,
                            value: value.substring(0, 50),
                            placeholder: placeholder
                        });
                    });
                    
                    // Botones principales (excluir sidebar)
                    main.querySelectorAll('button').forEach(el => {
                        const text = el.innerText.trim();
                        if (text && text.length < 80 && !text.includes('Dashboard') && !text.includes('Ordenes') && !text.includes('Clientes')) {
                            data.buttons.push(text);
                        }
                    });
                    
                    // Listas
                    document.querySelectorAll('ul, ol').forEach(el => {
                        const items = Array.from(el.querySelectorAll('li')).map(li => li.innerText.trim()).filter(t => t);
                        if (items.length > 0) data.lists.push(items);
                    });
                    
                    return data;
                }
            """)
            
            report[tab_name] = content
            
            log(f"  Headings: {len(content['headings'])}")
            log(f"  Fields: {len(content['fields'])}")
            log(f"  Buttons: {len(content['buttons'])}")
            for f in content['fields'][:8]:
                req = " *" if f['required'] else ""
                log(f"    - {f['label']}{req} ({f['type']})")

        # Generar reporte markdown
        with open(os.path.join(OUTPUT_DIR, "CONFIGURACION_COMPLETA.md"), "w") as f:
            f.write("# Documentacion Completa: Modulo Configuracion - SIF Agent Staging\n\n")
            f.write(f"**Fecha de exploracion:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"**URL Base:** {BASE_URL}settings\n\n")
            f.write("---\n\n")
            
            f.write("## Tabs Disponibles\n\n")
            for tab_name in report.keys():
                anchor = tab_name.lower().replace(' ', '-').replace('/', '')
                f.write(f"- [{tab_name}](#{anchor})\n")
            f.write("\n---\n\n")
            
            for tab_name, data in report.items():
                anchor = tab_name.lower().replace(' ', '-').replace('/', '')
                f.write(f"## {tab_name}\n\n")
                f.write(f"**Screenshot:** `cfg_{tab_name.lower().replace(' ', '_').replace('/', '_')}.png`\n\n")
                
                if data['headings']:
                    f.write("### Secciones\n\n")
                    for h in data['headings']:
                        if h:
                            f.write(f"- **{h}**\n")
                    f.write("\n")
                
                if data['paragraphs']:
                    f.write("### Descripciones\n\n")
                    for p in data['paragraphs'][:5]:
                        if p and len(p) > 5:
                            f.write(f"> {p}\n\n")
                
                if data['fields']:
                    f.write("### Campos y Opciones\n\n")
                    f.write("| Campo | Tipo | Requerido | Valor/Placeholder |\n")
                    f.write("|-------|------|-----------|-------------------|\n")
                    seen = set()
                    for field in data['fields']:
                        key = field['label'] + field['type']
                        if key not in seen:
                            req = "Si" if field['required'] else "No"
                            val = field['value'] or field['placeholder'] or '-'
                            f.write(f"| {field['label']} | {field['type']} | {req} | {val} |\n")
                            seen.add(key)
                    f.write("\n")
                
                if data['buttons']:
                    f.write("### Botones y Acciones\n\n")
                    seen_btns = set()
                    for btn in data['buttons']:
                        if btn not in seen_btns and len(btn) < 80:
                            f.write(f"- `{btn}`\n")
                            seen_btns.add(btn)
                    f.write("\n")
                
                if data['lists']:
                    f.write("### Listas/Items\n\n")
                    for lst in data['lists'][:2]:
                        for item in lst[:10]:
                            f.write(f"- {item}\n")
                        f.write("\n")
                
                f.write("---\n\n")
        
        log(f"\n\u2705 Reporte completo guardado: {OUTPUT_DIR}/CONFIGURACION_COMPLETA.md")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
