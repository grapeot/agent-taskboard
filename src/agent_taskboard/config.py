import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

ENV_HOST = "AGENT_TASKBOARD_HOST"
ENV_PORT = "AGENT_TASKBOARD_PORT"
ENV_DB_PATH = "AGENT_TASKBOARD_DB_PATH"
ENV_TOKEN = "AGENT_TASKBOARD_TOKEN"
ENV_CORS = "AGENT_TASKBOARD_CORS_ORIGINS"
ENV_ARTIFACT_ROOTS = "AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS"
ENV_STALE = "AGENT_TASKBOARD_STALE_AFTER_SECONDS"
ENV_FILE = "AGENT_TASKBOARD_ENV_FILE"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DB_PATH = "./data/agent_taskboard.sqlite3"
DEFAULT_STALE = 1800
PUBLIC_PLACEHOLDER = "replace-with-a-long-random-token"


class Settings(BaseModel):
    host: str = Field(description="Bind address. Default is loopback.", examples=["127.0.0.1"])
    port: int = Field(description="HTTP port.", examples=[8765])
    db_path: str = Field(description="SQLite file path. The parent directory is created on startup.", examples=["./data/agent_taskboard.sqlite3"])
    token: str = Field(description="Write bearer token. The public placeholder is rejected.", examples=["replace-with-a-long-random-token"])
    cors_origins: list[str] = Field(description="Explicit browser origins. Empty means no extra origins. * is rejected.", examples=[[]])
    allowed_artifact_roots: list[str] = Field(
        description="Reserved for a future opaque file route. This build does not read files from these roots.",
        examples=[[]],
    )
    stale_after_seconds: int = Field(
        description="Age, in seconds, after which a non-accepted row is marked not updated at read time. Zero disables that mark.",
        examples=[1800],
        ge=0,
    )

    @model_validator(mode="after")
    def reject_placeholder_token(self) -> "Settings":
        if not self.token or self.token == PUBLIC_PLACEHOLDER:
            raise ValueError("AGENT_TASKBOARD_TOKEN must be set to a private value. The public placeholder is rejected.")
        return self


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _check_origins(origins: list[str]) -> None:
    for origin in origins:
        if origin == "*":
            raise ValueError("AGENT_TASKBOARD_CORS_ORIGINS must not be *")
        if not origin.startswith(("http://", "https://")) or " " in origin:
            raise ValueError("CORS origins must be explicit http or https origins")


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def default_env_file() -> Path:
    explicit = os.environ.get(ENV_FILE, "").strip()
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".env"


def load_settings(env_file: Path | None = None) -> Settings:
    load_env_file(default_env_file() if env_file is None else env_file)
    origins = _split_csv(os.environ.get(ENV_CORS, ""))
    _check_origins(origins)
    port_raw = os.environ.get(ENV_PORT, str(DEFAULT_PORT))
    stale_raw = os.environ.get(ENV_STALE, str(DEFAULT_STALE))
    try:
        port = int(port_raw)
        stale_after = int(stale_raw)
    except ValueError as exc:
        raise ValueError("AGENT_TASKBOARD_PORT and AGENT_TASKBOARD_STALE_AFTER_SECONDS must be integers") from exc
    if not 1 <= port <= 65535:
        raise ValueError("AGENT_TASKBOARD_PORT is out of range")
    return Settings(
        host=os.environ.get(ENV_HOST, DEFAULT_HOST) or DEFAULT_HOST,
        port=port,
        db_path=os.environ.get(ENV_DB_PATH, DEFAULT_DB_PATH) or DEFAULT_DB_PATH,
        token=os.environ.get(ENV_TOKEN, ""),
        cors_origins=origins,
        allowed_artifact_roots=_split_csv(os.environ.get(ENV_ARTIFACT_ROOTS, "")),
        stale_after_seconds=stale_after,
    )
