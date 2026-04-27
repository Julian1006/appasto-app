import secrets
from collections import defaultdict
from hmac import compare_digest
from time import time
from urllib.parse import urljoin, urlparse

from flask import abort, request, session, url_for
from markupsafe import Markup, escape


CSRF_SESSION_KEY = "_csrf_token"
CSRF_FIELD_NAME = "csrf_token"
CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def rotate_csrf_token():
    session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_SESSION_KEY]


def csrf_field():
    return Markup(
        '<input type="hidden" name="%s" value="%s">'
        % (CSRF_FIELD_NAME, escape(csrf_token()))
    )


def validate_csrf():
    expected = session.get(CSRF_SESSION_KEY)
    supplied = (
        request.form.get(CSRF_FIELD_NAME)
        or request.headers.get("X-CSRFToken")
        or request.headers.get("X-CSRF-Token")
    )
    if not expected or not supplied or not compare_digest(str(expected), str(supplied)):
        abort(400, description="Solicitud rechazada por seguridad. Recarga la pagina e intentalo de nuevo.")


def register_security(app):
    @app.before_request
    def _csrf_before_request():
        if request.method in CSRF_METHODS:
            validate_csrf()


def is_safe_url(target):
    if not target:
        return False
    host_url = request.host_url
    ref = urlparse(host_url)
    test = urlparse(urljoin(host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def safe_redirect_target(target, default_endpoint="main.index", **default_values):
    default = url_for(default_endpoint, **default_values)
    return target if is_safe_url(target) else default


def safe_next(default_endpoint="auth.account", **default_values):
    target = request.form.get("next") or request.args.get("next")
    return safe_redirect_target(target, default_endpoint, **default_values)


def apply_security_headers(response, is_production=False):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=(self)"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = _content_security_policy(is_production)

    if is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")

    if request.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"

    return response


def _content_security_policy(is_production):
    directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://checkout.wompi.co",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: https://wompi.com https://*.wompi.com https://*.wompi.co",
        "connect-src 'self' https://*.wompi.co https://*.wompi.com",
        "frame-src 'self' https://checkout.wompi.co https://*.wompi.co https://maps.google.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' https://checkout.wompi.co https://*.wompi.co",
        "frame-ancestors 'self'",
    ]
    if is_production:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


class MemoryRateLimiter:
    def __init__(self, max_attempts=5, window_seconds=900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures = defaultdict(list)

    def _pruned(self, key):
        now = time()
        self._failures[key] = [
            timestamp for timestamp in self._failures[key]
            if now - timestamp < self.window_seconds
        ]
        return self._failures[key]

    def is_locked(self, key):
        return len(self._pruned(key)) >= self.max_attempts

    def record_failure(self, key):
        self._pruned(key)
        self._failures[key].append(time())

    def reset(self, key):
        self._failures.pop(key, None)

    def remaining(self, key):
        return max(0, self.max_attempts - len(self._pruned(key)))
