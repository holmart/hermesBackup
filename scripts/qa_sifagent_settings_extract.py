#!/usr/bin/env python3
"""
Extraer HTML de settings para analizar tabs
"""
import asyncio
from playwright.async_api import async_playwright

BASE_URL = "https://app-staging.sifagent.co/"
EMAIL = "Cliente1@sifagent.co"
PASSWORD = "History1*"

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
        try:
            await page.click("button:has-text('Entendido')", timeout=2000)
        except:
            pass

        await page.goto(BASE_URL + "settings", wait_until="networkidle")
        await asyncio.sleep(3)

        # Extraer todos los elementos que parecen tabs
        tabs_data = await page.evaluate("""
            () => {
                const results = [];
                
                // Buscar por role=tab
                document.querySelectorAll('[role="tab"]').forEach((el, i) => {
                    results.push({type: 'role=tab', index: i, text: el.innerText.trim(), className: el.className, tagName: el.tagName});
                });
                
                // Buscar botones dentro de nav
                document.querySelectorAll('nav button, nav a').forEach((el, i) => {
                    results.push({type: 'nav-child', index: i, text: el.innerText.trim(), className: el.className, tagName: el.tagName});
                });
                
                // Buscar elementos con aria-selected
                document.querySelectorAll('[aria-selected]').forEach((el, i) => {
                    results.push({type: 'aria-selected', index: i, text: el.innerText.trim(), selected: el.getAttribute('aria-selected'), className: el.className});
                });
                
                // Buscar por clases que contengan tab
                document.querySelectorAll('[class*="tab"]').forEach((el, i) => {
                    results.push({type: 'class-tab', index: i, text: el.innerText.trim(), className: el.className, tagName: el.tagName});
                });
                
                // Buscar headings en el contenido
                const headings = [];
                document.querySelectorAll('h1, h2, h3, h4').forEach(el => {
                    headings.push(el.innerText.trim());
                });
                
                return {tabs: results, headings: headings};
            }
        """)
        
        print("=== TABS ENCONTRADOS ===")
        for t in tabs_data['tabs']:
            if t['text']:
                print(f"  [{t['type']}] '{t['text']}' (class={t.get('className','')[:50]})")
        
        print("\n=== HEADINGS ===")
        for h in tabs_data['headings']:
            print(f"  {h}")

        # Guardar HTML parcial para inspeccion
        html = await page.content()
        with open("/home/ubuntu/.hermes/qa_output/settings_html_snippet.txt", "w") as f:
            f.write(html[:10000])
        print("\nHTML guardado en settings_html_snippet.txt")

        await browser.close()

asyncio.run(main())
