from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR_ENV = "ROBOAI_LIBS_CONFIG_DIR"
TOKEN_FILE_ENV = "ROBOAI_LIBS_TOKEN_FILE"
TOKEN_ENV_VARS = ("ROBOAI_LIBS_API_KEY", "ROBOAI_LIBS_TOKEN")


def token_from_env() -> str | None:
    for var in TOKEN_ENV_VARS:
        value = os.getenv(var)
        if value and value.strip():
            return value.strip()
    return None


def extract_access_token(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("Token cannot be empty.")
    if value.startswith("Bearer "):
        return value.removeprefix("Bearer ").strip()
    if value.startswith("{"):
        data = json.loads(value)
        token = data.get("access_token") or data.get("api_key")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("JSON did not contain an access_token value.")
        return token.strip()
    return value


def get_config_dir() -> Path:
    configured = os.getenv(CONFIG_DIR_ENV)
    if configured:
        return Path(configured).expanduser()

    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "roboai-libs"

    return Path.home() / ".config" / "roboai-libs"


def get_token_file() -> Path:
    configured = os.getenv(TOKEN_FILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return get_config_dir() / "auth.json"


def load_stored_api_key() -> str | None:
    token_file = get_token_file()
    try:
        data = json.loads(token_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    token = data.get("api_key") or data.get("access_token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def save_api_key(api_key: str) -> Path:
    token = api_key.strip()
    if token.startswith("Bearer "):
        token = token.removeprefix("Bearer ").strip()
    if not token:
        raise ValueError("API token cannot be empty.")

    token_file = get_token_file()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(json.dumps({"api_key": token}, indent=2) + "\n")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return token_file


def clear_stored_api_key() -> bool:
    token_file = get_token_file()
    try:
        token_file.unlink()
        return True
    except FileNotFoundError:
        return False
