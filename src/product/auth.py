"""Minimal API authentication and RBAC for AuditLens foundation."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

import orjson


class Role(str, Enum):
    VIEWER = "viewer"
    RESPONDER = "responder"
    EXPORTER = "exporter"
    ADMIN = "admin"


@dataclass(frozen=True)
class AccessToken:
    token: str
    actor_id: str
    role: Role
    organizations: tuple[str, ...] = ("*",)
    environments: tuple[str, ...] = ("*",)
    clusters: tuple[str, ...] = ("*",)

    def can_export(self) -> bool:
        return self.role in {Role.EXPORTER, Role.ADMIN}

    def can_view(self) -> bool:
        return self.role in {Role.VIEWER, Role.RESPONDER, Role.EXPORTER, Role.ADMIN}

    def scope_allows(self, organization_id: Optional[str], environment_id: Optional[str], cluster_id: Optional[str]) -> bool:
        return (
            _scope_match(self.organizations, organization_id) and
            _scope_match(self.environments, environment_id) and
            _scope_match(self.clusters, cluster_id)
        )


def _scope_match(allowed: tuple[str, ...], value: Optional[str]) -> bool:
    if "*" in allowed:
        return True
    if value is None:
        return False
    return value in allowed


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    tokens: Dict[str, AccessToken]
    token_file: Optional[str] = None
    source_json: Optional[str] = None
    token_file_mtime: Optional[float] = None

    @classmethod
    def from_env(cls) -> "AuthConfig":
        enabled = os.getenv("API_AUTH_ENABLED", "true").lower() == "true"
        if not enabled:
            return cls(enabled=False, tokens={})

        raw = os.getenv("API_AUTH_TOKENS_JSON")
        token_file = os.getenv("API_AUTH_TOKEN_FILE")
        token_file_mtime = None
        if not raw and token_file and os.path.exists(token_file):
            with open(token_file, "rb") as handle:
                raw = handle.read().decode("utf-8")
            token_file_mtime = os.path.getmtime(token_file)

        if raw:
            return cls.from_json(raw, token_file=token_file, token_file_mtime=token_file_mtime)

        if not raw:
            raise ValueError("API auth is enabled but no API_AUTH_TOKENS_JSON or API_AUTH_TOKEN_FILE was provided")

        return cls(enabled=True, tokens={}, token_file=token_file, source_json=raw, token_file_mtime=token_file_mtime)

    @classmethod
    def from_json(cls, raw: str, token_file: Optional[str] = None, token_file_mtime: Optional[float] = None) -> "AuthConfig":
        payload = orjson.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("API auth token config must be a JSON list")
        tokens: Dict[str, AccessToken] = {}
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each API auth token entry must be an object")
            role = Role(item["role"])
            token_value = str(item["token"]).strip()
            actor_id = str(item.get("actor_id") or item.get("name") or role.value).strip()
            if not token_value:
                raise ValueError("API auth token must not be empty")
            if not actor_id:
                raise ValueError("API auth actor_id must not be empty")
            organizations = tuple(item.get("organizations", ["*"]))
            environments = tuple(item.get("environments", ["*"]))
            clusters = tuple(item.get("clusters", ["*"]))
            if any(not str(v).strip() for v in organizations + environments + clusters):
                raise ValueError("API auth scopes must not contain empty values")
            token = AccessToken(
                token=token_value,
                actor_id=actor_id,
                role=role,
                organizations=organizations,
                environments=environments,
                clusters=clusters,
            )
            if token.token in tokens:
                raise ValueError("Duplicate API auth token configured")
            tokens[token.token] = token
        return cls(
            enabled=True,
            tokens=tokens,
            token_file=token_file,
            source_json=raw,
            token_file_mtime=token_file_mtime,
        )


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    status_code: int
    error: Optional[str] = None
    actor: Optional[AccessToken] = None


class Authenticator:
    def __init__(self, config: AuthConfig):
        self.config = config

    def authenticate(self, headers) -> AuthResult:
        self.refresh_if_needed()
        if not self.config.enabled:
            return AuthResult(ok=True, status_code=200, actor=AccessToken(
                token="anonymous-dev",
                actor_id="anonymous-dev",
                role=Role.VIEWER,
            ))

        token = self._extract_token(headers)
        if not token:
            return AuthResult(ok=False, status_code=401, error="missing credentials")

        actor = self._match_token(token)
        if not actor:
            return AuthResult(ok=False, status_code=401, error="invalid credentials")

        return AuthResult(ok=True, status_code=200, actor=actor)

    def require_view(self, actor: AccessToken) -> AuthResult:
        if actor.can_view():
            return AuthResult(ok=True, status_code=200, actor=actor)
        return AuthResult(ok=False, status_code=403, error="viewer access required", actor=actor)

    def require_export(self, actor: AccessToken) -> AuthResult:
        if actor.can_export():
            return AuthResult(ok=True, status_code=200, actor=actor)
        return AuthResult(ok=False, status_code=403, error="export permission required", actor=actor)

    def refresh_if_needed(self) -> None:
        if not self.config.enabled or not self.config.token_file:
            return
        token_file = self.config.token_file
        if not os.path.exists(token_file):
            return
        current_mtime = os.path.getmtime(token_file)
        if self.config.token_file_mtime is not None and current_mtime <= self.config.token_file_mtime:
            return
        with open(token_file, "rb") as handle:
            raw = handle.read().decode("utf-8")
        self.config = AuthConfig.from_json(raw, token_file=token_file, token_file_mtime=current_mtime)

    @staticmethod
    def _extract_token(headers) -> Optional[str]:
        auth_header = headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ", 1)[1].strip()
        api_key = headers.get("X-API-Key")
        if api_key:
            return api_key.strip()
        return None

    def _match_token(self, provided_token: str) -> Optional[AccessToken]:
        if isinstance(provided_token, bytes):
            provided_bytes = provided_token
        elif isinstance(provided_token, str):
            provided_bytes = provided_token.encode()
        else:
            return None
        for stored_token, actor in self.config.tokens.items():
            try:
                if hmac.compare_digest(stored_token.encode(), provided_bytes):
                    return actor
            except TypeError:
                continue
        return None
