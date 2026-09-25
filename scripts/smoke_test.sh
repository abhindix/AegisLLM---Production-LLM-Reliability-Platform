#!/usr/bin/env bash
set -euo pipefail
curl -fsS http://localhost:8080/health/ready
curl -fsS -X POST http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"mock-model","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}'
curl -fsS http://localhost:8080/metrics >/dev/null
echo 'AegisLLM smoke test passed'
