import os

from pydantic import BaseModel, Field

ENV_HOST = "AGENT_TASKBOARD_HOST"
ENV_PORT = "AGENT_TASKBOARD_PORT"
ENV_DB_PATH = "AGENT_TASKBOARD_DB_PATH"
ENV_TOKEN = "AGENT_TASKBOARD_TOKEN"
ENV_CORS = "AGENT_TASKBOARD_CORS_ORIGINS"
ENV_ARTIFACT_ROOTS = "AGENT_TASKBOARD_ALLOWED_ARTIFACT_ROOTS"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DB_PATH = "./data/agent_taskboard.sqlite3"


class Settings(BaseModel):
    host: str = Field(description="Bind address. Default is loopback.", examples=["127.0.0.1"])
    port: int = Field(description="HTTP port.", examples=[8765])
    db_path: str = Field(
        description="SQLite path reserved for a later phase. This build does not open it.",
        examples=["./data/agent_taskboard.sqlite3"],
    )
    token: str = Field(
        description="Write bearer token from the environment. Empty disables writes.",
        examples=["replace-with-a-long-random-token"],
    )
    cors_origins: list[str] = Field(
        description="Explicit browser origins. Empty means no extra origins. * is rejected.",
        examples=[[]],
    )
    allowed_artifact_roots: list[str] = Field(
        description="Directory roots reserved for a later opaque artifact route. Unused in this build.",
        examples=[[]],
    )


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _check_origins(origins: list[str]) -> None:
    for origin in origins:
        if origin == "*":
            raise ValueError("AGENT_TASKBOARD_CORS_ORIGINS must not be *")
        if not origin.startswith(("http://", "https://")) or " " in origin:
            raise ValueError("CORS origins must be explicit http or https origins")


def load_settings() -> Settings:
    origins = _split_csv(os.environ.get(ENV_CORS, ""))
    _check_origins(origins)
    port_raw = os.environ.get(ENV_PORT, str(DEFAULT_PORT))
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError("AGENT_TASKBOARD_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("AGENT_TASKBOARD_PORT is out of range")
    return Settings(
        host=os.environ.get(ENV_HOST, DEFAULT_HOST) or DEFAULT_HOST,
        port=port,
        db_path=os.environ.get(ENV_DB_PATH, DEFAULT_DB_PATH) or DEFAULT_DB_PATH,
        token=os.environ.get(ENV_TOKEN, ""),
        cors_origins=origins,
        allowed_artifact_roots=_split_csv(os.environ.get(ENV_ARTIFACT_ROOTS, "")),
    )
