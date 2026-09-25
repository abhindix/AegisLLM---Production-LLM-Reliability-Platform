# AegisLLM — Production LLM Reliability Platform

A runnable portfolio implementation of the seven-phase AegisLLM roadmap. It starts locally with **Docker Compose + Kafka + FastAPI + PostgreSQL + Redis + mock LLM**, then provides optional vLLM/GPU observability, model lifecycle gates, canary/rollback, LangGraph incident workflow, Kubernetes/Helm/Argo CD, Terraform AWS scaffolding, chaos tests and load benchmarks.

## Architecture
Client → FastAPI Gateway → mock/vLLM → PostgreSQL + Redis; inference/deployment events → Kafka; metrics → Prometheus → Grafana; traces → OpenTelemetry/Jaeger. Kubernetes delivery is Helm + Argo CD; AWS path is Terraform → EKS/ECR/S3 with a clear extension point for SageMaker.

## Quick start — Phase 1

Prerequisites: Docker Desktop with the Linux engine running and Docker Compose v2.

```bash
cp .env.example .env
# review the placeholder dev secrets in .env before sharing the stack
docker compose up --build -d
```

Wait for healthy containers, then:

```bash
curl http://localhost:18080/health/ready
bash scripts/smoke_test.sh
```

Open:
- API: http://localhost:18080/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (aegisadmin / value from GRAFANA_ADMIN_PASSWORD)
- Jaeger: http://localhost:16686

Protected endpoints require a bearer token derived from `AEGIS_API_KEY`. Health and the demo landing pages stay open for local checks, and `/metrics` stays open for Prometheus scraping.

## Demo the lifecycle

```bash
AEGIS_API_KEY=${AEGIS_API_KEY:-change-me-aegis-api-key} bash scripts/demo_canary.sh
```

The first candidate passes the quality/latency gate and receives 5% canary traffic. The second intentionally fails and is recorded as a rollback.

## Phase 2 — vLLM

A GPU profile is included:

```bash
HUGGING_FACE_HUB_TOKEN=... docker compose --profile gpu up -d
```

Then switch `MODEL_BACKEND=vllm` and recreate the API. The vLLM service exposes Prometheus-compatible metrics and supports OpenTelemetry tracing.

## Phase 3 — registry + quality + canary

`/models` stores immutable model versions. `/deploy/canary` evaluates quality and latency gates and records `CANARY`, `PROMOTED`-style decisions or `ROLLED_BACK` evidence in PostgreSQL. Extend the evaluation dataset under `evaluations/` before production use.

## Phase 4 — LangGraph incident commander

`/incidents/analyze` is the deterministic safety boundary. The production design is: classify → collect evidence → form hypotheses → recommend remediation → human approval → verify → document. Keep infrastructure mutations behind explicit policy and approval.

## Phase 5 — Kubernetes / Helm / Argo CD / chaos

```bash
kubectl create secret generic postgres-auth -n aegisllm --from-literal=POSTGRES_PASSWORD='<strong-password>'
kubectl create secret generic aegisllm-api-secrets -n aegisllm --from-literal=DATABASE_URL='postgresql+psycopg://aegis:<strong-password>@postgres:5432/aegis' --from-literal=AEGIS_API_KEY='<api-key>'
kubectl apply -f infra/k8s/aegisllm.yaml
helm upgrade --install aegisllm infra/helm/aegisllm -n aegisllm --create-namespace --set-string secrets.databaseUrl='postgresql+psycopg://aegis:<strong-password>@postgres:5432/aegis' --set-string secrets.apiKey='<api-key>'
kubectl apply -f chaos/pod-kill.yaml
kubectl apply -f chaos/network-delay.yaml
```

Set the real Git repository URL in `infra/argocd/application.yaml`, then install Argo CD and apply the Application.

## Phase 6 — AWS

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```

The module creates an EKS cluster, ECR repository and S3 artifact bucket. Do **not** run `apply` until AWS cost/quota/network/security choices are reviewed. SageMaker should be enabled only when a concrete model endpoint and IAM design are selected.

## Phase 7 — evidence

```bash
# Python load test
pip install locust
AEGIS_API_KEY=${AEGIS_API_KEY:-change-me-aegis-api-key} locust -f benchmarks/locustfile.py --host http://localhost:18080

# k6
AEGIS_API_KEY=${AEGIS_API_KEY:-change-me-aegis-api-key} k6 run benchmarks/k6-smoke.js
```

Record p50/p95/p99 latency, throughput, error rate, TTFT/TPOT for vLLM, token throughput, recovery time, lost requests, failover time, maximum sustainable throughput and cost per million tokens. Do not claim production numbers until measured.

## Safety / production notes

- Replace placeholder image repositories and pin image/model digests.
- Use real OIDC, IAM least privilege, Secrets Manager/KMS and private networking.
- Add migrations, signed images, SBOM/scanning, prompt/response redaction and tenant isolation.
- Run sustained, stress, spike, soak and failure-injection tests before making SLO claims.

This repository is intentionally honest: it is a **working local production-shaped platform plus deployable infrastructure scaffolding**, not a claim that AWS/GPU production execution has already occurred.
>>>>>>> 229a42a (Initial secure project snapshot)
