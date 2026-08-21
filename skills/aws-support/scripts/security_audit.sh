#!/bin/bash
# AWS Security Quick Audit
# Uso: bash security_audit.sh [region]

REGION="${1:-us-east-1}"
echo "=========================================="
echo "  AWS Security Audit - $(date +%Y-%m-%d\ %H:%M\ UTC)"
echo "  Region: $REGION"
echo "=========================================="

echo ""
echo "--- 1. Security Groups con acceso 0.0.0.0/0 (ingress) ---"
aws ec2 describe-security-groups --region "$REGION" --query "SecurityGroups[?IpPermissions[?IpRanges[?CidrIp=='0.0.0.0/0']]].[GroupId,GroupName]" --output table 2>/dev/null

echo ""
echo "--- 2. IAM Users sin MFA ---"
for user in $(aws iam list-users --query "Users[].UserName" --output text 2>/dev/null); do
  MFA=$(aws iam list-mfa-devices --user-name "$user" --query "MFADevices" --output text 2>/dev/null)
  if [ -z "$MFA" ]; then
    echo "  WARN: $user - Sin MFA"
  fi
done

echo ""
echo "--- 3. EBS Volumes sin encriptacion ---"
aws ec2 describe-volumes --region "$REGION" --query "Volumes[?Encrypted==\`false\`].[VolumeId,Size,State]" --output table 2>/dev/null || echo "Todos encriptados"

echo ""
echo "--- 4. Root Account MFA ---"
aws iam get-account-summary --query "SummaryMap.AccountMFAEnabled" --output text 2>/dev/null

echo ""
echo "--- 5. Access Keys antiguas (>90 dias) ---"
aws iam generate-credential-report > /dev/null 2>&1
sleep 2
aws iam get-credential-report --query "Content" --output text 2>/dev/null | base64 -d 2>/dev/null | awk -F',' 'NR>1 && $9!="N/A" {print $1, $9}'

echo ""
echo "=========================================="
echo "  Security Audit completo"
echo "=========================================="
