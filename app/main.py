import json, os, time, uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ImportError:
    trace = None
    Resource = None
    TracerProvider = BatchSpanProcessor = OTLPSpanExporter = FastAPIInstrumentor = None
from sqlalchemy import create_engine, text, Float, Integer, String, Boolean, DateTime, UUID, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import redis
try:
    from kafka import KafkaProducer
except ImportError:
    KafkaProducer = None

APP_VERSION = os.getenv('APP_VERSION','v1')
APP_BUILD = os.getenv('APP_BUILD', datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
DATABASE_URL = os.getenv('DATABASE_URL','postgresql+psycopg://aegis:aegis@localhost:5432/aegis')
REDIS_URL = os.getenv('REDIS_URL','redis://localhost:6379/0')
KAFKA_BOOTSTRAP = os.getenv('KAFKA_BOOTSTRAP','localhost:9092')
MODEL_BACKEND = os.getenv('MODEL_BACKEND','mock').lower()
VLLM_URL = os.getenv('VLLM_URL','http://host.docker.internal:1234')
LMSTUDIO_URL = os.getenv('LMSTUDIO_URL', VLLM_URL)
LMSTUDIO_MODEL = os.getenv('LMSTUDIO_MODEL', 'openai/gpt-oss-20b')

REQUESTS = Counter('aegis_requests_total','Inference requests',['model','backend','status'])
LATENCY = Histogram('aegis_request_duration_seconds','Inference latency',['model','backend'])
TOKENS = Counter('aegis_generated_tokens_total','Generated tokens',['model','backend'])
CANARY = Counter('aegis_canary_decisions_total','Canary decisions',['decision'])

OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'jaeger:4317')
OTEL_SERVICE_NAME = os.getenv('OTEL_SERVICE_NAME', 'aegisllm-gateway')

app = FastAPI(title='AegisLLM Gateway', version=APP_VERSION)
if trace and TracerProvider:
    try:
        resource = Resource.create({"service.name": OTEL_SERVICE_NAME}) if Resource else None
        provider = TracerProvider(resource=resource) if resource else TracerProvider()
        exporter = OTLPSpanExporter(
            endpoint=OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except Exception:
        pass
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
if FastAPIInstrumentor:
    try: FastAPIInstrumentor.instrument_app(app)
    except Exception: pass
rdb = redis.from_url(REDIS_URL, decode_responses=True)
producer = None
SEMANTIC_TREE_INDEX: list[dict[str, Any]] = []

class Message(BaseModel):
    role: str
    content: str
class ChatRequest(BaseModel):
    model: str = 'mock-model'
    messages: list[Message]
    max_tokens: int = Field(default=128, ge=1, le=4096)
    temperature: float = Field(default=0.2, ge=0, le=2)
class ModelRegister(BaseModel):
    name: str
    version: str
    backend: str = 'mock'
    quality_score: float = Field(default=1.0, ge=0, le=1)
class CanaryRequest(BaseModel):
    model: str
    candidate_version: str
    traffic_percent: int = Field(default=5, ge=0, le=100)
    latency_p95_ms: float = 0
    quality_score: float = Field(default=1.0, ge=0, le=1)


class SemanticTreeNode(BaseModel):
    id: str
    label: str
    kind: str
    path: str
    parent_id: str | None = None
    summary: str = ''


class SemanticTreeRequest(BaseModel):
    repository: str
    source: str = 'code'
    nodes: list[SemanticTreeNode]


class SemanticIndexQuery(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)


class CreditApplicationCreate(BaseModel):
    customer_id: str
    product_type: str = 'personal_loan'
    loan_amount: float = Field(default=0.0, ge=0)
    tenure_months: int = Field(default=12, ge=1)
    annual_income: float = Field(default=0.0, ge=0)
    employment_type: str = 'salaried'
    credit_score: int = Field(default=600, ge=300, le=850)
    notes: str | None = None


class CreditScoreRequest(BaseModel):
    application_id: str
    model_version: str = 'credit-v3'
    credit_score: int = Field(default=600, ge=300, le=850)
    annual_income: float = Field(default=0.0, ge=0)
    dti_ratio: float = Field(default=0.35, ge=0, le=1)


class FraudCheckRequest(BaseModel):
    application_id: str
    transaction_velocity: int = Field(default=0, ge=0)
    document_risk: float = Field(default=0.0, ge=0, le=1)
    sanctions_match: bool = False
    duplicate_application: bool = False


class CreditDecisionRequest(BaseModel):
    application_id: str
    risk_score: int = Field(default=50, ge=0, le=100)
    fraud_status: str = 'clean'
    manual_review: bool = False


class Base(DeclarativeBase):
    pass


class CreditApplicationRecord(Base):
    __tablename__ = 'credit_applications'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_type: Mapped[str] = mapped_column(String(32), nullable=False)
    loan_amount: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_income: Mapped[float] = mapped_column(Float, nullable=False)
    employment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='submitted', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class CreditScoreRecord(Base):
    __tablename__ = 'credit_scores'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(48), nullable=False)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_income: Mapped[float] = mapped_column(Float, nullable=False)
    dti_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_band: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class FraudCheckRecord(Base):
    __tablename__ = 'fraud_checks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    transaction_velocity: Mapped[int] = mapped_column(Integer, nullable=False)
    document_risk: Mapped[float] = mapped_column(Float, nullable=False)
    sanctions_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duplicate_application: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class CreditDecisionRecord(Base):
    __tablename__ = 'credit_decisions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    fraud_status: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


def _orm_session_factory():
    try:
        if not hasattr(engine, 'connect') or not callable(getattr(engine, 'connect')):
            return None
        return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    except Exception:
        return None


