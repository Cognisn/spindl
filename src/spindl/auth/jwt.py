"""A reference authenticator for JWT access tokens from an OAuth server.

spindl stays a resource server: it never logs anyone in, issues tokens or
registers clients. :class:`JwtAuthenticator` checks JWT access tokens that
an external OAuth 2.1 authorisation server issued, as the MCP authorisation
specification requires of a resource server:

* the signature, with keys from the issuer's JWKS (fetched over HTTPS,
  cached, refreshed for an unknown key id at most once per interval) or a
  static key set;
* the algorithm, against an allow-list of asymmetric algorithms (``none``
  and the HMAC algorithms are never accepted, RFC 8725 sections 3.1 and
  3.2);
* the issuer, exactly;
* the audience, which must be this server's resource URL (RFC 8707,
  RFC 9728): a token issued for another server is refused here;
* expiry and not-before, with a small bounded leeway.

Mapping the verified claims to tool permissions and reach is the adopter's
decision, made by the ``claims_to_permissions`` and ``claims_to_reach``
callables. Anything that goes wrong (a bad token, an unreachable JWKS, a
mapper that raises) is a refusal: spindl answers ``401``. Refusals are
logged by reason only; no token or claim value is ever logged.
"""

import asyncio
import ipaddress
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol

import jwt
from jwt.exceptions import PyJWKError

from spindl.auth._types import Credentials, Identity, ToolAction

if TYPE_CHECKING:
    from spindl.tool import BaseTool

logger = logging.getLogger("spindl.auth")

MAX_LEEWAY_SECONDS = 120
"""The largest clock-skew leeway, in seconds, a JwtAuthenticator accepts."""

MAX_JWKS_BYTES = 1024 * 1024
"""The largest JWKS document, in bytes, that is read."""

# Asymmetric JWS algorithms (RFC 7518 section 3.1, RFC 8037). HMAC
# algorithms are deliberately absent: with a published key set, an HMAC
# "secret" would be a public key anyone can sign with (RFC 8725 section 2.1).
_ASYMMETRIC_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES256K",
        "ES384",
        "ES512",
        "EdDSA",
    }
)

ClaimsMapper = Callable[[Mapping[str, Any]], Any]
"""A callable given a token's verified claims."""


class ToolAuthoriser(Protocol):
    """Anything with an ``authorise`` method like :class:`Authenticator`'s.

    For example a scope authoriser that compares ``tool.permissions`` with
    ``identity.tool_permissions``.
    """

    async def authorise(
        self, identity: Identity, tool: "BaseTool", action: ToolAction
    ) -> bool: ...


def default_claims_to_permissions(claims: Mapping[str, Any]) -> list[str]:
    """Tool permissions from the ``scope`` claim, else the ``scp`` claim.

    ``scope`` is the space-separated string of RFC 8693 section 4.2 and
    RFC 9068; ``scp`` is the list (or string) some issuers use instead. A
    token with neither grants no permissions. A malformed claim raises
    ``ValueError``, which refuses the token.
    """
    for name in ("scope", "scp"):
        if name not in claims:
            continue
        value = claims[name]
        if isinstance(value, str):
            return value.split()
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
        raise ValueError(f"malformed {name} claim")
    return []


class _Refused(Exception):
    """A token was refused; the message is a fixed reason, never a value."""


