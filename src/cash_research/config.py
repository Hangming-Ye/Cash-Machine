"""Explicit configuration loading and read-only request boundaries."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator


ALLOWED_SOURCE_OPERATIONS: dict[str, frozenset[str]] = {
    "finnhub": frozenset({"quote", "news"}),
    "tiingo": frozenset({"bars"}),
    "fmp_stable": frozenset({"profile", "statements"}),
    "akshare": frozenset({"quote", "bars", "news", "profile", "statements"}),
    "ibkr_flex": frozenset({"accounts", "positions", "executions"}),
    "longbridge_oauth": frozenset({"accounts", "positions", "executions"}),
}

_SECRET_KEY_TOKENS = frozenset(
    {"secret", "password", "token", "apikey", "privatekey", "credential", "authorization"}
)
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigurationError(ValueError):
    """Raised when explicit configuration cannot be loaded safely."""


class RequestBoundaryError(ValueError):
    """Raised when a request crosses the approved read-only boundary."""


class Settings(BaseModel):
    """Resolved non-secret settings plus redacted explicitly loaded credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    enabled_sources: tuple[str, ...] = Field(
        default_factory=lambda: tuple(ALLOWED_SOURCE_OPERATIONS)
    )
    credentials: dict[str, SecretStr] = Field(default_factory=dict, exclude=True, repr=False)

    @field_validator("enabled_sources")
    @classmethod
    def validate_sources(cls, sources: tuple[str, ...]) -> tuple[str, ...]:
        unsupported = sorted(set(sources) - ALLOWED_SOURCE_OPERATIONS.keys())
        if unsupported:
            raise ValueError(f"unsupported source names: {', '.join(unsupported)}")
        if len(set(sources)) != len(sources):
            raise ValueError("enabled_sources contains duplicates")
        return sources


def credential_secret_values(settings: Settings) -> tuple[str, ...]:
    """Return only values whose environment names identify actual credentials."""

    values: list[str] = []
    for name, secret in settings.credentials.items():
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if any(
            normalized == token or normalized.endswith(token)
            for token in _SECRET_KEY_TOKENS
        ):
            value = secret.get_secret_value()
            if value:
                values.append(value)
    return tuple(dict.fromkeys(values))


def load_settings(
    *,
    root: str | Path | None = None,
    config_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> Settings:
    """Load only explicitly named files; a direct ``root`` overrides config."""

    values: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigurationError(f"configuration file does not exist: {path}")
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"configuration file could not be read: {path}") from exc
        if not isinstance(loaded, dict):
            raise ConfigurationError("configuration file must contain a JSON object")
        secret_key = _find_secret_key(loaded)
        if secret_key is not None:
            raise ConfigurationError("configuration contains a credential field; use --env-file")
        values.update(loaded)

    if root is not None:
        values["root"] = root
    values.setdefault("root", "/workspace/cash-machine")

    resolved_root = _absolute_path(values["root"], label="root")
    values["root"] = resolved_root
    if env_file is not None:
        values["credentials"] = _read_env_file(Path(env_file))

    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise ConfigurationError("configuration does not match the approved settings schema") from exc


def validate_read_request(request: Mapping[str, Any]) -> None:
    """Reject secrets, unknown sources, and operations outside the read-only allowlist."""

    secret_key = _find_secret_key(request)
    if secret_key is not None:
        raise RequestBoundaryError("request contains a credential field")

    source = request.get("source")
    operation = request.get("operation")
    if not isinstance(source, str) or source not in ALLOWED_SOURCE_OPERATIONS:
        raise RequestBoundaryError("unsupported source")
    if not isinstance(operation, str) or operation not in ALLOWED_SOURCE_OPERATIONS[source]:
        raise RequestBoundaryError(f"operation is not allowed for source {source!r}")


def _read_env_file(path: Path) -> dict[str, SecretStr]:
    if not path.is_file():
        raise ConfigurationError(f"environment file does not exist: {path}")
    credentials: dict[str, SecretStr] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"environment file could not be read: {path}") from exc
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ConfigurationError(f"invalid environment entry on line {line_number}")
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ConfigurationError(f"invalid environment name on line {line_number}")
        credentials[name] = SecretStr(_unquote(value.strip()))
    return credentials


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _find_secret_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(normalized == token or normalized.endswith(token) for token in _SECRET_KEY_TOKENS):
                return str(key)
            nested = _find_secret_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, (list, tuple)):
        for item in value:
            nested = _find_secret_key(item)
            if nested is not None:
                return nested
    return None


def _absolute_path(value: str | Path, *, label: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ConfigurationError(f"{label} must be an absolute path")
    raw = str(value)
    try:
        path = Path(value).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must be an absolute path") from exc
    if not (path.is_absolute() or raw.startswith("/")):
        raise ConfigurationError(f"{label} must be an absolute path")
    return path.resolve(strict=False) if path.is_absolute() else path
