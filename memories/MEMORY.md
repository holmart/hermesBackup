§ SIF Agent (sifagent.co) - FSM software para PYMEs servicios tecnicos Colombia. Planes desde $175k COP/mes. App offline, WhatsApp auto, PDF firma, contratos recurrentes.

§ ICP Fumigacion: Empresas colombianas 3-50 tecnicos, +1 anio, clientes comerciales, coordinan por WhatsApp/Excel. Descalificar: unipersonal, solo productos, multinacional.

§ Verticales SIF Agent (15+ verticales activas). Campo VerticalNormalizada - valores permitidos: Control de Plagas / Fumigacion, HVAC / Refrigeracion, Instalaciones Electricas / RETIE, Ascensores / Elevadores, Telecomunicaciones / ISPs / FTTH, Ingenieria Biomedica / Equipos Medicos, Gas Natural / Instalaciones Gas, Extintores / Proteccion Contra Incendios, Limpieza / Aseo / Servicios Generales, Soporte Tecnico / TI, Cadena de Frio / Refrigeracion Industrial, Lavado de Tanques / Agua Potable, Mantenimiento de Piscinas, Mantenimiento de Plantas Electricas, Mantenimiento de Paneles Solares. NUNCA "Sin clasificar". Si no encaja, usar "Otro".

§ Pipeline Leads v5 Multi-Vertical + LLM. Script: ~/.hermes/skills/sif-agent-prospecting/scripts/unified_lead_pipeline.py. Cron diario: 13:00 UTC Fumigacion, 13:30 UTC HVAC, 14:00 UTC Electrico. CRM: sifagent-crm-clients. Campos: PK,NombreComercial,Telefono,Email,WhatsApp,RepresentanteLegal,Ciudad,Score,Estado,Vertical,Pitch.

§ Cron Jobs: 1) Pipeline v5 Fumigacion - Diario 13:00 UTC. 2) Pipeline v5 HVAC - Diario 13:30 UTC. 3) Pipeline v5 Electrico - Diario 14:00 UTC. 4) Internal enrichment v2 - Lun/Mie/Vie 09:00 UTC.

§ Comandos Telegram rapidos: "Busca leads hoy" | "Contacte a X" -> estado contactada | "Demo con X" -> estado demo | "Cuantas leads?" -> resumen | "Enriquece el CRM" -> enrichment.

§ AWS Region us-east-1. EC2: Hermes-Agent-Server (t3.small, Ubuntu 22.04) - Gateway Telegram. Acceso SSM only. Servicio hermes-gateway.service. DynamoDB: sifagent-crm-clients (CRM leads) + tablas FSM SaaS backend (32 Lambdas). Servicios: Lambda, API Gateway + Cognito, S3, CloudFront. Monitoreo scripts en ~/.hermes/skills/aws-support/scripts/. IP EC2 cambia, no hay Elastic IP.

§ Consulta de Leads (query_leads.py): Script en ~/.hermes/skills/sif-agent-prospecting/scripts/query_leads.py. Skill: crm-query. Comandos: --stats, --ciudad, --min-score, --estado, --vertical, --buscar, --recientes. Combinar filtros libremente.

§ FSM backend ofusca telefonos ANTES de guardar en DynamoDB/Cognito. Formato: +573****6311. Aplica a tenants, customers, technicians-metadata. No se puede recuperar completo desde AWS. Si se necesita en reportes, hay que modificar backend o enviar alerta antes de ofuscar.
§
FSM backend ofusca telefonos ANTES de guardar en DynamoDB/Cognito. Formato: +573****6311. Aplica a tenants, customers, technicians-metadata. No se puede recuperar completo desde AWS. Si se necesita en reportes, hay que modificar backend o enviar alerta antes de ofuscar.