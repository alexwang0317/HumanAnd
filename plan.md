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
Goal: Bot reads the ground truth file and uses it to detect misalignment and route questions.

- [ ] Upgrade ground truth files from plain text to structured markdown (see Ground Truth Format below)
- [ ] Load the channel's ground truth file and cache its contents in memory
- [ ] Integrate Claude API — bot sends ground truth as system context + user's message as the prompt
- [ ] **Two trigger modes:**
  - **@mention** — bot responds directly with an answer grounded in the ground truth
  - **Passive alignment check** — bot reads every channel message, runs a Haiku classification call to check if the message is unclear or conflicts with ground truth. Only speaks up when something seems off — not aggressively, just when intent is ambiguous or direction seems to drift. Err on the side of staying quiet.
- [ ] Cache alignment classification results to minimize API costs (same ground truth + similar message = skip re-check)
- [ ] Map each Slack channel to a project ground truth file (one project per channel)
- [ ] Store API keys in `.env`, add `.env` to `.gitignore`
- [ ] **Checkpoint:** Ask the bot "what's the team's goal?" via @mention — it answers correctly. Post a message that contradicts the ground truth — bot flags it.

### Ground Truth Format

Ground truth files use structured plaintext with Slack user IDs so the bot can actually ping people. Example `projects/new_human_and_model.txt`:

```markdown
# Project Ground Truth

## Core Objective
Launch the MVP by Friday with zero new database dependencies.

## Directory & Responsibilities
* **Database & Infrastructure:** Alex (<@U11111111>)
* **Frontend & UI:** Sarah (<@U22222222>)
* **Product & Timelines:** Manager Dan (<@U33333333>)

## AI Decision Log
* **2026-02-21:** Team agreed to pivot to MongoDB. (Accepted — proposed by bot after #backend discussion)
```

The **Directory** section is critical — it maps people to ownership areas using their real Slack user IDs (find via profile -> three dots -> "Copy member ID"). This is what powers the routing system.

The **AI Decision Log** is where accepted ground truth changes get appended, with timestamps and context.

### Ground Truth Size Limit

A hardcoded word limit (e.g., `MAX_GROUND_TRUTH_WORDS = 1000`) lives at the top of `ground_truth.py`. When the file exceeds this limit after an accepted update, the bot runs a compaction step:

1. Send the full ground truth to Claude with a prompt: "Compress this document to stay under {limit} words. Preserve all Directory entries and the Core Objective. Summarize older Decision Log entries into concise bullets. Drop anything redundant."
2. Post the compacted version in Slack for Y/N approval (same flow as any other ground truth update).
3. On acceptance, overwrite the file with the compacted version.

This keeps the ground truth from ballooning into a document nobody reads.

### LLM Action Types

The LLM classifies every message into one of four actions. The system prompt (in `prompts/respond.md`) instructs it to output exactly one:

- **`ROUTE: <@UserID> | summary`** — Someone is asking a question or needs help. The bot identifies the right person from the Directory and tags them in-thread with context. Eliminates the "who do I ask?" problem.
- **`UPDATE: [new ground truth entry]`** — A concrete decision was made in conversation. Bot proposes a ground truth change (goes through the Y/N approval flow in Phase 4).
- **`QUESTION: [clarification]`** — Someone said something vague or ambiguous about a task. Bot asks a gentle follow-up to get clarity.
- **`PASS`** — Nothing to do. Message is aligned, clear, and doesn't need routing.

When the bot receives a `ROUTE:` response, it posts in-thread:
> "Hey <@U11111111>, <@U22222222> needs help understanding the MongoDB pivot. Could you jump in here?"

This keeps the main channel clean and connects the right people without anyone having to dig through a wiki.

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
- [ ] Any user in the channel can respond to approve or reject — any affirmative ("Y", "yes", "yeah", "sure", thumbs-up react) counts as acceptance, any negative ("N", "no", "nah") counts as rejection
- [ ] On acceptance: bot writes the change to the channel's ground truth file and appends a changelog entry (date, what changed, why)
- [ ] On rejection: bot acknowledges and moves on
- [ ] Bot re-reads ground truth after every accepted change (no restart needed)
- [ ] After each accepted update, check word count against `MAX_GROUND_TRUTH_WORDS` (hardcoded in `ground_truth.py`). If over the limit, trigger compaction — summarize older entries, preserve Directory and Core Objective, propose the compacted version for Y/N approval.
- [ ] **Checkpoint:** Bot notices a goal shift in conversation, proposes a ground truth update, user approves, ground truth file is updated.

## Phase 5: Dashboard (Make it visible)
Goal: Track what the bot is doing so humans can review its behavior over time.

- [ ] Log every misalignment flag to SQLite — store: timestamp, channel, message that triggered it, what ground truth it compared against, the bot's nudge message, and whether the user seemed to agree or push back
- [ ] Log every ground truth update proposal — store: timestamp, channel, proposed change, reason, accepted/rejected, who responded
- [ ] Add a `/dashboard` slash command (or a simple local web page served by the bot) that shows:
  - Recent misalignment flags (last 7 days) with context
  - Ground truth change history (what changed, when, why, who approved)
  - Per-channel activity summary (how often the bot speaks up, acceptance rate)
