---
name: fsm-saas-platform
description: Contexto completo de la plataforma FSM SaaS (SifAgent) — arquitectura, módulos, endpoints, flujos, pantallas y reglas de negocio.
version: 1.0.0
author: Holmart
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [fsm, saas, field-service, angular, ionic, aws, dynamodb, lambda, typescript, colombia]
    related_skills: [plan, test-driven-development]
---

# FSM SaaS Platform — Contexto Completo

Eres el agente de desarrollo de la plataforma FSM SaaS (SifAgent), una aplicación multi-tenant de gestión de servicios en campo y servicios en local, dirigida a PYMEs en Colombia.

**Usa este skill cuando trabajes en cualquier aspecto de la plataforma FSM:** frontend (Angular/Ionic), backend (Lambda/Node), infraestructura (CDK), diseño de UI, flujos de negocio, o cualquier decisión técnica relacionada.

---

## 1. Visión General

| Aspecto | Detalle |
|---------|---------|
| Producto | Plataforma SaaS de Field Service Management |
| Dominio | `app.sifagent.co` |
| Mercado | Colombia (COP, DIAN, Wompi) |
| Target | PYMEs de mantenimiento y servicios |
| Flujos | Campo (Field Service) + Local (In-House) |
| Estado backend | 100% implementado (32 Lambdas, 178 endpoints, 119 tests) |
| Estado frontend | Pendiente implementación |

---

## 2. Arquitectura Técnica

### Stack Backend (Implementado)
- **Runtime:** Node.js + TypeScript
- **API:** API Gateway HTTP (REST, `/v1/*`)
- **Auth:** AWS Cognito (4 Lambda triggers: pre-signup, post-confirmation, pre-token, custom-message)
- **DB:** 16 tablas DynamoDB + 30+ GSIs
- **Compute:** 32 Lambda functions
- **Eventos:** EventBridge (12 reglas) + 2 Step Functions
- **Storage:** S3 (media, frontend assets)
- **CDN:** CloudFront (2 distributions)
- **Email:** SES (domain identity + DKIM)
- **PDF:** @react-pdf/renderer via Step Function
- **Pagos:** Wompi (tokenized 3RI, cobro automático diario)
- **Facturación:** DIAN electrónica via Alegra/Siigo (multi-proveedor)
- **Notificaciones:** FCM push + WhatsApp Meta Cloud API + SES email
- **Infra como código:** 10 CDK stacks

### Stack Frontend (Por implementar)

| App | Framework | Puerto | Usuarios |
|-----|-----------|--------|----------|
| Web Admin (`fsm-web`) | Angular 18.2 + TailwindCSS 3.4 | 4200 | Admin, Coordinador |
| App Móvil (`fsm-mobile`) | Ionic 8.8 + Angular 18.2 + Capacitor 8.5 | 8100 | Técnico |
| Platform Admin (`fsm-platform-admin`) | Angular 18.2 + TailwindCSS 3.4 | 4300 | Super admin |
| Landing (`fsm-landing`) | Astro 4.16 + Preact + TailwindCSS 3.4 | 3000 | Público |

### Tecnologías Compartidas Frontend
- Auth: AWS Amplify 6.18 (Cognito)
- Validación: Zod 3.24
- Charts: chart.js + ng2-charts
- Testing: Vitest + Testing Library + vitest-axe (accesibilidad)
- Shared package: `@fsm/shared` (tipos, constantes, utils)

---

## 3. Roles del Sistema

| Rol | Plataforma | Permisos |
|-----|-----------|----------|
| `admin` | Web | Todo: configuración, equipo, reportes, finanzas |
| `coordinator` | Web | Crear OTs, asignar técnicos, seguimiento |
| `technician` | App Móvil | Recibir asignaciones, ejecutar, registrar evidencia |
| `platform_admin` | Platform Admin | Gestión cross-tenant, facturación, métricas globales |

---

## 4. Módulos y Endpoints

### Core (disponibles en todos los planes)

#### 4.1 Tenants — `tenant-handler` (15 endpoints)
- Config general: nombre, NIT, teléfono, plan, vertical
- Gestión de plan: Trial → Starter → Pro → Business
- VerticalConfig: checklistTemplates, reportTemplate, fieldDataSections (max 10 secciones, max 20 campos)
- Branding PDF: logo + firma empresa (presigned URL, S3)
- Execution Templates: CRUD completo + duplicado
- Suspensión/Reactivación (ADR-013)

| Método | Ruta | Roles |
|--------|------|-------|
| GET | `/v1/tenant/config` | admin, coordinator, technician |
| PUT | `/v1/tenant/config` | admin |
| PATCH | `/v1/tenant/suspend` | admin |
| PATCH | `/v1/tenant/reactivate` | admin |
| POST | `/v1/tenant/branding/logo/upload-url` | admin |
| POST | `/v1/tenant/branding/signature/upload-url` | admin |
| PUT | `/v1/tenant/branding` | admin |
| DELETE | `/v1/tenant/branding/logo` | admin |
| DELETE | `/v1/tenant/branding/signature` | admin |
| POST | `/v1/execution-templates` | admin |
| GET | `/v1/execution-templates` | admin, coordinator, technician |
| GET | `/v1/execution-templates/:templateId` | admin, coordinator |
| POST | `/v1/execution-templates/:templateId/duplicate` | admin |
| PUT | `/v1/execution-templates/:templateId` | admin |
| DELETE | `/v1/execution-templates/:templateId` | admin |

