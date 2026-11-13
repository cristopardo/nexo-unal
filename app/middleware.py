"""Bound streamed request bodies before FastAPI buffers or parses them."""

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int = 256_000):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        try:
            length = int(dict(scope["headers"]).get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            await PlainTextResponse("Invalid content length", status_code=400)(scope, receive, send)
            return
        if length > self.max_bytes:
            await PlainTextResponse("Payload too large", status_code=413)(scope, receive, send)
            return
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                # Stop reading immediately, including when Content-Length is absent or false.
                await PlainTextResponse("Payload too large", status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)
