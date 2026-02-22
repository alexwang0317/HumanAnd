import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.services.project_service import ProjectAgent

# --- log_message tests ---


def test_log_message_appends_to_messages_file():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            agent.log_message("U123", "https://slack.com/archives/C1/p111", "decision", "Switch to Postgres")
        msg_path = Path(tmp, "testproject", "messages.txt")
        content = msg_path.read_text()
    assert "U123" in content
    assert "decision" in content
    assert "Switch to Postgres" in content
    assert "https://slack.com/archives/C1/p111" in content


def test_log_message_updates_agent_messages():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            agent.log_message("U123", "https://slack.com/archives/C1/p111", "blocker", "CI broken")
    assert "CI broken" in agent.messages


# --- _git_commit tests ---


@patch("src.services.project_service.subprocess.run")
def test_git_commit_uses_project_branch(mock_run):
    # rev-parse returns non-zero (branch doesn't exist), rest succeed
    check_result = MagicMock(returncode=1)
    mock_run.return_value = check_result

    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            # Reset to clear any calls from initialize
            mock_run.reset_mock()
            mock_run.return_value = MagicMock(returncode=1)
            agent._git_commit("Switch to Postgres", "U123")

    calls = [str(c) for c in mock_run.call_args_list]
    # Should check if branch exists
    assert any("rev-parse" in c and "project/testproject" in c for c in calls)
    # Should create branch (since rev-parse returned non-zero)
    assert any("'git', 'branch', 'project/testproject'" in c for c in calls)
    # Should create worktree
    assert any("worktree" in c and "add" in c for c in calls)
    # Should commit
    assert any("commit" in c for c in calls)
    # Should clean up worktree in finally
    assert any("worktree" in c and "remove" in c for c in calls)


@patch("src.services.project_service.subprocess.run", side_effect=Exception("git not found"))
def test_git_commit_skips_silently_on_failure(mock_run):
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            # Should not raise
            agent._git_commit("test", "U123")


# --- validate_directory tests ---


def test_validate_directory_finds_missing_members():
    with tempfile.TemporaryDirectory() as tmp:
        members = [
            {"id": "U111", "real_name": "Alex", "name": "alex", "title": ""},
            {"id": "U222", "real_name": "Sarah", "name": "sarah", "title": ""},
        ]
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize(members)
            # U222 is in directory but not in channel
            missing = agent.validate_directory(["U111", "U333"])
    assert "U222" in missing
    assert "U111" not in missing


def test_validate_directory_returns_empty_when_all_present():
    with tempfile.TemporaryDirectory() as tmp:
        members = [{"id": "U111", "real_name": "Alex", "name": "alex", "title": ""}]
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize(members)
            missing = agent.validate_directory(["U111", "U222"])
    assert missing == []


def test_loads_ground_truth():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp, "myproject")
        project_dir.mkdir()
        (project_dir / "ground_truth.txt").write_text("Launch MVP by Friday.")
        (project_dir / "messages.txt").write_text("")
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("myproject")
    assert agent.ground_truth == "Launch MVP by Friday."


def test_loads_messages_file():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp, "myproject")
        project_dir.mkdir()
        (project_dir / "ground_truth.txt").write_text("")
        (project_dir / "messages.txt").write_text("https://slack.com/archives/C1/p123 - pivot decision")
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("myproject")
    assert "pivot decision" in agent.messages


def test_missing_files_return_empty():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("nonexistent")
    assert agent.ground_truth == ""
    assert agent.messages == ""


def test_initialize_creates_ground_truth_with_members():
    members = [
        {"id": "U111", "real_name": "Alex", "name": "alex", "title": "Engineer"},
        {"id": "U222", "real_name": "Sarah", "name": "sarah", "title": "Designer"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            result = agent.initialize(members)

        gt_path = Path(tmp, "testproject", "ground_truth.txt")
        content = gt_path.read_text()

    assert "Alex" in content
    assert "<@U111>" in content
    assert "Engineer" in content
    assert "Sarah" in content
    assert "2 team members" in result


def test_initialize_creates_messages_file():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])

        msg_path = Path(tmp, "testproject", "messages.txt")
        assert msg_path.exists()
        assert "testproject" in msg_path.read_text()


def test_initialize_reloads_ground_truth():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            assert agent.ground_truth == ""
            agent.initialize([{"id": "U111", "real_name": "Alex", "name": "alex", "title": ""}])
            assert "Alex" in agent.ground_truth


@patch("src.services.project_service.subprocess.run")
def test_apply_update_replaces_placeholder(mock_run):
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            agent.apply_update("Switch to PostgreSQL", "U123")
    content = agent.ground_truth
    assert "Switch to PostgreSQL" in content
    assert "approved by <@U123>" in content
    assert "(Bot will populate this as decisions are made)" not in content


@patch("src.services.project_service.subprocess.run")
def test_apply_update_appends_when_no_placeholder(mock_run):
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            agent.apply_update("First decision", "U111")
            agent.apply_update("Second decision", "U222")
    assert "First decision" in agent.ground_truth
    assert "Second decision" in agent.ground_truth


def test_set_role_updates_directory_entry():
    members = [{"id": "U111", "real_name": "Alex", "name": "alex", "title": ""}]
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize(members)
            result = agent.set_role("U111", "Database & Infrastructure")
    assert "Database & Infrastructure" in result
    assert "Database & Infrastructure" in agent.ground_truth
    assert "(<@U111>) — Database & Infrastructure" in agent.ground_truth


def test_set_role_replaces_existing_role():
    members = [{"id": "U111", "real_name": "Alex", "name": "alex", "title": "Engineer"}]
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize(members)
            agent.set_role("U111", "Frontend & UI")
    assert "Frontend & UI" in agent.ground_truth
    assert "Engineer" not in agent.ground_truth


def test_set_role_unknown_user():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            result = agent.set_role("U999", "Some role")
    assert "Couldn't find" in result
