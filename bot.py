import logging
import re
from pathlib import Path

from slack_bolt import App

log = logging.getLogger(__name__)

from agent import ProjectAgent
from dashboard import deploy
from db import log_event, update_reaction
from history import fetch_context

_agents: dict[str, ProjectAgent] = {}
_pending_updates: dict[str, dict] = {}
_pending_nudges: dict[str, dict] = {}


def _get_agent(channel_name: str) -> ProjectAgent:
    if channel_name not in _agents:
        _agents[channel_name] = ProjectAgent(channel_name)
    return _agents[channel_name]


def _resolve_channel_name(client, channel_id: str) -> str:
    try:
        response = client.conversations_info(channel=channel_id)
        return response["channel"]["name"]
    except Exception:
        return channel_id


def _fetch_channel_members(client, channel_id: str) -> list[dict]:
    """Fetch all non-bot members in a channel with their profile info."""
    members_response = client.conversations_members(channel=channel_id)
    member_ids = members_response.get("members", [])

    members = []
    for user_id in member_ids:
        info = client.users_info(user=user_id)
        user = info.get("user", {})
        if user.get("is_bot") or user.get("id") == "USLACKBOT":
            continue
        members.append({
            "id": user.get("id", ""),
            "name": user.get("name", ""),
            "real_name": user.get("real_name", ""),
            "title": user.get("profile", {}).get("title", ""),
        })
    return members


def _strip_mention(text: str) -> str:
    """Remove the @bot mention from the message text."""
    return re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()


def _build_permalink(channel_id: str, ts: str) -> str:
    """Build a Slack message permalink from channel ID and timestamp."""
    return f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}"


def _parse_category(result: str) -> tuple[str, str]:
    """Extract category from classify result like 'UPDATE|decision: text'.

    Returns (action_with_content, category). If no category found, defaults to 'general'.
    """
    # Match ACTION|category: content
    match = re.match(r"^(\w+)\|(\w+):\s*(.*)", result, re.DOTALL)
    if match:
        action = match.group(1)
        category = match.group(2)
        content = match.group(3)
        return f"{action}: {content}", category
    return result, "general"


def _format_diff(current: str, addition: str) -> str:
    """Format a ground truth change with context lines and emoji indicators."""
    lines = current.strip().splitlines()
    context_lines = lines[-2:] if len(lines) >= 2 else lines
    parts = [f">    {line}" for line in context_lines]
    parts.append(f"> :large_green_circle:  `+ {addition}`")
    return "\n".join(parts)


def register_handlers(app: App) -> None:
    app.event("app_mention")(handle_app_mention)
    app.event("message")(handle_message)
    app.event("reaction_added")(handle_reaction)


def handle_app_mention(event: dict, client, say) -> None:
    channel_id = event.get("channel", "")
    channel_name = _resolve_channel_name(client, channel_id)
    user_message = _strip_mention(event.get("text", ""))
    user_id = event.get("user", "")
    thread_ts = event.get("ts")

    if user_message.lower().startswith("initialize"):
        agent = _get_agent(channel_name)
        members = _fetch_channel_members(client, channel_id)
        result = agent.initialize(members)
        say(result, thread_ts=thread_ts)
        say("To make routing work, each person should set their role: `@bot role <your responsibilities>`")
        return

    if user_message.lower().startswith("role "):
        role = user_message[5:].strip()
        agent = _get_agent(channel_name)
        result = agent.set_role(user_id, role)
        say(result, thread_ts=thread_ts)
        return

    if user_message.lower().startswith("dashboard"):
        say(":chart_with_upwards_trend: Deploying dashboard...", thread_ts=thread_ts)
        try:
            url = deploy()
            say(f":white_check_mark: Dashboard deployed: {url}", thread_ts=thread_ts)
        except Exception as e:
            log.error("Dashboard deploy failed: %s", e)
            say(f":x: Dashboard deploy failed: {e}", thread_ts=thread_ts)
        return

    agent = _get_agent(channel_name)
    history = fetch_context(client, channel_id)
    response = agent.respond(user_message, history)
    say(response, thread_ts=thread_ts)


