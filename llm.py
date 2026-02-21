import os
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
PROMPTS_DIR = Path("prompts")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _extract_text(response: anthropic.types.Message) -> str:
    # pyrefly: ignore[missing-attribute]
    return response.content[0].text.strip()  # pyrefly: ignore


def classify_message(ground_truth: str, user: str, message: str, history: str = "") -> str:
    system_prompt = _load_prompt("classify.md").format(
        ground_truth=ground_truth,
        user=user,
        message=message,
        history=history or "(no recent messages)",
    )
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    )
    return _extract_text(response)


def compact_ground_truth(ground_truth: str) -> str:
    system_prompt = _load_prompt("compaction.md").format(ground_truth=ground_truth)
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": "Compact this ground truth document."}],
    )
    return _extract_text(response)


def respond_to_mention(ground_truth: str, message: str, history: str = "", messages: str = "") -> str:
    system_prompt = _load_prompt("respond.md").format(
        ground_truth=ground_truth,
        history=history or "(no recent messages)",
        messages=messages or "(no important messages yet)",
    )
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    )
    return _extract_text(response)
