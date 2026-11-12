"""Tests for the reference API key authenticator (spindl.auth.api_key).

Keys are synthetic, generated here with ``generate_api_key``. The tests pin
the key helpers, the record and store, every refusal the authenticator
makes (wrong, expired and revoked keys, the header it reads and the bearer
form), that the plaintext key is never kept, logged or shown, and the
authenticator working inside a real ``MCPServer`` over streamable HTTP and
through the WSGI bridge.
"""

import base64
import dataclasses
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
import pytest
from flask import Flask
from pydantic import BaseModel

import spindl.auth.api_key as api_key_module
from spindl.auth import AuthConfig, Authenticator, Credentials, Identity, ToolAction
from spindl.auth.api_key import (
    ApiKeyAuthenticator,
    ApiKeyRecord,
    ApiKeyStore,
    InMemoryApiKeyStore,
    generate_api_key,
    hash_api_key,
)
from spindl.auth.scopes import ScopeAuthoriser
from spindl.server import MCPServer
from spindl.tool import BaseTool
from spindl.wsgi import init_app

RESOURCE_URL = "http://testserver/mcp"
WSGI_RESOURCE_URL = "http://localhost/mcp"
AUTH_SERVER_URL = "https://auth.example.com"
REACH = {"tenants": ["tenant-a"]}
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "example-client", "version": "1"},
}
MODERN_HEADERS = {**JSON_HEADERS, "MCP-Protocol-Version": "2026-07-28"}


def issue(
    store: InMemoryApiKeyStore,
    subject: str = "alice",
    permissions: tuple[str, ...] = ("read",),
    reach: object = REACH,
    **extra: Any,
) -> str:
    """Generate a synthetic key, store its record and return the plaintext."""
    key = generate_api_key("test")
    store.add(
        ApiKeyRecord(
            key_id=f"{subject}-{len(store)}",
            key_hash=hash_api_key(key),
            subject=subject,
            tool_permissions=frozenset(permissions),
            reach=reach,
            **extra,
        )
    )
    return key


def header_credentials(key: str, name: str = "x-api-key") -> Credentials:
    return Credentials(headers={name: key})


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


class TestKeyHelpers:
    def test_a_generated_key_is_the_prefix_and_256_random_bits(self):
        key = generate_api_key("sk")
        assert key.startswith("sk_")
        random_part = key[len("sk_") :]
        raw = base64.urlsafe_b64decode(random_part + "=" * (-len(random_part) % 4))
        assert len(raw) >= 32

    def test_the_random_part_comes_from_secrets(self, monkeypatch):
        requested: list[int] = []

        def fake_token_urlsafe(nbytes: int) -> str:
            requested.append(nbytes)
            return "R" * 43

        monkeypatch.setattr(api_key_module.secrets, "token_urlsafe", fake_token_urlsafe)
        assert generate_api_key("sk") == "sk_" + "R" * 43
        assert requested and requested[0] >= 32

    def test_generated_keys_differ(self):
        assert len({generate_api_key("sk") for _ in range(200)}) == 200

    @pytest.mark.parametrize("prefix", ["sk_live", "svc-key", "A1"])
    def test_prefixes_of_letters_digits_hyphens_and_underscores(self, prefix):
        assert generate_api_key(prefix).startswith(prefix + "_")

    @pytest.mark.parametrize("prefix", ["", "has space", "a/b", "x" * 33, 7, None])
    def test_an_invalid_prefix_is_refused(self, prefix):
        with pytest.raises(ValueError):
            generate_api_key(prefix)

    def test_hash_is_the_sha256_hex_of_the_whole_key(self):
        key = generate_api_key("sk")
        expected = hashlib.sha256(key.encode("utf-8")).hexdigest()
        assert hash_api_key(key) == expected
        assert len(hash_api_key(key)) == 64

    @pytest.mark.parametrize("bad", ["", None, b"bytes-key"])
    def test_hashing_refuses_an_empty_or_non_text_key(self, bad):
        with pytest.raises((TypeError, ValueError)) as excinfo:
            hash_api_key(bad)
        assert "bytes-key" not in str(excinfo.value)

    def test_the_docstrings_say_a_fast_hash_fits_random_keys_not_passwords(self):
        doc = " ".join((hash_api_key.__doc__ or "").split()).lower()
        assert "high-entropy" in doc
        assert "password" in doc


