---
name: aws-support
description: Soporte y administracion de infraestructura AWS
version: 1.0.0
author: holmart
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [aws, cloud, devops, infrastructure, support, monitoring, security]
    category: devops
    requires_toolsets: [terminal, web_search]
environments:
  - terminal
---

# AWS Support Skill

Skill de soporte y administracion de infraestructura AWS.

## Cuando Usar

- Revisar estado de instancias EC2, servicios, o recursos AWS
- Diagnosticar problemas de infraestructura
- Auditar seguridad (security groups, IAM policies, public access)
- Revisar y optimizar costos
- Gestionar recursos (start/stop instancias, escalar, backups)
- Monitorear metricas de CloudWatch
- Revisar logs de CloudTrail o CloudWatch Logs
- Gestionar DynamoDB (tablas, capacidad, backups)
- Verificar estado de Lambda, API Gateway, S3
- Responder a alarmas o incidentes

## Scripts Disponibles

- scripts/health_check.sh: Health check completo
- scripts/security_audit.sh: Auditoria de seguridad
- scripts/cost_report.sh: Reporte de costos
- scripts/instance_diagnostics.sh: Diagnostico de instancia EC2

## Protocolo de Incidentes

1. Identificar recurso afectado
2. Evaluar impacto (produccion?)
3. Contener (rollback, failover, scale)
4. Diagnosticar (CloudWatch, logs)
5. Resolver y verificar
6. Documentar causa raiz

## Notas

- Operaciones destructivas: SIEMPRE confirmar con usuario
- Usar --dry-run cuando este disponible
- Region por defecto: us-east-1
- Costos en USD con 2 decimales
