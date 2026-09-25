$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\abhin\Desktop\AI-books\app=creation\research\aegisllm-production-platform"
Set-Location $projectRoot

$baseUrl = if ($env:AEGIS_BASE_URL) { $env:AEGIS_BASE_URL } else { "http://localhost:18080" }
$apiKey = if ($env:AEGIS_API_KEY) { $env:AEGIS_API_KEY } else { "change-me-aegis-api-key" }
$authHeaders = @{ Authorization = ("Bearer " + $apiKey) }

$env:MODEL_BACKEND = "lmstudio"
$env:LMSTUDIO_URL = "http://host.docker.internal:1234"
$env:LMSTUDIO_MODEL = "openai/gpt-oss-20b"
$env:VLLM_URL = "http://host.docker.internal:1234"

Write-Host "==> Restarting API in LM Studio mode..."
docker compose up -d --force-recreate api

Write-Host "==> Waiting for app health..."
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "$baseUrl/health/ready" -Method Get -UseBasicParsing
        if ($resp.StatusCode -eq 200) { break }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host "==> Sending request through the gateway..."
$body = '{"model":"openai/gpt-oss-20b","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}'
$resp = Invoke-WebRequest -Uri "$baseUrl/v1/chat/completions" -Method Post -ContentType "application/json" -Headers $authHeaders -Body $body -UseBasicParsing
$resp.Content

Write-Host "==> LM Studio should be available at http://localhost:1234"
Write-Host "==> Phase 2 via LM Studio validation complete."