#### 4.2 Team & Technicians — `team-handler` (11 endpoints)
- Invitar usuarios por email con contraseña temporal (Cognito AdminCreateUser)
- Roles: admin, coordinator, technician
- Metadata técnico: especialidad, zona, certificación, whatsappOptIn, deviceToken
- Soft-delete (no permite si tiene OTs activas)
- Agenda por ejecutor (GSI technician-date-index)
- Comisiones (ADR-019): porcentaje, arriendo fijo, salario + comisión
- Límites: Trial 3 técnicos, Pro 10, Business ilimitado

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/team/invite` | admin |
| GET | `/v1/team` | admin, coordinator |
| PUT | `/v1/team/:userId` | admin |
| DELETE | `/v1/team/:userId` | admin |
| POST | `/v1/technicians/:userId/metadata` | admin |
| GET | `/v1/technicians/:userId/metadata` | admin, coordinator |
| GET | `/v1/technicians` | admin, coordinator |
| GET | `/v1/technicians/:userId/schedule` | admin, coordinator, technician |
| PATCH | `/v1/technicians/:userId/whatsapp-optin` | admin, technician |
| POST | `/v1/devices/register` | technician |
| DELETE | `/v1/devices` | technician |

#### 4.3 Customers — `customers-handler` (7 endpoints)
- CRUD con paginación + búsqueda
- Ubicaciones múltiples (N sedes por cliente)
- WhatsApp opt-in (autorización para notificaciones)
- GPS coordenadas opcionales
- Execution Template por cliente
- Precondición de baja: no OTs activas
- Auto-cancelación de contratos al desactivar

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/customers` | admin, coordinator |
| GET | `/v1/customers` | admin, coordinator |
| GET | `/v1/customers/:id` | admin, coordinator, technician |
| PUT | `/v1/customers/:id` | admin, coordinator |
| DELETE | `/v1/customers/:id` | admin |
| PATCH | `/v1/customers/:id/reactivate` | admin |
| PATCH | `/v1/customers/:id/whatsapp-optin` | admin |

#### 4.4 Assets/Equipos — `assets-handler` (7 endpoints, solo flujo Campo)
- Asociados a cliente + location específica
- Datos: tipo, marca, modelo, serial (único por tenant), capacidad BTU, refrigerante
- Foto de placa (presigned URL, max 10MB)
- Búsqueda por serial (GSI)
- Decommission (soft-delete)

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/customers/:customerId/assets` | admin, coordinator |
| GET | `/v1/customers/:customerId/assets` | admin, coordinator |
| GET | `/v1/assets/search?serial=X` | admin, coordinator, technician |
| GET | `/v1/assets/:id` | admin, coordinator, technician |
| PUT | `/v1/assets/:id` | admin |
| POST | `/v1/assets/:id/photo/upload-url` | admin, coordinator |
| PATCH | `/v1/assets/:id/decommission` | admin |

#### 4.5 Work Orders — `work-orders-handler` (12 endpoints)
- Estados: PENDING → ASSIGNED → IN_PROGRESS → COMPLETED (CANCELLED desde cualquier no-terminal)
- Creación: 4 campos visibles + "Más opciones"
- "En camino": solo emite evento WhatsApp, NO cambia status
- "Llegué": ASSIGNED → IN_PROGRESS
- Endpoint `/mine`: respuesta enriquecida para app móvil (offline-first)
- Límites OT/mes: Trial 20, Starter 50, Pro/Business ilimitado
- Walk-in (ADR-019): técnico crea OT directamente (solo in-house)
- Mutabilidad por estado: PENDING todo editable, ASSIGNED sin cambiar asset/customer, IN_PROGRESS solo notas

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/work-orders` | admin, coordinator |
| GET | `/v1/work-orders` | admin, coordinator |
| GET | `/v1/work-orders/mine` | technician |
| GET | `/v1/work-orders/:id` | admin, coordinator, technician |
| PUT | `/v1/work-orders/:id` | admin, coordinator |
| PATCH | `/v1/work-orders/:id/assign` | admin, coordinator |
| PATCH | `/v1/work-orders/:id/on-way` | technician |
| PATCH | `/v1/work-orders/:id/status` | technician |
| PATCH | `/v1/work-orders/:id/cancel` | admin, coordinator |
| POST | `/v1/work-orders/walk-in` | technician |
| PATCH | `/v1/work-orders/:id/reschedule` | admin, coordinator |
| GET | `/v1/work-orders/agenda/:date` | admin, coordinator |

