#!/usr/bin/env bash
# Usage: ./scripts.sh reload   (stop n8n, re-import + publish the workflow, start n8n)
#        ./scripts.sh demo     (post the three sample briefs)
set -euo pipefail
cd "$(dirname "$0")"
export N8N_USER_FOLDER="$PWD/n8n-app/data" N8N_DIAGNOSTICS_ENABLED=false N8N_PERSONALIZATION_ENABLED=false N8N_SECURE_COOKIE=false
case "${1:-}" in
  reload)
    pkill -f "n8n start" || true; sleep 3
    python3 workflow/build_workflow.py
    (cd n8n-app && npx n8n import:workflow --input=../workflow/creative-brief-intake.json >/dev/null && npx n8n publish:workflow --id=kmBriefIntake01 >/dev/null)
    (cd n8n-app && nohup npx n8n start > /tmp/n8n.log 2>&1 &)
    until curl -sf localhost:5678/healthz >/dev/null; do sleep 2; done; echo "n8n up" ;;
  demo)
    for f in complete-brief vague-brief invalid; do
      echo "== $f"; curl -s -X POST localhost:5678/webhook/creative-brief -H 'Content-Type: application/json' \
        -d @samples/$f.json -w '\nHTTP %{http_code}\n' | tee output/response-$f.json; done ;;
esac