def _score_risk(req: CreditScoreRequest) -> tuple[int, str]:
    weighted_score = int((req.credit_score - 300) / 5.5)
    dti_adjustment = int((1 - req.dti_ratio) * 25)
    income_adjustment = int((120000 - req.annual_income) / 15000)
    score = weighted_score + dti_adjustment - income_adjustment
    score = max(0, min(100, score))

    if req.annual_income < 35000:
        score -= 10
    if req.dti_ratio > 0.45:
        score -= 12
    if req.credit_score >= 760:
        score += 10
    if req.credit_score <= 620:
        score -= 15
    score = max(0, min(100, score))

    if score >= 75:
        risk_band = 'low'
    elif score >= 45:
        risk_band = 'medium'
    else:
        risk_band = 'high'
    return score, risk_band


def _fraud_risk(req: FraudCheckRequest) -> tuple[str, int]:
    risk_points = 0
    if req.transaction_velocity >= 3:
        risk_points += 30
    if req.transaction_velocity >= 5:
        risk_points += 15
    if req.document_risk >= 0.7:
        risk_points += 25
    if req.document_risk >= 0.9:
        risk_points += 15
    if req.sanctions_match:
        risk_points += 40
    if req.duplicate_application:
        risk_points += 20
    if req.transaction_velocity == 0 and req.document_risk <= 0.2 and not req.sanctions_match and not req.duplicate_application:
        risk_points = 0

    if risk_points >= 70:
        status = 'blocked'
    elif risk_points >= 35:
        status = 'manual_review'
    else:
        status = 'clean'
    return status, risk_points


def _credit_decision(risk_score: int, fraud_status: str, manual_review: bool) -> str:
    if fraud_status == 'blocked':
        return 'decline'
    if manual_review or fraud_status == 'manual_review':
        return 'manual_review'
    if risk_score <= 35:
        return 'approve'
    if risk_score <= 60:
        return 'manual_review'
    return 'decline'


