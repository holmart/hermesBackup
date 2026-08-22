#!/usr/bin/env python3
"""
Documentacion Configuracion - usando el metodo que SI funciono
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

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})

        await page.goto(BASE_URL, wait_until="networkidle")
        await page.fill("input[type='email']", EMAIL)
        await page.fill("input[type='password']", PASSWORD)
        await page.click("button:has-text('Ingresar')")
        await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
        await asyncio.sleep(2)
        try: await page.click("button:has-text('Entendido')", timeout=2000)
        except: pass

        await page.goto(BASE_URL + "settings", wait_until="networkidle")
        await asyncio.sleep(3)

        # Obtener tabs usando el metodo que funciono antes
        all_nav_buttons = await page.query_selector_all("nav button")
        # Los tabs de config estan despues del sidebar (indices 9+)
        tab_buttons = []
        for btn in all_nav_buttons[8:]:
            text = await btn.inner_text()
            text = text.strip()
            if text and text != '<<' and len(text) < 30 and text not in ['Dashboard', 'Ordenes de Trabajo', 'Agenda', 'Clientes', 'Activos', 'Analytics', 'Equipo', 'Configuracion']:
                tab_buttons.append((text, btn))
                log(f"Tab: '{text}'")

        report = {}

        for tab_name, tab_btn in tab_buttons:
            log(f"\n{'='*50}")
            log(f"TAB: {tab_name}")
            log(f"{'='*50}")
            
            try:
                await tab_btn.click()
                await asyncio.sleep(2)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(1)
                
                path = os.path.join(OUTPUT_DIR, f"cfg_{tab_name.lower().replace(' ', '_').replace('/', '_')}.png")
                await page.screenshot(path=path, full_page=True)
                log(f"Screenshot: {path}")
                
                data = await page.evaluate("""
                    () => {
                        const main = document.querySelector('main') || document.body;
                        const r = { headings: [], texts: [], fields: [], buttons: [] };
                        
                        main.querySelectorAll('h1, h2, h3, h4').forEach(el => {
                            const t = el.innerText.trim();
                            if (t && t.length < 100) r.headings.push(t);
                        });
                        
                        main.querySelectorAll('p').forEach(el => {
                            const t = el.innerText.trim();
                            if (t && t.length > 10 && t.length < 300) r.texts.push(t);
                        });
                        
                        main.querySelectorAll('input, select, textarea').forEach(el => {
                            const lbl = el.closest('label') || document.querySelector(`label[for="${el.id}"]`);
                            const label = lbl ? lbl.innerText.trim().substring(0, 60) : (el.placeholder || el.name || el.type);
                            r.fields.push({
                                label: label,
                                type: el.type || el.tagName.toLowerCase(),
                                required: el.required,
                                value: (el.value || '').substring(0, 40),
                                placeholder: el.placeholder || ''
                            });
                        });
                        
                        main.querySelectorAll('button').forEach(el => {
                            const t = el.innerText.trim();
                            if (t && t.length < 80 && !['Dashboard', 'Ordenes de Trabajo', 'Agenda', 'Clientes', 'Activos', 'Analytics', 'Equipo', 'Configuracion', '<<'].some(x => t.includes(x))) {
                                r.buttons.push(t);
                            }
                        });
                        
                        return r;
                    }
                """)
                
                report[tab_name] = data
                log(f"  Headings: {len(data['headings'])}, Fields: {len(data['fields'])}, Buttons: {len(data['buttons'])}")
                
            except Exception as e:
                log(f"  ERROR: {e}")
                report[tab_name] = {"error": str(e)}

        with open(os.path.join(OUTPUT_DIR, "CONFIGURACION_DOCUMENTADA.md"), "w") as f:
            f.write("# Modulo Configuracion - SIF Agent Staging\n\n")
            f.write(f"**Explorado:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write("---\n\n")
            
            f.write("## Tabs Disponibles\n\n")
            for name in report.keys():
                anchor = name.lower().replace(' ', '-').replace('/', '')
                f.write(f"- [{name}](#{anchor})\n")
            f.write("\n---\n\n")
            
            for name, data in report.items():
                anchor = name.lower().replace(' ', '-').replace('/', '')
                f.write(f"## {name}\n\n")
                
                if "error" in data:
                    f.write(f"❌ Error: {data['error']}\n\n")
                    continue
                
                if data['headings']:
                    f.write("### Secciones\n")
                    for h in data['headings']:
                        if h: f.write(f"- **{h}**\n")
                    f.write("\n")
                
                if data['texts']:
                    f.write("### Descripciones\n")
                    for t in data['texts'][:5]:
                        if t: f.write(f"> {t}\n\n")
                
                if data['fields']:
                    f.write("### Campos\n\n")
                    f.write("| Campo | Tipo | Requerido | Valor/Placeholder |\n")
                    f.write("|-------|------|-----------|-------------------|\n")
                    seen = set()
                    for fld in data['fields']:
                        key = fld['label'] + fld['type']
                        if key not in seen:
                            req = "Si" if fld['required'] else "No"
                            val = fld['value'] or fld['placeholder'] or '-'
                            f.write(f"| {fld['label']} | {fld['type']} | {req} | {val} |\n")
                            seen.add(key)
                    f.write("\n")
                
                if data['buttons']:
                    f.write("### Acciones\n")
                    seen = set()
                    for b in data['buttons']:
                        if b not in seen:
                            f.write(f"- `{b}`\n")
                            seen.add(b)
                    f.write("\n")
                
                f.write("---\n\n")
        
        log(f"\n✅ Documento generado: CONFIGURACION_DOCUMENTADA.md")
        await browser.close()

asyncio.run(main())
