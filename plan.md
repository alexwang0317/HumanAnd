# Creation Plan

# Fundamental Problem
The fundamental premise is that AI shouldn't just be a standalone oracle that humans query for answers, or a machine that just generates content. Instead, AI should act as an ambient, ever-present facilitator or coordinator.

Modern teams lose massive amounts of bandwidth to "meta-work" and context-switching. The AI’s job is to sit in the background of human communication and act as a "cognitive middleware," subtly steering the team to keep them aligned with their Stated Higher Goals. It doesn't do the work for them; it optimizes the environment so humans can focus entirely on problem-solving without drifting off track.

## Vision
A Slack bot that listens to channel messages and responds using an LLM, grounded by a project-specific "ground truth" (the stated goal/context in `projects/new_human_and_model.txt`). The bot keeps conversations aligned with the team's actual objectives.

---

## Phase 1: Skeleton (Get a heartbeat)
Goal: Bot exists, connects to Slack via Socket Mode, and echoes back that it heard you.

- [ ] Set up repo (initial commit, push to GitHub)
- [ ] Install dependencies (`slack-bolt`, `anthropic`, `python-dotenv`)
- [ ] Create Slack app with full OAuth scopes (see Slack Scopes below)
- [ ] Enable Socket Mode in Slack API dashboard, generate `xapp-...` token
- [ ] Write minimal `main.py` + `bot.py` — connects via Socket Mode, responds to @mention with a static acknowledgment
- [ ] **Checkpoint:** @mention the bot in Slack, it responds. Done.

### Slack Scopes

**Bot Token Scopes (OAuth & Permissions):**
- `app_mentions:read` — detect when the bot is @mentioned
- `channels:history` — read messages in public channels
- `channels:read` — list and get info about public channels
- `chat:write` — send messages
- `chat:write.public` — send messages to channels the bot hasn't joined

**Event Subscriptions (subscribe to bot events):**
- `app_mention` — triggers when someone @mentions the bot
- `message.channels` — triggers on every message in public channels the bot is in

## Phase 2: Grounding (Give it memory)
Goal: Bot reads the ground truth file and uses it to detect misalignment.

- [ ] Load `projects/new_human_and_model.txt` and cache its contents in memory
- [ ] Integrate Claude API — bot sends ground truth as system context + user's message as the prompt
- [ ] **Two trigger modes:**
  - **@mention** — bot responds directly with an answer grounded in the ground truth
  - **Passive alignment check** — bot reads every channel message, runs a cheap cached classification call (Claude Haiku) to check if the message conflicts with ground truth. Only speaks up if misalignment is detected.
- [ ] Cache alignment classification results to minimize API costs (same ground truth + similar message = skip re-check)
- [ ] Store API keys in `.env`, add `.env` to `.gitignore`
- [ ] **Checkpoint:** Ask the bot "what's the team's goal?" via @mention — it answers correctly. Post a message that contradicts the ground truth — bot flags it.

## Phase 3: Conversation (Make it useful)
Goal: Bot maintains conversation context and gives substantive responses.

- [ ] Add message threading — bot replies in-thread, not flooding the channel
- [ ] Keep last 20 messages per thread as context (most research discussions stay under this)
- [ ] Dynamic relevance detection — determine whether a new message is a continuation of an existing conversation (see Message Relevance Strategies below)
- [ ] Load system prompts from `prompts/` directory (`.md` files, one per prompt type)
- [ ] **Checkpoint:** Have a multi-turn conversation in a thread. Bot remembers context, stays grounded, and correctly associates related messages.

### Message Relevance Strategies

The bot needs to decide: "Is this new message part of an ongoing conversation, or something new?"

**Option A: Time + Participant Window**
Messages from the same participants within a time window (e.g., 10 minutes) are assumed continuous. A gap resets context. Simple, cheap, no API calls — but misses topic changes within a window and connections across gaps.

**Option B: Lightweight LLM Classification**
Send the new message + a summary of the recent thread to Claude Haiku with a yes/no prompt: "Is this message a continuation of this conversation?" Accurate but costs an API call per message.

**Option C: Keyword Overlap**
Extract key terms from the active thread context. If the new message shares enough terms, treat it as continuous. No API cost, but brittle with synonyms and implicit references.

**Option D: Hybrid (Recommended)**
Use time + participant window as a first pass (free). If ambiguous (e.g., same channel but different participants, or edge of the time window), fall back to a cheap Haiku classification call. Best accuracy-to-cost ratio.

## Phase 4: Living Ground Truth
Goal: Ground truth evolves based on what's happening in Slack.

- [ ] Bot detects when conversations suggest the team's direction is shifting (new decisions, changed priorities, revised goals)
- [ ] Bot proposes an edit to the ground truth file directly in Slack — posts the suggested change with a short explanation of *why* it's proposing the update
- [ ] Users respond with "Y" to accept or "N" to reject
- [ ] On acceptance: bot writes the change to `projects/new_human_and_model.txt` and appends a changelog entry (date, what changed, why)
- [ ] On rejection: bot acknowledges and moves on
- [ ] Bot re-reads ground truth after every accepted change (no restart needed)
- [ ] **Checkpoint:** Bot notices a goal shift in conversation, proposes a ground truth update, user approves, ground truth file is updated.