# ---------------------------------------------------------------------------
# Record and store
# ---------------------------------------------------------------------------


class TestRecord:
    def make(self, **overrides: Any) -> ApiKeyRecord:
        values: dict[str, Any] = {
            "key_id": "k1",
            "key_hash": hash_api_key(generate_api_key("sk")),
            "subject": "alice",
        }
        values.update(overrides)
        return ApiKeyRecord(**values)

    def test_defaults_and_frozen(self):
        record = self.make()
        assert record.tool_permissions == frozenset()
        assert record.reach is None
        assert record.expires_at is None
        assert record.revoked is False
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.revoked = True  # type: ignore[misc]

    def test_permissions_are_coerced_to_a_frozenset_and_a_bare_string_refused(self):
        assert self.make(tool_permissions=["a", "b"]).tool_permissions == frozenset(
            {"a", "b"}
        )
        with pytest.raises(TypeError):
            self.make(tool_permissions="read")

    def test_a_plaintext_key_is_refused_as_the_hash_without_echoing_it(self):
        key = generate_api_key("sk")
        with pytest.raises(ValueError) as excinfo:
            self.make(key_hash=key)
        assert key not in str(excinfo.value)
        assert key not in repr(excinfo.value)

    def test_an_upper_case_hash_is_normalised(self):
        digest = hash_api_key(generate_api_key("sk"))
        assert self.make(key_hash=digest.upper()).key_hash == digest

    @pytest.mark.parametrize("field", ["key_id", "subject"])
    def test_key_id_and_subject_are_required(self, field):
        with pytest.raises(ValueError):
            self.make(**{field: ""})

    def test_repr_shows_neither_key_nor_hash(self):
        key = generate_api_key("sk")
        record = self.make(key_hash=hash_api_key(key))
        assert key not in repr(record)
        assert record.key_hash not in repr(record)


