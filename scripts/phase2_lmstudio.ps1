$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\abhin\Desktop\AI-books\app=creation\research\aegisllm-production-platform"
Set-Location $projectRoot

$env:MODEL_BACKEND = "lmstudio"
$env:LMSTUDIO_URL = "http://host.docker.internal:1234"
$env:LMSTUDIO_MODEL = "openai/gpt-oss-20b"
$env:VLLM_URL = "http://host.docker.internal:1234"

Write-Host "==> Restarting API in LM Studio mode..."
docker compose up -d --force-recreate api

Write-Host "==> Waiting for app health..."
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8080/health/ready" -Method Get -UseBasicParsing
        if ($resp.StatusCode -eq 200) { break }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host "==> Sending request through the gateway..."
$body = '{"model":"openai/gpt-oss-20b","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}'
$resp = Invoke-WebRequest -Uri "http://localhost:8080/v1/chat/completions" -Method Post -ContentType "application/json" -Body $body -UseBasicParsing
$resp.Content

Write-Host "==> LM Studio should be available at http://localhost:1234"
Write-Host "==> Phase 2 via LM Studio validation complete."
