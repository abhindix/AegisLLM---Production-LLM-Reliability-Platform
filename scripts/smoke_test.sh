#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${AEGIS_BASE_URL:-http://localhost:18080}"
AUTH_HEADER="Authorization: ******"
curl -fsS "$BASE_URL/health/ready"
curl -fsS -X POST "$BASE_URL/v1/chat/completions" -H 'Content-Type: application/json' -H "$AUTH_HEADER" -d '{"model":"mock-model","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}'
curl -fsS "$BASE_URL/metrics" >/dev/null
echo 'AegisLLM smoke test passed'