#### 4.6 Field/Ejecución — `field-handler` (9 endpoints)
- Checklist: selección de template, items con completed + notas
- Field Data dinámico: secciones configurables con campos numérico/texto/selección/boolean + condicionales
- Fotos: presigned URL, tipos before/after/equipment_plate, max 20 por OT
- Firma digital: canvas → presigned URL → imagen S3
- Completar OT: validación checklist + secciones required
- Regenerar PDF (admin)

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/work-orders/:id/checklist` | technician |
| POST | `/v1/work-orders/:id/field-data/:sectionKey` | technician |
| GET | `/v1/work-orders/:id/field-data` | technician, admin, coordinator |
| POST | `/v1/work-orders/:id/photos/upload-url` | technician |
| POST | `/v1/work-orders/:id/photos` | technician |
| POST | `/v1/work-orders/:id/signature/upload-url` | technician |
| POST | `/v1/work-orders/:id/signature` | technician |
| POST | `/v1/work-orders/:id/complete` | technician |
| POST | `/v1/work-orders/:id/regenerate-pdf` | admin |

#### 4.7 Dashboard — `dashboard-handler` (2 endpoints)
- Summary: 7 queries paralelas (todayScheduled, todayInProgress, todayCompleted, totalPending, totalAssigned, contractsExpiringSoon, techniciansActive)
- Field Data Report (Business): reporte por sectionKey y rango de fechas

| Método | Ruta | Roles |
|--------|------|-------|
| GET | `/v1/dashboard/summary` | admin, coordinator |
| GET | `/v1/dashboard/field-data-report` | admin |

### Pro (desde plan Pro)

#### 4.8 Contracts — `contracts-handler` (5 endpoints, solo Campo)
- Cliente + assets + frecuencia (monthly/quarterly/biannual/annual) + precio
- Auto-generación de OTs: Step Function diario 6AM COT
- Cálculos: totalVisits, completedVisits, nextVisitDate
- Expiración automática
- Idempotencia: contractId + scheduledDate

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/contracts` | admin |
| GET | `/v1/contracts` | admin, coordinator |
| GET | `/v1/contracts/expiring` | admin |
| GET | `/v1/contracts/:id` | admin, coordinator |
| PUT | `/v1/contracts/:id` | admin |

#### 4.9 Finance — `finance-handler` (10 endpoints)
- Ingresos y gastos con monto, descripción, categoría, fecha, método de pago (cash, nequi, daviplata, card, transfer)
- Vinculación opcional a OT, ejecutor, cliente
- Categorías personalizables (CRUD, soft-delete, separadas por tipo income/expense)
- Reporte de rentabilidad: período max 365 días, desglose byExecutor (con comisión), byCategory, byPaymentMethod
- Cobro post-completar: botón voluntario "Registrar cobro" (no popup automático)

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/finance/entries` | admin, coordinator, technician |
| GET | `/v1/finance/entries` | admin, coordinator |
| GET | `/v1/finance/entries/:id` | admin, coordinator |
| PUT | `/v1/finance/entries/:id` | admin, coordinator |
| DELETE | `/v1/finance/entries/:id` | admin |
| POST | `/v1/finance/categories` | admin |
| GET | `/v1/finance/categories` | admin, coordinator, technician |
| PUT | `/v1/finance/categories/:id` | admin |
| DELETE | `/v1/finance/categories/:id` | admin |
| GET | `/v1/finance/report` | admin |

### Business (desde plan Business)

#### 4.10 Catalog & Availability — `catalog-handler` (8 endpoints)
- Servicios: nombre, precio COP, duración minutos, categoría, ejecutores asignados
- Disponibilidad: horario laboral, citas existentes, bloqueos, appointmentBuffer
- Bloqueo de slots: vacaciones, permisos

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/catalog` | admin |
| GET | `/v1/catalog` | admin, coordinator |
| GET | `/v1/catalog/:serviceId` | admin, coordinator, technician |
| PUT | `/v1/catalog/:serviceId` | admin |
| DELETE | `/v1/catalog/:serviceId` | admin |
| GET | `/v1/availability/:executorId/:date` | admin, coordinator |
| POST | `/v1/availability/:executorId/block` | admin, coordinator |
| DELETE | `/v1/availability/:executorId/block/:blockId` | admin, coordinator |

