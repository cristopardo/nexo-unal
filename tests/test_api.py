import asyncio
import hashlib
import hmac
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.knowledge import KnowledgeBase
from app.main import create_app
from app.middleware import RequestBodyLimit
from app.storage import SQLiteStore
from app.whatsapp import valid_signature


@pytest.fixture
def setup(tmp_path):
    settings = Settings(
        admin_token="test-admin-token",
        whatsapp_verify_token="test-verify",
        whatsapp_app_secret="test-app-secret",
        whatsapp_access_token="test-access-token",
        whatsapp_phone_number_id="1234",
        sqlite_path=str(tmp_path / "test.sqlite3"),
        web_path=str(tmp_path / "absent"),
    )
    store = SQLiteStore(settings.sqlite_path)
    return settings, store, TestClient(create_app(settings, store))


def event(message_id="wamid.test.private", body="¿Cómo pido apoyo de alimentación?"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "573001234567",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


def signed(payload, secret="test-app-secret"):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": signature, "Content-Type": "application/json"}


def test_chat_answers_with_official_citations_and_retains_no_content(setup):
    _, store, client = setup
    question = "¿Cómo pido apoyo de alimentación? mi celular es 573001234567"
    result = client.post("/api/chat", json={"message": question})
    assert result.status_code == 200
    data = result.json()
    assert data["grounded"] is True
    assert data["category"] == "bienestar"
    assert any("bienestar.bogota.unal.edu.co" in item["url"] for item in data["sources"])
    stored = " ".join(store.db.iterdump())
    assert question not in stored
    assert "573001234567" not in stored
    assert "test-admin-token" not in stored
    metrics = client.get("/api/metrics", headers={"X-Admin-Token": "test-admin-token"}).json()
    assert metrics["total_messages"] == 1
    assert metrics["grounded_messages"] == 1
    assert metrics["by_channel"] == {"web": 1}
    assert metrics["stores_conversation_content"] is False


def test_unknown_topic_does_not_invent_sources(setup):
    _, _, client = setup
    data = client.post("/api/chat", json={"message": "¿Cuál es la capital de Francia?"}).json()
    assert data["grounded"] is False
    assert data["sources"] == []
    assert "fuente verificada" in data["answer"]


def test_metrics_requires_configured_matching_token(setup):
    settings, store, client = setup
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers={"X-Admin-Token": "incorrect"}).status_code == 401
    disabled = TestClient(create_app(replace(settings, admin_token=""), store))
    assert disabled.get("/api/metrics").status_code == 503


def test_whatsapp_challenge_and_signature(setup):
    _, _, client = setup
    params = {"hub.mode": "subscribe", "hub.verify_token": "test-verify", "hub.challenge": "123"}
    assert client.get("/webhooks/whatsapp", params=params).text == "123"
    params["hub.verify_token"] = "wrong"
    assert client.get("/webhooks/whatsapp", params=params).status_code == 403
    assert client.post("/webhooks/whatsapp", json=event()).status_code == 401
    body, headers = signed(event(), "wrong-secret")
    assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 401
    body, headers = signed({"object": "whatsapp_business_account", "entry": []})
    assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200


def test_signed_delivery_is_idempotent_and_message_ids_are_hashed(setup, monkeypatch):
    _, store, client = setup
    sent = []

    async def capture(settings, recipient, text):
        sent.append((recipient, text))

    monkeypatch.setattr("app.whatsapp.send_text", capture)
    body, headers = signed(event())
    assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200
    assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200
    assert len(sent) == 1
    assert "https://bienestar.bogota.unal.edu.co/gestion.php" in sent[0][1]
    stored = " ".join(store.db.iterdump())
    assert "wamid.test.private" not in stored
    assert "573001234567" not in stored
    assert store.metrics()["by_channel"] == {"whatsapp": 1}


def test_failed_delivery_releases_claim_for_meta_retry(setup, monkeypatch):
    _, store, client = setup

    async def fail(settings, recipient, text):
        raise RuntimeError("provider temporarily offline")

    monkeypatch.setattr("app.whatsapp.send_text", fail)
    body, headers = signed(event())
    result = client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert result.status_code == 503
    assert "provider temporarily offline" not in result.text
    assert store.claim("wamid.test.private") == "claimed"
    assert store.metrics()["total_messages"] == 0


def test_input_limits_and_hardening(setup):
    _, _, client = setup
    assert client.post("/api/chat", json={"message": " "}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 2001}).status_code == 422
    assert client.post("/api/chat", content="x" * 256001).status_code == 413
    result = client.get("/healthz")
    assert result.json()["status"] == "ok"
    assert "frame-ancestors 'none'" in result.headers["Content-Security-Policy"]


