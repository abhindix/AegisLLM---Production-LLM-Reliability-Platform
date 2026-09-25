# Phase 5 Production-Safe Deployment

This repository uses a production-safe split for Docker Desktop Kubernetes.

## Recommended architecture

- Kubernetes runtime: app, PostgreSQL, Redis
- Local compose runtime: Kafka when needed for event-stream testing
- Kafka is intentionally not forced into Docker Desktop Kubernetes because the single-node KRaft broker is not reliable there
- The app tolerates missing Kafka and reports it as `unavailable` instead of failing readiness

## Why Kafka is excluded from the cluster

The Kafka KRaft configuration repeatedly fails in Docker Desktop Kubernetes with connection and timeout errors such as:

- `Connection to node 1 ... could not be established`
- `Unable to register the broker because the RPC got timed out before it could be sent`
- readiness and liveness probes timing out

This is not an application bug. It is a local-environment operational issue with single-node KRaft in a constrained Kubernetes setup.

## Stable Phase 5 setup

Use the Kubernetes manifest for the app runtime:

```powershell
kubectl apply -f .\infra\k8s\aegisllm.yaml
kubectl -n aegisllm get pods
kubectl -n aegisllm port-forward svc/aegisllm 18081:80
```

Verify the app with:

```powershell
Invoke-RestMethod -Uri 'http://localhost:18081/health/ready'
```

Expected result:

```json
{
  "status": "ok",
  "checks": {
    "postgres": "ok",
    "redis": "ok",
    "kafka": "unavailable"
  }
}
```

## Local eventing when Kafka is needed

If you need Kafka for local event-flow testing, start it in Docker Compose instead of the Kubernetes cluster:

```powershell
docker compose up -d postgres redis kafka jaeger prometheus grafana
docker compose up -d api
```

Then validate:

```powershell
docker compose logs --tail=200 kafka
curl http://localhost:18080/health/ready
```

## Operational rule

For Docker Desktop, the supported production-safe pattern is:

1. Kubernetes for the stable app runtime
2. Compose for local event-stream integration
3. Kafka not installed inside the cluster until you have a real multi-node or managed broker deployment

## Verification status

The stable Phase 5 app runtime has been verified live:

- health endpoint returns `ok`
- Postgres and Redis are healthy
- the app remains reachable even with Kafka unavailable
- the application still responds normally to chat and operational requests
