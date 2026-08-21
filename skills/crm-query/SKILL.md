---
name: crm-query
description: Consultar leads del CRM de SIF Agent — filtrar por ciudad, score, estado, vertical, o texto libre
version: 1.0.0
author: Hermes Agent
category: sales
---
# CRM Query — Consulta de Leads

## Cuándo usar este skill

Cuando el usuario pregunte sobre leads, prospectos, o el CRM. Ejemplos de frases que activan este skill:

- "Dame las leads de Bogotá"
- "¿Cuántas leads tenemos?"
- "Leads nuevas de esta semana"
- "Leads score 5"
- "¿Hay leads de HVAC en Medellín?"
- "Leads de fumigación"
- "Stats del CRM"
- "¿Cuántas leads contactamos?"
- "Top leads"
- "Busca leads de restaurantes"

## Cómo ejecutar

Usa el terminal para ejecutar `query_leads.py` con los argumentos apropiados:

```bash
cd ~/.hermes/skills/sif-agent-prospecting/scripts
python3 query_leads.py [OPCIONES]
```

## Opciones disponibles

| Opción | Descripción | Ejemplo |
|--------|-------------|---------|
| `--stats` | Estadísticas generales del CRM | `python3 query_leads.py --stats` |
| `--ciudad CIUDAD` | Filtrar por ciudad | `--ciudad Bogota` |
| `--min-score N` | Score mínimo (1-5) | `--min-score 4` |
| `--estado ESTADO` | Filtrar por estado | `--estado nuevo` |
| `--vertical VERTICAL` | Filtrar por vertical | `--vertical fumigacion` |
| `--buscar TEXTO` | Búsqueda de texto libre | `--buscar "restaurante"` |
| `--recientes N` | Leads de los últimos N días | `--recientes 7` |
| `--top N` | Cantidad de resultados | `--top 5` |
| `--json` | Output JSON (para procesamiento) | `--json` |

## Mapeo de preguntas a comandos

| El usuario dice | Comando a ejecutar |
|----------------|-------------------|
| "¿Cuántas leads tenemos?" / "stats" / "resumen CRM" | `python3 query_leads.py --stats` |
| "Leads de Bogotá" / "dame leads en Cali" | `python3 query_leads.py --ciudad Bogota --top 10` |
| "Leads score 4 o más" / "mejores leads" | `python3 query_leads.py --min-score 4 --top 10` |
| "Leads nuevas" / "leads sin contactar" | `python3 query_leads.py --estado nuevo --top 10` |
| "Leads de fumigación/HVAC/eléctrico" | `python3 query_leads.py --vertical fumigacion --top 10` |
| "Leads de esta semana" / "leads recientes" | `python3 query_leads.py --recientes 7 --top 10` |
| "Busca leads de restaurantes" / "leads con X" | `python3 query_leads.py --buscar "restaurante" --top 10` |
| "Top 5 leads" / "las mejores" | `python3 query_leads.py --min-score 4 --top 5` |
| "Leads contactadas" / "¿a cuántas contactamos?" | `python3 query_leads.py --estado contactada --top 10` |
| "Leads de HVAC en Medellín score 4+" | `python3 query_leads.py --vertical hvac --ciudad Medellin --min-score 4` |

## Combinaciones

Los filtros se combinan con AND. Si el usuario pide "leads de fumigación en Cali con score 4":
```bash
python3 query_leads.py --vertical fumigacion --ciudad Cali --min-score 4
```

## Estados válidos

- `nuevo` — recién ingresada al CRM
- `contactada` — ya se contactó
- `demo` — tiene demo agendada
- `trial` — está en período de prueba
- `cerrada` — venta cerrada
- `descartada` — no calificó

## Verticales válidas

- `fumigacion`
- `hvac`
- `electrico`

## Formato de respuesta

El script devuelve formato markdown con emojis, listo para enviar directo por Telegram. No necesitas reformatear el output — solo cópialo al usuario.

Si el usuario pide datos específicos de una lead (como "dame el teléfono de X"), busca con `--buscar "nombre"` y extrae del resultado.

## Notas

- El script se conecta directamente a DynamoDB (tabla `sifagent-crm-clients`, región us-east-1)
- No modifica datos, solo lee
- Si no hay resultados, responde que no se encontraron leads con esos criterios
- Para cambiar el estado de una lead (contactada, demo, etc.) NO uses este script — usa el enrichment o DynamoDB directo