def test_catalog_rejects_unofficial_sources(tmp_path):
    path = tmp_path / "knowledge.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "bad",
                    "title": "Bad",
                    "url": "https://evil.test",
                    "category": "test",
                    "keywords": [],
                    "content": "",
                    "reviewed_at": "2026-11-13",
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="official UNAL"):
        KnowledgeBase(str(path))


def test_vertex_unavailable_keeps_extract_and_citations(setup, monkeypatch):
    settings, store, _ = setup

    async def unavailable(*args):
        raise RuntimeError("private provider response")

    monkeypatch.setattr("app.vertex.generate", unavailable)
    client = TestClient(
        create_app(
            replace(settings, enable_vertex_ai=True, google_cloud_project="test-project"), store
        )
    )
    result = client.post("/api/chat", json={"message": "plan de estudios computación"})
    assert result.status_code == 200
    assert result.json()["grounded"] is True
    assert result.json()["sources"]
    assert "private provider response" not in result.text


@pytest.mark.parametrize(
    ("question", "source_id"),
    [
        ("¿Cómo renuevo un libro?", "bibliotecas"),
        ("¿Cómo cancelo una asignatura?", "sia-inscripcion"),
        ("Quiero atención psicológica", "salud-estudiantil"),
    ],
)
def test_retrieval_handles_common_spanish_inflections(question, source_id):
    matches = KnowledgeBase("knowledge/sources.json").search(question)
    assert matches and matches[0].id == source_id


def test_broad_single_overlap_does_not_claim_an_answer():
    assert KnowledgeBase("knowledge/sources.json").search("plan de vacaciones") == []


def test_pending_webhook_is_not_acknowledged_before_delivery(setup, monkeypatch):
    _, store, client = setup
    assert store.claim("wamid.pending") == "claimed"
    body, headers = signed(event(message_id="wamid.pending"))
    result = client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert result.status_code == 503
    assert store.metrics()["total_messages"] == 0
    store.complete("wamid.pending")
    assert store.claim("wamid.pending") == "sent"
    assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200


@pytest.mark.parametrize(
    "campus",
    ["Medellín", "Manizales", "Palmira", "Amazonia", "Orinoquia", "Caribe", "Tumaco", "La Paz"],
)
def test_other_campuses_get_explicit_scope_fallback(setup, campus):
    _, _, client = setup
    result = client.post("/api/chat", json={"message": f"apoyo de alimentación en {campus}"})
    assert result.status_code == 200
    data = result.json()
    assert data["grounded"] is False
    assert data["sources"] == []
    assert "catálogo verificado cubre la Sede Bogotá" in data["answer"]


def test_bogota_question_remains_supported(setup):
    _, _, client = setup
    result = client.post("/api/chat", json={"message": "apoyo de alimentación en Bogotá"})
    assert result.json()["grounded"] is True


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_stream_limit_stops_reading_as_soon_as_cap_is_exceeded(headers):
    received = []
    responses = []
    called = []
    chunks = [b"x" * 128000, b"x" * 128001, b"never read"]

    async def receive():
        received.append(True)
        return {"type": "http.request", "body": chunks[len(received) - 1], "more_body": True}

    async def send(message):
        responses.append(message)

    async def downstream(scope, receive, send):
        called.append(True)

    middleware = RequestBodyLimit(downstream)
    asyncio.run(middleware({"type": "http", "method": "POST", "headers": headers}, receive, send))
    assert len(received) == 2
    assert not called
    assert responses[0]["status"] == 413


def test_non_ascii_tokens_and_signature_fail_cleanly(setup):
    _, _, client = setup
    result = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "inválido", "hub.challenge": "123"},
    )
    assert result.status_code == 403
    assert valid_signature(b"{}", "sha256=inválida", "secret") is False


def test_static_dashboard_and_assets_are_served(setup):
    settings, store, _ = setup
    client = TestClient(create_app(replace(settings, web_path="web"), store))
    assert client.get("/").status_code == 200
    assert "Nexo" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


@pytest.mark.parametrize(
    ("question", "source_id"),
    [
        ("¿Cómo solicito un certificado de estudios?", "certificados-ciencias"),
        ("¿Qué apoyos de bienestar hay?", "apoyos-bienestar"),
        ("¿Dónde consulto el plan de Ciencias de la Computación?", "computacion-plan"),
    ],
)
def test_dashboard_suggestions_have_relevant_sources(setup, question, source_id):
    _, _, client = setup
    data = client.post("/api/chat", json={"message": question}).json()
    expected = KnowledgeBase("knowledge/sources.json").sources
    expected_url = next(source.url for source in expected if source.id == source_id)
    assert data["grounded"] is True
    assert data["sources"][0]["url"] == expected_url


def test_cloud_run_compatible_health_route_and_legacy_alias(setup):
    _, _, client = setup
    for path in ("/health", "/healthz"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "nexo-unal"}
