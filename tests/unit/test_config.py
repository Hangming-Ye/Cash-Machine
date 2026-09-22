import json
from pathlib import Path

import pytest

from cash_research.config import (
    ConfigurationError,
    RequestBoundaryError,
    load_settings,
    validate_read_request,
)


def test_load_settings_uses_explicit_paths_and_env_file(tmp_path: Path) -> None:
    root = tmp_path / "research-root"
    config_path = tmp_path / "settings.json"
    env_path = tmp_path / "credentials.env"
    config_path.write_text(
        json.dumps({"root": str(root), "enabled_sources": ["finnhub", "ibkr_flex"]}),
        encoding="utf-8",
    )
    env_path.write_text("FINNHUB_API_KEY=super-secret\n", encoding="utf-8")

    settings = load_settings(config_path=config_path, env_file=env_path)

    assert settings.root == root.resolve()
    assert settings.enabled_sources == ("finnhub", "ibkr_flex")
    assert settings.credentials["FINNHUB_API_KEY"].get_secret_value() == "super-secret"
    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings.model_dump())


def test_load_settings_never_discovers_sec_analysis_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sec-analysis.env").write_text("SHOULD_NOT_LOAD=secret\n", encoding="utf-8")

    settings = load_settings(root=tmp_path / "workspace")

    assert settings.credentials == {}


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
def test_order_operations_are_rejected(operation: str) -> None:
    with pytest.raises(RequestBoundaryError, match="not allowed"):
        validate_read_request({"source": "longbridge_oauth", "operation": operation})


def test_request_secret_is_rejected_without_echoing_value() -> None:
    secret = "should-never-appear"

    with pytest.raises(RequestBoundaryError) as caught:
        validate_read_request(
            {"source": "finnhub", "operation": "quote", "api_key": secret}
        )

    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "secret_field", ["accessToken", "clientSecret", "apiKey", "Authorization"]
)
def test_nested_secret_spellings_are_rejected_without_echoing_field(
    secret_field: str,
) -> None:
    with pytest.raises(RequestBoundaryError) as caught:
        validate_read_request(
            {
                "source": "finnhub",
                "operation": "quote",
                "headers": {secret_field: "hidden"},
            }
        )

    assert secret_field not in str(caught.value)


def test_source_and_operation_must_match_read_only_whitelist() -> None:
    with pytest.raises(RequestBoundaryError, match="unsupported source"):
        validate_read_request({"source": "new_vendor", "operation": "quote"})
    with pytest.raises(RequestBoundaryError, match="not allowed"):
        validate_read_request({"source": "tiingo", "operation": "positions"})

    validate_read_request({"source": "ibkr_flex", "operation": "positions"})


def test_explicit_missing_files_and_relative_root_fail(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="configuration file"):
        load_settings(config_path=tmp_path / "missing.json")
    with pytest.raises(ConfigurationError, match="environment file"):
        load_settings(env_file=tmp_path / "missing.env")
    with pytest.raises(ConfigurationError, match="absolute"):
        load_settings(root=Path("relative-root"))


def test_config_file_cannot_contain_credential_values(tmp_path: Path) -> None:
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps({"root": str(tmp_path / "root"), "api_key": "embedded-secret"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as caught:
        load_settings(config_path=config_path)

    assert "embedded-secret" not in str(caught.value)


def test_root_override_wins_and_unknown_settings_fail(tmp_path: Path) -> None:
    config_path = tmp_path / "settings.json"
    config_path.write_text(
        json.dumps(
            {
                "root": str(tmp_path / "configured"),
                "enabled_sources": ["tiingo"],
            }
        ),
        encoding="utf-8",
    )
    override = tmp_path / "override"

    settings = load_settings(root=override, config_path=config_path)

    assert settings.root == override.resolve()
    assert settings.enabled_sources == ("tiingo",)

    config_path.write_text(
        json.dumps({"root": str(tmp_path / "root"), "unexpected": True}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_settings(config_path=config_path)


@pytest.mark.parametrize("invalid_root", [None, [], {}])
def test_invalid_config_root_has_typed_error(tmp_path: Path, invalid_root: object) -> None:
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps({"root": invalid_root}), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="absolute"):
        load_settings(config_path=config_path)