#### 4.11 Inventory — `inventory-handler` (14 endpoints)
- Productos: código, nombre, categoría, unidad (und/kg/lt/mt/caja/par/rollo/galón/ml/cm), stock mínimo, precio venta
- Movimientos: compra (entrada), consumo (salida), ajuste (+/-)
- Costo promedio ponderado automático
- Alertas stock bajo (EventBridge)
- Consumo vinculable a OT y ejecutor

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/inventory/products` | admin, coordinator |
| GET | `/v1/inventory/products` | admin, coordinator, technician |
| GET | `/v1/inventory/products/:productId` | admin, coordinator, technician |
| PUT | `/v1/inventory/products/:productId` | admin, coordinator |
| DELETE | `/v1/inventory/products/:productId` | admin |
| POST | `/v1/inventory/products/:productId/purchase` | admin, coordinator |
| POST | `/v1/inventory/products/:productId/consume` | admin, coordinator, technician |
| POST | `/v1/inventory/products/:productId/adjust` | admin |
| GET | `/v1/inventory/products/:productId/movements` | admin, coordinator |
| POST | `/v1/inventory/categories` | admin |
| GET | `/v1/inventory/categories` | admin, coordinator, technician |
| PUT | `/v1/inventory/categories/:categoryId` | admin |
| DELETE | `/v1/inventory/categories/:categoryId` | admin |
| GET | `/v1/inventory/report` | admin |

#### 4.12 GPS & Route Optimization — `gps-handler` (13 endpoints)
- Ingesta de ubicaciones desde app móvil
- Mapa en tiempo real (AppSync GraphQL subscriptions)
- Optimización de rutas (AWS Location Service)
- ETA, heatmap, replay, geofencing
- Tracking page pública compartible con cliente

| Método | Ruta | Roles |
|--------|------|-------|
| POST | `/v1/gps/locations` | technician |
| GET | `/v1/gps/history/:technicianId` | admin, coordinator |
| GET | `/v1/gps/map/technicians` | admin, coordinator |
| POST | `/v1/gps/routes/optimize` | admin, coordinator |
| GET | `/v1/gps/eta/:workOrderId` | admin, coordinator, technician |
| GET | `/v1/gps/reports/km` | admin, coordinator |
| GET | `/v1/gps/reports/productivity` | admin, coordinator |
| GET | `/v1/gps/reports/check-in` | admin, coordinator |
| GET | `/v1/gps/reports/speed-alerts` | admin, coordinator |
| GET | `/v1/gps/suggest-technician` | admin, coordinator |
| GET | `/v1/gps/tracking/:workOrderId` | público (token) |
| GET | `/v1/gps/heatmap` | admin, coordinator |
| GET | `/v1/gps/replay/:technicianId` | admin, coordinator |

#### 4.13 Analytics — `analytics-handler` (16 endpoints)
- KPIs operativos, SLA, First-Time-Fix, satisfacción, retención
- Revenue por período, costo por OT, rentabilidad por cliente
- Utilización de técnicos, ranking, distribución de carga

#### 4.14 Settlement — `field-handler` controladores settlement (9 endpoints)
- Liquidación por OT completada: ingresos, repuestos, gastos por categoría (transporte, materiales, herramientas, alimentación, otro)
- Cálculos: totalIncome, totalExpenses, grossMargin, profitPercent, profitabilityLevel
- Reportes consolidados por período, por ejecutor, por cliente

### Add-on (cualquier plan)

#### 4.15 Quotes/Cotizaciones — `quotes-handler` (9 endpoints)
- Estados: draft → sent → accepted | rejected | expired (lazy)
- Numeración secuencial: COT-0001
- Conversión a OT al aceptar
- Envío: evento QuoteSent → PDF + WhatsApp + Email

### Plataforma (cross-tenant)

#### 4.16 Platform Admin — `platform-admin-handler` (13 endpoints)
- Listar/suspender/reactivar tenants
- Métricas globales, gestión de suscripciones

#### 4.17 Payments/Billing — `payments-webhook-handler` + `billing-scheduler`
- Webhook Wompi (HMAC validation)
- Cobro automático diario 6AM COT (max 50 tenants/ejecución)
- Evento PaymentApproved → facturación

#### 4.18 Invoices/Facturación DIAN — `invoice-handler` (14 endpoints)
- Multi-proveedor (ADR-027): Alegra + Siigo
- Platform mode (FSM factura a tenants) + Tenant mode (tenants facturan a clientes)
- Notas crédito, PDF, re-envío
- IVA 19% Colombia

### Comunicación

#### 4.19 Push Notifications — `notification-push`
- FCM al técnico al asignar OT
- Email SES a admins cuando OT se completa
- Gratuito (Firebase Cloud Messaging)

#### 4.20 WhatsApp — `notification-whatsapp`
- 4 templates Meta Cloud API: technician_assigned, technician_on_way, service_completed, visit_reminder
- Verificación opt-in antes de enviar
- Scheduler recordatorio: EventBridge 8AM COT

#### 4.21 WhatsApp Chatbot — `whatsapp-chatbot-handler` (2 endpoints públicos)
- Agendamiento: cliente selecciona servicio → fecha → horario
- Cancelación y reagendamiento
- HMAC SHA-256 (sin Cognito Authorizer)
- Campo: crea OT PENDING. In-house: crea OT ASSIGNED directo

---

## 5. Estados de Orden de Trabajo

```
PENDING (sin técnico) → ASSIGNED (con técnico) → IN_PROGRESS (ejecutando) → COMPLETED (PDF + email)
                    ↘         ↘
                     CANCELLED  CANCELLED
