$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\abhin\Desktop\AI-books\app=creation\research\aegisllm-production-platform"
Set-Location $projectRoot

$baseUrl = if ($env:AEGIS_BASE_URL) { $env:AEGIS_BASE_URL } else { "http://localhost:18080" }
$apiKey = $env:AEGIS_API_KEY
if (-not $apiKey) { throw "Set AEGIS_API_KEY before running this script." }
$authHeaders = @{ Authorization = ("Bearer " + $apiKey) }

Write-Host "==> Starting Docker Compose stack..."
docker compose down
docker compose up --build -d

Write-Host "==> Waiting for app health..."
$health = $null
for ($i = 0; $i -lt 30; $i++) {
    try {
        $health = Invoke-WebRequest -Uri "$baseUrl/health/ready" -Method Get -UseBasicParsing
        if ($health.StatusCode -eq 200) { break }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $health -or $health.StatusCode -ne 200) {
    throw "API health check failed. Check docker logs."
}

Write-Host "==> Health check passed"
$health.Content

Write-Host "==> Sending chat completion request..."
$resp = Invoke-WebRequest -Uri "$baseUrl/v1/chat/completions" -Method Post -ContentType "application/json" -Headers $authHeaders -Body '{"model":"mock-model","messages":[{"role":"user","content":"Explain KV cache in one sentence."}],"max_tokens":32}' -UseBasicParsing
$resp.Content

Write-Host "==> Prometheus metrics check..."
$metrics = Invoke-WebRequest -Uri "$baseUrl/metrics" -UseBasicParsing
if ($metrics.StatusCode -ne 200) { throw "Metrics endpoint not responding" }
Write-Host "Metrics endpoint OK"

Write-Host "==> Open Prometheus, Grafana, and Jaeger in browser"
Start-Process "http://localhost:9090"
Start-Process "http://localhost:3000"
Start-Process "http://localhost:16686"

Write-Host "==> Prometheus queries to run:"
Write-Host "  sum(aegis_requests_total)"
Write-Host "  sum by (backend) (aegis_requests_total)"
Write-Host "  histogram_quantile(0.95, sum by (le, backend) (rate(aegis_request_duration_seconds_bucket[5m])))"
Write-Host "  up"

Write-Host "==> Jaeger service to inspect: aegisllm-gateway"
Write-Host "==> Done."
