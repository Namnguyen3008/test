"""Consistent browser security headers for API responses."""

from collections.abc import Mapping, Sequence

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_SECURITY_HEADERS: Mapping[str, str] = {
    "Content-Security-Policy": ("default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class SecurityHeadersMiddleware:
    """Attach defense-in-depth headers without overwriting stricter handlers."""

    def __init__(
        self,
        app: ASGIApp,
        headers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    ) -> None:
        self.app = app
        self.headers = dict(headers or DEFAULT_SECURITY_HEADERS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                path = scope.get("path", "")
                for name, value in self.headers.items():
                    # Skip CSP on docs/redoc/root routes so Swagger UI and web client load cleanly
                    if name == "Content-Security-Policy" and (path in ("/", "/docs", "/redoc", "/openapi.json") or path.startswith("/chat-ui")):
                        continue
                    if name not in response_headers:
                        response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
