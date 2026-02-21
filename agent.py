import logging
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from llm import classify_message, compact_ground_truth, respond_to_mention

log = logging.getLogger(__name__)

PROJECTS_DIR = Path("projects")
MAX_GROUND_TRUTH_WORDS = 1000


class ProjectAgent:
    def __init__(self, project_name: str) -> None:
        self.name = project_name
        self.project_dir = PROJECTS_DIR / project_name
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.ground_truth = self._load_file("ground_truth.txt")
        self.messages = self._load_file("messages.txt")

    def _load_file(self, filename: str) -> str:
        path = self.project_dir / filename
        if path.exists():
            return path.read_text().strip()
        return ""

    def _write_file(self, filename: str, content: str) -> None:
        path = self.project_dir / filename
        path.write_text(content)

    def initialize(self, members: list[dict]) -> str:
        """Set up ground truth with channel members. Returns confirmation message."""
        directory_lines = []
        for member in members:
            name = member.get("real_name", member.get("name", "Unknown"))
            user_id = member.get("id", "")
            title = member.get("title", "")
            role_line = f"* **{name}** (<@{user_id}>)"
            if title:
                role_line += f" — {title}"
            directory_lines.append(role_line)

        directory = "\n".join(directory_lines) if directory_lines else "(No members found)"

        ground_truth = (
            f"# Project Ground Truth\n\n"
            f"## Core Objective\n"
            f"(Set your team's objective here)\n\n"
            f"## Directory & Responsibilities\n"
            f"{directory}\n\n"
            f"## AI Decision Log\n"
            f"(Bot will populate this as decisions are made)\n"
        )

        self._write_file("ground_truth.txt", ground_truth)
        self._write_file(
            "messages.txt",
            "# Important messages for {}\n"
            "# Format: YYYY-MM-DD HH:MM | <@user_id> | slack_permalink | category | summary\n".format(self.name),
        )
        self.reload_ground_truth()
        return f"Initialized project *{self.name}* with {len(members)} team members."

    def set_role(self, user_id: str, role: str) -> str:
        """Update a user's Directory entry with their role description."""
        path = self.project_dir / "ground_truth.txt"
        if not path.exists():
            return "No ground truth file found. Run `@bot initialize` first."

        content = path.read_text()
        marker = f"(<@{user_id}>)"

        for line in content.splitlines():
            if marker in line:
                # Build new line: keep name and ID, replace role
                prefix = line.split(marker)[0] + marker
                new_line = f"{prefix} — {role}"
                content = content.replace(line, new_line)
                self._write_file("ground_truth.txt", content)
                self.reload_ground_truth()
                return f"Updated your role: {role}"

        return f"Couldn't find <@{user_id}> in the Directory. Run `@bot initialize` first."

    def classify(self, user: str, message: str, history: str = "") -> str:
        return classify_message(self.ground_truth, user, message, history)

    def respond(self, message: str, history: str = "") -> str:
        return respond_to_mention(self.ground_truth, message, history, self.messages)

    def apply_update(self, update_text: str, approved_by: str) -> bool:
        """Append an accepted update to the AI Decision Log, then git commit.

        Returns True if compaction is needed after the update.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"* **{timestamp}:** {update_text} (approved by <@{approved_by}>)"

        path = self.project_dir / "ground_truth.txt"
        content = path.read_text() if path.exists() else ""

        placeholder = "(Bot will populate this as decisions are made)\n"
        if placeholder in content:
            content = content.replace(placeholder, entry + "\n")
        else:
            content = content.rstrip() + "\n" + entry + "\n"

        self._write_file("ground_truth.txt", content)
        self.reload_ground_truth()
        self._git_commit(update_text, approved_by)
        return self.check_compaction()

    def check_compaction(self) -> bool:
        """Return True if ground truth exceeds the word limit."""
        return len(self.ground_truth.split()) > MAX_GROUND_TRUTH_WORDS

    def compact(self) -> str:
        """Compress the ground truth via LLM and save the result."""
        compacted = compact_ground_truth(self.ground_truth)
        self._write_file("ground_truth.txt", compacted)
        self.reload_ground_truth()
        self._git_commit("compacted ground truth", "bot")
        return compacted

    def log_message(self, user: str, permalink: str, category: str, summary: str) -> None:
        """Append an important message entry to messages.txt."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"{timestamp} | <@{user}> | {permalink} | {category} | {summary}\n"
        path = self.project_dir / "messages.txt"
        with open(path, "a") as f:
            f.write(line)
        self.messages = self._load_file("messages.txt")

    def _git_commit(self, summary: str, approved_by: str) -> None:
        """Commit ground truth to a project-specific branch via a temporary worktree."""
        branch = f"project/{self.name}"
        gt_path = self.project_dir / "ground_truth.txt"
        worktree_dir = None

        try:
            # Create branch from HEAD if it doesn't exist
            if subprocess.run(
                ["git", "rev-parse", "--verify", branch], capture_output=True
            ).returncode != 0:
                subprocess.run(["git", "branch", branch], check=True, capture_output=True)

            worktree_dir = Path(tempfile.mkdtemp(prefix="gt-"))
            subprocess.run(
                ["git", "worktree", "add", str(worktree_dir), branch],
                check=True, capture_output=True,
            )

            # Copy ground truth into worktree at the repo-relative path
            gt_rel = f"projects/{self.name}/ground_truth.txt"
            dest = worktree_dir / gt_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(gt_path), str(dest))

            subprocess.run(
                ["git", "-C", str(worktree_dir), "add", gt_rel],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(worktree_dir), "commit", "-m",
                 f"ground truth: {summary} (approved by {approved_by})"],
                check=True, capture_output=True,
            )
            log.info("Committed ground truth to branch %s: %s", branch, summary)
        except Exception as e:
            log.debug("Git commit skipped: %s", e)
        finally:
            if worktree_dir:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree_dir)],
                    capture_output=True,
                )

    def validate_directory(self, channel_members: list[str]) -> list[str]:
        """Return user IDs listed in directory but not in the channel."""
        directory_ids = re.findall(r"<@(U[A-Z0-9]+)>", self.ground_truth)
        return [uid for uid in directory_ids if uid not in channel_members]

    def reload_ground_truth(self) -> None:
        self.ground_truth = self._load_file("ground_truth.txt")
        self.messages = self._load_file("messages.txt")