class TestInMemoryStore:
    async def test_lookup_by_hash(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        record = await store.lookup(hash_api_key(key))
        assert record is not None and record.subject == "alice"
        assert await store.lookup(hash_api_key(generate_api_key("test"))) is None

    async def test_records_given_at_construction(self):
        key = generate_api_key("sk")
        record = ApiKeyRecord(key_id="k1", key_hash=hash_api_key(key), subject="s")
        store = InMemoryApiKeyStore([record])
        assert await store.lookup(hash_api_key(key)) is record
        assert len(store) == 1

    def test_a_duplicate_hash_or_key_id_is_refused(self):
        store = InMemoryApiKeyStore()
        digest = hash_api_key(generate_api_key("sk"))
        store.add(ApiKeyRecord(key_id="k1", key_hash=digest, subject="s"))
        with pytest.raises(ValueError):
            store.add(ApiKeyRecord(key_id="k2", key_hash=digest, subject="s"))
        with pytest.raises(ValueError):
            store.add(
                ApiKeyRecord(
                    key_id="k1",
                    key_hash=hash_api_key(generate_api_key("sk")),
                    subject="s",
                )
            )

    async def test_revoke_marks_the_record_revoked(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        record = await store.lookup(hash_api_key(key))
        assert record is not None
        store.revoke(record.key_id)
        revoked = await store.lookup(hash_api_key(key))
        assert revoked is not None and revoked.revoked is True
        with pytest.raises(KeyError):
            store.revoke("no-such-key")

    def test_is_an_api_key_store(self):
        assert isinstance(InMemoryApiKeyStore(), ApiKeyStore)


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


class MisbehavingStore:
    """A store that answers every lookup with one record, whatever the hash.

    Stands in for a backing store whose lookup is looser than an exact match
    (a prefix index, a case-folding collation); the authenticator must not
    trust it.
    """

    def __init__(self, record: ApiKeyRecord) -> None:
        self.record = record

    async def lookup(self, key_hash: str) -> Optional[ApiKeyRecord]:
        return self.record


class RaisingStore:
    async def lookup(self, key_hash: str) -> Optional[ApiKeyRecord]:
        raise RuntimeError("store unavailable")


class TestAuthenticate:
    async def test_a_valid_key_gives_the_records_identity(self):
        store = InMemoryApiKeyStore()
        expires = time.time() + 3600
        key = issue(store, permissions=("read", "write"), expires_at=expires)
        identity = await ApiKeyAuthenticator(store).authenticate(
            header_credentials(key)
        )
        assert identity == Identity(
            subject="alice",
            client_id="alice-0",
            tool_permissions=frozenset({"read", "write"}),
            reach=REACH,
            expires_at=expires,
        )

    def test_is_an_authenticator(self):
        assert isinstance(ApiKeyAuthenticator(InMemoryApiKeyStore()), Authenticator)

    async def test_a_wrong_key_is_refused(self):
        store = InMemoryApiKeyStore()
        issue(store)
        wrong = generate_api_key("test")
        assert (
            await ApiKeyAuthenticator(store).authenticate(header_credentials(wrong))
            is None
        )

    async def test_no_key_is_refused(self):
        store = InMemoryApiKeyStore()
        issue(store)
        authenticator = ApiKeyAuthenticator(store)
        assert await authenticator.authenticate(Credentials()) is None
        assert await authenticator.authenticate(header_credentials("")) is None

    async def test_a_record_whose_hash_does_not_match_is_refused(self):
        key = generate_api_key("test")
        record = ApiKeyRecord(key_id="k1", key_hash=hash_api_key(key), subject="s")
        authenticator = ApiKeyAuthenticator(MisbehavingStore(record))
        wrong = generate_api_key("test")
        assert await authenticator.authenticate(header_credentials(wrong)) is None
        assert await authenticator.authenticate(header_credentials(key)) is not None

    async def test_hashes_are_compared_with_hmac_compare_digest(self, monkeypatch):
        compared: list[tuple[Any, Any]] = []
        real = hmac.compare_digest

        def spy(a: Any, b: Any) -> bool:
            compared.append((a, b))
            return real(a, b)

        monkeypatch.setattr(api_key_module.hmac, "compare_digest", spy)
        store = InMemoryApiKeyStore()
        key = issue(store)
        assert await ApiKeyAuthenticator(store).authenticate(header_credentials(key))
        digest = hash_api_key(key)
        assert [sorted(map(str, pair)) for pair in compared] == [[digest, digest]]

    async def test_an_expired_key_is_refused(self):
        store = InMemoryApiKeyStore()
        key = issue(store, expires_at=time.time() - 1)
        assert (
            await ApiKeyAuthenticator(store).authenticate(header_credentials(key))
            is None
        )

    async def test_a_key_expiring_later_is_accepted(self):
        store = InMemoryApiKeyStore()
        key = issue(store, expires_at=time.time() + 60)
        assert await ApiKeyAuthenticator(store).authenticate(header_credentials(key))

    async def test_a_revoked_key_is_refused(self):
        store = InMemoryApiKeyStore()
        key = issue(store, revoked=True)
        assert (
            await ApiKeyAuthenticator(store).authenticate(header_credentials(key))
            is None
        )

    async def test_revoking_through_the_store_refuses_the_key(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        authenticator = ApiKeyAuthenticator(store)
        assert await authenticator.authenticate(header_credentials(key))
        store.revoke("alice-0")
        assert await authenticator.authenticate(header_credentials(key)) is None


class TestHeaderAndBearer:
    async def test_the_configured_header_is_read_and_the_default_is_not(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        authenticator = ApiKeyAuthenticator(store, header="X-Service-Key")
        assert await authenticator.authenticate(
            header_credentials(key, "x-service-key")
        )
        assert await authenticator.authenticate(header_credentials(key)) is None

    def test_credential_headers_names_the_header_for_auth_config(self):
        authenticator = ApiKeyAuthenticator(
            InMemoryApiKeyStore(), header="X-Service-Key"
        )
        assert authenticator.header == "x-service-key"
        assert authenticator.credential_headers == ["x-service-key"]

    @pytest.mark.parametrize("header", ["", "authorization", "Authorization", "a b"])
    def test_an_unusable_header_name_is_refused(self, header):
        with pytest.raises(ValueError):
            ApiKeyAuthenticator(InMemoryApiKeyStore(), header=header)

    async def test_the_bearer_form_is_refused_by_default(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        authenticator = ApiKeyAuthenticator(store)
        assert await authenticator.authenticate(Credentials(bearer_token=key)) is None

    async def test_the_bearer_form_is_accepted_when_enabled(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        authenticator = ApiKeyAuthenticator(store, accept_bearer=True)
        assert await authenticator.authenticate(Credentials(bearer_token=key))
        assert await authenticator.authenticate(header_credentials(key))

    async def test_the_header_takes_precedence_over_the_bearer_token(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        wrong = generate_api_key("test")
        authenticator = ApiKeyAuthenticator(store, accept_bearer=True)
        both = Credentials(bearer_token=key, headers={"x-api-key": wrong})
        assert await authenticator.authenticate(both) is None


class TestPlaintextIsNeverKept:
    async def test_no_log_record_carries_the_key(self, caplog):
        store = InMemoryApiKeyStore()
        good = issue(store)
        revoked = issue(store, subject="bob", revoked=True)
        expired = issue(store, subject="carol", expires_at=time.time() - 1)
        wrong = generate_api_key("test")
        authenticator = ApiKeyAuthenticator(store, accept_bearer=True)
        with caplog.at_level(logging.DEBUG):
            for key in (good, revoked, expired, wrong):
                await authenticator.authenticate(header_credentials(key))
                await authenticator.authenticate(Credentials(bearer_token=key))
        assert caplog.records, "the refusals are expected to be logged"
        for key in (good, revoked, expired, wrong):
            assert key not in caplog.text
            assert hash_api_key(key) not in caplog.text

    async def test_no_repr_carries_the_key(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        authenticator = ApiKeyAuthenticator(store, authoriser=ScopeAuthoriser())
        identity = await authenticator.authenticate(header_credentials(key))
        for obj in (authenticator, store, identity, header_credentials(key)):
            assert key not in repr(obj)
            assert hash_api_key(key) not in repr(obj)

    async def test_the_authenticator_keeps_no_copy_of_the_key(self):
        store = InMemoryApiKeyStore()
        key = issue(store)
        authenticator = ApiKeyAuthenticator(store)
        await authenticator.authenticate(header_credentials(key))
        assert key not in repr(vars(authenticator))
        assert key not in repr(vars(store))

    async def test_a_store_failure_carries_no_key(self):
        key = generate_api_key("test")
        authenticator = ApiKeyAuthenticator(RaisingStore())
        with pytest.raises(RuntimeError) as excinfo:
            await authenticator.authenticate(header_credentials(key))
        assert key not in str(excinfo.value)
        assert key not in repr(excinfo.value.args)


# ---------------------------------------------------------------------------
# authorise
# ---------------------------------------------------------------------------


class ReadTool(BaseTool):
    name = "read_records"
    description = "Read the records the caller can reach"
    category = "records"
    read_only = True
    permissions = ["read"]

    class InputModel(BaseModel):
        limit: int = 10

    async def execute(self, **params: Any) -> dict[str, Any]:
        context = self.context
        assert context is not None and context.identity is not None
        return {"subject": context.identity.subject, "reach": context.reach}


class WriteTool(BaseTool):
    name = "write_records"
    description = "Write records"
    category = "records"
    destructive = True
    permissions = ["write"]

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"written": True}


class PingTool(BaseTool):
    name = "ping"
    description = "Touches nothing, so needs no reach"
    category = "general"
    read_only = True
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"pong": True}


class RecordingAuthoriser:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.calls: list[tuple[Identity, BaseTool, ToolAction]] = []

    async def authorise(
        self, identity: Optional[Identity], tool: BaseTool, action: ToolAction
    ) -> bool:
        assert identity is not None
        self.calls.append((identity, tool, action))
        return self.answer


class TestAuthorise:
    async def test_without_an_authoriser_every_authenticated_caller_is_allowed(self):
        authenticator = ApiKeyAuthenticator(InMemoryApiKeyStore())
        caller = Identity(subject="alice")
        assert await authenticator.authorise(caller, WriteTool(), "call") is True
        assert await authenticator.authorise(caller, ReadTool(), "list") is True

    @pytest.mark.parametrize("answer", [True, False])
    async def test_the_given_authoriser_decides(self, answer):
        authoriser = RecordingAuthoriser(answer)
        authenticator = ApiKeyAuthenticator(
            InMemoryApiKeyStore(), authoriser=authoriser
        )
        caller = Identity(subject="alice")
        tool = WriteTool()
        assert await authenticator.authorise(caller, tool, "list") is answer
        assert authoriser.calls == [(caller, tool, "list")]

    async def test_with_the_scope_authoriser(self):
        authenticator = ApiKeyAuthenticator(
            InMemoryApiKeyStore(), authoriser=ScopeAuthoriser()
        )
        reader = Identity(subject="alice", tool_permissions=frozenset({"read"}))
        assert await authenticator.authorise(reader, ReadTool(), "call") is True
        assert await authenticator.authorise(reader, WriteTool(), "call") is False
        assert await authenticator.authorise(reader, PingTool(), "call") is True


# ---------------------------------------------------------------------------
# Through a real MCPServer over streamable HTTP
# ---------------------------------------------------------------------------


def make_server(
    authenticator: ApiKeyAuthenticator,
    *,
    resource_url: str = RESOURCE_URL,
    denial_mode: str = "hide",
) -> MCPServer:
    server = MCPServer(
        prefix="test",
        auth=AuthConfig(
            authenticator=authenticator,
            resource_server_url=resource_url,
            authorization_servers=[AUTH_SERVER_URL],
            credential_headers=authenticator.credential_headers,
            denial_mode=denial_mode,  # type: ignore[arg-type]
        ),
    )
    for tool in (ReadTool(), WriteTool(), PingTool()):
        server.register(tool)
    return server


@asynccontextmanager
async def http_client(server: MCPServer) -> AsyncIterator[httpx.AsyncClient]:
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def tool_text(body: dict[str, Any]) -> Any:
    return json.loads(body["result"]["content"][0]["text"])


class Fixture:
    """A store with a reader, an editor, a key without reach and bad keys."""

    def __init__(self) -> None:
        self.store = InMemoryApiKeyStore()
        self.reader = issue(self.store, "reader", ("read",))
        self.editor = issue(self.store, "editor", ("read", "write"))
        self.no_reach = issue(self.store, "nobody", ("read",), reach=None)
        self.revoked = issue(self.store, "gone", ("read",), revoked=True)
        self.expired = issue(self.store, "late", ("read",), expires_at=time.time() - 1)
        self.wrong = generate_api_key("test")


@pytest.fixture
def keys() -> Fixture:
    return Fixture()


class TestThroughStreamableHttp:
    async def post(
        self, server: MCPServer, body: dict[str, Any], **headers: str
    ) -> httpx.Response:
        async with http_client(server) as client:
            return await client.post(
                "/mcp", json=body, headers={**JSON_HEADERS, **headers}
            )

    async def call(
        self, server: MCPServer, name: str, key: str, header: str = "X-API-Key"
    ) -> httpx.Response:
        (resp,) = await self.calls(server, (name, key, header))
        return resp

    async def calls(
        self, server: MCPServer, *requests: tuple[str, str, str]
    ) -> list[httpx.Response]:
        """Several tools/call requests to one running server."""
        responses = []
        async with http_client(server) as client:
            for name, key, header in requests:
                body = rpc("tools/call", {"name": name, "arguments": {}})
                responses.append(
                    await client.post(
                        "/mcp", json=body, headers={**JSON_HEADERS, header: key}
                    )
                )
        return responses

    @pytest.mark.parametrize("which", ["wrong", "revoked", "expired"])
    async def test_a_refused_key_gets_401(self, keys, which):
        server = make_server(ApiKeyAuthenticator(keys.store))
        resp = await self.call(server, "test_ping", getattr(keys, which))
        assert resp.status_code == 401
        assert "resource_metadata=" in resp.headers["WWW-Authenticate"]

    async def test_no_key_gets_401(self, keys):
        server = make_server(ApiKeyAuthenticator(keys.store))
        resp = await self.post(server, rpc("tools/list"))
        assert resp.status_code == 401

    async def test_a_valid_key_calls_a_tool_with_its_reach(self, keys):
        server = make_server(ApiKeyAuthenticator(keys.store))
        resp = await self.call(server, "test_read_records", keys.reader)
        assert resp.status_code == 200
        assert tool_text(resp.json()) == {"subject": "reader", "reach": REACH}

    async def test_a_key_without_reach_runs_only_tools_needing_none(self, keys):
        server = make_server(ApiKeyAuthenticator(keys.store))
        refused, allowed = await self.calls(
            server,
            ("test_read_records", keys.no_reach, "X-API-Key"),
            ("test_ping", keys.no_reach, "X-API-Key"),
        )
        assert tool_text(refused.json())["error"]["error_code"] == "REACH_REQUIRED"
        assert tool_text(allowed.json()) == {"pong": True}

    async def test_scope_authoriser_filters_tools_list(self, keys):
        server = make_server(
            ApiKeyAuthenticator(keys.store, authoriser=ScopeAuthoriser())
        )
        async with http_client(server) as client:
            reader = await client.post(
                "/mcp",
                json=rpc("tools/list"),
                headers={**JSON_HEADERS, "X-API-Key": keys.reader},
            )
            editor = await client.post(
                "/mcp",
                json=rpc("tools/list"),
                headers={**JSON_HEADERS, "X-API-Key": keys.editor},
            )
        reader_names = {t["name"] for t in reader.json()["result"]["tools"]}
        editor_names = {t["name"] for t in editor.json()["result"]["tools"]}
        assert {"test_read_records", "test_ping"} <= reader_names
        assert "test_write_records" not in reader_names
        assert "test_write_records" in editor_names

    async def test_scope_authoriser_answers_a_denied_call_as_unknown(self, keys):
        server = make_server(
            ApiKeyAuthenticator(keys.store, authoriser=ScopeAuthoriser())
        )
        denied, allowed = await self.calls(
            server,
            ("test_write_records", keys.reader, "X-API-Key"),
            ("test_write_records", keys.editor, "X-API-Key"),
        )
        assert tool_text(denied.json())["error"]["error_code"] == "TOOL_NOT_FOUND"
        assert tool_text(allowed.json()) == {"written": True}

    async def test_scope_authoriser_with_step_up_answers_403(self, keys):
        server = make_server(
            ApiKeyAuthenticator(keys.store, authoriser=ScopeAuthoriser()),
            denial_mode="step_up",
        )
        resp = await self.call(server, "test_write_records", keys.reader)
        assert resp.status_code == 403
        assert 'scope="write"' in resp.headers["WWW-Authenticate"]

    async def test_a_custom_header_is_honoured_end_to_end(self, keys):
        server = make_server(ApiKeyAuthenticator(keys.store, header="X-Service-Key"))
        custom, default = await self.calls(
            server,
            ("test_ping", keys.reader, "X-Service-Key"),
            ("test_ping", keys.reader, "X-API-Key"),
        )
        assert custom.status_code == 200
        assert default.status_code == 401

    async def test_the_bearer_form_only_when_enabled(self, keys):
        refusing = make_server(ApiKeyAuthenticator(keys.store))
        accepting = make_server(ApiKeyAuthenticator(keys.store, accept_bearer=True))
        auth = f"Bearer {keys.reader}"
        refused = await self.call(refusing, "test_ping", auth, "Authorization")
        accepted = await self.call(accepting, "test_ping", auth, "Authorization")
        assert refused.status_code == 401
        assert accepted.status_code == 200
        assert tool_text(accepted.json()) == {"pong": True}


# ---------------------------------------------------------------------------
# Through the WSGI bridge
# ---------------------------------------------------------------------------


def wsgi_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {**(params or {}), "_meta": dict(ENVELOPE)},
    }


def wsgi_headers(method: str, name: str | None = None, **extra: str) -> dict[str, str]:
    headers = {**MODERN_HEADERS, "Mcp-Method": method, **extra}
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


@pytest.fixture
def wsgi_server(keys: Fixture) -> Iterator[MCPServer]:
    yield from _wsgi_server(keys, "hide")


@pytest.fixture
def wsgi_step_up_server(keys: Fixture) -> Iterator[MCPServer]:
    yield from _wsgi_server(keys, "step_up")


def _wsgi_server(keys: Fixture, denial_mode: str) -> Iterator[MCPServer]:
    server = make_server(
        ApiKeyAuthenticator(keys.store, authoriser=ScopeAuthoriser()),
        resource_url=WSGI_RESOURCE_URL,
        denial_mode=denial_mode,
    )
    yield server
    bridge = getattr(server, "_wsgi_bridge", None)
    if bridge is not None:
        bridge.close()


def flask_client(server: MCPServer) -> Any:
    app = Flask("wsgi-host")
    init_app(app, server)
    return app.test_client()


def wsgi_call(client: Any, name: str, key: str) -> Any:
    return client.post(
        "/mcp",
        json=wsgi_rpc("tools/call", {"name": name, "arguments": {}}),
        headers=wsgi_headers("tools/call", name, **{"X-API-Key": key}),
    )


class TestThroughTheWsgiBridge:
    @pytest.mark.parametrize("which", ["wrong", "revoked", "expired"])
    def test_a_refused_key_gets_401(self, wsgi_server, keys, which):
        resp = wsgi_call(flask_client(wsgi_server), "test_ping", getattr(keys, which))
        assert resp.status_code == 401
        assert "resource_metadata=" in resp.headers["WWW-Authenticate"]

    def test_a_valid_key_calls_a_tool_with_its_reach(self, wsgi_server, keys):
        resp = wsgi_call(flask_client(wsgi_server), "test_read_records", keys.reader)
        assert resp.status_code == 200
        assert tool_text(resp.get_json()) == {"subject": "reader", "reach": REACH}

    def test_tools_list_is_filtered_and_a_denied_call_is_unknown(
        self, wsgi_server, keys
    ):
        client = flask_client(wsgi_server)
        listed = client.post(
            "/mcp",
            json=wsgi_rpc("tools/list"),
            headers=wsgi_headers("tools/list", **{"X-API-Key": keys.reader}),
        )
        names = {t["name"] for t in listed.get_json()["result"]["tools"]}
        denied = wsgi_call(client, "test_write_records", keys.reader)
        assert "test_write_records" not in names and "test_read_records" in names
        assert tool_text(denied.get_json())["error"]["error_code"] == "TOOL_NOT_FOUND"

    def test_step_up_answers_403_naming_the_missing_permission(
        self, wsgi_step_up_server, keys
    ):
        client = flask_client(wsgi_step_up_server)
        resp = wsgi_call(client, "test_write_records", keys.reader)
        assert resp.status_code == 403
        assert 'scope="write"' in resp.headers["WWW-Authenticate"]
