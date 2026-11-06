"""Tests for the reference JwtAuthenticator.

Every guard a resource server needs for JWT access tokens is pinned here:
the signature, the algorithm allow-list (``none``, algorithms outside the
list and an HS256 token keyed with the public key), the exact issuer, the
audience bound to this server's resource URL, expiry and not-before with a
bounded leeway, JWKS caching and refresh, failing closed when the JWKS
cannot be fetched or a claims mapper fails, and that no token or claim
value is logged. Keys are generated here and the JWKS is served from a
local listener; no real issuer is contacted.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel

from spindl.auth import AuthConfig, Authenticator, Credentials, Identity, ToolAction
from spindl.auth.jwt import (
    MAX_LEEWAY_SECONDS,
    JwtAuthenticator,
    default_claims_to_permissions,
)
from spindl.server import MCPServer
from spindl.tool import BaseTool

ISSUER = "https://issuer.example.com"
RESOURCE_URL = "http://testserver/mcp"
OTHER_RESOURCE_URL = "https://other.example.com/mcp"
# The JWKS listener needs a real socket. Port 0 asks the OS for a free one;
# set SPINDL_TEST_JWKS_PORT to keep it inside a reserved block.
JWKS_PORT = int(os.environ.get("SPINDL_TEST_JWKS_PORT", "0"))
# A claim value that must never reach a log line.
SECRET_TENANT = "tenant-value-never-logged"

RSA_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_PRIVATE = ec.generate_private_key(ec.SECP256R1())


def jwk_for(public_key: Any, kid: Optional[str], **extra: Any) -> dict[str, Any]:
    if isinstance(public_key, rsa.RSAPublicKey):
        data: dict[str, Any] = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    else:
        data = ECAlgorithm.to_jwk(public_key, as_dict=True)
    if kid is not None:
        data["kid"] = kid
    data.update(extra)
    return data


RSA_JWK = jwk_for(RSA_PRIVATE.public_key(), "rsa-1")
EC_JWK = jwk_for(EC_PRIVATE.public_key(), "ec-1")
ROTATED_JWK = jwk_for(RSA_OTHER.public_key(), "rsa-2")
STATIC_JWKS = {"keys": [RSA_JWK, EC_JWK]}


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    data: dict[str, Any] = {
        "iss": ISSUER,
        "aud": RESOURCE_URL,
        "sub": "alice",
        "client_id": "app",
        "scope": "read write",
        "tenant": SECRET_TENANT,
        "iat": now,
        "exp": now + 300,
    }
    for name, value in overrides.items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    return data


def make_token(
    key: Any = RSA_PRIVATE,
    alg: str = "RS256",
    kid: Optional[str] = "rsa-1",
    **overrides: Any,
) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims(**overrides), key, algorithm=alg, headers=headers)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def hand_made_token(header: dict[str, Any], body: dict[str, Any], key: bytes) -> str:
    """A token built by hand, for headers PyJWT refuses to produce."""
    signing_input = (
        f"{b64(json.dumps(header).encode())}.{b64(json.dumps(body).encode())}"
    )
    if header["alg"] == "none":
        return signing_input + "."
    mac = hmac.new(key, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(mac)}"


def reach_from_claims(token_claims: Mapping[str, Any]) -> object:
    tenant = token_claims.get("tenant")
    return {"tenant": tenant} if tenant else None


def make_jwt(**overrides: Any) -> JwtAuthenticator:
    kwargs: dict[str, Any] = {
        "issuer": ISSUER,
        "audience": RESOURCE_URL,
        "jwks": STATIC_JWKS,
        "claims_to_reach": reach_from_claims,
    }
    kwargs.update(overrides)
    return JwtAuthenticator(**kwargs)


async def authenticate(auth: JwtAuthenticator, token: Optional[str]) -> Any:
    return await auth.authenticate(Credentials(bearer_token=token))


# ---------------------------------------------------------------------------
# A local JWKS listener
# ---------------------------------------------------------------------------


class JwksState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.document: Any = {"keys": [RSA_JWK, EC_JWK]}
        self.status = 200
        self.body: Optional[bytes] = None
        self.redirect_to: Optional[str] = None
        self.delay = 0.0
        self.requests = 0


class JwksHandler(BaseHTTPRequestHandler):
    server: "JwksServer"

    def do_GET(self) -> None:
        state = self.server.state
        state.requests += 1
        if state.delay:
            time.sleep(state.delay)
        if state.redirect_to and "redirected" not in self.path:
            self.send_response(302)
            self.send_header("Location", state.redirect_to)
            self.end_headers()
            return
        body = state.body
        if body is None:
            body = json.dumps(state.document).encode()
        self.send_response(state.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class JwksServer(ThreadingHTTPServer):
    daemon_threads = True
    # Never share a port with another listener (SO_REUSEADDR on Windows would).
    allow_reuse_address = False

    def __init__(self, port: int = JWKS_PORT) -> None:
        super().__init__(("127.0.0.1", port), JwksHandler)
        self.state = JwksState()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/jwks.json"


@pytest.fixture(scope="module")
def jwks_listener() -> Iterator[JwksServer]:
    server = JwksServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def jwks_server(jwks_listener: JwksServer) -> JwksServer:
    jwks_listener.state.reset()
    return jwks_listener


def fetching_jwt(server: JwksServer, **overrides: Any) -> JwtAuthenticator:
    kwargs: dict[str, Any] = {
        "jwks": None,
        "jwks_url": server.url,
        "allow_insecure_loopback": True,
    }
    kwargs.update(overrides)
    return make_jwt(**kwargs)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_is_an_authenticator(self):
        assert isinstance(make_jwt(), Authenticator)

    def test_audience_is_required(self):
        with pytest.raises(TypeError):
            JwtAuthenticator(  # type: ignore[call-arg]
                issuer=ISSUER, jwks=STATIC_JWKS, claims_to_reach=reach_from_claims
            )

    @pytest.mark.parametrize("audience", ["", None])
    def test_empty_audience_is_refused(self, audience):
        with pytest.raises(ValueError):
            make_jwt(audience=audience)

    @pytest.mark.parametrize("issuer", ["", None])
    def test_empty_issuer_is_refused(self, issuer):
        with pytest.raises(ValueError):
            make_jwt(issuer=issuer)

    def test_claims_to_reach_is_required(self):
        with pytest.raises(TypeError):
            JwtAuthenticator(  # type: ignore[call-arg]
                issuer=ISSUER, audience=RESOURCE_URL, jwks=STATIC_JWKS
            )

    def test_claims_to_reach_must_be_callable(self):
        with pytest.raises(TypeError):
            make_jwt(claims_to_reach=None)

    def test_exactly_one_key_source(self):
        with pytest.raises(ValueError):
            make_jwt(jwks=None)
        with pytest.raises(ValueError):
            make_jwt(jwks_url="https://issuer.example.com/jwks.json")

    def test_static_keys_must_hold_a_usable_key(self):
        with pytest.raises(ValueError):
            make_jwt(jwks={"keys": []})

    @pytest.mark.parametrize(
        "url",
        [
            "http://issuer.example.com/jwks.json",
            "http://127.0.0.1:8080/jwks.json",
            "ftp://issuer.example.com/jwks.json",
            "https:///jwks.json",
        ],
    )
    def test_jwks_url_must_be_https(self, url):
        with pytest.raises(ValueError):
            make_jwt(jwks=None, jwks_url=url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://issuer.example.com/jwks.json",
            "http://localhost:8080/jwks.json",
            "http://127.0.0.2:8080/jwks.json",
        ],
    )
    def test_the_loopback_flag_allows_http_only_for_127_0_0_1(self, url):
        with pytest.raises(ValueError):
            make_jwt(jwks=None, jwks_url=url, allow_insecure_loopback=True)

    def test_the_loopback_flag_allows_http_127_0_0_1(self):
        make_jwt(
            jwks=None,
            jwks_url="http://127.0.0.1:8080/jwks.json",
            allow_insecure_loopback=True,
        )

    def test_https_needs_no_flag(self):
        make_jwt(jwks=None, jwks_url="https://issuer.example.com/jwks.json")

    def test_default_algorithms(self):
        assert make_jwt().algorithms == ("RS256", "ES256")

    @pytest.mark.parametrize(
        "algorithms",
        [[], ["none"], ["RS256", "none"], ["HS256"], ["RS256", "HS512"], ["XX999"]],
    )
    def test_unsafe_or_unknown_algorithms_are_refused(self, algorithms):
        with pytest.raises(ValueError):
            make_jwt(algorithms=algorithms)

    def test_leeway_is_capped(self):
        make_jwt(leeway_seconds=MAX_LEEWAY_SECONDS)
        with pytest.raises(ValueError):
            make_jwt(leeway_seconds=MAX_LEEWAY_SECONDS + 1)
        with pytest.raises(ValueError):
            make_jwt(leeway_seconds=-1)

    def test_cache_and_refresh_intervals_must_be_positive_and_ordered(self):
        with pytest.raises(ValueError):
            make_jwt(jwks_cache_seconds=0)
        with pytest.raises(ValueError):
            make_jwt(jwks_refresh_interval_seconds=0)
        with pytest.raises(ValueError):
            make_jwt(jwks_cache_seconds=30, jwks_refresh_interval_seconds=60)

    def test_repr_names_the_issuer_and_audience_only(self):
        text = repr(make_jwt())
        assert ISSUER in text and RESOURCE_URL in text


# ---------------------------------------------------------------------------
# Accepting a token
# ---------------------------------------------------------------------------


class TestAccepting:
    async def test_a_valid_rs256_token_gives_an_identity(self):
        token_claims = claims()
        token = jwt.encode(
            token_claims, RSA_PRIVATE, algorithm="RS256", headers={"kid": "rsa-1"}
        )
        identity = await authenticate(make_jwt(), token)
        assert isinstance(identity, Identity)
        assert identity.subject == "alice"
        assert identity.client_id == "app"
        assert identity.tool_permissions == frozenset({"read", "write"})
        assert identity.reach == {"tenant": SECRET_TENANT}
        assert identity.expires_at == token_claims["exp"] + 30

    async def test_a_valid_es256_token_gives_an_identity(self):
        token = make_token(EC_PRIVATE, "ES256", "ec-1")
        identity = await authenticate(make_jwt(), token)
        assert identity is not None and identity.subject == "alice"

    async def test_client_id_falls_back_to_azp(self):
        token = make_token(client_id=None, azp="web-app")
        identity = await authenticate(make_jwt(), token)
        assert identity.client_id == "web-app"

    async def test_client_id_is_none_without_either_claim(self):
        identity = await authenticate(make_jwt(), make_token(client_id=None))
        assert identity.client_id is None

    async def test_permissions_from_an_scp_list(self):
        token = make_token(scope=None, scp=["read", "admin"])
        identity = await authenticate(make_jwt(), token)
        assert identity.tool_permissions == frozenset({"read", "admin"})

    async def test_no_scope_claim_means_no_permissions(self):
        identity = await authenticate(make_jwt(), make_token(scope=None))
        assert identity.tool_permissions == frozenset()

    async def test_a_custom_permissions_mapper_is_used(self):
        def roles(token_claims: Mapping[str, Any]) -> list[str]:
            return [f"role:{r}" for r in token_claims["roles"]]

        auth = make_jwt(claims_to_permissions=roles)
        identity = await authenticate(auth, make_token(roles=["viewer"]))
        assert identity.tool_permissions == frozenset({"role:viewer"})

    async def test_reach_may_be_none(self):
        identity = await authenticate(make_jwt(), make_token(tenant=None))
        assert identity is not None and identity.reach is None

    async def test_the_mappers_receive_the_verified_claims(self):
        seen: list[Mapping[str, Any]] = []

        def record(token_claims: Mapping[str, Any]) -> object:
            seen.append(token_claims)
            return "r"

        await authenticate(make_jwt(claims_to_reach=record), make_token())
        assert seen[0]["sub"] == "alice" and seen[0]["iss"] == ISSUER

    async def test_a_token_without_kid_uses_the_only_key(self):
        auth = make_jwt(jwks={"keys": [jwk_for(RSA_PRIVATE.public_key(), None)]})
        identity = await authenticate(auth, make_token(kid=None))
        assert identity is not None

    async def test_an_audience_list_holding_this_resource_is_accepted(self):
        token = make_token(aud=[OTHER_RESOURCE_URL, RESOURCE_URL])
        assert await authenticate(make_jwt(), token) is not None


class TestDefaultPermissions:
    @pytest.mark.parametrize(
        "token_claims, expected",
        [
            ({"scope": "a b  c"}, ["a", "b", "c"]),
            ({"scope": ""}, []),
            ({"scp": ["a", "b"]}, ["a", "b"]),
            ({"scp": "a b"}, ["a", "b"]),
            ({"scope": "a", "scp": ["b"]}, ["a"]),
            ({}, []),
        ],
    )
    def test_scope_then_scp(self, token_claims, expected):
        assert list(default_claims_to_permissions(token_claims)) == expected

    @pytest.mark.parametrize(
        "token_claims", [{"scope": 5}, {"scp": [1, 2]}, {"scp": {"a": 1}}]
    )
    def test_malformed_scope_claims_raise(self, token_claims):
        with pytest.raises(ValueError):
            default_claims_to_permissions(token_claims)


# ---------------------------------------------------------------------------
# Refusing a token: every guard
# ---------------------------------------------------------------------------


class TestRefusing:
    async def test_no_token(self):
        assert await authenticate(make_jwt(), None) is None

    @pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", "", "...."])
    async def test_garbage(self, token):
        assert await authenticate(make_jwt(), token) is None

    async def test_a_signature_from_another_key(self):
        token = make_token(RSA_OTHER, "RS256", "rsa-1")
        assert await authenticate(make_jwt(), token) is None

    async def test_a_tampered_payload(self):
        header, _, signature = make_token().split(".")
        body = b64(json.dumps(claims(sub="mallory")).encode())
        assert await authenticate(make_jwt(), f"{header}.{body}.{signature}") is None

    async def test_alg_none(self):
        token = hand_made_token({"alg": "none", "kid": "rsa-1"}, claims(), b"")
        assert await authenticate(make_jwt(), token) is None

    async def test_alg_none_even_when_allowed_by_mistake_upstream(self):
        token = hand_made_token({"alg": "None", "kid": "rsa-1"}, claims(), b"")
        assert await authenticate(make_jwt(), token) is None

    async def test_an_algorithm_outside_the_allow_list(self):
        auth = make_jwt(algorithms=["RS256"])
        token = make_token(EC_PRIVATE, "ES256", "ec-1")
        assert await authenticate(auth, token) is None

    async def test_hs256_signed_with_the_public_key(self):
        public_pem = RSA_PRIVATE.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        token = hand_made_token({"alg": "HS256", "kid": "rsa-1"}, claims(), public_pem)
        assert await authenticate(make_jwt(), token) is None

    async def test_an_algorithm_the_key_does_not_declare(self):
        auth = make_jwt(
            algorithms=["RS256", "RS384"],
            jwks={"keys": [jwk_for(RSA_PRIVATE.public_key(), "rsa-1", alg="RS384")]},
        )
        assert await authenticate(auth, make_token()) is None

    async def test_a_key_not_for_signatures(self):
        auth = make_jwt(
            jwks={
                "keys": [jwk_for(RSA_PRIVATE.public_key(), "rsa-1", use="enc"), EC_JWK]
            }
        )
        assert await authenticate(auth, make_token()) is None

    @pytest.mark.parametrize(
        "issuer", ["https://evil.example.com", ISSUER + "/", ISSUER.upper()]
    )
    async def test_another_issuer(self, issuer):
        assert await authenticate(make_jwt(), make_token(iss=issuer)) is None

    async def test_no_issuer(self):
        assert await authenticate(make_jwt(), make_token(iss=None)) is None

    @pytest.mark.parametrize(
        "audience",
        [
            OTHER_RESOURCE_URL,
            RESOURCE_URL + "/",
            "http://testserver",
            [OTHER_RESOURCE_URL],
        ],
    )
    async def test_a_token_for_another_resource(self, audience):
        assert await authenticate(make_jwt(), make_token(aud=audience)) is None

    async def test_no_audience(self):
        assert await authenticate(make_jwt(), make_token(aud=None)) is None

    async def test_expired_beyond_the_leeway(self):
        token = make_token(exp=int(time.time()) - 45)
        assert await authenticate(make_jwt(), token) is None

    async def test_expired_within_the_leeway_is_accepted(self):
        token = make_token(exp=int(time.time()) - 10)
        assert await authenticate(make_jwt(), token) is not None

    async def test_expired_with_no_leeway(self):
        token = make_token(exp=int(time.time()) - 2)
        assert await authenticate(make_jwt(leeway_seconds=0), token) is None

    async def test_no_expiry(self):
        assert await authenticate(make_jwt(), make_token(exp=None)) is None

    async def test_not_yet_valid_beyond_the_leeway(self):
        token = make_token(nbf=int(time.time()) + 45)
        assert await authenticate(make_jwt(), token) is None

    async def test_not_yet_valid_within_the_leeway_is_accepted(self):
        token = make_token(nbf=int(time.time()) + 10)
        assert await authenticate(make_jwt(), token) is not None

    @pytest.mark.parametrize("subject", [None, "", 42])
    async def test_no_usable_subject(self, subject):
        assert await authenticate(make_jwt(), make_token(sub=subject)) is None

    async def test_an_unknown_kid_with_static_keys(self):
        token = make_token(RSA_OTHER, "RS256", "rsa-2")
        assert await authenticate(make_jwt(), token) is None

    async def test_no_kid_when_there_are_several_keys(self):
        assert await authenticate(make_jwt(), make_token(kid=None)) is None

    async def test_a_raising_reach_mapper_fails_closed(self):
        def broken(token_claims: Mapping[str, Any]) -> object:
            raise RuntimeError("mapper failed")

        assert (
            await authenticate(make_jwt(claims_to_reach=broken), make_token()) is None
        )

    async def test_a_raising_permissions_mapper_fails_closed(self):
        def broken(token_claims: Mapping[str, Any]) -> list[str]:
            raise KeyError("roles")

        auth = make_jwt(claims_to_permissions=broken)
        assert await authenticate(auth, make_token()) is None

    async def test_a_permissions_mapper_returning_a_string_fails_closed(self):
        auth = make_jwt(claims_to_permissions=lambda c: "read write")
        assert await authenticate(auth, make_token()) is None

    async def test_a_permissions_mapper_returning_non_strings_fails_closed(self):
        auth = make_jwt(claims_to_permissions=lambda c: ["read", 7])
        assert await authenticate(auth, make_token()) is None

    async def test_a_malformed_scope_claim_fails_closed(self):
        assert await authenticate(make_jwt(), make_token(scope=["read", 1])) is None


class TestLogging:
    async def test_no_token_or_claim_value_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG)

        def broken(token_claims: Mapping[str, Any]) -> object:
            raise RuntimeError(f"bad tenant {token_claims['tenant']}")

        good = make_token()
        other_audience = make_token(aud=OTHER_RESOURCE_URL)
        await authenticate(make_jwt(), good)
        await authenticate(make_jwt(), other_audience)
        await authenticate(make_jwt(claims_to_reach=broken), good)
        await authenticate(make_jwt(), "garbage-token-text")
        text = caplog.text
        assert "refused" in text
        for secret in (good, other_audience, "garbage-token-text"):
            assert secret not in text
            for part in secret.split("."):
                assert len(part) < 8 or part not in text
        assert SECRET_TENANT not in text
        assert "alice" not in text
        assert OTHER_RESOURCE_URL not in text


# ---------------------------------------------------------------------------
# JWKS fetching, caching and refresh
# ---------------------------------------------------------------------------


class TestJwks:
    async def test_keys_are_fetched_and_cached(self, jwks_server):
        auth = fetching_jwt(jwks_server)
        assert await authenticate(auth, make_token()) is not None
        assert await authenticate(auth, make_token(EC_PRIVATE, "ES256", "ec-1"))
        assert jwks_server.state.requests == 1

    async def test_the_cache_expires(self, jwks_server):
        clock = FakeClock()
        auth = fetching_jwt(jwks_server, jwks_cache_seconds=300)
        auth._clock = clock
        await authenticate(auth, make_token())
        clock.now += 299
        await authenticate(auth, make_token())
        assert jwks_server.state.requests == 1
        clock.now += 2
        assert await authenticate(auth, make_token()) is not None
        assert jwks_server.state.requests == 2

    async def test_an_unknown_kid_refreshes_once_per_interval(self, jwks_server):
        clock = FakeClock()
        auth = fetching_jwt(jwks_server, jwks_refresh_interval_seconds=60)
        auth._clock = clock
        await authenticate(auth, make_token())
        assert jwks_server.state.requests == 1
        unknown = make_token(RSA_OTHER, "RS256", "rsa-2")
        clock.now += 61
        assert await authenticate(auth, unknown) is None
        assert jwks_server.state.requests == 2
        for _ in range(5):
            clock.now += 5
            assert await authenticate(auth, unknown) is None
        assert jwks_server.state.requests == 2
        clock.now += 40
        assert await authenticate(auth, unknown) is None
        assert jwks_server.state.requests == 3

    async def test_an_unknown_kid_right_after_a_fetch_does_not_refetch(
        self, jwks_server
    ):
        auth = fetching_jwt(jwks_server)
        await authenticate(auth, make_token())
        for _ in range(3):
            await authenticate(auth, make_token(RSA_OTHER, "RS256", "rsa-2"))
        assert jwks_server.state.requests == 1

    async def test_a_rotated_key_is_picked_up_by_the_refresh(self, jwks_server):
        clock = FakeClock()
        auth = fetching_jwt(jwks_server)
        auth._clock = clock
        await authenticate(auth, make_token())
        jwks_server.state.document = {"keys": [RSA_JWK, ROTATED_JWK]}
        clock.now += 61
        rotated = make_token(RSA_OTHER, "RS256", "rsa-2")
        identity = await authenticate(auth, rotated)
        assert identity is not None and identity.subject == "alice"

    async def test_concurrent_unknown_kids_share_one_refresh(self, jwks_server):
        auth = fetching_jwt(jwks_server)
        jwks_server.state.delay = 0.2
        unknown = make_token(RSA_OTHER, "RS256", "rsa-2")
        results = await asyncio.gather(*(authenticate(auth, unknown) for _ in range(5)))
        assert results == [None] * 5
        assert jwks_server.state.requests == 1

    @pytest.mark.parametrize(
        "status, body",
        [
            (500, None),
            (404, None),
            (200, b"not json"),
            (200, b'{"no_keys": []}'),
            (200, b'{"keys": "nope"}'),
            (200, b'{"keys": []}'),
            (200, b'{"keys": [' + b" " * (1024 * 1024 + 10) + b"]}"),
        ],
        ids=["500", "404", "not-json", "no-keys", "keys-not-list", "empty", "huge"],
    )
    async def test_a_failed_fetch_fails_closed(self, jwks_server, status, body):
        jwks_server.state.status = status
        jwks_server.state.body = body
        assert await authenticate(fetching_jwt(jwks_server), make_token()) is None

    async def test_an_unreachable_jwks_fails_closed(self):
        # A port that was free a moment ago and now has no listener.
        with JwksServer(JWKS_PORT + 1 if JWKS_PORT else 0) as closed:
            url = closed.url
        auth = make_jwt(
            jwks=None,
            jwks_url=url,
            allow_insecure_loopback=True,
            jwks_timeout_seconds=2,
        )
        assert await authenticate(auth, make_token()) is None

    async def test_stale_keys_are_not_used_when_the_refresh_fails(self, jwks_server):
        clock = FakeClock()
        auth = fetching_jwt(jwks_server)
        auth._clock = clock
        assert await authenticate(auth, make_token()) is not None
        jwks_server.state.status = 500
        clock.now += 301
        assert await authenticate(auth, make_token()) is None

    async def test_recovers_after_a_failed_fetch(self, jwks_server):
        clock = FakeClock()
        auth = fetching_jwt(jwks_server)
        auth._clock = clock
        jwks_server.state.status = 500
        assert await authenticate(auth, make_token()) is None
        jwks_server.state.status = 200
        clock.now += 61
        assert await authenticate(auth, make_token()) is not None

    async def test_a_failed_fetch_is_not_retried_within_the_interval(self, jwks_server):
        clock = FakeClock()
        auth = fetching_jwt(jwks_server)
        auth._clock = clock
        jwks_server.state.status = 500
        for _ in range(4):
            clock.now += 5
            assert await authenticate(auth, make_token()) is None
        assert jwks_server.state.requests == 1

    async def test_redirects_are_not_followed(self, jwks_server):
        jwks_server.state.redirect_to = jwks_server.url + "?redirected=1"
        assert await authenticate(fetching_jwt(jwks_server), make_token()) is None

    async def test_the_fetch_does_not_block_the_event_loop(self, jwks_server):
        jwks_server.state.delay = 0.5
        ticks = 0
        done = False

        async def ticker() -> None:
            nonlocal ticks
            while not done:
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        try:
            identity = await authenticate(fetching_jwt(jwks_server), make_token())
        finally:
            done = True
            await task
        assert identity is not None
        assert ticks >= 10


# ---------------------------------------------------------------------------
# Tool access
# ---------------------------------------------------------------------------


class RecordingAuthoriser:
    """Allows a tool when the identity holds every permission it declares."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def authorise(
        self, identity: Identity, tool: BaseTool, action: ToolAction
    ) -> bool:
        self.calls.append((identity.subject, tool.name, action))
        return set(tool.permissions) <= identity.tool_permissions


