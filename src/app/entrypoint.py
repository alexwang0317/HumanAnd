import logging
import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.handlers.slack_events import _agents, register_handlers


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    load_dotenv()
    app = create_app()
    register_handlers(app)

    log = logging.getLogger(__name__)
    github_repo = os.environ.get("GITHUB_REPO")
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_repo and github_token:
        from src.services.github_monitor import start_polling
        log.info("Starting GitHub PR monitor for %s", github_repo)
        start_polling(github_repo, app.client, _agents)
    else:
        log.info("GitHub PR monitor disabled (GITHUB_REPO=%s, GITHUB_TOKEN=%s)", github_repo or "missing", "set" if github_token else "missing")

    start_socket_mode(app)


def create_app() -> App:
    return App(token=os.environ["SLACK_BOT_TOKEN"])


def start_socket_mode(app: App) -> None:
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()


if __name__ == "__main__":
    main()
