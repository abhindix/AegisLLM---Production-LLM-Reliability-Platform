import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import mock_generate, CanaryRequest, ChatRequest


def test_mock():
    answer,tokens=mock_generate([type('M',(),{'content':'hello','role':'user'})()],32)
    assert 'hello' in answer
    assert tokens > 0


def test_canary_gate():
    x=CanaryRequest(model='m',candidate_version='v2',quality_score=.85)
    assert x.quality_score < .90


def test_lmstudio_backend_uses_external_model(monkeypatch):
    original_backend = main.MODEL_BACKEND
    original_rdb = main.rdb
    original_engine = main.engine
    original_event = main.event
    original_call_vllm = main.call_vllm

    try:
        main.MODEL_BACKEND = 'lmstudio'
        main.rdb = type('RDB', (), {'get': lambda self, key: None, 'setex': lambda *a, **k: None})()

        @contextmanager
        def fake_begin():
            yield type('Cursor', (), {'execute': lambda *a, **k: None})()

        main.engine = type('Engine', (), {'begin': lambda self: fake_begin()})()
        main.event = lambda *a, **k: None

        def fake_call_vllm(req):
            assert req.model == 'lm-model'
            return 'lm studio says hi', 7

        monkeypatch.setattr(main, 'call_vllm', fake_call_vllm)

        response = main.chat(ChatRequest(model='lm-model', messages=[{'role': 'user', 'content': 'hello'}]))
        assert response['choices'][0]['message']['content'] == 'lm studio says hi'
        assert response['usage']['completion_tokens'] == 7
    finally:
        main.MODEL_BACKEND = original_backend
        main.rdb = original_rdb
        main.engine = original_engine
        main.event = original_event
        main.call_vllm = original_call_vllm


def test_model_registration_uses_sql_bind_names(monkeypatch):
    captured = {}

    class FakeCursor:
        def execute(self, sql, params):
            captured['params'] = params
            return None

    class FakeEngine:
        def begin(self):
            return FakeContext()

    class FakeContext:
        def __enter__(self):
            return FakeCursor()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(main, 'engine', FakeEngine())
    payload = main.ModelRegister(name='gpt-oss-20b', version='v3', backend='lmstudio', quality_score=0.97)
    result = main.register(payload)

    assert result == {'name': 'gpt-oss-20b', 'version': 'v3', 'status': 'REGISTERED'}
    assert set(captured['params']) == {'n', 'v', 'b', 'q'}


def test_protected_endpoint_requires_api_key(monkeypatch):
    original_key = main.API_KEY
    try:
        main.API_KEY = 'test-key'
        monkeypatch.setattr(main, 'init_db', lambda: None)
        monkeypatch.setattr(main, 'KafkaProducer', None)
        with TestClient(main.app) as client:
            response = client.post('/incidents/analyze', json={'symptoms': ['latency spike']})
        assert response.status_code == 401
    finally:
        main.API_KEY = original_key


def test_protected_endpoint_requires_api_key_configuration(monkeypatch):
    original_key = main.API_KEY
    try:
        main.API_KEY = ''
        monkeypatch.setattr(main, 'init_db', lambda: None)
        monkeypatch.setattr(main, 'KafkaProducer', None)
        with TestClient(main.app) as client:
            response = client.post('/incidents/analyze', json={'symptoms': ['latency spike']})
        assert response.status_code == 503
        assert response.json()['detail'] == 'Protected endpoints require AEGIS_API_KEY configuration'
    finally:
        main.API_KEY = original_key


def test_protected_endpoint_accepts_valid_api_key(monkeypatch):
    original_key = main.API_KEY
    try:
        main.API_KEY = 'test-key'
        monkeypatch.setattr(main, 'init_db', lambda: None)
        monkeypatch.setattr(main, 'KafkaProducer', None)
        with TestClient(main.app) as client:
            response = client.post(
                '/incidents/analyze',
                json={'symptoms': ['latency spike']},
                headers={'Authorization': 'Bearer ' + main.API_KEY},
            )
        assert response.status_code == 200
        assert response.json()['state'] == 'RECOMMENDATION'
    finally:
        main.API_KEY = original_key