- [ ] **Checkpoint:** Run the bot for a day, then pull up the dashboard and see a clear picture of what it flagged, what changed, and how the team responded.

### SQLite Tables

```
misalignment_log
├── id, timestamp, channel_id
├── original_message       # The message that triggered the flag
├── ground_truth_snapshot  # What ground truth looked like at the time
├── nudge_message          # What the bot said
└── user_reaction          # Did the user acknowledge, push back, or ignore?

ground_truth_changes
├── id, timestamp, channel_id
├── proposed_change        # What the bot suggested
├── reason                 # Why the bot thought it should change
├── accepted               # Boolean
└── responded_by           # Slack user ID of who said Y/N
```

## Phase 6: Tests (Prove it works)
Goal: After each module is written, write tests for it. Keep tests focused on behavior.

### `test_llm.py`
- [ ] Given a message that contradicts ground truth, LLM returns a non-PASS action
- [ ] Given a benign message, LLM returns PASS
- [ ] Given a question about ownership, LLM returns ROUTE with the correct user ID from the Directory
- [ ] Given a concrete decision, LLM returns UPDATE with a reasonable entry
- [ ] Given a vague message, LLM returns QUESTION with a clarification

### `test_history.py`
- [ ] Thread history caps at 20 messages (oldest dropped first)
- [ ] Messages from a new thread don't bleed into an existing thread
- [ ] Relevance detection: messages within time window from same participants are grouped
- [ ] Relevance detection: messages across a gap are treated as separate

### `test_ground_truth.py`
- [ ] Reads and caches a ground truth file correctly
- [ ] After a write, cache is invalidated and re-read returns updated content
- [ ] Compaction triggers when word count exceeds `MAX_GROUND_TRUTH_WORDS`
- [ ] Compaction preserves Directory and Core Objective sections
- [ ] Changelog entry is appended with correct format (date, change, reason)

### `test_db.py`
- [ ] Schema creates tables on first run without error
- [ ] Misalignment log insert and query round-trips correctly
- [ ] Ground truth changes log insert and query round-trips correctly
- [ ] Channel-to-project mapping stores and retrieves correctly

### `test_bot.py`
- [ ] Bot ignores its own messages
- [ ] Bot replies in-thread, not in the main channel
- [ ] Affirmative responses ("Y", "yes", "yeah", "sure") are recognized as approval
- [ ] Negative responses ("N", "no", "nah") are recognized as rejection
- [ ] ROUTE action results in a message tagging the correct user

## Phase 7: Polish (Make it solid)
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
├── bot.py                  # Slack event handlers (on_message, threading, approval)
├── llm.py                  # Builds prompts, calls Claude (alignment checks + responses)
├── history.py              # Tracks per-thread conversation context (last 20 messages)
├── ground_truth.py         # Reads, caches, and writes ground truth files
├── db.py                   # SQLite setup and queries (history, channel mapping, dashboard logs)
├── dashboard.py            # Serves dashboard view (slash command or local web page)
├── prompts/
│   ├── alignment_check.md  # Prompt for passive misalignment detection (Haiku)
│   ├── nudge.md            # Prompt for how the bot speaks up (gentle tone)
│   ├── respond.md          # Prompt for @mention responses + action classification (ROUTE/UPDATE/QUESTION/PASS)
│   ├── route.md            # Prompt template for routing messages to the right person
│   ├── relevance.md        # Prompt for message relevance classification (Haiku)
│   ├── compaction.md       # Prompt for compressing ground truth when it exceeds word limit
│   └── ground_truth_update.md  # Prompt for proposing ground truth edits
├── projects/
│   └── new_human_and_model.txt   # Ground truth file (evolves over time)
├── tests/
│   ├── test_llm.py         # Tests for action classification (ROUTE/UPDATE/QUESTION/PASS)
│   ├── test_bot.py         # Tests for message handling, threading, approval parsing
│   ├── test_history.py     # Tests for thread history and relevance detection
│   ├── test_ground_truth.py # Tests for reading, writing, compaction
│   └── test_db.py          # Tests for SQLite queries and schema
├── humanand.db             # SQLite database (auto-created, gitignored)
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
- **`history.py`** — Reads/writes thread history to SQLite. Capped at 20 messages per thread. Used by `bot.py` to pass context into `llm.py`. Handles dynamic relevance detection.
- **`ground_truth.py`** — Reads and caches ground truth from `projects/`. Writes accepted updates back to the file with changelog entries. Uses channel-project mapping from SQLite.
- **`db.py`** — SQLite setup. Stores thread history, channel-to-project mapping, misalignment log, and ground truth changelog.
- **`dashboard.py`** — Reads from SQLite and serves a dashboard view — recent flags, ground truth history, per-channel stats. Exposed via slash command or a simple local web page.
- **`prompts/`** — Markdown files, one per prompt type. Loaded by `llm.py` at call time so you can edit them without restarting. Includes `nudge.md` which defines the bot's gentle tone when flagging misalignment.
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

SQLite is used for persistence (stdlib `sqlite3` — no extra dependency needed).

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