## Phase 5: Polish (Make it solid)
Goal: Handle edge cases, clean up, make it presentable.

- [ ] Error handling (API failures, rate limits, malformed messages)
- [ ] Ignore bot's own messages (prevent loops)
- [ ] Add logging
- [ ] **Checkpoint:** Bot runs reliably for an extended session without crashing.

---

## Repo Structure

```
HumanAnd/
├── main.py                 # Entry point — loads config, starts the Slack bot
├── bot.py                  # Slack event handlers (on_message, threading, Y/N approval)
├── llm.py                  # Builds prompts, calls Claude (alignment checks + responses)
├── history.py              # Tracks per-thread conversation context (last 20 messages)
├── ground_truth.py         # Reads, caches, and writes ground truth files
├── prompts/
│   ├── alignment_check.md  # Prompt for passive misalignment detection (Haiku)
│   ├── respond.md          # Prompt for @mention responses (Sonnet/Opus)
│   ├── relevance.md        # Prompt for message relevance classification (Haiku)
│   └── ground_truth_update.md  # Prompt for proposing ground truth edits
├── projects/
│   └── new_human_and_model.txt   # Ground truth file (evolves over time)
├── pyproject.toml
├── .env                    # SLACK_BOT_TOKEN, SLACK_APP_TOKEN, ANTHROPIC_API_KEY
├── .gitignore
├── CLAUDE.md
├── plan.md
└── README.md
```

**What each file does:**

- **`main.py`** — Wires everything together. Loads `.env`, initializes the Slack app in Socket Mode, registers handlers from `bot.py`, starts listening. The only file you run.
- **`bot.py`** — Owns all Slack interaction. Handles @mentions, passive message listening, in-thread replies, and Y/N approval flow for ground truth updates.
- **`llm.py`** — Owns all Claude API calls. Loads prompt templates from `prompts/`, builds the full prompt with ground truth + history, routes to the right model (Haiku for cheap classification, Sonnet/Opus for substantive responses).
- **`history.py`** — Dict of `thread_id -> list of messages`, capped at 20. Used by `bot.py` to pass context into `llm.py`. Handles dynamic relevance detection.
- **`ground_truth.py`** — Reads and caches ground truth from `projects/`. Writes accepted updates back to the file with changelog entries.
- **`prompts/`** — Markdown files, one per prompt type. Loaded by `llm.py` at call time so you can edit them without restarting.
- **`projects/`** — Ground truth files. The bot reads from and writes to here.

## Environment Variables

The `.env` file needs these keys:

```
SLACK_BOT_TOKEN=xoxb-...        # From Slack app OAuth & Permissions
SLACK_APP_TOKEN=xapp-...        # From Slack app Socket Mode settings
ANTHROPIC_API_KEY=sk-ant-...     # From Anthropic console
```

## Dependencies

Add to `pyproject.toml`:

```
slack-bolt          # Slack bot framework
python-dotenv       # Load .env file
anthropic           # Claude API client
```

## How to Run

```bash
# 1. Install dependencies
uv sync

# 2. Run the bot (Socket Mode — no tunnel needed)
uv run python main.py
```

---

## Stretch Goals

### Integration with External Tools
- **Jira** — Bot reads ticket status and links conversations back to specific issues. When someone asks "what's the status of X?", the bot checks Jira instead of guessing.
- **GitHub** — Surface open PRs, blockers, or recent merges relevant to the current conversation.
- **Google Docs / Notion** — Pull in living documents as additional ground truth beyond the local `projects/` files.

### Relationship Graph + Task Assignment
- **People graph** — Track who works with whom, who owns what areas, and who's blocked on who. Built from Slack message patterns and explicit declarations.
- **Task assignment** — Bot can assign or suggest owners for action items that come up in conversation, based on the relationship graph and past ownership.
- **Workload awareness** — Before suggesting someone for a task, the bot considers what they're already committed to.

---

## Setup Instructions

**The Repository:** Clone this repo. Copy `.env.example` to `.env` and fill in the keys. Run `uv sync`.

**The Slack App:**
1. Go to api.slack.com, create a new app from scratch.
2. **OAuth & Permissions** — add bot token scopes: `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`, `chat:write.public`.
3. **Event Subscriptions** — subscribe to bot events: `app_mention`, `message.channels`.
4. **Socket Mode** — toggle it on. Generate an app-level token with `connections:write` scope. This is your `xapp-...` token.
5. Install the app to your workspace. Copy the Bot User OAuth Token (`xoxb-...`).
6. Add both tokens + your Anthropic API key to `.env`.

**Run it:** `uv run python main.py`. No tunnel needed — Socket Mode connects outbound.
