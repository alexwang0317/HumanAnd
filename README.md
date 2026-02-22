# HumanAnd

Slack bot that keeps a shared "ground truth" for a project, routes questions to owners, and logs team decisions with approvals.

## Setup

1. Create a virtual env and install deps:

```bash
uv sync
```

2. Set required environment variables:

```bash
export SLACK_BOT_TOKEN=...
export SLACK_APP_TOKEN=...
export ANTHROPIC_API_KEY=...
```

Optional GitHub PR monitor:

```bash
export GITHUB_REPO=owner/repo
export GITHUB_TOKEN=...
```

## Run

```bash
uv run python -m src.app.entrypoint
```

## Lint

```bash
uv run pyrefly check .
```

## Tests

```bash
uv run pytest
```

## Demo

See `demo.md` for the end-to-end live demo script.
