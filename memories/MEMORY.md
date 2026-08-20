## SIF Agent - Contexto

SIF Agent (sifagent.co) - FSM software para PYMEs servicios tecnicos Colombia. Planes desde $175k COP/mes. App offline, WhatsApp auto, PDF firma, contratos recurrentes.

### ICP Fumigacion
Empresas colombianas 3-50 tecnicos, +1 anio, clientes comerciales, coordinan por WhatsApp/Excel. Descalificar: unipersonal, solo productos, multinacional.

### Verticales SIF Agent (12 verticales activas en sifagent.co)
Campo VerticalNormalizada - valores permitidos:
- Control de Plagas / Fumigacion (sifagent.co/fumigacion)
- HVAC / Refrigeracion / Aire Acondicionado (sifagent.co/hvac)
- Instalaciones Electricas / RETIE (sifagent.co/electrico)
- Ascensores / Elevadores (sifagent.co/elevadores)
- Telecomunicaciones / ISPs / FTTH (sifagent.co/telecomunicaciones)
- Ingenieria Biomedica / Equipos Medicos (sifagent.co/biomedica)
- Gas Natural / Instalaciones Gas (sifagent.co/gas)
- Extintores / Proteccion Contra Incendios (sifagent.co/extintores)
- Limpieza / Aseo / Servicios Generales (sifagent.co/limpieza)
- Soporte Tecnico / TI (sifagent.co/soporte-tecnico)
- Cadena de Frio / Refrigeracion Industrial (sifagent.co/cadena-de-frio)
- Lavado de Tanques / Agua Potable (sifagent.co/lavado-de-tanques)
- Mantenimiento de Piscinas (normativa Ley 1209/2008, mediciones pH/cloro)
- Mantenimiento de Plantas Electricas (bitacora RETIE obligatoria)
- Mantenimiento de Paneles Solares (sector creciendo 30%/anio)
NUNCA "Sin clasificar". Si no encaja, usar "Otro".

### Checklists por Vertical Nueva
**Piscinas:** pH, cloro libre, cloro total, alcalinidad, temperatura, turbidez, estado motobomba, estado filtro, dosificador, nivel de agua, foto estado general. Frecuencia: semanal/quincenal.
**Plantas Electricas:** nivel combustible, nivel aceite, temperatura motor, voltaje (L1/L2/L3), amperaje, frecuencia Hz, prueba de carga, horas acumuladas, estado baterias, foto tablero. Frecuencia: mensual/trimestral.
**Paneles Solares:** potencia generada vs esperada (kWh), estado modulos (micro-fisuras, suciedad), estado inversor, voltaje string, corriente string, temperatura modulo, limpieza realizada, conexiones/cableado, foto evidencia. Frecuencia: semestral/anual.

### Pipeline Leads (v5 Multi-Vertical + LLM)
Script: ~/.hermes/skills/sif-agent-prospecting/scripts/unified_lead_pipeline.py
Cron diario (3 verticales activas en prospeccion):
- 13:00 UTC: Fumigacion
- 13:30 UTC: HVAC
- 14:00 UTC: Electrico
LLM genera queries inteligentes + valida leads. 15 ciudades rotacion por vertical.
CRM: sifagent-crm-clients. Campos: PK,NombreComercial,Telefono,Email,WhatsApp,RepresentanteLegal,Ciudad,Score,Estado,Vertical,Pitch

### Cron Jobs
1. Pipeline v5 Fumigacion - Diario 13:00 UTC
2. Pipeline v5 HVAC - Diario 13:30 UTC
3. Pipeline v5 Electrico - Diario 14:00 UTC
4. Internal enrichment v2 - Lun/Mie/Vie 09:00 UTC

### Comandos Telegram
"Busca leads hoy" | "Contacte a X" -> estado contactada | "Demo con X" -> estado demo | "Cuantas leads?" -> resumen | "Enriquece el CRM" -> enrichment

## AWS Infrastructure Context

### Region: us-east-1

### EC2
- Hermes-Agent-Server (t3.small, Ubuntu 22.04) - Gateway Telegram
- Acceso: SSM only (sin SSH)
- Servicio: hermes-gateway.service (systemd)

### DynamoDB
- sifagent-crm-clients: CRM de leads
- Tablas del FSM SaaS backend (32 Lambdas)

### Servicios
- Lambda (32 functions - FSM backend)
- API Gateway + Cognito
- S3 (assets, uploads)
- CloudFront

### Monitoreo
- Scripts en: ~/.hermes/skills/aws-support/scripts/
- health_check.sh, security_audit.sh, cost_report.sh, instance_diagnostics.sh

### Notas
- IP de EC2 puede cambiar (buscar por tag Name=Hermes-Agent-Server)
- No hay Elastic IP
- Security Group: solo outbound abierto + puertos especificos desde IP del usuario
