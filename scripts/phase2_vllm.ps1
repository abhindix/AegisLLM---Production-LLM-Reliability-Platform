$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\abhin\Desktop\AI-books\app=creation\research\aegisllm-production-platform"
Set-Location $projectRoot

$env:HUGGING_FACE_HUB_TOKEN = "your_token_here"
$env:MODEL_BACKEND = "vllm"

Write-Host "==> Starting vLLM GPU profile..."
docker compose --profile gpu up -d

Write-Host "==> Restarting API with vLLM backend..."
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
$body = '{"model":"mock-model","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}'
$resp = Invoke-WebRequest -Uri "http://localhost:8080/v1/chat/completions" -Method Post -ContentType "application/json" -Body $body -UseBasicParsing
$resp.Content

Write-Host "==> vLLM health check..."
try {
    $vllm = Invoke-WebRequest -Uri "http://localhost:8001/health" -Method Get -UseBasicParsing
    $vllm.Content
}
catch {
    Write-Host "vLLM health endpoint is not ready yet. Check docker compose logs vllm."
}

Write-Host "==> Prometheus and Jaeger are available at:"
Write-Host "  http://localhost:9090"
Write-Host "  http://localhost:16686"
Write-Host "==> Phase 2 validation complete."
