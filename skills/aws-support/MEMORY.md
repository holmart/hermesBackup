# AWS Infrastructure - Contexto

## Cuenta AWS

- Region principal: us-east-1
- Servicios principales: EC2, DynamoDB, Lambda, API Gateway, S3, CloudFront, Cognito, SSM

## Infraestructura Activa

### EC2

| Tag Name | Tipo | Proposito |
|----------|------|----------|
| Hermes-Agent-Server | t3.small | Hermes Agent + Gateway Telegram |

- OS: Ubuntu 22.04
- Acceso: SSM (sin SSH, sin key pair)
- Servicio: hermes-gateway.service (systemd)

### DynamoDB

| Tabla | Proposito |
|-------|----------|
| sifagent-crm-clients | CRM de leads/clientes |

### Lambda

- Backend FSM SaaS: 32 Lambdas
- Region: us-east-1

### S3

- Buckets del FSM (verificar nombres actuales)

### API Gateway

- APIs REST del FSM backend
- Autenticacion via Cognito

## Proyecto Principal: FSM SaaS (SIF Agent)

Plataforma de Field Service Management:
- Backend: AWS Serverless (Lambda + DynamoDB + API Gateway)
- Frontend Web: Angular 18
- App Movil: Ionic 8 + Capacitor 8

## Patrones de Acceso

- Para la EC2 de Hermes: siempre buscar por tag Name=Hermes-Agent-Server
- La IP puede cambiar (no hay Elastic IP)
- Instance ID puede cambiar si se recrea

## Contactos

- Telegram: canal principal de notificaciones
- Usuario: holmart