def _check_text_approval(event: dict, client, say) -> bool:
    """Check if message is a text approval/rejection for a pending update or nudge.

    Returns True if the message was handled as an approval/rejection.
    """
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return False

    word = event.get("text", "").strip().lower()
    channel_id = event.get("channel", "")
    user = event.get("user", "")

    if thread_ts in _pending_updates:
        if word in APPROVE_WORDS:
            pending = _pending_updates.pop(thread_ts)
            agent = _get_agent(pending["channel_name"])
            agent.apply_update(pending["update_text"], user)
            agent.log_message(pending["user"], pending["permalink"], pending["category"], pending["update_text"])
            update_reaction(pending["channel_name"], pending["event_id"], "approved", user)
            client.chat_postMessage(
                channel=channel_id,
                text=":white_check_mark: Ground truth updated.",
                thread_ts=pending["thread_ts"],
            )
            return True
        if word in REJECT_WORDS:
            pending = _pending_updates.pop(thread_ts)
            update_reaction(pending["channel_name"], pending["event_id"], "rejected", user)
            client.chat_postMessage(
                channel=channel_id,
                text=":x: Change discarded.",
                thread_ts=pending["thread_ts"],
            )
            return True

    if thread_ts in _pending_nudges:
        if word in APPROVE_WORDS:
            pending = _pending_nudges.pop(thread_ts)
            if "event_id" in pending:
                update_reaction(pending["channel_name"], pending["event_id"], "approved", "")
            client.chat_postMessage(
                channel=channel_id,
                text=":white_check_mark: Thanks for the feedback — flagged as off-track.",
                thread_ts=pending["thread_ts"],
            )
            return True
        if word in REJECT_WORDS:
            pending = _pending_nudges.pop(thread_ts)
            if "event_id" in pending:
                update_reaction(pending["channel_name"], pending["event_id"], "rejected", "")
            client.chat_postMessage(
                channel=channel_id,
                text=":ok_hand: Got it — seems like things are on track.",
                thread_ts=pending["thread_ts"],
            )
            return True

    return False


def handle_message(event: dict, client, say) -> None:
    if event.get("bot_id") or event.get("subtype"):
        return

    if _check_text_approval(event, client, say):
        return

    channel_id = event.get("channel", "")
    channel_name = _resolve_channel_name(client, channel_id)
    agent = _get_agent(channel_name)

    user = event.get("user", "someone")
    user_message = event.get("text", "")
    thread_ts = event.get("ts", "")

    log.info("[%s] @%s: %s", channel_name, user, user_message)
    history = fetch_context(client, channel_id)
    raw_result = agent.classify(user, user_message, history)
    result, category = _parse_category(raw_result)
    log.info("[%s] -> %s (category=%s)", channel_name, result, category)

    permalink = _build_permalink(channel_id, thread_ts)

    if result.startswith("ROUTE:"):
        route_data = result.replace("ROUTE:", "").strip().split("|", 1)
        target_user = route_data[0].strip()
        context = route_data[1].strip() if len(route_data) > 1 else "could use your help here"
        say(
            f"Hey {target_user}, <@{user}> {context} Could you jump in here?",
            thread_ts=thread_ts,
        )
        route_content = result.replace("ROUTE:", "").strip()
        agent.log_message(user, permalink, category, route_content)
        log_event(channel_name, "ROUTE", user, category, route_content, permalink)

    elif result.startswith("UPDATE:"):
        update_text = result.replace("UPDATE:", "").strip()
        diff = _format_diff(agent.ground_truth, update_text)
        response = say(
            f":memo: *Proposed ground truth change:*\n\n{diff}\n\nReact :white_check_mark: to accept or :x: to reject.",
            thread_ts=thread_ts,
        )
        event_id = log_event(channel_name, "UPDATE", user, category, update_text, permalink)
        _pending_updates[response["ts"]] = {
            "update_text": update_text,
            "channel_name": channel_name,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "category": category,
            "user": user,
            "permalink": permalink,
            "event_id": event_id,
        }

    elif result.startswith("MISALIGN:"):
        misalign_text = result.replace("MISALIGN:", "").strip()
        warning = Path("prompts/misalign.md").read_text().format(misalign_content=misalign_text)
        response = say(warning, thread_ts=thread_ts)
        agent.log_message(user, permalink, category, misalign_text)
        event_id = log_event(channel_name, "MISALIGN", user, category, misalign_text, permalink)
        _pending_nudges[response["ts"]] = {
            "nudge_text": misalign_text,
            "channel_name": channel_name,
            "thread_ts": thread_ts,
            "user": user,
            "event_id": event_id,
        }

    elif result.startswith("QUESTION:"):
        question_text = result.replace("QUESTION:", "").strip()
        nudge = Path("prompts/nudge.md").read_text().format(nudge_content=question_text)
        response = say(nudge, thread_ts=thread_ts)
        agent.log_message(user, permalink, category, question_text)
        event_id = log_event(channel_name, "QUESTION", user, category, question_text, permalink)
        _pending_nudges[response["ts"]] = {
            "nudge_text": question_text,
            "channel_name": channel_name,
            "thread_ts": thread_ts,
            "user": user,
            "event_id": event_id,
        }

    # PASS — do nothing


