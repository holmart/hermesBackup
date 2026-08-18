---
name: sif-agent-prospecting
description: Unified SIF Agent commercial prospecting - lead generation, enrichment, and pipeline management for fumigation companies in Colombia.
version: 3.0.0
author: Holmart
category: sales
---

# SIF Agent — Prospección Comercial Unificada

## Qué hace este skill

Gestiona todo el ciclo de prospección comercial de SIF Agent:
1. **Genera leads** — busca empresas de fumigación en Colombia (DuckDuckGo → scrape → RUES)
2. **Enriquece datos** — visita sitios web, extrae contactos, busca en RUES
3. **Gestiona pipeline** — tracking de leads desde generación hasta cierre
4. **Reporta** — entrega leads calificadas por Telegram

## Uso

### Comando: Buscar leads
Ejecuta el pipeline de búsqueda para la siguiente ciudad en rotación.
```
Busca leads hoy
```

### Comando: Buscar en ciudad específica
```
Busca fumigadoras en Medellín
```

### Comando: Enriquecer CRM
Ejecuta enriquecimiento de datos internos + RUES sobre el CRM existente.
```
Enriquece el CRM
```

### Comando: Investigar empresa
Profundiza en una empresa específica (RUES, web, Instagram, LinkedIn).
```
Investiga más sobre [nombre empresa]
```

### Comando: Actualizar pipeline
```
Contacté a [empresa]
Demo con [empresa] el [fecha]
[empresa] activó trial
[empresa] pagó
```

### Comando: Resumen
```
¿Cuántas leads llevo?
Dame las mejores leads de esta semana
```

## Scripts disponibles

| Script | Función | Ubicación |
|--------|---------|-----------|
| `unified_lead_pipeline.py` | Pipeline completo: búsqueda + scrape + RUES + DynamoDB + Telegram | `scripts/` |
| `run_pipeline.sh` | Wrapper para cron (setea env vars) | `scripts/` |

## Para ejecutar manualmente

```bash
cd /home/ubuntu/.hermes/skills/sif-agent-prospecting/scripts
python3 unified_lead_pipeline.py
```

## CRM (DynamoDB)

**Tabla:** `sifagent-crm-clients`
**Campos clave:** PK, NombreComercial, Telefono, Email, WhatsApp, NIT, RepresentanteLegal, ContactoPrincipal, Ciudad, Score, Estado, TamanoEmpresa, Instagram

**Estados del pipeline:**
- `nuevo` — lead generada, no contactada
- `contactada` — se envió mensaje/llamó
- `demo` — demo agendada o realizada
- `trial` — en prueba gratuita (30 días)
- `cerrada` — cliente pagando
- `descartada` — no califica o no interesada

## Scoring (1-5)

| Score | Criterio |
|-------|----------|
| 5 | Teléfono + email + NIT + rep legal + empresa mediana/grande + sector regulado |
| 4 | Teléfono + email + NIT o persona + empresa pequeña |
| 3 | Teléfono o email + servicios relevantes |
| 2 | Solo URL con indicios de empresa real |
| 1 | Datos insuficientes o unipersonal |

## Calificación de Leads

Para cada lead entregada, reportar:
- **Nombre empresa** (limpio, sin taglines SEO)
- **Ciudad**
- **Teléfono / WhatsApp** (formato +573XX)
- **Email** (priorizar gerencia@ sobre info@)
- **Contacto principal** (nombre persona si disponible)
- **Representante Legal** (de RUES si disponible)
- **NIT**
- **Score**
- **Servicios**
- **Tamaño estimado**



## Estandarizacion de Verticales (OBLIGATORIO)

Al insertar leads en DynamoDB, el campo VerticalNormalizada DEBE ser uno de:
- Control de Plagas / Fumigacion / MIP
- HVAC / Refrigeracion / Climatizacion
- Limpieza / Aseo / Servicios Generales
- Ingenieria / Consultoria Tecnica
- Formacion / Seguridad Industrial
- Otro (solo si no se puede deducir)

Deducir por keywords en nombre, servicios, actividad o website de la empresa.
NUNCA inventar valores libres. NUNCA usar "Sin clasificar".