```

| Estado | Icono | Desde | Trigger |
|--------|:-----:|-------|---------|
| PENDING | 🟡 | Creación | POST /work-orders |
| ASSIGNED | 🟢 | PENDING | PATCH /assign |
| IN_PROGRESS | 🔵 | ASSIGNED | PATCH /status ("Llegué") |
| COMPLETED | ✅ | IN_PROGRESS | POST /complete |
| CANCELLED | 🔴 | PENDING, ASSIGNED | PATCH /cancel |

---

## 6. Flujo Completo de Servicio en Campo

1. **Coordinador** crea OT (web): cliente + equipo + fecha + técnico
2. **Sistema** emite WorkOrderAssigned → push FCM + WhatsApp al técnico
3. **Técnico** (app): ve OT en "Mis Órdenes", toca "Navegar" (Google Maps)
4. **Técnico** toca "Estoy en camino" → WhatsApp al cliente (NO cambia estado)
5. **Técnico** toca "Llegué" → estado = IN_PROGRESS
6. **Técnico** ejecuta: checklist + field data + fotos + firma
7. **Técnico** toca "Completar" → POST /complete → Step Function:
   - Genera PDF → S3
   - Email al cliente con PDF
   - WhatsApp "Servicio completado ✅"
   - Push al admin
8. **Técnico** (opcional) toca "Registrar cobro" → entrada financiera
9. **Coordinador** ve OT completada en Dashboard con PDF y datos

### Notificaciones automáticas

| Momento | Destinatario | Canal |
|---------|-------------|-------|
| Al asignar | Técnico | Push + WhatsApp |
| "En camino" | Cliente | WhatsApp |
| Al completar | Cliente | Email (PDF) + WhatsApp |
| Al completar | Admin | Push |
| Día anterior | Cliente | WhatsApp 8AM |

---

## 7. Verticales Soportadas

| # | Vertical | Clave | Flujo |
|---|----------|-------|-------|
| 1 | HVAC / Refrigeración | `hvac` | Campo |
| 2 | Fumigación / Control de plagas | `fumigation` | Campo |
| 3 | Mantenimiento eléctrico | `electrical` | Campo |
| 4 | Elevadores | `elevators` | Campo |
| 5 | Limpieza industrial | `cleaning` | Campo |
| 6 | Gas | `gas` | Campo |
| 7 | Extintores / Contra incendios | `fire_safety` | Campo |
| 8 | Telecomunicaciones | `telco` | Campo |
| 9 | Biomédica | `biomedical` | Campo |
| 10 | Cadena de frío | `cold_chain` | Campo |
| 11 | Lavado de tanques | `tank_cleaning` | Campo |
| 12 | Soporte técnico general | `support` | Campo |
| 13 | Genérico (Peluquerías, Spas) | `generic` | In-House |

---

## 8. Planes y Precios

### Servicio en Campo

| Plan | Precio/mes | Técnicos | OT/mes | Coordinadores |
|------|-----------|----------|--------|---------------|
| Trial | $0 (30 días) | 3 | 20 | 1 |
| Starter | $175.000 COP | 3 | 50 | 1 |
| Pro | $249.000 COP | 10 | ilimitado | 1 |
| Business | $420.000 COP | ilimitado | ilimitado | ilimitado |

### Servicio en Local

| Plan | Precio/mes |
|------|-----------|
| Trial | $0 (30 días) |
| Starter | $70.000 COP |
| Pro | $149.000 COP |
| Business | $199.000 COP |

### Módulos por Plan

| Módulo | Trial | Starter | Pro | Business |
|--------|:-----:|:-------:|:---:|:--------:|
| Clientes, OTs, Equipos, Dashboard, Push | ✅ | ✅ | ✅ | ✅ |
| Contratos | ✅ | ✅ | ✅ | ✅ |
| WhatsApp notificaciones | ✅ | ✅ | ✅ | ✅ |
| Chatbot WhatsApp (add-on) | ✅ | ✅* | ✅* | ✅* |
| Finanzas | ✅ | ❌ | ✅ | ✅ |
| Walk-in / Comisiones | ✅ | ❌ | ✅ | ✅ |
| Plantillas ejecución personalizadas | ✅ | ❌ | ✅ | ✅ |
| Inventario | ✅ | ❌ | ❌ | ✅ |
| Reportes avanzados (Analytics) | ✅ | ❌ | ❌ | ✅ |
| GPS & Route Optimization | ✅ | ❌ | ❌ | ✅ |
| Catálogo + Disponibilidad | ✅ | ❌ | ❌ | ✅ |
| Settlement (Liquidación) | ✅ | ❌ | ❌ | ✅ |
| Multi-coordinador | ✅ | ❌ | ❌ | ✅ |

> Trial incluye TODO durante 30 días para evaluación.

---

## 9. Infraestructura AWS (10 CDK Stacks)

| Stack | Contenido |
|-------|-----------|
| `dns-stack` | Route53 + 3 ACM certificates (api, app, media) |
| `auth-stack` | Cognito User Pool + groups + 4 triggers |
| `database-stack` | 16 tablas DynamoDB + 30+ GSIs + PITR |
| `storage-stack` | S3 media + S3 frontend + 2 CloudFront |
| `email-stack` | SES domain identity + DKIM |
| `api-stack` | HTTP API Gateway + Cognito Authorizer + 32 Lambdas + Layer |
| `events-stack` | EventBridge + 12 rules + 4 DLQs + 2 Schedulers + 2 Step Functions |
| `monitoring-stack` | CloudWatch dashboard + alarmas + SNS + X-Ray |
| `log-archival-stack` | Kinesis Firehose → S3 (GZIP, particionado) |
| `landing-stack` | S3 + CloudFront para landing estática |

### 16 Tablas DynamoDB

| Tabla | GSIs | Módulo |
|-------|:----:|--------|
| fsm-tenants | 0 | Core |
| fsm-technicians-metadata | 1 | Core |
| fsm-customers | 1 | Core |
| fsm-assets | 2 | Core |
| fsm-work-orders | 6 | Core |
| fsm-work-order-details | 1 | Core (Field + Settlement) |
| fsm-contracts | 2 | Core |
| fsm-finance-entries | 3 | Finance |
| fsm-service-catalog | 1 | Catalog |
| fsm-inventory | 4 | Inventory |
| fsm-quotes | 3 | Quotes |
| fsm-subscriptions | 1 | Platform |
| fsm-payment-history | 2 | Platform |
| fsm-invoices | 2 | Facturación |
| fsm-invoice-issuers | 0 | Facturación |
| fsm-gps-locations | 1+ | GPS |

### EventBridge — 12 Reglas

| Evento | Target |
|--------|--------|
| WorkOrderAssigned | notification-push + notification-whatsapp |
| TechnicianOnWay | notification-whatsapp |
| WorkOrderCompleted | Step Function (PDF → email → WA → push) |
| WorkOrderCancelled | notification-push + notification-whatsapp |
| QuoteSent | notification-whatsapp |
| QuoteAccepted | notification-push |
| WalkInCreated | notification-push |
| InventoryLowStock | notification-push |
| InventoryConsumed | logging |
| Scheduler 6AM COT | Step Function generate-scheduled-orders |
| Scheduler 8AM COT | notification-whatsapp (recordatorio) |

---

## 10. Feature Modules Frontend

### Web Admin — 17 módulos
analytics, assets, auth, contracts, customers, dashboard, gps-reports, inventory, invoicing, not-found, quotes, reports, schedule, settings, settlement, team, work-orders

### App Móvil — 17 módulos
asset-registration, auth, complete, customers, evidence, execution, history, inventory, login, my-orders, notifications, onboarding, order-detail, profile, settlement, sync, walk-in

### Platform Admin — 8 módulos
auth, crm, dashboard, finance, login, payments, settings, tenants

---

## 11. Diferencias entre Flujos

| Aspecto | Campo (Field) | Local (In-House) |
|---------|:---:|:---:|
| Terminología UI | "Orden de Trabajo" / "Técnico" | "Cita" / "Estilista" |
| Equipos/Activos | ✅ | ❌ |
| Dirección | Del cliente (variable) | Del local (fija) |
| Scheduling | Solo fecha | Fecha + hora + slot |
| "En camino" | ✅ WhatsApp | ❌ |
| Catálogo con duración | Opcional | Precios + duración |
| Walk-in | ❌ | ✅ |
| Contratos auto-generación | ✅ | ❌ |
| Chatbot | Crea OT PENDING | Crea OT ASSIGNED |
| Comisiones | Porcentaje | Porcentaje/arriendo/salario+comisión |

---

## 12. Reglas de Implementación

1. **Backend inmutable:** No modificar endpoints, schemas ni lógica sin consultar la documentación de módulos.
2. **APIs exactas:** Usar endpoints, payloads y roles exactamente como están documentados.
3. **Validar plan:** Verificar módulos habilitados por plan antes de mostrar funcionalidades en UI.
4. **Feature modules:** Respetar la estructura definida para cada aplicación frontend.
5. **Offline-first:** App móvil usa SQLite + sync queue. Datos cacheados en Ionic Storage.
6. **Terminología por flujo:** "Orden de Trabajo"/"Técnico" (campo) vs "Cita"/"Estilista" (in-house).
7. **Accesibilidad:** Usar vitest-axe en todos los componentes.
8. **Shared types:** Todo tipo compartido va en `@fsm/shared`.

---

## 13. Registro y Onboarding (ADR-021)

### Registro simplificado (3 campos)
1. Selector visual: "Voy donde el cliente" vs "El cliente viene a mí"
2. Email
3. Contraseña (min 8 chars, mayúscula + número, NO hay confirmar contraseña)

### Onboarding post-registro (3 pasos dentro de la app)
1. Nombre de la empresa
2. Vertical (selector múltiple)
3. Invitar primer técnico (opcional)

---

## 14. PDF y Reportes

El Step Function `sfn-complete-work-order` al completar una OT:
1. `GeneratePDF` (1024MB, 30s): lee 5 tablas, genera PDF con @react-pdf/renderer, sube a S3
2. En paralelo: SendEmail (SES) + NotifyAdmin (SES) + NotifyClientWhatsApp

Contenido PDF: encabezado empresa (logo/firma branding) + info OT + cliente + equipo + técnico + checklist + field data + fotos embebidas + firma + pie.

---

## 15. Seguridad y Auth

- JWT con custom claims: `custom:tenantId`, `custom:role`
- Middleware `extractAuth()` en cada request
- Tenant suspendido (ADR-013): solo `GET /tenant/config` y `PATCH /tenant/reactivate` permitidos
- WhatsApp Chatbot: HMAC SHA-256 (sin Cognito, endpoints públicos)
- Wompi webhook: HMAC validation
- Opt-in WhatsApp: Ley 1581 Habeas Data Colombia

---

## 16. Resumen de Endpoints

| Módulo | Endpoints | Plan mínimo |
|--------|:---------:|:-----------:|
| Tenant (config + branding + templates) | 15 | Core |
| Team + Technicians | 11 | Core |
| Customers | 7 | Core |
| Assets | 7 | Core |
| Work Orders | 12 | Core |
| Field (Ejecución) | 9 | Core |
| Dashboard | 2 | Core |
| Contracts | 5 | Pro |
| Finance | 10 | Pro |
| Catalog + Availability | 8 | Business |
| Inventory | 14 | Business |
| GPS & Route Optimization | 13 | Business |
| Analytics | 16 | Business |
| Settlement | 9 | Business |
| Quotes | 9 | Add-on |
| Platform Admin | 13 | platform_admin |
| Invoices | 14 | platform_admin / admin |
| Webhooks (WA + Payments) | 4 | — |
| **Total** | **~178** | |

---

## 17. Código Fuente — Monorepo

**Ruta del proyecto:** `/Users/holmart/Documents/proyecto`
**Package manager:** pnpm (workspace)
**Nombre workspace:** `fsm-saas-workspace`

### Estructura del Monorepo

```
/Users/holmart/Documents/proyecto/
├── package.json                    # Workspace root
├── pnpm-workspace.yaml             # Packages: fsm-backend, fsm-web, fsm-mobile, fsm-shared, packages/*
├── pnpm-lock.yaml
│
├── fsm-backend/                    # Backend (Lambdas + CDK Infrastructure)
│   ├── src/
│   │   ├── core/                   # Handlers principales
│   │   │   ├── analytics/          # analytics-handler
│   │   │   ├── assets/             # assets-handler
│   │   │   ├── catalog/            # catalog-handler
│   │   │   ├── contracts/          # contracts-handler
│   │   │   ├── customers/          # customers-handler
│   │   │   ├── dashboard/          # dashboard-handler
│   │   │   ├── field/              # field-handler
│   │   │   ├── finance/            # finance-handler
│   │   │   ├── gps/                # gps-handler
│   │   │   ├── inventory/          # inventory-handler
│   │   │   ├── invoices/           # invoice-handler
│   │   │   ├── quotes/             # quotes-handler
│   │   │   ├── settlement/         # settlement (dentro de field-handler)
│   │   │   ├── team/               # team-handler
│   │   │   ├── technicians/        # (parte de team-handler)
│   │   │   ├── tenants/            # tenant-handler
│   │   │   └── work-orders/        # work-orders-handler
│   │   ├── notifications/          # notification-push + notification-whatsapp
│   │   ├── platform/               # platform-admin-handler + payments-webhook
│   │   ├── shared/                 # Código compartido backend (repos, utils, middleware)
│   │   ├── triggers/               # Cognito Lambda triggers (pre-signup, post-confirmation, pre-token, custom-message)
│   │   ├── verticals/              # Configuración por vertical (hvac, fumigation, electrical, etc.)
│   │   ├── webhooks/               # whatsapp-chatbot-handler
│   │   └── workflows/              # Step Function tasks (generate-pdf, send-email, generate-scheduled-orders)
│   ├── infra/
│   │   ├── bin/                    # CDK app entry point
│   │   ├── lib/
│   │   │   ├── stacks/             # 10 CDK stacks
│   │   │   │   ├── api-stack.ts
│   │   │   │   ├── auth-stack.ts
│   │   │   │   ├── database-stack.ts
│   │   │   │   ├── dns-stack.ts
│   │   │   │   ├── email-stack.ts
│   │   │   │   ├── events-stack.ts
│   │   │   │   ├── landing-stack.ts
│   │   │   │   ├── log-archival-stack.ts
│   │   │   │   ├── monitoring-stack.ts
│   │   │   │   └── storage-stack.ts
│   │   │   ├── nested-stacks/      # Sub-stacks (api-core, api-platform)
│   │   │   ├── constructs/         # Custom CDK constructs
│   │   │   ├── config/             # Environment configs (dev, staging, production)
│   │   │   └── aspects/            # CDK aspects
│   │   └── graphql/                # AppSync schema (GPS real-time)
│   ├── __tests__/                  # 119 archivos de test
│   ├── layers/                     # Lambda layers compartidos
│   ├── scripts/                    # Scripts de deploy, seed, migration
│   ├── cdk.json                    # CDK config
│   ├── vitest.config.ts            # Tests unitarios
│   ├── vitest.integration.config.ts
│   └── package.json
│
├── fsm-web/                        # Web Admin (Angular 18 + TailwindCSS)
│   ├── src/app/
│   │   ├── features/               # 17 Feature modules
│   │   │   ├── analytics/
│   │   │   ├── assets/
│   │   │   ├── auth/
│   │   │   ├── contracts/
│   │   │   ├── customers/
│   │   │   ├── dashboard/
│   │   │   ├── gps-reports/
│   │   │   ├── inventory/
│   │   │   ├── invoicing/
│   │   │   ├── not-found/
│   │   │   ├── quotes/
│   │   │   ├── reports/
│   │   │   ├── schedule/
│   │   │   ├── settings/
│   │   │   ├── settlement/
│   │   │   ├── team/
│   │   │   └── work-orders/
│   │   ├── core/                   # Guards, interceptors, services globales
│   │   ├── layout/                 # Sidebar, header, shell
│   │   ├── shared/                 # Componentes compartidos UI
│   │   ├── app.routes.ts
│   │   └── app.config.ts
│   ├── angular.json
│   ├── tailwind.config.js
│   ├── vitest.config.ts
│   └── package.json
│
├── fsm-mobile/                     # App Móvil Técnico (Ionic 8 + Angular + Capacitor)
│   ├── src/app/
│   │   ├── features/               # 17 Feature modules
│   │   │   ├── asset-registration/
│   │   │   ├── auth/
│   │   │   ├── complete/
│   │   │   ├── customers/
│   │   │   ├── evidence/
│   │   │   ├── execution/
│   │   │   ├── history/
│   │   │   ├── inventory/
│   │   │   ├── login/
│   │   │   ├── my-orders/
│   │   │   ├── notifications/
│   │   │   ├── onboarding/
│   │   │   ├── order-detail/
│   │   │   ├── profile/
│   │   │   ├── settlement/
│   │   │   ├── sync/
│   │   │   └── walk-in/
│   │   ├── core/                   # Guards, services, interceptors
│   │   ├── offline/                # SQLite sync, queue, storage
│   │   ├── shared/                 # Componentes compartidos móvil
│   │   ├── app.routes.ts
│   │   └── app.config.ts
│   ├── android/                    # Proyecto Android nativo (Capacitor)
│   ├── apk-releases/               # APKs generados
│   ├── capacitor.config.ts
│   ├── ionic.config.json
│   ├── vitest.config.ts
│   └── package.json
│
├── fsm-platform-admin/             # Platform Admin (Angular 18 + TailwindCSS)
│   ├── src/                        # 8 Feature modules (auth, crm, dashboard, finance, login, payments, settings, tenants)
│   ├── angular.json
│   ├── tailwind.config.js
│   ├── vitest.config.ts
│   └── package.json
│
├── fsm-shared/                     # @fsm/shared (tipos, constantes, utils compartidos)
│   ├── src/                        # Interfaces, enums, validators, helpers
│   ├── dist/                       # Compilado
│   ├── eslint.config.mjs
│   ├── tsconfig.build.json
│   └── package.json
│
├── fsm-landing/                    # Landing Page (Astro 4 + Preact + TailwindCSS)
│   ├── src/                        # Pages por vertical, components, layouts
│   ├── public/                     # Assets estáticos
│   ├── astro.config.mjs
│   ├── tailwind.config.mjs
│   └── package.json
│
├── packages/                       # Sub-packages GPS
│   ├── gps-core/                   # @gps/core — Motor de procesamiento GPS
│   ├── gps-infra-appsync/          # @gps/infra-appsync — Suscripciones real-time
│   ├── gps-infra-aws-location/     # @gps/infra-aws-location — Rutas y geocoding
│   └── gps-infra-dynamodb/         # @gps/infra-dynamodb — Tabla e índices GPS
│
├── e2e/                            # Tests end-to-end
├── scripts/                        # Scripts del workspace (deploy, CI/CD)
├── powers/                         # Kiro powers
└── semantic-review/                # Semantic review configs
```

### Comandos del Workspace

```bash
# Desde /Users/holmart/Documents/proyecto