APPROVE_REACTIONS = {"white_check_mark", "+1", "thumbsup"}
REJECT_REACTIONS = {"x", "-1", "thumbsdown"}
APPROVE_WORDS = {"y", "yes", "yeah", "sure", "approve", "approved", "ok"}
REJECT_WORDS = {"n", "no", "nah", "reject", "rejected", "nope"}


def handle_reaction(event: dict, client, say) -> None:
    reaction = event.get("reaction", "")
    item = event.get("item", {})
    msg_ts = item.get("ts", "")
    channel_id = item.get("channel", "")

    if msg_ts in _pending_nudges:
        _handle_nudge_reaction(msg_ts, reaction, channel_id, client)
        return

    if msg_ts not in _pending_updates:
        return

    pending = _pending_updates[msg_ts]
    user = event.get("user", "")

    if reaction in APPROVE_REACTIONS:
        del _pending_updates[msg_ts]
        agent = _get_agent(pending["channel_name"])
        agent.apply_update(pending["update_text"], user)
        agent.log_message(
            pending["user"], pending["permalink"], pending["category"], pending["update_text"]
        )
        update_reaction(pending["channel_name"], pending["event_id"], "approved", user)
        client.chat_postMessage(
            channel=channel_id,
            text=":white_check_mark: Ground truth updated.",
            thread_ts=pending["thread_ts"],
        )
        log.info("[%s] UPDATE accepted by %s", pending["channel_name"], user)

        # Validate directory user IDs against channel membership
        try:
            members_resp = client.conversations_members(channel=channel_id)
            channel_member_ids = members_resp.get("members", [])
            missing = agent.validate_directory(channel_member_ids)
            if missing:
                mentions = ", ".join(f"<@{uid}>" for uid in missing)
                log.warning("[%s] Directory lists users not in channel: %s", pending["channel_name"], mentions)
                client.chat_postMessage(
                    channel=channel_id,
                    text=f":warning: Directory lists users not in this channel: {mentions}",
                    thread_ts=pending["thread_ts"],
                )
        except Exception as e:
            log.debug("Directory validation skipped: %s", e)

    elif reaction in REJECT_REACTIONS:
        del _pending_updates[msg_ts]
        update_reaction(pending["channel_name"], pending["event_id"], "rejected", user)
        client.chat_postMessage(
            channel=channel_id,
            text=":x: Change discarded.",
            thread_ts=pending["thread_ts"],
        )
        log.info("[%s] UPDATE rejected by %s", pending["channel_name"], user)


def _handle_nudge_reaction(msg_ts: str, reaction: str, channel_id: str, client) -> None:
    pending = _pending_nudges[msg_ts]

    if reaction in APPROVE_REACTIONS:
        del _pending_nudges[msg_ts]
        if "event_id" in pending:
            update_reaction(pending["channel_name"], pending["event_id"], "approved", "")
        client.chat_postMessage(
            channel=channel_id,
            text=":white_check_mark: Thanks for the feedback — flagged as off-track.",
            thread_ts=pending["thread_ts"],
        )
        log.info("[%s] NUDGE accepted by reaction", pending["channel_name"])

    elif reaction in REJECT_REACTIONS:
        del _pending_nudges[msg_ts]
        if "event_id" in pending:
            update_reaction(pending["channel_name"], pending["event_id"], "rejected", "")
        client.chat_postMessage(
            channel=channel_id,
            text=":ok_hand: Got it — seems like things are on track.",
            thread_ts=pending["thread_ts"],
        )
        log.info("[%s] NUDGE dismissed by reaction", pending["channel_name"])