class ReadTool(BaseTool):
    name = "read_records"
    description = "Read records the caller can reach"
    category = "records"
    read_only = True
    permissions = ["read"]

    class InputModel(BaseModel):
        limit: int = 10

    async def execute(self, **params: Any) -> dict[str, Any]:
        context = self.context
        assert context is not None and context.identity is not None
        return {
            "subject": context.identity.subject,
            "client_id": context.identity.client_id,
            "reach": context.reach,
        }


class WriteTool(BaseTool):
    name = "write_records"
    description = "Write records"
    category = "records"
    destructive = True
    permissions = ["write"]

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"written": True}


class TestAuthorise:
    async def test_without_an_authoriser_any_authenticated_caller_is_allowed(self):
        identity = Identity(subject="alice")
        assert await make_jwt().authorise(identity, WriteTool(), "call") is True

    @pytest.mark.parametrize("action", ["list", "call"])
    async def test_delegates_to_the_authoriser(self, action):
        authoriser = RecordingAuthoriser()
        auth = make_jwt(authoriser=authoriser)
        reader = Identity(subject="bob", tool_permissions={"read"})
        assert await auth.authorise(reader, ReadTool(), action) is True
        assert await auth.authorise(reader, WriteTool(), action) is False
        assert authoriser.calls == [
            ("bob", "read_records", action),
            ("bob", "write_records", action),
        ]