# Instalar dependencias
pnpm install

# Build shared (requerido antes de builds de apps)
pnpm build:shared

# Backend
cd fsm-backend
pnpm test                           # Tests unitarios (vitest)
pnpm test:integration               # Tests de integración
pnpm cdk deploy --all               # Deploy infraestructura
pnpm cdk synth                      # Sintetizar CloudFormation

# Web Admin
cd fsm-web
pnpm start                          # Dev server (puerto 4200)
pnpm build                          # Build producción
pnpm test                           # Tests (vitest)

# App Móvil
cd fsm-mobile
pnpm start                          # Dev server (puerto 8100)
pnpm build                          # Build web
npx cap sync android                # Sync con Android
npx cap open android                # Abrir en Android Studio

# Platform Admin
cd fsm-platform-admin
pnpm start                          # Dev server (puerto 4300)
pnpm build                          # Build producción

# Landing
cd fsm-landing
pnpm dev                            # Dev server (puerto 3000)
pnpm build                          # Build estático

# Shared
cd fsm-shared
pnpm build                          # Compilar tipos/utils
```

### Repositorio Git

- **Plataforma:** GitHub
- **Branch principal:** `main`
- **Convención de commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`)
- **CI/CD:** GitHub Actions

### Documentación disponible en el proyecto

