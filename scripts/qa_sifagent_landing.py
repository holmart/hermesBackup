#!/usr/bin/env python3
"""
Exploracion y QA de la landing page de SIF Agent
Screenshots por seccion y analisis visual
"""

import asyncio
import os
from datetime import datetime
from playwright.async_api import async_playwright

OUTPUT_DIR = "/home/ubuntu/.hermes/qa_output"
BASE_URL = "https://www.sifagent.co/"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

async def screenshot(page, name):
    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=False)
    log(f"Screenshot: {path}")
    return path

async def screenshot_full(page, name):
    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    log(f"Screenshot full: {path}")
    return path

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # Capturar console logs
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console_logs.append(f"[PAGE_ERROR] {err}"))

        # === 1. HOME / HERO ===
        log("Navegando a landing...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await asyncio.sleep(3)
        
        # Verificar si hay cookie banner o popup
        try:
            cookie_btns = await page.query_selector_all("button")
            for btn in cookie_btns:
                text = await btn.inner_text()
                if any(k in text.lower() for k in ["aceptar", "acepto", "continuar", "cerrar", "ok", "entendido"]):
                    log(f"Click en popup/banner: {text}")
                    await btn.click()
                    await asyncio.sleep(1)
                    break
        except:
            pass
        
        await screenshot_full(page, "landing_01_hero_full")
        
        # Scroll por secciones
        viewport_height = 800
        total_height = await page.evaluate("document.body.scrollHeight")
        scrolls = int(total_height / viewport_height) + 1
        
        for i in range(scrolls):
            await page.evaluate(f"window.scrollTo(0, {i * viewport_height})")
            await asyncio.sleep(1.5)
            await screenshot(page, f"landing_scroll_{i+1}")
        
        # Volver arriba
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)
        
        # === 2. NAVEGACION Y LINKS ===
        log("Analizando navegacion y links...")
        links = await page.query_selector_all("a")
        link_data = []
        for link in links:
            text = await link.inner_text()
            href = await link.get_attribute("href")
            if text.strip():
                link_data.append((text.strip()[:50], href))
        
        # === 3. CTA BUTTONS ===
        log("Analizando botones CTA...")
        buttons = await page.query_selector_all("button, a[class*='cta'], a[class*='button'], a[class*='btn']")
        cta_data = []
        for btn in buttons:
            text = await btn.inner_text()
            href = await btn.get_attribute("href")
            if text.strip():
                cta_data.append((text.strip()[:50], href))
        
        # === 4. FORMULARIOS (si hay) ===
        log("Buscando formularios...")
        forms = await page.query_selector_all("form")
        form_data = []
        for form in forms:
            inputs = await form.query_selector_all("input, textarea, select")
            form_fields = []
            for inp in inputs:
                itype = await inp.get_attribute("type") or "text"
                iplaceholder = await inp.get_attribute("placeholder") or ""
                iname = await inp.get_attribute("name") or ""
                form_fields.append(itype + (f"({iplaceholder})" if iplaceholder else ""))
            form_data.append(form_fields)
        
        # === 5. PERFORMANCE BASICO ===
        log("Midiendo performance...")
        perf = await page.evaluate("""
            () => {
                const nav = performance.getEntriesByType('navigation')[0];
                if (nav) {
                    return {
                        domContentLoaded: nav.domContentLoadedEventEnd - nav.domContentLoadedEventStart,
                        loadComplete: nav.loadEventEnd - nav.loadEventStart,
                        responseTime: nav.responseEnd - nav.responseStart,
                        totalTime: nav.loadEventEnd - nav.startTime
                    };
                }
                return null;
            }
        """)
        
        # === 6. SEO BASICO ===
        log("Extrayendo datos SEO...")
        seo = await page.evaluate("""
            () => {
                return {
                    title: document.title,
                    description: document.querySelector('meta[name="description"]')?.content || '',
                    h1: Array.from(document.querySelectorAll('h1')).map(h => h.innerText.trim()),
                    h2: Array.from(document.querySelectorAll('h2')).map(h => h.innerText.trim()).slice(0, 10),
                    canonical: document.querySelector('link[rel="canonical"]')?.href || '',
                    ogImage: document.querySelector('meta[property="og:image"]')?.content || ''
                };
            }
        """)
        
        # === 7. RESPONSIVE - Mobile viewport ===
        log("Simulando viewport movil...")
        await page.set_viewport_size({"width": 375, "height": 812})
        await page.reload(wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot_full(page, "landing_mobile_full")
        
        # === 8. Console errors ===
        errors = [l for l in console_logs if l.startswith("[error]") or l.startswith("[PAGE_ERROR]")]
        warnings = [l for l in console_logs if l.startswith("[warning]")]
        
        # === REPORTE ===
        with open(os.path.join(OUTPUT_DIR, "landing_analysis.md"), "w") as f:
            f.write("# Analisis Landing Page - SIF Agent\n\n")
            f.write(f"**URL:** {BASE_URL}\n")
            f.write(f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            
            f.write("## Resumen Ejecutivo\n\n")
            if perf:
                f.write(f"- **Tiempo de carga total:** {perf.get('totalTime', 'N/A'):.0f}ms\n")
                f.write(f"- **DOM Content Loaded:** {perf.get('domContentLoaded', 'N/A'):.0f}ms\n")
                f.write(f"- **Load complete:** {perf.get('loadComplete', 'N/A'):.0f}ms\n")
            f.write(f"- **Links encontrados:** {len(link_data)}\n")
            f.write(f"- **CTAs encontrados:** {len(cta_data)}\n")
            f.write(f"- **Errores JS:** {len(errors)}\n")
            f.write(f"- **Warnings JS:** {len(warnings)}\n\n")
            
            f.write("## SEO\n\n")
            f.write(f"**Title:** {seo.get('title', 'N/A')}\n\n")
            f.write(f"**Meta Description:** {seo.get('description', 'N/A') or '**No encontrada**'}\n\n")
            f.write(f"**Canonical:** {seo.get('canonical', 'N/A') or '**No encontrada**'}\n\n")
            f.write(f"**OG Image:** {seo.get('ogImage', 'N/A') or '**No encontrada**'}\n\n")
            
            f.write("### Headings H1\n")
            for h in seo.get('h1', []):
                f.write(f"- {h}\n")
            f.write("\n")
            
            f.write("### Headings H2\n")
            for h in seo.get('h2', []):
                f.write(f"- {h}\n")
            f.write("\n")
            
            f.write("## Navegacion\n\n")
            seen_links = set()
            for text, href in link_data[:30]:
                key = text + str(href)
                if key not in seen_links:
                    f.write(f"- [{text}]({href})\n")
                    seen_links.add(key)
            f.write("\n")
            
            f.write("## CTAs / Botones de Accion\n\n")
            seen_ctas = set()
            for text, href in cta_data:
                key = text + str(href)
                if key not in seen_ctas:
                    f.write(f"- **{text}** -> {href or 'N/A'}\n")
                    seen_ctas.add(key)
            f.write("\n")
            
            if form_data:
                f.write("## Formularios\n\n")
                for i, fields in enumerate(form_data):
                    f.write(f"### Formulario {i+1}\n")
                    for field in fields:
                        f.write(f"- {field}\n")
                    f.write("\n")
            
            if errors:
                f.write("## Errores JavaScript\n\n")
                for e in errors[:10]:
                    f.write(f"- `{e}`\n")
                f.write("\n")
            
            if warnings:
                f.write("## Warnings JavaScript\n\n")
                for w in warnings[:10]:
                    f.write(f"- `{w}`\n")
                f.write("\n")
            
            f.write("## Screenshots Generados\n\n")
            f.write("| Archivo | Descripcion |\n")
            f.write("|---------|-------------|\n")
            f.write("| landing_01_hero_full.png | Vista completa desktop |\n")
            f.write("| landing_mobile_full.png | Vista completa mobile |\n")
            for i in range(scrolls):
                f.write(f"| landing_scroll_{i+1}.png | Scroll seccion {i+1} |\n")
            f.write("\n")
            
            f.write("---\n*Analisis generado por Hermes Agent QA*\n")
        
        log(f"Reporte guardado: {OUTPUT_DIR}/landing_analysis.md")
        log(f"Errores JS: {len(errors)}, Warnings: {len(warnings)}")
        
        await browser.close()

asyncio.run(main())
