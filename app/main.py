import asyncio
import hmac
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import vertex, whatsapp
from app.config import Settings
from app.knowledge import KnowledgeBase, fallback_for
from app.middleware import RequestBodyLimit
from app.storage import make_store


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=2, max_length=2000)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Message must contain at least two characters")
        return value


class Citation(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Citation]
    category: str
    grounded: bool


def create_app(settings: Settings | None = None, store=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.prepare()
    knowledge = KnowledgeBase(settings.knowledge_path)
    store = store or make_store(settings)
    app = FastAPI(title="Nexo UNAL", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.settings = settings
    windows = defaultdict(deque)

    @app.middleware("http")
    async def hardening(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    async def answer(message: str):
        start = time.monotonic()
        sources = knowledge.search(message)
        text = knowledge.extract(sources) if sources else fallback_for(message)
        if sources and settings.enable_vertex_ai:
            try:
                text = await vertex.generate(settings, message, sources)
            except Exception:
                # Keep the verified extractive answer; never log user content or provider payloads.
                pass
        result = ChatResponse(
            answer=text,
            sources=[item.public() for item in sources],
            category=sources[0].category if sources else "sin_fuente",
            grounded=bool(sources),
        )
        return result, (time.monotonic() - start) * 1000

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": "nexo-unal"}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request):
        now = time.monotonic()
        # In-memory only. Cloud deployments need an edge quota for a global limit.
        address = request.client.host if request.client else "unknown"
        window = windows[address]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= 30:
            raise HTTPException(429, "Intenta de nuevo en un minuto")
        window.append(now)
        if len(windows) > 10000:
            stale = [key for key, values in windows.items() if not values or now - values[-1] > 60]
            for key in stale:
                windows.pop(key, None)
        result, latency = await answer(payload.message)
        await asyncio.to_thread(store.record, result.category, "web", result.grounded, latency)
        return result

    @app.get("/api/metrics")
    async def metrics(x_admin_token: Annotated[str | None, Header()] = None):
        if not settings.admin_token:
            raise HTTPException(503, "Configura ADMIN_TOKEN para habilitar las métricas")
        if not x_admin_token or not hmac.compare_digest(
            settings.admin_token.encode(), x_admin_token.encode()
        ):
            raise HTTPException(401, "No autorizado")
        return await asyncio.to_thread(store.metrics)

    @app.get("/webhooks/whatsapp", response_class=PlainTextResponse)
    def verify(
        mode: Annotated[str, Query(alias="hub.mode")] = "",
        token: Annotated[str, Query(alias="hub.verify_token")] = "",
        challenge: Annotated[str, Query(alias="hub.challenge", max_length=200)] = "",
    ):
        if not settings.whatsapp_verify_token:
            raise HTTPException(503, "Webhook no configurado")
        if mode != "subscribe" or not hmac.compare_digest(
            token.encode(), settings.whatsapp_verify_token.encode()
        ):
            raise HTTPException(403, "Verificación inválida")
        return challenge

    @app.post("/webhooks/whatsapp")
    async def webhook(request: Request, x_hub_signature_256: Annotated[str, Header()] = ""):
        if not settings.whatsapp_app_secret:
            raise HTTPException(503, "Webhook no configurado")
        body = await request.body()
        if not whatsapp.valid_signature(body, x_hub_signature_256, settings.whatsapp_app_secret):
            raise HTTPException(401, "Firma inválida")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError
            messages = list(whatsapp.text_messages(payload))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(400, "Evento inválido") from None
        if messages and not (settings.whatsapp_access_token and settings.whatsapp_phone_number_id):
            raise HTTPException(503, "Entrega de WhatsApp no configurada")
        for message in messages:
            message_id = message["id"]
            claim = await asyncio.to_thread(store.claim, message_id)
            if claim == "sent":
                continue
            if claim == "pending":
                # Acknowledge only completed delivery; Meta must retry an active/stale lease.
                raise HTTPException(503, "Entrega en curso; reintenta el evento")
            try:
                text = message["text"]["body"].strip()
                result = None
                if not 2 <= len(text) <= 2000:
                    response = "Envía una pregunta de 2 a 2000 caracteres sobre la UNAL."
                else:
                    result, latency = await answer(text)
                    response = result.answer
                    if result.sources:
                        response += "\n\nFuentes:\n" + "\n".join(
                            source.url for source in result.sources
                        )
                await whatsapp.send_text(settings, message["from"], response)
                metric = (
                    {
                        "category": result.category,
                        "grounded": result.grounded,
                        "latency_ms": latency,
                    }
                    if result is not None
                    else None
                )
                await asyncio.to_thread(store.complete, message_id, metric)
            except Exception:
                await asyncio.to_thread(store.release, message_id)
                raise HTTPException(503, "Entrega temporalmente no disponible") from None
        return {"status": "ok"}

    web = Path(settings.web_path)
    if web.is_dir():

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(web / "index.html")

        app.mount("/static", StaticFiles(directory=web), name="static")
    app.add_middleware(RequestBodyLimit)
    return app


app = create_app()