@dataclass(frozen=True)
class _Key:
    jwk: jwt.PyJWK
    declared_alg: Optional[str]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses redirects, so a JWKS fetch can never leave the configured URL."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _parse_key_set(document: Any) -> dict[Optional[str], _Key]:
    """The usable signing keys in a JWK Set document, by key id.

    Keys marked for another use, keys PyJWT cannot load and key ids that
    appear more than once are left out. Raises ``ValueError`` when no
    usable key remains.
    """
    if not isinstance(document, Mapping):
        raise ValueError("a JWK Set must be a JSON object")
    entries = document.get("keys")
    if not isinstance(entries, list):
        raise ValueError("a JWK Set must have a keys list")
    keys: dict[Optional[str], _Key] = {}
    duplicates: set[Optional[str]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("use", "sig") != "sig":
            continue
        try:
            key = jwt.PyJWK(dict(entry))
        except (PyJWKError, ValueError, TypeError, KeyError):
            continue
        kid = entry.get("kid")
        kid = kid if isinstance(kid, str) else None
        if kid in keys:
            duplicates.add(kid)
        alg = entry.get("alg")
        keys[kid] = _Key(key, alg if isinstance(alg, str) else None)
    for kid in duplicates:
        del keys[kid]
    if not keys:
        raise ValueError("the JWK Set holds no usable signing key")
    return keys


def _check_jwks_url(url: str, allow_insecure_loopback: bool) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and allow_insecure_loopback:
        try:
            loopback = ipaddress.ip_address(parts.hostname or "") == (
                ipaddress.ip_address("127.0.0.1")
            )
        except ValueError:
            loopback = False
        if loopback:
            return url
        raise ValueError(
            "allow_insecure_loopback permits http only for 127.0.0.1 (for tests)"
        )
    raise ValueError("jwks_url must be an https URL")


class JwtAuthenticator:
    """Authenticates JWT access tokens issued by an external OAuth server.

    An :class:`~spindl.auth.Authenticator` for
    ``AuthConfig(authenticator=...)``. All arguments are keyword-only.

    Args:
        issuer: The authorisation server's issuer identifier. The token's
            ``iss`` claim must equal it exactly.
        audience: This server's resource URL, the same value as
            ``AuthConfig.resource_server_url``. The token's ``aud`` claim
            must be exactly this string (or a list holding it). This is
            required because a token the authorisation server issued for
            another resource server (RFC 8707) must not work here: without
            the check, any server trusting the same issuer could replay its
            callers' tokens against this one. spindl cannot check it for
            you, because an authenticator is not told the resource URL.
        claims_to_reach: Required. Given the verified claims, returns the
            caller's reach (``Identity.reach``): what this credential's
            calls may touch. It is required so that reach is a deliberate
            decision. It may return ``None``, and then every tool that
            requires reach is refused.
        jwks_url: The issuer's JWKS endpoint, fetched over HTTPS. Give
            exactly one of ``jwks_url`` and ``jwks``.
        jwks: A static JWK Set document (``{"keys": [...]}``) instead of a
            JWKS endpoint.
        algorithms: The JWS algorithms accepted, by default RS256 and
            ES256. Only asymmetric algorithms are allowed; ``none`` and the
            HMAC algorithms are refused here and in every token.
        leeway_seconds: Clock-skew allowance for ``exp`` and ``nbf``, at
            most :data:`MAX_LEEWAY_SECONDS`. Default 30.
        jwks_cache_seconds: How long fetched keys are used before the JWKS
            is fetched again. Default 300.
        jwks_refresh_interval_seconds: The least time between two JWKS
            fetches. A token with an unknown key id triggers a refresh at
            most once per interval, and a failed fetch is not retried
            within it. Default 60; at most ``jwks_cache_seconds``.
        jwks_timeout_seconds: Network timeout for one JWKS fetch.
        claims_to_permissions: Given the verified claims, returns the
            caller's tool permissions (``Identity.tool_permissions``) as an
            iterable of strings. Defaults to
            :func:`default_claims_to_permissions` (``scope``, else ``scp``).
        authoriser: Decides tool access in :meth:`authorise`, for example
            a scope authoriser. Without one, **every authenticated caller
            may list and call every tool**; tool access then rests on
            ``AuthConfig.required_scopes`` and reach alone.
        allow_insecure_loopback: Allows an ``http`` ``jwks_url`` on
            127.0.0.1, for tests only. Never set it in production.

    The subject comes from ``sub`` (required); the client id from
    ``client_id``, else ``azp``. ``Identity.expires_at`` is the token's
    ``exp`` plus the leeway, the end of the window in which it is accepted.

    JWKS fetches use the standard library's HTTP client in a worker thread,
    so they never block the event loop, and never follow redirects. When
    keys cannot be fetched every token is refused: stale keys are not used
    past ``jwks_cache_seconds``.

    If ``claims_to_permissions`` or ``claims_to_reach`` raises, or returns
    something unusable, the token is refused. Refusals are logged at
    ``INFO`` on ``spindl.auth`` with a fixed reason; no token or claim value
    is logged.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        claims_to_reach: ClaimsMapper,
        jwks_url: Optional[str] = None,
        jwks: Optional[Mapping[str, Any]] = None,
        algorithms: Sequence[str] = ("RS256", "ES256"),
        leeway_seconds: float = 30,
        jwks_cache_seconds: float = 300,
        jwks_refresh_interval_seconds: float = 60,
        jwks_timeout_seconds: float = 10,
        claims_to_permissions: Optional[ClaimsMapper] = None,
        authoriser: Optional[ToolAuthoriser] = None,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not isinstance(issuer, str) or not issuer:
            raise ValueError("issuer must be a non-empty string")
        if not isinstance(audience, str) or not audience:
            raise ValueError(
                "audience must be this server's resource URL "
                "(AuthConfig.resource_server_url)"
            )
        if not callable(claims_to_reach):
            raise TypeError("claims_to_reach must be callable")
        if claims_to_permissions is not None and not callable(claims_to_permissions):
            raise TypeError("claims_to_permissions must be callable")
        algorithms = tuple(algorithms)
        if not algorithms:
            raise ValueError("algorithms must name at least one algorithm")
        unsafe = [alg for alg in algorithms if alg not in _ASYMMETRIC_ALGORITHMS]
        if unsafe:
            raise ValueError(
                "algorithms may name only asymmetric JWS algorithms; refused: "
                + ", ".join(unsafe)
            )
        if not 0 <= leeway_seconds <= MAX_LEEWAY_SECONDS:
            raise ValueError(
                f"leeway_seconds must be between 0 and {MAX_LEEWAY_SECONDS}"
            )
        if jwks_cache_seconds <= 0 or jwks_refresh_interval_seconds <= 0:
            raise ValueError("JWKS cache and refresh intervals must be positive")
        if jwks_refresh_interval_seconds > jwks_cache_seconds:
            raise ValueError(
                "jwks_refresh_interval_seconds must not exceed jwks_cache_seconds"
            )
        if (jwks_url is None) == (jwks is None):
            raise ValueError("give exactly one of jwks_url and jwks")

        self.issuer = issuer
        self.audience = audience
        self.algorithms: tuple[str, ...] = algorithms
        self.leeway_seconds = leeway_seconds
        self._claims_to_reach = claims_to_reach
        self._claims_to_permissions: ClaimsMapper = (
            claims_to_permissions or default_claims_to_permissions
        )
        self._authoriser = authoriser
        self._cache_seconds = jwks_cache_seconds
        self._refresh_interval = jwks_refresh_interval_seconds
        self._timeout = jwks_timeout_seconds
        self._clock: Callable[[], float] = time.monotonic
        self._lock = threading.Lock()
        self._keys: Optional[dict[Optional[str], _Key]] = None
        self._fetched_at: Optional[float] = None
        self._last_attempt: Optional[float] = None
        self._jwks_url: Optional[str] = None
        if jwks is not None:
            self._keys = _parse_key_set(jwks)
        else:
            assert jwks_url is not None
            self._jwks_url = _check_jwks_url(jwks_url, allow_insecure_loopback)
            self._opener = urllib.request.build_opener(_NoRedirect)

    def __repr__(self) -> str:
        return (
            f"JwtAuthenticator(issuer={self.issuer!r}, audience={self.audience!r}, "
            f"algorithms={list(self.algorithms)!r})"
        )

    # -- Authenticator ------------------------------------------------------

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        """The caller's identity from a valid bearer JWT, else ``None``."""
        token = credentials.bearer_token
        if not token:
            return None
        try:
            return await self._identity(token)
        except _Refused as exc:
            logger.info("JWT refused: %s", exc)
        except Exception as exc:
            logger.info("JWT refused: %s", type(exc).__name__)
        return None

    async def authorise(
        self, identity: Identity, tool: "BaseTool", action: ToolAction
    ) -> bool:
        """Delegates to the configured authoriser; allows every tool without one."""
        if self._authoriser is None:
            return True
        return await self._authoriser.authorise(identity, tool, action)

    # -- Verification -------------------------------------------------------

    async def _identity(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise _Refused("malformed token") from None
        alg = header.get("alg")
        if not isinstance(alg, str) or alg not in self.algorithms:
            raise _Refused("algorithm not allowed")
        kid = header.get("kid")
        if kid is not None and not isinstance(kid, str):
            raise _Refused("malformed key id")
        key = await self._key_for(kid)
        if key is None:
            raise _Refused("no signing key for the token")
        if key.declared_alg is not None and key.declared_alg != alg:
            raise _Refused("algorithm does not match the key")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.jwk.key,
                algorithms=[alg],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.leeway_seconds,
                options={
                    "verify_signature": True,
                    "require": ["exp", "iss", "aud", "sub"],
                },
            )
        except jwt.PyJWTError as exc:
            raise _Refused(type(exc).__name__) from None
        return self._map(claims)

    def _map(self, claims: Mapping[str, Any]) -> Identity:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise _Refused("no subject")
        client_id = claims.get("client_id")
        if not isinstance(client_id, str):
            azp = claims.get("azp")
            client_id = azp if isinstance(azp, str) else None
        try:
            permissions = self._claims_to_permissions(claims)
        except Exception as exc:
            raise _Refused(
                f"claims_to_permissions raised {type(exc).__name__}"
            ) from None
        if isinstance(permissions, (str, bytes)) or not isinstance(
            permissions, Iterable
        ):
            raise _Refused("claims_to_permissions must return an iterable of names")
        names = list(permissions)
        if not all(isinstance(name, str) for name in names):
            raise _Refused("claims_to_permissions must return strings")
        try:
            reach = self._claims_to_reach(claims)
        except Exception as exc:
            raise _Refused(f"claims_to_reach raised {type(exc).__name__}") from None
        return Identity(
            subject=subject,
            client_id=client_id,
            tool_permissions=frozenset(names),
            reach=reach,
            expires_at=float(claims["exp"]) + self.leeway_seconds,
        )

    # -- Keys ---------------------------------------------------------------

    @staticmethod
    def _lookup(keys: Mapping[Optional[str], _Key], kid: Optional[str]) -> Any:
        if kid is None:
            if len(keys) == 1:
                return next(iter(keys.values()))
            return None
        return keys.get(kid)

    async def _key_for(self, kid: Optional[str]) -> Optional[_Key]:
        if self._jwks_url is None:
            assert self._keys is not None
            found: Optional[_Key] = self._lookup(self._keys, kid)
            return found
        return await asyncio.to_thread(self._fetched_key_for, kid)

    def _fetched_key_for(self, kid: Optional[str]) -> Optional[_Key]:
        """The key for ``kid`` from the JWKS, fetching when due. In a thread."""
        with self._lock:
            now = self._clock()
            if (
                self._fetched_at is None
                or now - self._fetched_at >= self._cache_seconds
            ):
                self._keys = None
                if self._may_fetch(now):
                    self._fetch(now)
            if self._keys is None:
                return None
            key: Optional[_Key] = self._lookup(self._keys, kid)
            if key is None and kid is not None and self._may_fetch(now):
                self._fetch(now)
                if self._keys is not None:
                    key = self._lookup(self._keys, kid)
            return key

    def _may_fetch(self, now: float) -> bool:
        return (
            self._last_attempt is None
            or now - self._last_attempt >= self._refresh_interval
        )

    def _fetch(self, now: float) -> None:
        """Fetches the JWKS; on any failure no keys are held (fail closed)."""
        assert self._jwks_url is not None
        self._last_attempt = now
        try:
            request = urllib.request.Request(
                self._jwks_url, headers={"Accept": "application/json"}
            )
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                body = response.read(MAX_JWKS_BYTES + 1)
            if len(body) > MAX_JWKS_BYTES:
                raise ValueError("JWKS document too large")
            keys = _parse_key_set(json.loads(body))
        except Exception as exc:
            self._keys = None
            self._fetched_at = None
            logger.warning(
                "JWKS fetch from %s failed (%s); refusing tokens until it succeeds",
                self._jwks_url,
                type(exc).__name__,
            )
            return
        self._keys = keys
        self._fetched_at = now
