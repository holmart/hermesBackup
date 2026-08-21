#!/bin/bash
# EC2 Instance Diagnostics
# Uso: bash instance_diagnostics.sh <instance-id> [region]

INSTANCE_ID="${1}"
REGION="${2:-us-east-1}"

if [ -z "$INSTANCE_ID" ]; then
  echo "Uso: bash instance_diagnostics.sh <instance-id> [region]"
  echo "Instancias disponibles:"
  aws ec2 describe-instances --region "$REGION" --query "Reservations[].Instances[].[Tags[?Key=='Name'].Value|[0],InstanceId,State.Name]" --output table
  exit 1
fi

echo "=========================================="
echo "  EC2 Diagnostics: $INSTANCE_ID"
echo "  Region: $REGION"
echo "=========================================="

echo ""
echo "--- Info General ---"
aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" --query "Reservations[].Instances[].{Name:Tags[?Key=='Name'].Value|[0],ID:InstanceId,Type:InstanceType,State:State.Name,PublicIP:PublicIpAddress,PrivateIP:PrivateIpAddress,LaunchTime:LaunchTime}" --output table 2>/dev/null

echo ""
echo "--- Status Checks ---"
aws ec2 describe-instance-status --region "$REGION" --instance-ids "$INSTANCE_ID" --query "InstanceStatuses[].{Instance:InstanceStatus.Status,System:SystemStatus.Status}" --output table 2>/dev/null

echo ""
echo "--- Security Groups ---"
aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" --query "Reservations[].Instances[].SecurityGroups[].[GroupId,GroupName]" --output table 2>/dev/null

echo ""
echo "--- CPU Utilization (ultima hora) ---"
START=$(date -u -d "1 hour ago" +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -v-1H +%Y-%m-%dT%H:%M:%S)
END=$(date -u +%Y-%m-%dT%H:%M:%S)
aws cloudwatch get-metric-statistics --region "$REGION" --namespace AWS/EC2 --metric-name CPUUtilization --dimensions "Name=InstanceId,Value=$INSTANCE_ID" --start-time "$START" --end-time "$END" --period 300 --statistics Average Maximum --output json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
points = sorted(data.get('Datapoints', []), key=lambda x: x['Timestamp'])
for p in points:
    ts = p['Timestamp'][:16]
    avg = p['Average']
    mx = p['Maximum']
    print(f'  {ts}  Avg:{avg:5.1f}%  Max:{mx:5.1f}%')
if not points: print('  Sin datos CPU')
"

echo ""
echo "--- EBS Volumes ---"
aws ec2 describe-volumes --region "$REGION" --filters "Name=attachment.instance-id,Values=$INSTANCE_ID" --query "Volumes[].{ID:VolumeId,Size:Size,Type:VolumeType,Encrypted:Encrypted}" --output table 2>/dev/null

echo ""
echo "--- SSM Agent ---"
aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query "InstanceInformationList[].{Status:PingStatus,Version:AgentVersion,Platform:PlatformName}" --output table 2>/dev/null

echo ""
echo "=========================================="
echo "  Diagnostics completo"
echo "=========================================="