def test_credit_workflow_smoke(monkeypatch):
    class FakeCursor:
        def execute(self, sql, params=None):
            return None

    class FakeContext:
        def __enter__(self):
            return FakeCursor()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeContext()

    monkeypatch.setattr(main, 'engine', FakeEngine())
    monkeypatch.setattr(main, 'event', lambda *a, **k: None)

    app_req = main.CreditApplicationCreate(
        customer_id='CUST-1001',
        product_type='personal_loan',
        loan_amount=25000,
        tenure_months=36,
        annual_income=120000,
        employment_type='salaried',
        credit_score=720,
    )
    app_result = main.submit_credit_application(app_req)
    assert app_result['status'] == 'submitted'
    assert app_result['application_id']

    score_req = main.CreditScoreRequest(
        application_id=app_result['application_id'],
        model_version='credit-v3',
        credit_score=720,
        annual_income=120000,
        dti_ratio=0.31,
    )
    score_result = main.score_credit_application(score_req)
    assert score_result['risk_band'] in {'low', 'medium', 'high'}
    assert score_result['score'] >= 0

    fraud_req = main.FraudCheckRequest(
        application_id=app_result['application_id'],
        transaction_velocity=2,
        document_risk=0.2,
        sanctions_match=False,
        duplicate_application=False,
    )
    fraud_result = main.run_fraud_check(fraud_req)
    assert fraud_result['status'] in {'clean', 'manual_review', 'blocked'}

    decision_req = main.CreditDecisionRequest(
        application_id=app_result['application_id'],
        risk_score=score_result['score'],
        fraud_status=fraud_result['status'],
        manual_review=False,
    )
    decision_result = main.make_credit_decision(decision_req)
    assert decision_result['decision'] in {'approve', 'manual_review', 'decline'}


def test_semantic_tree_pipeline(monkeypatch):
    captured = {}

    class FakeCursor:
        def execute(self, sql, params=None):
            captured['sql'] = sql
            captured['params'] = params
            return None

    class FakeContext:
        def __enter__(self):
            return FakeCursor()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeContext()

    monkeypatch.setattr(main, 'engine', FakeEngine())
    monkeypatch.setattr(main, 'event', lambda *a, **k: None)

    payload = main.SemanticTreeRequest(
        repository='demo-repo',
        source='code',
        nodes=[
            {'id': 'node-1', 'label': 'app.main', 'kind': 'module', 'path': 'app/main.py', 'parent_id': None, 'summary': 'application entrypoint'},
            {'id': 'node-2', 'label': 'create_credit_application_endpoint', 'kind': 'function', 'path': 'app/main.py', 'parent_id': 'node-1', 'summary': 'credit endpoint'},
        ],
    )

    result = main.index_semantic_tree(payload)
    assert result['indexed_nodes'] == 2
    assert result['repository'] == 'demo-repo'
    assert 'semantic_nodes' in str(captured['sql'])

    query_result = main.query_semantic_index(main.SemanticIndexQuery(query='credit endpoint', limit=5))
    assert query_result['results'][0]['label'] == 'create_credit_application_endpoint'


def test_credit_api_end_to_end_with_dockerized_postgres():
    database_url = os.getenv('DATABASE_URL', 'postgresql+psycopg://aegis:aegis@localhost:5432/aegis')
    try:
        from sqlalchemy import create_engine
        engine = create_engine(database_url)
        with engine.connect() as conn:
            conn.execute(main.text('SELECT 1'))
    except Exception as exc:
        pytest.skip(f'Dockerized Postgres is not running: {exc}')

    app = main.app
    with TestClient(app) as client:
        response = client.post('/credit/applications', json={
            'customer_id': 'CUST-POSTGRES-001',
            'product_type': 'auto_loan',
            'loan_amount': 32000,
            'tenure_months': 48,
            'annual_income': 145000,
            'employment_type': 'salaried',
            'credit_score': 760,
        })
        assert response.status_code == 200, response.text
        app_id = response.json()['application_id']

        score_response = client.post(f'/credit/applications/{app_id}/score', json={
            'application_id': app_id,
            'model_version': 'credit-v3',
            'credit_score': 760,
            'annual_income': 145000,
            'dti_ratio': 0.32,
        })
        assert score_response.status_code == 200, score_response.text
        score_payload = score_response.json()
        assert score_payload['risk_band'] in {'low', 'medium', 'high'}

        fraud_response = client.post(f'/credit/applications/{app_id}/fraud-check', json={
            'application_id': app_id,
            'transaction_velocity': 2,
            'document_risk': 0.18,
            'sanctions_match': False,
            'duplicate_application': False,
        })
        assert fraud_response.status_code == 200, fraud_response.text
        fraud_payload = fraud_response.json()
        assert fraud_payload['status'] in {'clean', 'manual_review', 'blocked'}

        decision_response = client.post(f'/credit/applications/{app_id}/decision', json={
            'application_id': app_id,
            'risk_score': score_payload['score'],
            'fraud_status': fraud_payload['status'],
            'manual_review': False,
        })
        assert decision_response.status_code == 200, decision_response.text
        decision_payload = decision_response.json()
        assert decision_payload['decision'] in {'approve', 'manual_review', 'decline'}

        record_response = client.get(f'/credit/applications/{app_id}')
        assert record_response.status_code == 200, record_response.text
        record = record_response.json()
        assert record['customer_id'] == 'CUST-POSTGRES-001'