# ---------------------------------------------------------------------------
# End to end through MCPServer over streamable HTTP
# ---------------------------------------------------------------------------


def jwt_server(authenticator: JwtAuthenticator) -> MCPServer:
    server = MCPServer(
        prefix="test",
        auth=AuthConfig(
            authenticator=authenticator,
            resource_server_url=RESOURCE_URL,
            authorization_servers=[ISSUER],
        ),
    )
    server.register(ReadTool())
    server.register(WriteTool())
    return server


@asynccontextmanager
async def mcp_client(server: MCPServer, token: str) -> AsyncIterator[Client]:
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as http_client:
            transport = streamable_http_client(RESOURCE_URL, http_client=http_client)
            async with Client(transport, cache=None) as client:
                yield client


async def raw_initialise(server: MCPServer, token: str) -> httpx2.Response:
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http_client:
            return await http_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )


class TestEndToEnd:
    async def test_tool_access_and_reach_from_a_jwt(self, jwks_server):
        auth = fetching_jwt(jwks_server, authoriser=RecordingAuthoriser())
        server = jwt_server(auth)
        async with mcp_client(server, make_token(scope="read")) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            result = await client.call_tool("test_read_records", {})
            denied = await client.call_tool("test_write_records", {})
        assert "test_read_records" in names and "test_write_records" not in names
        payload = json.loads(result.content[0].text)
        assert payload == {
            "subject": "alice",
            "client_id": "app",
            "reach": {"tenant": SECRET_TENANT},
        }
        assert denied.is_error or "TOOL_NOT_FOUND" in denied.content[0].text
        assert jwks_server.state.requests == 1

    async def test_a_token_without_reach_runs_no_reach_requiring_tool(
        self, jwks_server
    ):
        server = jwt_server(fetching_jwt(jwks_server))
        async with mcp_client(server, make_token(tenant=None)) as client:
            refused = await client.call_tool("test_read_records", {})
        error = json.loads(refused.content[0].text)["error"]
        assert error["error_code"] == "REACH_REQUIRED"

    async def test_a_token_for_another_resource_gets_401(self, jwks_server):
        server = jwt_server(fetching_jwt(jwks_server))
        resp = await raw_initialise(server, make_token(aud=OTHER_RESOURCE_URL))
        assert resp.status_code == 401
        assert "resource_metadata=" in resp.headers["www-authenticate"]

    async def test_an_unreachable_jwks_gets_401(self, jwks_server):
        jwks_server.state.status = 503
        server = jwt_server(fetching_jwt(jwks_server))
        resp = await raw_initialise(server, make_token())
        assert resp.status_code == 401
