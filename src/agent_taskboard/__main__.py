import sys

import uvicorn

from agent_taskboard.config import load_settings


def main() -> None:
    try:
        settings = load_settings()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    uvicorn.run("agent_taskboard.app:create_app", factory=True, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
