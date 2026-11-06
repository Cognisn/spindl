"""A reference API key authenticator.

An API key is a high-entropy random string that a caller presents in a
header (``X-API-Key`` by default) or, when enabled, as a bearer token.
spindl never keeps the key itself: a store holds an :class:`ApiKeyRecord`
with the key's SHA-256 hex digest, and :class:`ApiKeyAuthenticator` hashes
what the caller presents, looks the digest up, compares the digests in
constant time and refuses expired or revoked keys.

Issuing a key::

    key = generate_api_key("acme")          # show this to the user once
    store.add(ApiKeyRecord(
        key_id="ci-runner",
        key_hash=hash_api_key(key),          # store only the hash
        subject="svc-ci",
        tool_permissions=frozenset({"records:read"}),
        reach={"tenants": ["t1"]},
    ))

Serving with it::

    authenticator = ApiKeyAuthenticator(store, authoriser=ScopeAuthoriser())
    auth = AuthConfig(
        authenticator=authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com"],
        credential_headers=authenticator.credential_headers,
    )

``AuthConfig.credential_headers`` must name the authenticator's header, or
spindl never passes it on; ``authenticator.credential_headers`` gives the
list to use.

The record's ``tool_permissions`` decide tool access (through the
``authoriser``) and its ``reach`` is what the key's calls may touch.
They are separate controls: a key allowed to call a tool is not limited
by that permission in what the tool touches; the tool applies
``self.context.reach``.
"""

import dataclasses
import hashlib
import hmac
import logging
import re
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from spindl.auth._types import Credentials, Identity, ToolAction
from spindl.auth.scopes import Authoriser

if TYPE_CHECKING:
    from spindl.tool import BaseTool

logger = logging.getLogger("spindl.auth")

_KEY_BYTES = 32  # 256 bits from the operating system's CSPRNG
_PREFIX = re.compile(r"[A-Za-z0-9_-]{1,32}")
_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")
# RFC 9110 section 5.6.2: field-name = token
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def generate_api_key(prefix: str) -> str:
    """A new API key of the form ``<prefix>_<random>``.

    The random part is 32 bytes (256 bits) from :mod:`secrets`, URL-safe
    base64 encoded. The prefix (1 to 32 letters, digits, hyphens or
    underscores) only makes a key recognisable, for example to secret
    scanners; it adds no strength. Show the key to its holder once and
    store only :func:`hash_api_key` of it.

    Raises:
        ValueError: The prefix is empty, too long or has other characters.
    """
    if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
        raise ValueError(
            "API key prefix must be 1 to 32 letters, digits, hyphens or underscores"
        )
    return f"{prefix}_{secrets.token_urlsafe(_KEY_BYTES)}"


def hash_api_key(key: str) -> str:
    """The SHA-256 hex digest of the whole key, as stored in a record.

    A single fast hash is appropriate here because API keys from
    :func:`generate_api_key` are high-entropy random strings: there is no
    dictionary to search and 256 bits cannot be brute-forced, so a slow,
    salted password hash would add cost without adding safety. That
    reasoning holds only for random keys. Never use a human-chosen password
    as an API key; passwords need a slow, salted password hash and a
    different scheme.

    Raises:
        TypeError: ``key`` is not a string.
        ValueError: ``key`` is empty.
    """
    if not isinstance(key, str):
        raise TypeError("An API key must be a string")
    if not key:
        raise ValueError("An API key must not be empty")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApiKeyRecord:
    """What a store holds for one API key. Never the key itself.

    Attributes:
        key_id: A stable, non-secret name for the key, used to revoke it
            and in log lines. It becomes ``Identity.client_id``.
        key_hash: :func:`hash_api_key` of the key: 64 hexadecimal digits,
            normalised to lower case. Anything else, including the key
            itself, is refused.
        subject: Who holds the key (a user or service principal); becomes
            ``Identity.subject``.
        tool_permissions: The tool permissions the key grants.
        reach: What the key's calls may touch, opaque to spindl and handed
            to tools as ``self.context.reach``. ``None`` means none, and
            spindl then refuses every tool that requires reach.
        expires_at: When the key expires, in seconds since the epoch, or
            ``None`` for no expiry.
        revoked: Whether the key has been revoked.

    ``repr`` does not show ``key_hash``.
    """

    key_id: str
    key_hash: str = field(repr=False)
    subject: str
    tool_permissions: frozenset[str] = frozenset()
    reach: object = None
    expires_at: Optional[float] = None
    revoked: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not self.key_id:
            raise ValueError("ApiKeyRecord.key_id must be a non-empty string")
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError("ApiKeyRecord.subject must be a non-empty string")
        if not isinstance(self.key_hash, str) or not _SHA256_HEX.fullmatch(
            self.key_hash
        ):
            raise ValueError(
                "ApiKeyRecord.key_hash must be the SHA-256 hex digest of the key "
                "(hash_api_key), never the key itself"
            )
        object.__setattr__(self, "key_hash", self.key_hash.lower())
        permissions: Iterable[str] = self.tool_permissions
        if isinstance(permissions, str):
            raise TypeError("ApiKeyRecord.tool_permissions must be a set of names")
        object.__setattr__(self, "tool_permissions", frozenset(permissions))


