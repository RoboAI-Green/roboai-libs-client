import json

import pytest

from roboai_libs_client.auth import extract_access_token, token_from_env


def test_extract_plain_token():
    assert extract_access_token("  tok_plain  ") == "tok_plain"


def test_extract_bearer_token():
    assert extract_access_token("Bearer tok_abc") == "tok_abc"


def test_extract_from_json_access_token():
    assert extract_access_token(json.dumps({"access_token": "tok_json"})) == "tok_json"


def test_extract_from_json_api_key_fallback():
    assert extract_access_token(json.dumps({"api_key": "tok_key"})) == "tok_key"


def test_extract_empty_raises():
    with pytest.raises(ValueError):
        extract_access_token("   ")


def test_extract_json_without_token_raises():
    with pytest.raises(ValueError):
        extract_access_token(json.dumps({"foo": "bar"}))


def test_token_from_env_prefers_api_key(monkeypatch):
    monkeypatch.setenv("ROBOAI_LIBS_API_KEY", "from_api_key")
    monkeypatch.setenv("ROBOAI_LIBS_TOKEN", "from_token")
    assert token_from_env() == "from_api_key"


def test_token_from_env_falls_back_to_token(monkeypatch):
    monkeypatch.delenv("ROBOAI_LIBS_API_KEY", raising=False)
    monkeypatch.setenv("ROBOAI_LIBS_TOKEN", "from_token")
    assert token_from_env() == "from_token"


def test_token_from_env_none_when_unset(monkeypatch):
    monkeypatch.delenv("ROBOAI_LIBS_API_KEY", raising=False)
    monkeypatch.delenv("ROBOAI_LIBS_TOKEN", raising=False)
    assert token_from_env() is None
