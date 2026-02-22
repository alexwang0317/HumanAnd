def fetch_context(client, channel_id: str) -> str:
    """Fetch last 20 channel messages from Slack, formatted for LLM context."""
    response = client.conversations_history(channel=channel_id, limit=20)
    messages = response.get("messages", [])

    # Slack returns newest-first; reverse to oldest-first
    messages.reverse()

    lines = []
    for msg in messages:
        if msg.get("bot_id") or msg.get("subtype"):
            continue
        user = msg.get("user", "unknown")
        text = msg.get("text", "")
        if text:
            lines.append(f"<@{user}>: {text}")

    return "\n".join(lines)
