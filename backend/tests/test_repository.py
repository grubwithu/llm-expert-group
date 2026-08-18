from pathlib import Path

from app.config import RepositoryConfig
from app.repository import RepositoryWorkspace, snapshot_repository


def test_snapshot_prioritizes_readme_and_skips_git(tmp_path: Path):
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret.txt").write_text("ignore", encoding="utf-8")
    snap = snapshot_repository(str(tmp_path), RepositoryConfig(max_context_chars=10000))
    assert snap.files[0] == "README.md"
    assert "src/x.py" in snap.files
    assert "secret" not in snap.context


def test_workspace_rejects_path_escape(tmp_path: Path):
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    workspace = RepositoryWorkspace(str(tmp_path), RepositoryConfig())
    try:
        workspace.read("../outside.txt")
    except ValueError as exc:
        assert "escapes repository root" in str(exc)
    else:
        raise AssertionError("path escape should have been rejected")


def test_workspace_search_rejects_missing_scope(tmp_path: Path):
    (tmp_path / "README.md").write_text("needle\n", encoding="utf-8")
    workspace = RepositoryWorkspace(str(tmp_path), RepositoryConfig())
    try:
        workspace.search("needle", path="missing")
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing search scope should have been rejected")


def test_snapshot_does_not_follow_file_symlink_outside_repo(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("TOP SECRET OUTSIDE", encoding="utf-8")
    (tmp_path / "README.md").write_text("inside", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    snap = snapshot_repository(str(tmp_path), RepositoryConfig(max_context_chars=10000))
    assert "TOP SECRET OUTSIDE" not in snap.context
    assert "linked.txt" not in snap.files
