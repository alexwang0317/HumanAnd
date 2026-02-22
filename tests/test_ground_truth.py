import tempfile
from pathlib import Path
from unittest.mock import patch

from src.services.project_service import MAX_GROUND_TRUTH_WORDS, ProjectAgent


def test_compaction_triggers_over_word_limit():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            # Write ground truth with more than MAX_GROUND_TRUTH_WORDS words
            big_text = "word " * (MAX_GROUND_TRUTH_WORDS + 100)
            agent._write_file("ground_truth.txt", big_text)
            agent.reload_ground_truth()
            assert agent.check_compaction() is True


def test_compaction_skips_under_limit():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            assert agent.check_compaction() is False


@patch("src.services.project_service.compact_ground_truth")
@patch("src.services.project_service.subprocess.run")
def test_compaction_preserves_directory_and_objective(mock_run, mock_compact):
    compacted = (
        "# Project Ground Truth\n\n"
        "## Core Objective\nLaunch MVP by Friday\n\n"
        "## Directory & Responsibilities\n"
        "* **Alex** (<@U111>) — Engineer\n\n"
        "## AI Decision Log\n"
        "* Summarized: switched to Postgres, added caching\n"
    )
    mock_compact.return_value = compacted

    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([{"id": "U111", "real_name": "Alex", "name": "alex", "title": "Engineer"}])
            result = agent.compact()

    assert "## Core Objective" in result
    assert "## Directory & Responsibilities" in result
    assert "<@U111>" in result


def test_reads_and_caches_ground_truth():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp, "myproject")
        project_dir.mkdir()
        (project_dir / "ground_truth.txt").write_text("Launch MVP by Friday.")
        (project_dir / "messages.txt").write_text("")
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("myproject")
    assert agent.ground_truth == "Launch MVP by Friday."


def test_cache_invalidated_after_write():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.services.project_service.PROJECTS_DIR", Path(tmp)):
            agent = ProjectAgent("testproject")
            agent.initialize([])
            old_gt = agent.ground_truth
            agent._write_file("ground_truth.txt", "Updated content")
            agent.reload_ground_truth()
            assert agent.ground_truth != old_gt
            assert agent.ground_truth == "Updated content"
