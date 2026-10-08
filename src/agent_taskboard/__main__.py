import uvicorn

from agent_taskboard.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "agent_taskboard.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
