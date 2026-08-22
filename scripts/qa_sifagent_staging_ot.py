#!/usr/bin/env python3
"""
QA Testing: Crear Orden de Trabajo en SIF Agent Staging
Usa selectores exactos basados en el analisis visual.
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

        # === CREAR OT ===
        log("Navegando a crear OT...")
        await page.goto(BASE_URL + "work-orders/create", wait_until="networkidle")
        await asyncio.sleep(3)
        await screenshot(page, "20_crear_ot_inicio")

        # Click en Cliente (select)
        log("Seleccionando cliente...")
        try:
            # El campo cliente parece ser un select custom o searchable
            await page.click("text=Seleccionar cliente...", timeout=5000)
            await asyncio.sleep(1)
            await screenshot(page, "21_cliente_dropdown")
            
            # Si hay opciones, intentar seleccionar la primera
            options = await page.query_selector_all("[role='option'], [role='listbox'] li, .select__option")
            if options:
                log(f"Opciones de cliente encontradas: {len(options)}")
                await options[0].click()
                log("Cliente seleccionado")
            else:
                log("No hay opciones de cliente disponibles")
        except Exception as e:
            log(f"No se pudo abrir cliente: {e}")

        await screenshot(page, "22_cliente_seleccionado")

        # Fecha programada
        log("Llenando fecha...")
        try:
            await page.fill("input[type='date']", "2026-08-25")
            log("Fecha llenada")
        except Exception as e:
            log(f"No se pudo llenar fecha: {e}")

        # Prioridad
        log("Seleccionando prioridad...")
        try:
            # Buscar el select de Prioridad
            selects = await page.query_selector_all("select")
            log(f"Selects encontrados: {len(selects)}")
            for i, sel in enumerate(selects):
                label = await sel.get_attribute("aria-label") or ""
                name = await sel.get_attribute("name") or ""
                print(f"  Select {i}: name={name} aria-label={label}")
            
            if len(selects) >= 2:
                await selects[1].select_option(index=1)  # Primera opcion despues del placeholder
                log("Prioridad seleccionada")
        except Exception as e:
            log(f"No se pudo seleccionar prioridad: {e}")

        # Tipo de servicio
        log("Seleccionando tipo de servicio...")
        try:
            if len(selects) >= 3:
                await selects[2].select_option(index=1)
                log("Tipo de servicio seleccionado")
        except Exception as e:
            log(f"No se pudo seleccionar tipo: {e}")

        # Descripcion
        log("Llenando descripcion...")
        try:
            await page.fill("textarea", "Orden de prueba QA automatizado - fumigacion en restaurante")
            log("Descripcion llenada")
        except Exception as e:
            log(f"No se pudo llenar descripcion: {e}")

        # Expandir "Mas opciones"
        log("Expandiendo mas opciones...")
        try:
            await page.click("text=+ Más opciones")
            await asyncio.sleep(2)
            await screenshot(page, "23_mas_opciones_expandido")
            log("Mas opciones expandido")
        except Exception as e:
            log(f"No se pudo expandir mas opciones: {e}")

        # Buscar campo de direccion en mas opciones
        log("Buscando direccion...")
        try:
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                placeholder = await inp.get_attribute("placeholder") or ""
                if "direccion" in placeholder.lower() or "address" in placeholder.lower():
                    await inp.fill("Calle 123 #45-67, Bogota")
                    log("Direccion llenada")
                    break
        except Exception as e:
            log(f"No se pudo llenar direccion: {e}")

        await screenshot(page, "24_ot_form_completo")

        # NO hacemos click en Crear para no generar datos basura en staging
        log("Formulario completo. NO se creo la OT (modo solo lectura QA)")

        # === ASIGNAR TECNICO ===
        # Volver a lista de OTs para ver si se puede asignar
        log("Navegando a lista de OTs...")
        await page.goto(BASE_URL + "work-orders", wait_until="networkidle")
        await asyncio.sleep(2)
        await screenshot(page, "25_lista_ots")

        # Verificar si hay OTs existentes para asignar
        rows = await page.query_selector_all("table tr, [role='row']")
        log(f"Filas en lista OTs: {len(rows)}")
        
        # Buscar boton de asignar si hay OTs
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            btext = await btn.inner_text()
            if any(k in btext.lower() for k in ["asignar", "assign", "tecnico", "editar"]):
                log(f"Boton accion OT: '{btext}'")

        await browser.close()
        log("QA OT finalizado")

if __name__ == "__main__":
    asyncio.run(main())
