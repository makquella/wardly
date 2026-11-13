"""ASGI boundary: loopback authority/origin, capabilities and bounded bodies."""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Mapping

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.diagnostics import record_error
from app.local_api_auth import LocalApiAuth
from app.storage_json import load_json

BODY_LIMIT = 1024 * 1024
GSI_BODY_LIMIT = 4 * 1024 * 1024
BACKUP_BODY_LIMIT = 512 * 1024 * 1024
PUBLIC_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json"}


def local_origins(port: int) -> list[str]:
    suffix = "" if port == 80 else f":{port}"
    return [f"http://{host}{suffix}" for host in ("127.0.0.1", "localhost", "[::1]")]


class LocalApiSecurity:
    def __init__(
        self,
        app: ASGIApp,
        *,
        auth: LocalApiAuth,
        port: int,
        limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.auth = auth
        self.origins = set(local_origins(port))
        self.hosts = {origin.removeprefix("http://").encode("ascii") for origin in self.origins}
        self.limits = {
            "/gsi": GSI_BODY_LIMIT,
            "/player/backup": BACKUP_BODY_LIMIT,
            **(limits or {}),
        }

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, status: int, code: str
    ) -> None:
        record_error("local-api", code, with_trace=False)
        await JSONResponse({"status": "error", "code": code}, status_code=status)(
            scope, receive, send
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, list[bytes]] = {}
        for name, value in scope["headers"]:
            headers.setdefault(name.lower(), []).append(value)
        hosts = headers.get(b"host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.hosts:
            await self._reject(scope, receive, send, 400, "invalid_host")
            return
        peer = scope.get("client")
        try:
            loopback = peer is not None and ipaddress.ip_address(peer[0]).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            await self._reject(scope, receive, send, 403, "nonlocal_client")
            return
        origins = headers.get(b"origin", [])
        if origins and (len(origins) != 1 or origins[0].decode("latin-1") not in self.origins):
            await self._reject(scope, receive, send, 403, "untrusted_origin")
            return
        path, method = scope["path"], scope["method"]
        limit = self.limits.get(path, BODY_LIMIT) if method == "POST" else BODY_LIMIT
        lengths = headers.get(b"content-length", [])
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 12):
            await self._reject(scope, receive, send, 400, "invalid_length")
            return
        if lengths and int(lengths[0]) > limit:
            await self._reject(scope, receive, send, 413, "body_too_large")
            return
        authorization = headers.get(b"authorization", [])
        scheme, _, credential = (
            authorization[0].partition(b" ") if len(authorization) == 1 else (b"", b"", b"")
        )
        control = scheme.lower() == b"bearer" and hmac.compare_digest(
            credential, self.auth.control.encode("ascii")
        )
        public = (method in {"GET", "HEAD"} and path in PUBLIC_PATHS) or method == "OPTIONS"
        gsi = path == "/gsi" and method == "POST"
        if not public and not gsi and not control:
            await self._reject(scope, receive, send, 401, "unauthorized")
            return
        if headers.get(b"content-encoding", [b"identity"]) != [b"identity"]:
            await self._reject(scope, receive, send, 415, "unsupported_encoding")
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await self._reject(scope, receive, send, 413, "body_too_large")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if body and method in {"POST", "PUT", "PATCH", "DELETE"}:
            media = headers.get(b"content-type", [])
            content_type = media[0].split(b";", 1)[0].strip().lower() if len(media) == 1 else b""
            if content_type != b"application/json":
                await self._reject(scope, receive, send, 415, "json_required")
                return
        if gsi:
            try:
                payload = load_json(body.decode("utf-8"))
            except (ValueError, TypeError, OverflowError, RecursionError):
                await self._reject(scope, receive, send, 400, "invalid_json")
                return
            if not isinstance(payload, dict):
                await self._reject(scope, receive, send, 400, "invalid_gsi")
                return
            auth = payload.pop("auth", None)
            token = auth.get("token") if isinstance(auth, dict) else None
            allowed = isinstance(token, str) and hmac.compare_digest(
                token.encode("utf-8"), self.auth.gsi.encode("ascii")
            )
            if not control and not allowed:
                await self._reject(scope, receive, send, 401, "unauthorized")
                return
            scope["wardly.gsi_payload"] = payload
        delivered = False

        async def replay() -> Message:
            nonlocal delivered, body
            if delivered:
                return await receive()
            delivered = True
            content = bytes(body)
            body = bytearray()
            return {"type": "http.request", "body": content, "more_body": False}

        await self.app(scope, replay, send)
