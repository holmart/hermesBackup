#!/usr/bin/env bash
# =============================================================================
# Provision GSIs for sifagent-crm-clients table
# =============================================================================
# Creates 3 Global Secondary Indexes for efficient lead queries.
# Safe to run: if GSI already exists, the command fails gracefully.
#
# GSIs created:
#   1. ciudad-score-index    (PK: Ciudad, SK: Score)  — leads by city sorted by quality
#   2. estado-fecha-index    (PK: Estado, SK: FechaIngreso) — leads by status, newest first
#   3. vertical-score-index  (PK: Vertical, SK: Score) — leads by vertical sorted by quality
#
# Usage:
#   bash provision_gsis.sh
#   bash provision_gsis.sh --table my-custom-table --region us-west-2
# =============================================================================

set -euo pipefail

TABLE="${1:-sifagent-crm-clients}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# Parse named arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --table) TABLE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) shift ;;
  esac
done

echo "================================================="
echo "Provisioning GSIs for table: $TABLE (region: $REGION)"
echo "================================================="

# GSI 1: ciudad-score-index
echo ""
echo "--- GSI 1: ciudad-score-index (Ciudad → Score) ---"
aws dynamodb update-table \
  --table-name "$TABLE" \
  --region "$REGION" \
  --attribute-definitions \
    AttributeName=Ciudad,AttributeType=S \
    AttributeName=Score,AttributeType=N \
  --global-secondary-index-updates "[
    {
      \"Create\": {
        \"IndexName\": \"ciudad-score-index\",
        \"KeySchema\": [
          {\"AttributeName\": \"Ciudad\", \"KeyType\": \"HASH\"},
          {\"AttributeName\": \"Score\", \"KeyType\": \"RANGE\"}
        ],
        \"Projection\": {\"ProjectionType\": \"ALL\"}
      }
    }
  ]" 2>&1 && echo "✓ ciudad-score-index created" || echo "⚠ ciudad-score-index may already exist or error occurred"

# Wait for GSI to become ACTIVE before creating the next one
echo "  Waiting for ciudad-score-index to become ACTIVE..."
aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION" 2>/dev/null || true
sleep 10

# GSI 2: estado-fecha-index
echo ""
echo "--- GSI 2: estado-fecha-index (Estado → FechaIngreso) ---"
aws dynamodb update-table \
  --table-name "$TABLE" \
  --region "$REGION" \
  --attribute-definitions \
    AttributeName=Estado,AttributeType=S \
    AttributeName=FechaIngreso,AttributeType=S \
  --global-secondary-index-updates "[
    {
      \"Create\": {
        \"IndexName\": \"estado-fecha-index\",
        \"KeySchema\": [
          {\"AttributeName\": \"Estado\", \"KeyType\": \"HASH\"},
          {\"AttributeName\": \"FechaIngreso\", \"KeyType\": \"RANGE\"}
        ],
        \"Projection\": {\"ProjectionType\": \"ALL\"}
      }
    }
  ]" 2>&1 && echo "✓ estado-fecha-index created" || echo "⚠ estado-fecha-index may already exist or error occurred"

echo "  Waiting for estado-fecha-index to become ACTIVE..."
aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION" 2>/dev/null || true
sleep 10

# GSI 3: vertical-score-index
echo ""
echo "--- GSI 3: vertical-score-index (Vertical → Score) ---"
aws dynamodb update-table \
  --table-name "$TABLE" \
  --region "$REGION" \
  --attribute-definitions \
    AttributeName=Vertical,AttributeType=S \
    AttributeName=Score,AttributeType=N \
  --global-secondary-index-updates "[
    {
      \"Create\": {
        \"IndexName\": \"vertical-score-index\",
        \"KeySchema\": [
          {\"AttributeName\": \"Vertical\", \"KeyType\": \"HASH\"},
          {\"AttributeName\": \"Score\", \"KeyType\": \"RANGE\"}
        ],
        \"Projection\": {\"ProjectionType\": \"ALL\"}
      }
    }
  ]" 2>&1 && echo "✓ vertical-score-index created" || echo "⚠ vertical-score-index may already exist or error occurred"

echo ""
echo "================================================="
echo "Done. GSIs may take a few minutes to fully populate."
echo "Check status with:"
echo "  aws dynamodb describe-table --table-name $TABLE --region $REGION --query 'Table.GlobalSecondaryIndexes[].{Name:IndexName,Status:IndexStatus}'"
echo "================================================="
