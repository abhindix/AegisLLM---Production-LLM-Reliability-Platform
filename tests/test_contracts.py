import pathlib

def test_required_artifacts_exist():
    required=['docker-compose.yml','Dockerfile','README.md','observability/prometheus.yml','infra/helm/aegisllm/Chart.yaml','infra/argocd/application.yaml','infra/terraform/main.tf','chaos/pod-kill.yaml','benchmarks/k6-smoke.js']
    assert all(pathlib.Path(x).exists() for x in required)

def test_canary_policy_documented():
    readme=pathlib.Path('README.md').read_text()
    assert '5% canary' in readme
    assert 'rollback' in readme.lower()