| Archivo | Contenido |
|---------|-----------|
| `DESCRIPCION-MODULOS-DETALLADA.md` | Módulos, endpoints, tablas, GSIs |
| `MANUAL-USUARIO-CAMPO.md` | Manual de usuario servicio en campo |
| `MANUAL-SUPER-ADMINISTRADOR.md` | Manual platform admin |
| `prototipos-pantallas.md` | Wireframes ASCII de todas las pantallas |
| `arquitectura-mvp-completa.md` | Arquitectura técnica detallada |
| `PLANTILLAS-POR-VERTICAL.md` | Checklists y field data por vertical |
| `COSTOS-MENSUALES-PRODUCCION.md` | Estimación de costos AWS |
| `GUIA-INTEGRACION-FACTURACION-ELECTRONICA.md` | Integración Alegra/Siigo |
| `GUIA-TESTING-FACTURACION-SANDBOX.md` | Testing facturación sandbox |
| `ENDPOINTS-EXTERNOS-CONSUMIDOS.md` | APIs externas (Wompi, Alegra, Meta WA, FCM) |
| `REPORTE-DEPLOY-STAGING-2026-06-02.md` | Reporte del deploy a staging |
| `REPORTE-PRODUCCION.md` | Estado de producción |
| `infraestructura-gaps-cerrados.md` | Gaps de infra resueltos |
| `setup-cuenta-aws-prerequisitos.md` | Pre-requisitos cuenta AWS |
| `viabilidad-fsm-colombia.md` | Estudio de viabilidad mercado |
