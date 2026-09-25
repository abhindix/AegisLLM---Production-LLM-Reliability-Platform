#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${AEGIS_BASE_URL:-http://localhost:18080}"
AUTH_HEADER="Authorization: ******"
curl -fsS -X POST "$BASE_URL/models" -H 'Content-Type: application/json' -H "$AUTH_HEADER" -d '{"name":"aegis-model","version":"v1","backend":"mock","quality_score":0.98}'
curl -fsS -X POST "$BASE_URL/deploy/canary" -H 'Content-Type: application/json' -H "$AUTH_HEADER" -d '{"model":"aegis-model","candidate_version":"v2","traffic_percent":5,"quality_score":0.97,"latency_p95_ms":400}'
curl -fsS -X POST "$BASE_URL/deploy/canary" -H 'Content-Type: application/json' -H "$AUTH_HEADER" -d '{"model":"aegis-model","candidate_version":"v3","traffic_percent":5,"quality_score":0.70,"latency_p95_ms":2500}'
