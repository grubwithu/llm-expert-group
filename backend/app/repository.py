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


def _candidate_files(root: Path, config: RepositoryConfig) -> list[Path]:
    candidates: list[Path] = []
    excluded = set(config.exclude_dirs)
    suffixes = set(config.include_suffixes)
    for item in root.rglob("*"):
        # Never follow repository symlinks into content outside the configured
        # root. Secretary.read() also resolves paths defensively, but the
        # initial snapshot/search candidate walk must enforce the same rule.
        if item.is_symlink() or not item.is_file():
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
    return candidates


class RepositoryWorkspace:
    """Read-only repository tools used by the Secretary role."""

    def __init__(self, path: str, config: RepositoryConfig):
        self.root = Path(path).expanduser().resolve()
        self.config = config
        if not self.root.exists() or not self.root.is_dir():
            raise ValueError(f"repository path does not exist or is not a directory: {self.root}")

    @property
    def commit(self) -> str | None:
        return _git_commit(self.root)

    def _safe_relative(self, value: str) -> Path:
        candidate = (self.root / value).resolve()
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("path escapes repository root") from exc
        if any(part in set(self.config.exclude_dirs) for part in relative.parts):
            raise ValueError("path is inside an excluded directory")
        return relative

    def list_tree(self, path: str = "", *, max_entries: int = 200) -> str:
        relative = self._safe_relative(path or ".")
        base = self.root / relative
        if not base.exists():
            raise ValueError(f"path does not exist: {path}")
        if base.is_file():
            return relative.as_posix()
        lines: list[str] = []
        excluded = set(self.config.exclude_dirs)
        for item in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            rel = item.relative_to(self.root)
            if any(part in excluded for part in rel.parts):
                continue
            suffix = "/" if item.is_dir() else ""
            lines.append(rel.as_posix() + suffix)
            if len(lines) >= max_entries:
                lines.append("... truncated ...")
                break
        return "\n".join(lines) or "(empty)"

    def search(self, query: str, *, path: str = "", max_results: int = 40) -> str:
        needle = query.strip().lower()
        if not needle:
            raise ValueError("search query must not be empty")
        scope = self.root / self._safe_relative(path or ".")
        if not scope.exists():
            raise ValueError(f"path does not exist: {path}")
        candidates = _candidate_files(self.root, self.config)
        results: list[str] = []
        for relative in candidates:
            absolute = self.root / relative
            try:
                absolute.relative_to(scope) if scope.is_dir() else None
            except ValueError:
                continue
            if scope.is_file() and absolute != scope:
                continue
            try:
                lines = absolute.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if needle in line.lower():
                    snippet = line.strip()
                    if len(snippet) > 240:
                        snippet = snippet[:237] + "..."
                    results.append(f"{relative.as_posix()}:{number}: {snippet}")
                    if len(results) >= max_results:
                        return "\n".join(results)
        return "\n".join(results) or "(no matches)"

    def read(self, path: str, *, start_line: int = 1, end_line: int = 220) -> str:
        relative = self._safe_relative(path)
        absolute = self.root / relative
        if not absolute.exists() or not absolute.is_file():
            raise ValueError(f"file does not exist: {path}")
        if absolute.stat().st_size > self.config.max_file_bytes:
            raise ValueError(f"file exceeds configured size limit: {path}")
        start_line = max(1, int(start_line))
        end_line = max(start_line, int(end_line))
        end_line = min(end_line, start_line + 399)
        lines = absolute.read_text(encoding="utf-8", errors="replace").splitlines()
        if start_line > len(lines) and lines:
            raise ValueError(f"start_line {start_line} exceeds file length {len(lines)}")
        selected = lines[start_line - 1:end_line]
        return "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line)) or "(empty file/range)"

    def evidence_excerpt(self, path: str, start_line: int, end_line: int) -> str | None:
        try:
            return self.read(path, start_line=start_line, end_line=end_line)
        except (ValueError, OSError):
            return None

    def git_log(self, *, max_entries: int = 20) -> str:
        count = min(max(1, int(max_entries)), 50)
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "log", f"-{count}", "--oneline", "--decorate=no"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            return result.stdout.strip() or "(no commits)"
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return f"(git log unavailable: {exc})"

    def git_diff(self, *, path: str = "") -> str:
        args = ["git", "-C", str(self.root), "diff", "--no-ext-diff", "--"]
        if path:
            relative = self._safe_relative(path)
            args.append(relative.as_posix())
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=True)
            text = result.stdout.strip()
            if len(text) > 30_000:
                text = text[:30_000] + "\n... diff truncated ..."
            return text or "(working tree has no matching unstaged diff)"
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return f"(git diff unavailable: {exc})"


def snapshot_repository(path: str, config: RepositoryConfig) -> RepositorySnapshot:
    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repository path does not exist or is not a directory: {root}")

    candidates = _candidate_files(root, config)
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
