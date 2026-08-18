from pathlib import Path

from app.config import RepositoryConfig
from app.repository import snapshot_repository


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
