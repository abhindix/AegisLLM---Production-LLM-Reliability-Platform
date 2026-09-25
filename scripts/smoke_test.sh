#!/usr/bin/env bash
set -euo pipefail
if [[ -f .env ]]; then
  set -a
  . ./.env
  set +a
fi
BASE_URL="${AEGIS_BASE_URL:-http://localhost:18080}"
API_KEY="${AEGIS_API_KEY:?set AEGIS_API_KEY or create .env from .env.example}"
curl -fsS "$BASE_URL/health/ready"
curl -fsS -X POST "$BASE_URL/v1/chat/completions" -H 'Content-Type: application/json' -H "Authorization: Bearer ${API_KEY}" -d '{"model":"mock-model","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}'
curl -fsS "$BASE_URL/metrics" >/dev/null
echo 'AegisLLM smoke test passed'
