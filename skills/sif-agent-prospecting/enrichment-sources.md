# Fuentes de Enriquecimiento — Representante Legal y Contacto

## Prioridad de datos a obtener

Para cada lead, estos son los datos OBLIGATORIOS (no entregar lead sin al menos 2 de 3):

1. **Nombre del Representante Legal / Gerente / Dueno** — CRITICO
2. **Telefono celular / WhatsApp** — CRITICO
3. **Email** — IMPORTANTE

## Flujo de enriquecimiento (seguir este orden, parar cuando se tengan los 3 datos)

1. Google Maps -> telefono + web
2. Sitio web de la empresa -> email + equipo + WhatsApp (footer, /contacto, /nosotros)
3. Instagram/Facebook bio -> WhatsApp + email
4. RUES (rues.org.co/RM) -> representante legal + NIT (usar browser, tiene JS)
5. EINforma (einforma.co) -> representante legal (buscar: site:einforma.co "nombre empresa")
6. LinkedIn -> nombre del decisor (buscar: "nombre empresa" fumigacion site:linkedin.com/in)
7. SECOP (secop.gov.co) -> representante legal en contratos publicos

## Instrucciones por fuente

### RUES (Representante Legal) — FUENTE PRINCIPAL
URL: https://www.rues.org.co/RM
- Usar browser_navigate para ir a la URL
- Buscar por nombre de empresa en el campo de busqueda
- Extraer: Representante Legal, NIT, Matricula, Estado, Direccion
- Si no aparece por nombre exacto, intentar sin S.A.S., sin LTDA, etc.
- REQUIERE browser (tiene JavaScript), no funciona con web_extract solo

### EINforma (Respaldo para Rep. Legal)
- Buscar en web: site:einforma.co "nombre de la empresa"
- Usar web_extract en la URL del resultado
- Campos: Representante Legal, NIT, Actividad CIIU, Direccion

### Google Maps (Telefono + Web)
- Buscar: "nombre empresa" fumigacion ciudad
- Extraer telefono del listing de Google Maps
- Si tiene sitio web, anotar URL para siguiente paso

### Sitio Web (Email + WhatsApp + Equipo)
- Usar web_extract en la pagina principal (footer tiene telefono y email)
- Luego web_extract en /contacto o /contact
- Luego web_extract en /nosotros o /quienes-somos (nombres de directivos)
- Patrones a buscar: info@, contacto@, gerencia@, +57, 3XX, wa.me/

### Instagram/Facebook (WhatsApp rapido)
- Buscar: "nombre empresa" fumigacion instagram.com
- La bio suele tener: telefono, email, link wa.me
- En Facebook: pestana Informacion de la pagina

### LinkedIn (Nombre del decisor)
- Buscar: "nombre empresa" fumigacion Colombia site:linkedin.com/in
- El perfil del dueno dice "Gerente General en {empresa}" o "Fundador"
- Extraer nombre completo

### SECOP (Contratos publicos)
- Buscar: site:secop.gov.co "nombre empresa" OR "NIT"
- Los contratos listan el representante legal que firma
- Solo si la empresa tiene contratos con el estado

## Regla de minimos

NO entregar una lead sin:
- Nombre de persona (rep legal, gerente, dueno) — de CUALQUIER fuente
- Al menos 1 contacto directo (celular, WhatsApp, o email)

Si despues de las 7 fuentes no se obtienen ambos datos: DESCARTAR la lead.

## Tools a usar

| Tool | Cuando |
|------|--------|
| web_search | Busquedas iniciales, encontrar URLs |
| web_extract | Sitios web simples, EINforma, directorios, LinkedIn snippets |
| browser_navigate + browser_snapshot | RUES (JS), Instagram (dinamico), sitios con login wall |
