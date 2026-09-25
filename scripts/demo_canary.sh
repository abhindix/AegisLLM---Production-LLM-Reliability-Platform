#!/usr/bin/env bash
set -euo pipefail
curl -fsS -X POST http://localhost:8080/models -H 'Content-Type: application/json' -d '{"name":"aegis-model","version":"v1","backend":"mock","quality_score":0.98}'
curl -fsS -X POST http://localhost:8080/deploy/canary -H 'Content-Type: application/json' -d '{"model":"aegis-model","candidate_version":"v2","traffic_percent":5,"quality_score":0.97,"latency_p95_ms":400}'
curl -fsS -X POST http://localhost:8080/deploy/canary -H 'Content-Type: application/json' -d '{"model":"aegis-model","candidate_version":"v3","traffic_percent":5,"quality_score":0.70,"latency_p95_ms":2500}'
