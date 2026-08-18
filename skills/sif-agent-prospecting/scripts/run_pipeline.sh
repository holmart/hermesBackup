#!/bin/bash
# Run pipeline for a specific vertical (or all if no argument)
# Usage: run_pipeline.sh [--vertical <id>]
export HOME=/home/ubuntu
export PATH=/home/ubuntu/.hermes/hermes-agent/.venv/bin:/home/ubuntu/.hermes/bin:/usr/local/bin:/usr/bin:/bin
export HERMES_HOME=/home/ubuntu/.hermes
cd /home/ubuntu/.hermes/skills/sif-agent-prospecting/scripts
python3 unified_lead_pipeline.py "$@" >> /home/ubuntu/.hermes/leads/cron_output.log 2>&1