@runtime_checkable
class ApiKeyStore(Protocol):
    """Where API key records live: a database, a secrets service or memory.

    ``lookup`` returns the record whose ``key_hash`` is the given digest,
    or ``None``. The authenticator compares the digests again in constant
    time, so a store whose lookup is looser than an exact match cannot
    let a wrong key in.
    """

    async def lookup(self, key_hash: str) -> Optional[ApiKeyRecord]: ...


class InMemoryApiKeyStore:
    """An :class:`ApiKeyStore` in a dictionary, for tests and simple servers.

    Records are lost when the process ends. Each ``key_hash`` and each
    ``key_id`` may appear only once.
    """

    def __init__(self, records: Iterable[ApiKeyRecord] = ()) -> None:
        self._by_hash: dict[str, ApiKeyRecord] = {}
        self._hash_by_id: dict[str, str] = {}
        for record in records:
            self.add(record)

    def add(self, record: ApiKeyRecord) -> None:
        """Store ``record``.

        Raises:
            ValueError: A record with the same hash or key id is stored.
        """
        if record.key_hash in self._by_hash:
            raise ValueError("A record with this key hash is already stored")
        if record.key_id in self._hash_by_id:
            raise ValueError(f"A record with key id '{record.key_id}' is stored")
        self._by_hash[record.key_hash] = record
        self._hash_by_id[record.key_id] = record.key_hash

    def revoke(self, key_id: str) -> None:
        """Mark the record with ``key_id`` revoked.

        Raises:
            KeyError: No record has that key id.
        """
        key_hash = self._hash_by_id[key_id]
        self._by_hash[key_hash] = dataclasses.replace(
            self._by_hash[key_hash], revoked=True
        )

    async def lookup(self, key_hash: str) -> Optional[ApiKeyRecord]:
        return self._by_hash.get(key_hash)

    def __len__(self) -> int:
        return len(self._by_hash)

    def __repr__(self) -> str:
        return f"InMemoryApiKeyStore({len(self)} records)"


class ApiKeyAuthenticator:
    """An :class:`~spindl.auth.Authenticator` for API keys.

    Args:
        store: Where the key records are looked up.
        header: The request header carrying the key, matched without
            regard to case. ``AuthConfig.credential_headers`` must name it
            (use :attr:`credential_headers`). ``Authorization`` is refused;
            use ``accept_bearer`` for that.
        accept_bearer: Also accept the key as ``Authorization: Bearer
            <key>``. Off by default. When a request carries both, the
            header is used.
        authoriser: Decides tool access, for example a
            :class:`~spindl.auth.scopes.ScopeAuthoriser`. Without one,
            **every authenticated caller may list and call every tool**;
            spindl still checks ``AuthConfig.required_scopes`` and reach.

    ``authenticate`` hashes the presented key, looks the digest up,
    compares the digests with :func:`hmac.compare_digest`, refuses expired
    and revoked keys, and returns an :class:`~spindl.auth.Identity` with the
    record's subject, key id (as ``client_id``), tool permissions, reach and
    expiry. It never keeps, logs or shows the key; refusals are logged at
    debug level with the key id when there is one.
    """

    def __init__(
        self,
        store: ApiKeyStore,
        header: str = "x-api-key",
        accept_bearer: bool = False,
        authoriser: Optional[Authoriser] = None,
    ) -> None:
        if not isinstance(header, str) or not _HEADER_NAME.fullmatch(header):
            raise ValueError("The API key header must be a valid header name")
        if header.lower() == "authorization":
            raise ValueError(
                "The API key header cannot be Authorization; use accept_bearer"
            )
        self.store = store
        self.header = header.lower()
        self.accept_bearer = accept_bearer
        self.authoriser = authoriser

    @property
    def credential_headers(self) -> list[str]:
        """The header names to give ``AuthConfig.credential_headers``."""
        return [self.header]

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        key = credentials.headers.get(self.header)
        if key is None and self.accept_bearer:
            key = credentials.bearer_token
        if not key:
            return None
        presented = hash_api_key(key)
        record = await self.store.lookup(presented)
        if record is None:
            logger.debug("API key refused: no matching key")
            return None
        if not hmac.compare_digest(record.key_hash, presented):
            logger.debug("API key refused: the store returned another key")
            return None
        if record.revoked:
            logger.debug("API key refused: key '%s' is revoked", record.key_id)
            return None
        if record.expires_at is not None and record.expires_at <= time.time():
            logger.debug("API key refused: key '%s' has expired", record.key_id)
            return None
        return Identity(
            subject=record.subject,
            client_id=record.key_id,
            tool_permissions=record.tool_permissions,
            reach=record.reach,
            expires_at=record.expires_at,
        )

    async def authorise(
        self, identity: Identity, tool: "BaseTool", action: ToolAction
    ) -> bool:
        if self.authoriser is None:
            return True
        return await self.authoriser.authorise(identity, tool, action)

    def __repr__(self) -> str:
        return (
            f"ApiKeyAuthenticator(header={self.header!r}, "
            f"accept_bearer={self.accept_bearer!r}, authoriser={self.authoriser!r})"
        )