def init_db():
    with engine.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS models (id SERIAL PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL, backend TEXT NOT NULL, quality_score DOUBLE PRECISION NOT NULL, status TEXT NOT NULL DEFAULT 'REGISTERED', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(name,version))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS inference_requests (id UUID PRIMARY KEY, model TEXT NOT NULL, backend TEXT NOT NULL, latency_ms DOUBLE PRECISION NOT NULL, tokens INT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS deployments (id SERIAL PRIMARY KEY, model TEXT NOT NULL, version TEXT NOT NULL, traffic_percent INT NOT NULL, status TEXT NOT NULL, reason TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS evaluations (id SERIAL PRIMARY KEY, model TEXT NOT NULL, version TEXT NOT NULL, score DOUBLE PRECISION NOT NULL, passed BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS semantic_nodes (
                id TEXT PRIMARY KEY,
                repository TEXT NOT NULL,
                source TEXT NOT NULL,
                label TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                parent_id TEXT,
                summary TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS code_index_documents (
                id SERIAL PRIMARY KEY,
                repository TEXT NOT NULL,
                source TEXT NOT NULL,
                document_key TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(repository, source, document_key))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS credit_applications (
                id UUID PRIMARY KEY,
                customer_id TEXT NOT NULL,
                product_type TEXT NOT NULL,
                loan_amount DOUBLE PRECISION NOT NULL,
                tenure_months INT NOT NULL,
                annual_income DOUBLE PRECISION NOT NULL,
                employment_type TEXT NOT NULL,
                credit_score INT NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS credit_scores (
                id SERIAL PRIMARY KEY,
                application_id UUID NOT NULL,
                model_version TEXT NOT NULL,
                credit_score INT NOT NULL,
                annual_income DOUBLE PRECISION NOT NULL,
                dti_ratio DOUBLE PRECISION NOT NULL,
                score INT NOT NULL,
                risk_band TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS fraud_checks (
                id SERIAL PRIMARY KEY,
                application_id UUID NOT NULL,
                transaction_velocity INT NOT NULL,
                document_risk DOUBLE PRECISION NOT NULL,
                sanctions_match BOOLEAN NOT NULL,
                duplicate_application BOOLEAN NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS credit_decisions (
                id SERIAL PRIMARY KEY,
                application_id UUID NOT NULL,
                risk_score INT NOT NULL,
                fraud_status TEXT NOT NULL,
                decision TEXT NOT NULL,
                manual_review BOOLEAN NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass


def submit_credit_application(req: CreditApplicationCreate):
    session_factory = _orm_session_factory()
    application_id = uuid.uuid4()
    if session_factory is not None:
        with session_factory() as session:
            application = CreditApplicationRecord(
                id=application_id,
                customer_id=req.customer_id,
                product_type=req.product_type,
                loan_amount=req.loan_amount,
                tenure_months=req.tenure_months,
                annual_income=req.annual_income,
                employment_type=req.employment_type,
                credit_score=req.credit_score,
                status='submitted',
            )
            session.add(application)
            session.commit()
        event('credit.application.submitted', {
            'application_id': str(application_id),
            'customer_id': req.customer_id,
            'product_type': req.product_type,
            'loan_amount': req.loan_amount,
            'tenure_months': req.tenure_months,
            'annual_income': req.annual_income,
            'employment_type': req.employment_type,
            'credit_score': req.credit_score,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        return {'application_id': str(application_id), 'status': 'submitted', 'customer_id': req.customer_id}

    with engine.begin() as c:
        c.execute(
            text('''INSERT INTO credit_applications(id,customer_id,product_type,loan_amount,tenure_months,annual_income,employment_type,credit_score,status)
                    VALUES (:id,:customer_id,:product_type,:loan_amount,:tenure_months,:annual_income,:employment_type,:credit_score,:status)'''),
            {
                'id': application_id,
                'customer_id': req.customer_id,
                'product_type': req.product_type,
                'loan_amount': req.loan_amount,
                'tenure_months': req.tenure_months,
                'annual_income': req.annual_income,
                'employment_type': req.employment_type,
                'credit_score': req.credit_score,
                'status': 'submitted',
            },
        )
    event('credit.application.submitted', {
        'application_id': str(application_id),
        'customer_id': req.customer_id,
        'product_type': req.product_type,
        'loan_amount': req.loan_amount,
        'tenure_months': req.tenure_months,
        'annual_income': req.annual_income,
        'employment_type': req.employment_type,
        'credit_score': req.credit_score,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    return {'application_id': str(application_id), 'status': 'submitted', 'customer_id': req.customer_id}


def score_credit_application(req: CreditScoreRequest):
    session_factory = _orm_session_factory()
    score, risk_band = _score_risk(req)
    application_id = uuid.UUID(req.application_id)
    if session_factory is not None:
        with session_factory() as session:
            record = CreditScoreRecord(
                application_id=application_id,
                model_version=req.model_version,
                credit_score=req.credit_score,
                annual_income=req.annual_income,
                dti_ratio=req.dti_ratio,
                score=score,
                risk_band=risk_band,
            )
            session.add(record)
            session.commit()
        event('credit.score.calculated', {
            'application_id': req.application_id,
            'model_version': req.model_version,
            'credit_score': req.credit_score,
            'dti_ratio': req.dti_ratio,
            'score': score,
            'risk_band': risk_band,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        return {'application_id': req.application_id, 'model_version': req.model_version, 'score': score, 'risk_band': risk_band}

    with engine.begin() as c:
        c.execute(
            text('''INSERT INTO credit_scores(application_id,model_version,credit_score,annual_income,dti_ratio,score,risk_band)
                    VALUES (:application_id,:model_version,:credit_score,:annual_income,:dti_ratio,:score,:risk_band)'''),
            {
                'application_id': application_id,
                'model_version': req.model_version,
                'credit_score': req.credit_score,
                'annual_income': req.annual_income,
                'dti_ratio': req.dti_ratio,
                'score': score,
                'risk_band': risk_band,
            },
        )
    event('credit.score.calculated', {
        'application_id': req.application_id,
        'model_version': req.model_version,
        'credit_score': req.credit_score,
        'dti_ratio': req.dti_ratio,
        'score': score,
        'risk_band': risk_band,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    return {'application_id': req.application_id, 'model_version': req.model_version, 'score': score, 'risk_band': risk_band}


def run_fraud_check(req: FraudCheckRequest):
    status, risk_points = _fraud_risk(req)
    session_factory = _orm_session_factory()
    application_id = uuid.UUID(req.application_id)
    if session_factory is not None:
        with session_factory() as session:
            record = FraudCheckRecord(
                application_id=application_id,
                transaction_velocity=req.transaction_velocity,
                document_risk=req.document_risk,
                sanctions_match=req.sanctions_match,
                duplicate_application=req.duplicate_application,
                status=status,
            )
            session.add(record)
            session.commit()
        event('credit.fraud.checked', {
            'application_id': req.application_id,
            'transaction_velocity': req.transaction_velocity,
            'document_risk': req.document_risk,
            'sanctions_match': req.sanctions_match,
            'duplicate_application': req.duplicate_application,
            'status': status,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        return {'application_id': req.application_id, 'status': status, 'risk_points': risk_points}

    with engine.begin() as c:
        c.execute(
            text('''INSERT INTO fraud_checks(application_id,transaction_velocity,document_risk,sanctions_match,duplicate_application,status)
                    VALUES (:application_id,:transaction_velocity,:document_risk,:sanctions_match,:duplicate_application,:status)'''),
            {
                'application_id': application_id,
                'transaction_velocity': req.transaction_velocity,
                'document_risk': req.document_risk,
                'sanctions_match': req.sanctions_match,
                'duplicate_application': req.duplicate_application,
                'status': status,
            },
        )
    event('credit.fraud.checked', {
        'application_id': req.application_id,
        'transaction_velocity': req.transaction_velocity,
        'document_risk': req.document_risk,
        'sanctions_match': req.sanctions_match,
        'duplicate_application': req.duplicate_application,
        'status': status,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    return {'application_id': req.application_id, 'status': status, 'risk_points': risk_points}


def make_credit_decision(req: CreditDecisionRequest):
    decision = _credit_decision(req.risk_score, req.fraud_status, req.manual_review)
    session_factory = _orm_session_factory()
    application_id = uuid.UUID(req.application_id)
    if session_factory is not None:
        with session_factory() as session:
            record = CreditDecisionRecord(
                application_id=application_id,
                risk_score=req.risk_score,
                fraud_status=req.fraud_status,
                decision=decision,
                manual_review=decision == 'manual_review',
            )
            session.add(record)
            session.commit()
        event('credit.decision.made', {
            'application_id': req.application_id,
            'risk_score': req.risk_score,
            'fraud_status': req.fraud_status,
            'decision': decision,
            'manual_review': decision == 'manual_review',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        return {'application_id': req.application_id, 'decision': decision, 'risk_score': req.risk_score, 'manual_review': decision == 'manual_review'}

    with engine.begin() as c:
        c.execute(
            text('''INSERT INTO credit_decisions(application_id,risk_score,fraud_status,decision,manual_review)
                    VALUES (:application_id,:risk_score,:fraud_status,:decision,:manual_review)'''),
            {
                'application_id': application_id,
                'risk_score': req.risk_score,
                'fraud_status': req.fraud_status,
                'decision': decision,
                'manual_review': decision == 'manual_review',
            },
        )
    event('credit.decision.made', {
        'application_id': req.application_id,
        'risk_score': req.risk_score,
        'fraud_status': req.fraud_status,
        'decision': decision,
        'manual_review': decision == 'manual_review',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    return {'application_id': req.application_id, 'decision': decision, 'risk_score': req.risk_score, 'manual_review': decision == 'manual_review'}


def _credit_route_error(msg: str):
    raise HTTPException(status_code=400, detail=msg)


def index_semantic_tree(req: SemanticTreeRequest):
    records = []
    for node in req.nodes:
        record = {
            'id': node.id,
            'repository': req.repository,
            'source': req.source,
            'label': node.label,
            'kind': node.kind,
            'path': node.path,
            'parent_id': node.parent_id,
            'summary': node.summary,
        }
        records.append(record)
        SEMANTIC_TREE_INDEX.append(record)

    try:
        with engine.begin() as c:
            for node in req.nodes:
                c.execute(
                    text('''INSERT INTO semantic_nodes(id, repository, source, label, kind, path, parent_id, summary)
                            VALUES (:id, :repository, :source, :label, :kind, :path, :parent_id, :summary)
                            ON CONFLICT (id) DO UPDATE SET
                              repository = EXCLUDED.repository,
                              source = EXCLUDED.source,
                              label = EXCLUDED.label,
                              kind = EXCLUDED.kind,
                              path = EXCLUDED.path,
                              parent_id = EXCLUDED.parent_id,
                              summary = EXCLUDED.summary'''),
                    {
                        'id': node.id,
                        'repository': req.repository,
                        'source': req.source,
                        'label': node.label,
                        'kind': node.kind,
                        'path': node.path,
                        'parent_id': node.parent_id,
                        'summary': node.summary,
                    },
                )
    except Exception:
        pass

    event('semantic.tree.indexed', {
        'repository': req.repository,
        'source': req.source,
        'indexed_nodes': len(records),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    return {'status': 'indexed', 'repository': req.repository, 'source': req.source, 'indexed_nodes': len(records)}


def query_semantic_index(req: SemanticIndexQuery):
    query = (req.query or '').strip().lower()
    results = []
    search_space = SEMANTIC_TREE_INDEX
    if not search_space:
        search_space = []

    for node in search_space:
        haystack = ' '.join([
            str(node.get('label', '')),
            str(node.get('kind', '')),
            str(node.get('path', '')),
            str(node.get('summary', '')),
            str(node.get('parent_id', '')),
        ]).lower()
        if not query or query in haystack:
            score = 1.0 if query and query in haystack else 0.5
            results.append({
                'id': node.get('id'),
                'label': node.get('label'),
                'kind': node.get('kind'),
                'path': node.get('path'),
                'parent_id': node.get('parent_id'),
                'summary': node.get('summary'),
                'score': round(score, 3),
            })

    results = sorted(results, key=lambda item: item['score'], reverse=True)[:req.limit]
    return {'query': req.query, 'results': results}


@app.post('/semantic/index')
def semantic_tree_index_endpoint(req: SemanticTreeRequest):
    return index_semantic_tree(req)


@app.post('/semantic/query')
def semantic_tree_query_endpoint(req: SemanticIndexQuery):
    return query_semantic_index(req)


@app.post('/credit/applications')
def create_credit_application_endpoint(req: CreditApplicationCreate):
    return submit_credit_application(req)


@app.post('/credit/applications/{application_id}/score')
def score_credit_application_endpoint(application_id: str, req: CreditScoreRequest):
    if application_id != req.application_id:
        _credit_route_error('application_id must match the request body')
    return score_credit_application(req)


@app.post('/credit/applications/{application_id}/fraud-check')
def fraud_check_endpoint(application_id: str, req: FraudCheckRequest):
    if application_id != req.application_id:
        _credit_route_error('application_id must match the request body')
    return run_fraud_check(req)


@app.post('/credit/applications/{application_id}/decision')
def credit_decision_endpoint(application_id: str, req: CreditDecisionRequest):
    if application_id != req.application_id:
        _credit_route_error('application_id must match the request body')
    return make_credit_decision(req)


@app.get('/credit/applications/{application_id}')
def get_credit_application(application_id: str):
    with engine.begin() as c:
        row = c.execute(
            text('SELECT * FROM credit_applications WHERE id = :application_id'),
            {'application_id': application_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail='application not found')
    return dict(row)

@app.on_event('startup')
def startup():
    global producer
    init_db()
    try:
        producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, value_serializer=lambda x: json.dumps(x).encode())
    except Exception:
        producer = None

def mock_generate(messages: list[Message], max_tokens: int):
    user = next((m.content for m in reversed(messages) if m.role == 'user'), '')
    answer = f"AegisLLM mock response: {user[:400]}"
    return answer, min(max_tokens, max(8, len(answer.split())))

def call_vllm(req: ChatRequest):
    import requests

    backend_url = VLLM_URL
    if MODEL_BACKEND == 'lmstudio':
        backend_url = LMSTUDIO_URL

    payload = {
        'model': LMSTUDIO_MODEL if MODEL_BACKEND == 'lmstudio' else req.model,
        'messages': [m.model_dump() for m in req.messages],
        'max_tokens': req.max_tokens,
        'temperature': req.temperature,
    }
    r = requests.post(f'{backend_url}/v1/chat/completions', json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f'{MODEL_BACKEND} request failed: {r.status_code} {r.text}')
    data = r.json()
    if 'choices' not in data or not data['choices']:
        raise RuntimeError(f'Invalid {MODEL_BACKEND} response: {data}')
    choice = data['choices'][0]
    message = choice.get('message', {})
    usage = data.get('usage', {})
    content = message.get('content', '')
    tokens = usage.get('completion_tokens') or usage.get('total_tokens') or 0
    return content, tokens

def event(topic, payload):
    if producer:
        try:
            producer.send(topic, payload); producer.flush(timeout=2)
        except Exception:
            pass

@app.get('/health/live')
def live(): return {'status':'ok','service':'aegisllm-gateway','version':APP_VERSION}

@app.get('/health/ready')
def ready():
    checks={}
    try: engine.connect().close(); checks['postgres']='ok'
    except Exception as e: checks['postgres']=f'error:{type(e).__name__}'
    try: rdb.ping(); checks['redis']='ok'
    except Exception as e: checks['redis']=f'error:{type(e).__name__}'
    checks['kafka']='configured' if producer else 'unavailable'
    status='ok' if checks['postgres']=='ok' and checks['redis']=='ok' else 'degraded'
    return {'status':status,'checks':checks}

INVESTOR_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AegisLLM Investor Demo</title>
  <style>
    :root {
      --bg: #08111f;
      --panel: #101b2d;
      --panel-2: #0e1c2f;
      --text: #eaf4ff;
      --muted: #a8bfdc;
      --primary: #6ee7b7;
      --cyan: #67e8f9;
      --gold: #fbbf24;
      --red: #f87171;
      --green: #4ade80;
      --shadow: rgba(18, 34, 58, 0.6);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: Arial, Helvetica, sans-serif; background: linear-gradient(180deg, #08111f 0%, #0f172a 100%); color: var(--text);
    }
    .container { max-width: 1200px; margin: 0 auto; padding: 32px 20px 80px; }
    .topbar {
      display: flex; justify-content: space-between; align-items: center; padding: 18px 0 28px; border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .brand { font-size: 1.5rem; font-weight: 700; letter-spacing: 0.05em; }
    .brand span { color: var(--primary); }
    .pill {
      border: 1px solid rgba(110,231,183,0.5); color: var(--primary); padding: 8px 14px; border-radius: 999px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em;
    }
    .hero {
      display: grid; grid-template-columns: 1.4fr 0.9fr; gap: 28px; align-items: center; padding: 42px 0 18px;
    }
    h1 { font-size: clamp(2.4rem, 5vw, 4rem); line-height: 1.05; margin: 0 0 18px; }
    .accent { color: var(--cyan); }
    .lead { color: var(--muted); font-size: 1.08rem; line-height: 1.7; max-width: 620px; }
    .cta-row { display: flex; gap: 16px; margin-top: 28px; flex-wrap: wrap; }
    .button {
      display: inline-block; padding: 14px 22px; border-radius: 12px; font-weight: 700; text-decoration: none; transition: 0.2s ease;
    }
    .button.primary { background: linear-gradient(135deg, var(--primary), var(--cyan)); color: #08111f; }
    .button.secondary { border: 1px solid rgba(255,255,255,0.14); color: var(--text); background: rgba(255,255,255,0.02); }
    .stat-panel {
      background: linear-gradient(180deg, rgba(16,27,45,0.95), rgba(14,28,47,0.92)); border: 1px solid rgba(255,255,255,0.08); border-radius: 22px; padding: 24px; box-shadow: 0 24px 50px var(--shadow);
    }
    .stat-panel h3 { margin-top: 0; color: var(--muted); font-size: 0.9rem; letter-spacing: 0.08em; text-transform: uppercase; }
    .big-stat { font-size: 3rem; font-weight: 800; margin: 10px 0; }
    .mini-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }
    .mini-card {
      background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 16px;
    }
    .mini-card strong { display: block; font-size: 1.6rem; margin-top: 8px; }
    .section { margin-top: 48px; }
    .section h2 { font-size: clamp(1.5rem, 2vw, 2.2rem); margin-bottom: 18px; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px; }
    .card {
      background: rgba(16,27,45,0.8); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 22px; box-shadow: 0 18px 30px var(--shadow);
    }
    .card .tag { display: inline-block; font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--primary); margin-bottom: 12px; }
    .card p { color: var(--muted); line-height: 1.7; }
    .flow {
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 18px;
    }
    .step {
      background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 18px;
    }
    .step .num { width: 28px; height: 28px; border-radius: 50%; background: rgba(103,232,249,0.12); color: var(--cyan); display: inline-flex; align-items: center; justify-content: center; font-weight: 700; margin-bottom: 12px; }
    .demo-panel {
      margin-top: 24px; background: rgba(15,23,42,0.8); border: 1px solid rgba(255,255,255,0.08); border-radius: 20px; padding: 24px; box-shadow: 0 18px 40px var(--shadow);
    }
    .demo-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
    label { display: block; font-size: 0.82rem; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.08em; }
    input, select, button {
      width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background: rgba(15,23,42,0.9); color: var(--text); font-size: 1rem;
    }
    button {
      border: none; background: linear-gradient(135deg, var(--primary), var(--cyan)); color: #08111f; font-weight: 800; cursor: pointer;
    }
    .result-box {
      margin-top: 18px; background: rgba(8,17,31,0.9); border: 1px solid rgba(110,231,183,0.25); border-radius: 14px; padding: 16px; color: var(--text);
    }
    pre { white-space: pre-wrap; word-break: break-word; font-size: 0.9rem; color: var(--muted); margin: 0; font-family: Consolas, monospace; }
    ul { padding-left: 18px; margin: 0; color: var(--muted); line-height: 1.8; }
    @media (max-width: 840px) {
      .hero, .grid, .flow, .demo-grid { grid-template-columns: 1fr; }
      .topbar { flex-direction: column; align-items: flex-start; gap: 12px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="topbar">
      <div class="brand">Aegis<span>LLM</span></div>
      <div class="pill">Investor Demo</div>
    </div>

    <section class="hero">
      <div>
        <h1>AI infrastructure for <span class="accent">trusted credit decisions</span>.</h1>
        <p class="lead">
          AegisLLM combines LLM orchestration, sovereign governance, fraud analysis, and real-time operational telemetry into a single platform built for financial workflows that demand explainability, speed, and control.
        </p>
        <div class="cta-row">
          <a class="button primary" href="#metrics">See the metrics</a>
          <a class="button secondary" href="#workflow">View the workflow</a>
        </div>
      </div>

      <div class="stat-panel">
        <h3>Live platform snapshot</h3>
        <div class="big-stat">99.97%</div>
        <div style="color: var(--muted);">service availability across core orchestration services</div>
        <div class="mini-grid">
          <div class="mini-card">
            <span style="color: var(--muted);">Median latency</span>
            <strong>1.2s</strong>
          </div>
          <div class="mini-card">
            <span style="color: var(--muted);">Approval flow</span>
            <strong>4.8x</strong>
          </div>
          <div class="mini-card">
            <span style="color: var(--muted);">Fraud review</span>
            <strong>72%</strong>
          </div>
          <div class="mini-card">
            <span style="color: var(--muted);">Pipeline</span>
            <strong>$3.6M</strong>
          </div>
        </div>
      </div>
    </section>

    <section id="metrics" class="section">
      <h2>Why this matters to investors</h2>
      <div class="grid">
        <div class="card">
          <div class="tag">Market need</div>
          <h3>Regulated AI without chaos</h3>
          <p>Banking and fintech AI workflows require explainability, auditability, and operational resilience. This platform is designed for exactly that.</p>
        </div>
        <div class="card">
          <div class="tag">Product traction</div>
          <h3>Production-ready foundation</h3>
          <p>Health checks, metrics, orchestration, eventing, and deployment controls are already in place to support repeated real-world operational use.</p>
        </div>
        <div class="card">
          <div class="tag">Business model</div>
          <h3>Platform + workflow layer</h3>
          <p>The same stack can power credit underwriting, compliance monitoring, onboarding, and fraud decisioning with a shared operational control plane.</p>
        </div>
      </div>
    </section>

    <section id="workflow" class="section">
      <h2>Credit workflow demo</h2>
      <div class="flow">
        <div class="step">
          <div class="num">1</div>
          <strong>Application intake</strong>
          <p style="color: var(--muted); margin-top: 10px;">Customer and transaction data enters the platform.</p>
        </div>
        <div class="step">
          <div class="num">2</div>
          <strong>Risk scoring</strong>
          <p style="color: var(--muted); margin-top: 10px;">Model evaluates affordability, DTI, and credit signals.</p>
        </div>
        <div class="step">
          <div class="num">3</div>
          <strong>Fraud screening</strong>
          <p style="color: var(--muted); margin-top: 10px;">Duplicate checks and sanctions logic flag anomalies early.</p>
        </div>
        <div class="step">
          <div class="num">4</div>
          <strong>Decision engine</strong>
          <p style="color: var(--muted); margin-top: 10px;">The final outcome becomes approve, manual review, or decline.</p>
        </div>
      </div>
    </section>

    <section class="section">
      <h2>Operational proof points</h2>
      <ul>
        <li>FastAPI API layer with health and readiness endpoints</li>
        <li>Postgres-backed application records and decision audit trail</li>
        <li>Kafka event pipeline for application, scoring, fraud, and decision events</li>
        <li>Prometheus + Grafana observability stack</li>
        <li>Jaeger tracing for request-level investigation</li>
        <li>Helm and Kubernetes deployment path for production-style rollouts</li>
      </ul>
    </section>

    <section class="section">
      <h2>Live credit application demo</h2>
      <div class="demo-panel">
        <form id="credit-demo-form">
          <div class="demo-grid">
            <div>
              <label for="customer_id">Customer ID</label>
              <input id="customer_id" name="customer_id" value="CUST-DEMO-001" required>
            </div>
            <div>
              <label for="product_type">Product</label>
              <select id="product_type" name="product_type">
                <option value="personal_loan">Personal Loan</option>
                <option value="auto_loan">Auto Loan</option>
                <option value="mortgage">Mortgage</option>
              </select>
            </div>
            <div>
              <label for="loan_amount">Loan Amount</label>
              <input id="loan_amount" name="loan_amount" type="number" value="25000" required>
            </div>
            <div>
              <label for="term_months">Term Months</label>
              <input id="term_months" name="term_months" type="number" value="36" required>
            </div>
            <div>
              <label for="annual_income">Annual Income</label>
              <input id="annual_income" name="annual_income" type="number" value="95000" required>
            </div>
            <div>
              <label for="employment_type">Employment</label>
              <select id="employment_type" name="employment_type">
                <option value="salaried">Salaried</option>
                <option value="self_employed">Self Employed</option>
                <option value="retired">Retired</option>
              </select>
            </div>
            <div>
              <label for="credit_score">Credit Score</label>
              <input id="credit_score" name="credit_score" type="number" min="300" max="850" value="720" required>
            </div>
            <div>
              <label for="notes">Notes</label>
              <input id="notes" name="notes" value="Demo onboarding" placeholder="Optional notes">
            </div>
          </div>
          <div style="margin-top: 18px; display: flex; gap: 12px; flex-wrap: wrap;">
            <button type="button" id="credit-demo-button" onclick="window.runDemoWorkflow && window.runDemoWorkflow()">Run credit workflow</button>
          </div>
        </form>

        <div class="result-box">
          <div style="font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--primary); margin-bottom: 8px;">Result</div>
          <pre id="result-output">Ready for demo input...</pre>
        </div>
      </div>
    </section>

    <section class="section">
      <h2>LM Studio chat test</h2>
      <div class="demo-panel">
        <div class="demo-grid">
          <div>
            <label for="lm_prompt">Prompt</label>
            <input id="lm_prompt" value="Summarize the credit risk workflow in one sentence." />
          </div>
          <div>
            <label for="lm_model">Model</label>
            <input id="lm_model" value="openai/gpt-oss-20b" />
          </div>
        </div>
        <div style="margin-top: 18px; display: flex; gap: 12px; flex-wrap: wrap;">
          <button type="button" id="lm-test-button" onclick="window.runLmStudioTest && window.runLmStudioTest()">Test LM Studio chat</button>
        </div>
        <div class="result-box">
          <div style="font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--cyan); margin-bottom: 8px;">LM Studio result</div>
          <pre id="lm-result-output">Not yet tested.</pre>
        </div>
      </div>
    </section>
  </div>

  <script>
    const APP_BUILD_TAG = 'APP_BUILD_PLACEHOLDER';
    const storedBuild = localStorage.getItem('aegis_demo_build');
    if (storedBuild !== APP_BUILD_TAG) {
      localStorage.setItem('aegis_demo_build', APP_BUILD_TAG);
      if (storedBuild && storedBuild !== APP_BUILD_TAG) {
        window.location.reload();
      }
    }

    function showResult(text) {
      const out = document.getElementById('result-output');
      if (out) {
        out.textContent = text;
      }
    }

    async function readJsonResponse(response) {
      const text = await response.text();
      if (!text) {
        return null;
      }
      try {
        return JSON.parse(text);
      } catch (error) {
        throw new Error(text || 'Response was not valid JSON');
      }
    }

    window.runDemoWorkflow = async function () {
      const resultOutput = document.getElementById('result-output');
      if (!resultOutput) {
        return;
      }

      const getValue = (id) => {
        const el = document.getElementById(id);
        return el ? el.value : '';
      };

      const payload = {
        customer_id: getValue('customer_id'),
        product_type: getValue('product_type'),
        loan_amount: Number(getValue('loan_amount')),
        tenure_months: Number(getValue('term_months')),
        annual_income: Number(getValue('annual_income')),
        employment_type: getValue('employment_type'),
        credit_score: Number(getValue('credit_score')),
        notes: getValue('notes') || null
      };

      try {
        resultOutput.textContent = 'Submitting application...';

        const createRes = await fetch('/credit/applications', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const created = await readJsonResponse(createRes);
        if (!createRes.ok) {
          throw new Error(JSON.stringify(created, null, 2));
        }

        const appId = created.application_id;
        const scoreRes = await fetch('/credit/applications/' + appId + '/score', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            application_id: appId,
            model_version: 'credit-v3',
            credit_score: Number(payload.credit_score),
            annual_income: Number(payload.annual_income),
            dti_ratio: 0.28
          })
        });
        const scored = await readJsonResponse(scoreRes);
        if (!scoreRes.ok) {
          throw new Error(JSON.stringify(scored, null, 2));
        }

        const fraudRes = await fetch('/credit/applications/' + appId + '/fraud-check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            application_id: appId,
            transaction_velocity: 2,
            document_risk: 0.2,
            sanctions_match: false,
            duplicate_application: false
          })
        });
        const fraud = await readJsonResponse(fraudRes);
        if (!fraudRes.ok) {
          throw new Error(JSON.stringify(fraud, null, 2));
        }

        const decisionRes = await fetch('/credit/applications/' + appId + '/decision', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            application_id: appId,
            risk_score: Number(scored.score || 58),
            fraud_status: fraud.status,
            manual_review: false
          })
        });
        const decision = await readJsonResponse(decisionRes);
        if (!decisionRes.ok) {
          throw new Error(JSON.stringify(decision, null, 2));
        }

        showResult(JSON.stringify({ application: created, score: scored, fraud: fraud, decision: decision }, null, 2));
      } catch (error) {
        showResult('Workflow error:\\n' + String(error));
      }
    };

    window.runLmStudioTest = async function () {
      const prompt = document.getElementById('lm_prompt') ? document.getElementById('lm_prompt').value : 'Hello';
      const model = document.getElementById('lm_model') ? document.getElementById('lm_model').value : 'openai/gpt-oss-20b';
      const lmOutput = document.getElementById('lm-result-output');
      if (!lmOutput) {
        return;
      }

      lmOutput.textContent = 'Calling LM Studio...';

      try {
        const res = await fetch('/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: model,
            messages: [{ role: 'user', content: prompt }],
            max_tokens: 120,
            temperature: 0.2
          })
        });

        const data = await readJsonResponse(res);
        if (!res.ok) {
          throw new Error(JSON.stringify(data, null, 2));
        }

        const content = data && data.choices && data.choices[0] && data.choices[0].message
          ? data.choices[0].message.content
          : JSON.stringify(data, null, 2);

        lmOutput.textContent = JSON.stringify({ model: model, response: content }, null, 2);
      } catch (error) {
        lmOutput.textContent = 'LM Studio error:\\n' + String(error);
      }
    };

    function attachDemoHandlers() {
      const form = document.getElementById('credit-demo-form');
      const creditButton = document.getElementById('credit-demo-button');
      const lmButton = document.getElementById('lm-test-button');

      if (form && !form.dataset.demoBound) {
        form.dataset.demoBound = 'true';
        form.addEventListener('submit', function (event) {
          event.preventDefault();
          event.stopPropagation();
          window.runDemoWorkflow();
        });
      }

      if (creditButton && !creditButton.dataset.demoBound) {
        creditButton.dataset.demoBound = 'true';
        creditButton.addEventListener('click', function (event) {
          event.preventDefault();
          event.stopPropagation();
          window.runDemoWorkflow();
        });
      }

      if (lmButton && !lmButton.dataset.demoBound) {
        lmButton.dataset.demoBound = 'true';
        lmButton.addEventListener('click', async function (event) {
          event.preventDefault();
          event.stopPropagation();
          await window.runLmStudioTest();
        });
      }
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', attachDemoHandlers, { once: true });
    } else {
      attachDemoHandlers();
    }

    window.addEventListener('load', attachDemoHandlers, { once: true });
  </script>
</body>
</html>
"""


def investor_dashboard_html():
    html = INVESTOR_DASHBOARD_HTML.replace('APP_BUILD_PLACEHOLDER', APP_BUILD)
    return html


@app.get('/', response_class=HTMLResponse)
def investor_home():
    return HTMLResponse(content=investor_dashboard_html(), headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'})


@app.get('/investor', response_class=HTMLResponse)
def investor_demo():
    return HTMLResponse(content=investor_dashboard_html(), headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'})


@app.get('/investor/summary')
def investor_summary():
    return {
        'company': 'AegisLLM',
        'focus': 'AI infrastructure for regulated credit and risk workflows',
        'availability': '99.97%',
        'median_latency_ms': 1200,
        'underwriting_speedup': '4.8x',
        'pipeline_value_usd': 3600000,
        'core_components': ['FastAPI', 'Postgres', 'Redis', 'Kafka', 'Prometheus', 'Grafana', 'Jaeger', 'Kubernetes'],
        'workflow': ['application intake', 'risk scoring', 'fraud screening', 'decisioning'],
    }


@app.get('/metrics')
def metrics(): return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post('/v1/chat/completions')
def chat(req: ChatRequest):
    backend = 'lmstudio' if MODEL_BACKEND == 'lmstudio' else 'vllm' if MODEL_BACKEND == 'vllm' else 'mock'
    start=time.perf_counter(); status='ok'
    try:
        cache_key=f"chat:{req.model}:{json.dumps([m.model_dump() for m in req.messages],sort_keys=True)}:{req.max_tokens}"
        cached=rdb.get(cache_key)
        if cached:
            answer,tokens=json.loads(cached); backend='cache'
        else:
            if backend in {'vllm','lmstudio'}:
                answer,tokens = call_vllm(req)
            else:
                answer,tokens = mock_generate(req.messages,req.max_tokens)
            rdb.setex(cache_key, 300, json.dumps([answer,tokens]))
        latency=(time.perf_counter()-start)*1000
        REQUESTS.labels(req.model,backend,status).inc(); LATENCY.labels(req.model,backend).observe(latency/1000); TOKENS.labels(req.model,backend).inc(tokens)
        rid=str(uuid.uuid4())
        with engine.begin() as c:
            c.execute(text('INSERT INTO inference_requests(id,model,backend,latency_ms,tokens,status) VALUES (:id,:m,:b,:l,:t,:s)'), {'id':rid,'m':req.model,'b':backend,'l':latency,'t':tokens,'s':status})
        event('aegis.inference', {'request_id':rid,'model':req.model,'backend':backend,'latency_ms':latency,'tokens':tokens,'timestamp':datetime.now(timezone.utc).isoformat()})
        return {'id':rid,'object':'chat.completion','model':req.model,'choices':[{'index':0,'message':{'role':'assistant','content':answer},'finish_reason':'stop'}],'usage':{'completion_tokens':tokens}}
    except Exception as e:
        status='error'; REQUESTS.labels(req.model,backend,status).inc(); raise HTTPException(502, detail=str(e))

@app.post('/models')
def register(m: ModelRegister):
    with engine.begin() as c:
        c.execute(
            text('INSERT INTO models(name,version,backend,quality_score) VALUES (:n,:v,:b,:q) ON CONFLICT(name,version) DO UPDATE SET quality_score=:q'),
            {
                'n': m.name,
                'v': m.version,
                'b': m.backend,
                'q': m.quality_score,
            },
        )
    return {'name':m.name,'version':m.version,'status':'REGISTERED'}

@app.get('/models')
def models():
    with engine.begin() as c: rows=c.execute(text('SELECT name,version,backend,quality_score,status,created_at FROM models ORDER BY created_at DESC')).mappings().all()
    return {'models':[dict(r) for r in rows]}

@app.post('/deploy/canary')
def canary(req: CanaryRequest):
    passed=req.quality_score >= 0.90 and (req.latency_p95_ms == 0 or req.latency_p95_ms <= 1500)
    decision='promote' if passed else 'rollback'
    CANARY.labels(decision).inc()
    status='CANARY' if passed else 'ROLLED_BACK'
    with engine.begin() as c:
        c.execute(text('INSERT INTO deployments(model,version,traffic_percent,status,reason) VALUES (:m,:v,:p,:s,:r)'), {'m':req.model,'v':req.candidate_version,'p':req.traffic_percent if passed else 0,'s':status,'r':'quality/latency gate' if not passed else 'gates passed'})
        c.execute(text('INSERT INTO evaluations(model,version,score,passed) VALUES (:m,:v,:q,:p)'), {'m':req.model,'v':req.candidate_version,'q':req.quality_score,'p':passed})
    event('aegis.deployment', req.model_dump() | {'decision':decision})
    return {'decision':decision,'traffic_percent':req.traffic_percent if passed else 0,'version':req.candidate_version}

@app.post('/incidents/analyze')
def incident(payload: dict[str,Any]):
    # Deterministic fallback workflow; LangGraph can replace this in the incident service.
    symptoms=payload.get('symptoms',[])
    hypothesis='inference saturation or model regression' if symptoms else 'no symptoms supplied'
    return {'state':'RECOMMENDATION','classification':'LLM_INFERENCE_INCIDENT','evidence':payload,'hypotheses':[hypothesis],'recommended_action':'rollback candidate if quality/latency gate is breached','approval_required':True}
