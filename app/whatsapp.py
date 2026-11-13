import asyncio
import hashlib
import hmac

import httpx


def valid_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def text_messages(payload: dict):
    if payload.get("object") != "whatsapp_business_account":
        return
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if (
                    message.get("type") == "text"
                    and isinstance(message.get("text"), dict)
                    and isinstance(message["text"].get("body"), str)
                    and isinstance(message.get("id"), str)
                    and isinstance(message.get("from"), str)
                ):
                    yield message


async def send_text(settings, recipient: str, text: str):
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(3):
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": recipient,
                        "type": "text",
                        "text": {"body": text[:4096], "preview_url": False},
                    },
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                elif response.is_error:
                    # Configuration/client errors will not resolve by retrying immediately.
                    raise ValueError("WhatsApp rejected delivery")
                else:
                    return
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 2:
                    raise RuntimeError("WhatsApp delivery unavailable") from None
                await asyncio.sleep(0.5 * (2**attempt))
