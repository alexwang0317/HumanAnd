import json
import logging
import os
import re
import threading
import time
import urllib.request

from src.services.project_service import ProjectAgent
from src.stores.db import log_event
from src.services.llm_service import classify_pr

log = logging.getLogger(__name__)

# Poll every 60s by default. GitHub API rate limit is 5,000/hr — this uses ~10/min, well within bounds.
POLL_INTERVAL = int(os.environ.get("GITHUB_POLL_INTERVAL", "60"))
# In-memory set to avoid re-checking PRs within a session. Resets on restart (by design — seeding handles it).
_seen_prs: set[int] = set()


def _github_get(url: str) -> list | dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_open_prs(repo: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/pulls?state=open&sort=created&direction=desc&per_page=10"
    result = _github_get(url)
    return result if isinstance(result, list) else []


def fetch_pr_commits(repo: str, pr_number: int) -> list[str]:
    """Fetch only the latest commit message for a PR.

    PR branches often carry old/unrelated commits. The most recent commit
    plus the PR title give the clearest signal of intent.
    """
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
    commits = _github_get(url)
    if not commits:
        return []
    return [commits[-1]["commit"]["message"]]


def parse_github_map(ground_truth: str) -> dict[str, dict]:
    """Parse Directory entries for 'github: username' to build github_user -> info map.

    Expects lines like: * **Name** (<@SLACK_ID>) — Role description. github: ghusername
    This is the bridge between GitHub identities and Slack/role identities.
    """
    mapping: dict[str, dict] = {}
    for line in ground_truth.splitlines():
        gh_match = re.search(r"github:\s*(\S+)", line, re.IGNORECASE)
        if not gh_match:
            continue
        github_username = gh_match.group(1).lower()
        name_match = re.search(r"\*\*(.+?)\*\*", line)
        slack_match = re.search(r"<@(U[A-Z0-9]+)>", line)
        role_match = re.search(r"—\s*(.+?)(?:\s*github:)", line, re.IGNORECASE)
        mapping[github_username] = {
            "name": name_match.group(1) if name_match else github_username,
            "slack_id": slack_match.group(1) if slack_match else "",
            "role": role_match.group(1).strip().rstrip(".") if role_match else "Unknown",
        }
    return mapping


def check_pr(pr: dict, repo: str, agent: ProjectAgent) -> dict | None:
    """Check a single PR for alignment. Returns nudge dict or None."""
    pr_number = pr["number"]
    pr_title = pr["title"]
    gh_username = pr["user"]["login"].lower()

    github_map = parse_github_map(agent.ground_truth)
    if gh_username not in github_map:
        log.info("PR #%d `%s` by %s — skipped (not in directory)", pr_number, pr_title, gh_username)
        return None

    author = github_map[gh_username]
    commit_messages = fetch_pr_commits(repo, pr_number)
    commits_text = "\n".join(commit_messages)

    result = classify_pr(author["name"], author["role"], pr_title, commits_text, agent.ground_truth)
    log.info("PR #%d `%s` by %s (owns %s) — LLM result: %s", pr_number, pr_title, author["name"], author["role"], result)
    if result.startswith("PASS"):
        return None

    return {
        "pr_number": pr_number,
        "pr_title": pr_title,
        "pr_url": pr["html_url"],
        "author_name": author["name"],
        "author_role": author["role"],
        "author_slack_id": author["slack_id"],
        "nudge_reason": result.replace("NUDGE:", "").strip(),
    }


def format_nudge(nudge: dict) -> str:
    return (
        f":octocat: <@{nudge['author_slack_id']}> opened "
        f"<{nudge['pr_url']}|PR #{nudge['pr_number']}> `{nudge['pr_title']}` "
        f"— {nudge['author_name']} owns *{nudge['author_role']}*. "
        f"{nudge['nudge_reason']}"
    )


def _resolve_channel_id(client, channel_name: str) -> str | None:
    """Find channel ID by name."""
    try:
        for page in client.conversations_list(types="public_channel", limit=200):
            for ch in page["channels"]:
                if ch["name"] == channel_name:
                    return ch["id"]
    except Exception as e:
        log.error("Failed to resolve channel %s: %s", channel_name, e)
    return None


def poll_once(repo: str, slack_client, agents: dict[str, ProjectAgent]) -> None:
    """Single poll iteration: fetch PRs, check new ones, post nudges."""
    project_name = repo.split("/")[-1]
    agent = agents.get(project_name)
    if not agent:
        agent = ProjectAgent(project_name)
        agents[project_name] = agent

    prs = fetch_open_prs(repo)
    for pr in prs:
        if pr["number"] in _seen_prs:
            continue
        _seen_prs.add(pr["number"])

        nudge = check_pr(pr, repo, agent)
        if not nudge:
            continue

        channel_id = _resolve_channel_id(slack_client, os.environ.get("GITHUB_CHANNEL", project_name))
        if not channel_id:
            log.warning("No Slack channel found for project %s", project_name)
            continue

        message = format_nudge(nudge)
        slack_client.chat_postMessage(channel=channel_id, text=message)
        log_event(project_name, "PR_NUDGE", nudge["author_name"], "pr_alignment", message, nudge["pr_url"])
        log.info("PR nudge posted for PR #%d", nudge["pr_number"])


def start_polling(repo: str, slack_client, agents: dict[str, ProjectAgent]) -> threading.Thread:
    """Start background polling thread. Returns the thread."""
    def _loop():
        log.info("GitHub PR monitor started for %s (every %ds)", repo, POLL_INTERVAL)
        # Seed existing PRs on first run so we don't flood Slack with nudges
        # for PRs that were opened before the bot started
        try:
            for pr in fetch_open_prs(repo):
                _seen_prs.add(pr["number"])
            log.info("Seeded %d existing PRs", len(_seen_prs))
        except Exception as e:
            log.error("Failed to seed PRs: %s", e)

        while True:
            time.sleep(POLL_INTERVAL)
            try:
                poll_once(repo, slack_client, agents)
            except Exception as e:
                log.error("GitHub poll error: %s", e)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread
