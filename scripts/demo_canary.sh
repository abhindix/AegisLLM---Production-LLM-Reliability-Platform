#!/usr/bin/env bash
set -euo pipefail
if [[ -f .env ]]; then
  set -a
  . ./.env
  set +a
fi
BASE_URL="${AEGIS_BASE_URL:-http://localhost:18080}"
API_KEY="${AEGIS_API_KEY:?set AEGIS_API_KEY or create .env from .env.example}"
curl -fsS -X POST "$BASE_URL/models" -H 'Content-Type: application/json' -H "Authorization: Bearer ${API_KEY}" -d '{"name":"aegis-model","version":"v1","backend":"mock","quality_score":0.98}'
curl -fsS -X POST "$BASE_URL/deploy/canary" -H 'Content-Type: application/json' -H "Authorization: Bearer ${API_KEY}" -d '{"model":"aegis-model","candidate_version":"v2","traffic_percent":5,"quality_score":0.97,"latency_p95_ms":400}'
curl -fsS -X POST "$BASE_URL/deploy/canary" -H 'Content-Type: application/json' -H "Authorization: Bearer ${API_KEY}" -d '{"model":"aegis-model","candidate_version":"v3","traffic_percent":5,"quality_score":0.70,"latency_p95_ms":2500}'
