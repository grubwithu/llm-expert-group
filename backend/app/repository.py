from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import RepositoryConfig


@dataclass(slots=True)
class RepositorySnapshot:
    path: str
    commit: str | None
    context: str
    files: list[str]
    truncated: bool


_PRIORITY_NAMES = {
    "README.md": 0, "README.rst": 0, "README.txt": 0,
    "AGENTS.md": 1, "CLAUDE.md": 1, "CONTRIBUTING.md": 1,
    "pyproject.toml": 2, "package.json": 2, "Cargo.toml": 2, "go.mod": 2,
}


def _priority(relative: Path) -> tuple[int, int, str]:
    name_score = _PRIORITY_NAMES.get(relative.name, 20)
    if relative.parts and relative.parts[0] in {"docs", "doc"}:
        name_score = min(name_score, 3)
    if relative.parts and relative.parts[0] in {"src", "app", "backend", "frontend", "lib", "cmd", "pkg"}:
        name_score = min(name_score, 6)
    return (name_score, len(relative.parts), relative.as_posix())


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3, check=True
        )
        return result.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def snapshot_repository(path: str, config: RepositoryConfig) -> RepositorySnapshot:
    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repository path does not exist or is not a directory: {root}")

    candidates: list[Path] = []
    excluded = set(config.exclude_dirs)
    suffixes = set(config.include_suffixes)
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        if item.suffix not in suffixes and item.name not in _PRIORITY_NAMES:
            continue
        try:
            if item.stat().st_size > config.max_file_bytes:
                continue
        except OSError:
            continue
        candidates.append(relative)

    candidates.sort(key=_priority)
    selected = candidates[: config.max_files]
    parts: list[str] = []
    used = 0
    included: list[str] = []
    truncated = len(candidates) > len(selected)

    for relative in selected:
        absolute = root / relative
        try:
            text = absolute.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        block = f"\n\n===== FILE: {relative.as_posix()} =====\n{text}"
        remaining = config.max_context_chars - used
        if remaining <= 0:
            truncated = True
            break
        if len(block) > remaining:
            parts.append(block[:remaining])
            included.append(relative.as_posix())
            truncated = True
            used += remaining
            break
        parts.append(block)
        included.append(relative.as_posix())
        used += len(block)

    manifest = "Repository file manifest (selected):\n" + "\n".join(f"- {name}" for name in included)
    context = manifest + "".join(parts)
    return RepositorySnapshot(
        path=str(root), commit=_git_commit(root), context=context, files=included, truncated=truncated
    )
