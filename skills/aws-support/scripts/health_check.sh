#!/bin/bash
# AWS Infrastructure Health Check
# Uso: bash health_check.sh [region]

REGION="${1:-us-east-1}"
echo "=========================================="
echo "  AWS Health Check - $(date +%Y-%m-%d\ %H:%M\ UTC)"
echo "  Region: $REGION"
echo "=========================================="

echo ""
echo "--- EC2 Instances ---"
aws ec2 describe-instances --region "$REGION" --query "Reservations[].Instances[].[Tags[?Key=='Name'].Value|[0],InstanceId,State.Name,InstanceType,PublicIpAddress]" --output table 2>/dev/null || echo "ERROR: No se pudo consultar EC2"

echo ""
echo "--- CloudWatch Alarms (ALARM state) ---"
aws cloudwatch describe-alarms --region "$REGION" --state-value ALARM --query "MetricAlarms[].[AlarmName,StateReason]" --output table 2>/dev/null || echo "Sin alarmas activas"

echo ""
echo "--- DynamoDB Tables ---"
aws dynamodb list-tables --region "$REGION" --query "TableNames" --output table 2>/dev/null || echo "Sin tablas DynamoDB"

echo ""
echo "--- Lambda Functions (count) ---"
aws lambda list-functions --region "$REGION" --query "length(Functions)" --output text 2>/dev/null

echo ""
echo "--- S3 Buckets ---"
aws s3api list-buckets --query "length(Buckets)" --output text 2>/dev/null

echo ""
echo "--- EC2 Status Checks (failed) ---"
aws ec2 describe-instance-status --region "$REGION" --filters "Name=instance-status.status,Values=impaired" "Name=system-status.status,Values=impaired" --query "InstanceStatuses[].[InstanceId,InstanceStatus.Status,SystemStatus.Status]" --output table 2>/dev/null || echo "Sin status checks fallidos"

echo ""
echo "=========================================="
echo "  Health Check completo"
echo "=========================================="
