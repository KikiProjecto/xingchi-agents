#!/usr/bin/env python3
"""Build a public, project-local bundle from the user's installed skills.

Only directories containing ``SKILL.md`` are considered skills. The source
roots may alias each other and may contain links into other skill trees; those
aliases are deduplicated and links are copied only when they resolve to a
skill file. Runtime state, dependencies, credentials, and repository metadata
are excluded from the bundle.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


SKIP_DIRS = {
    ".git", ".gstack", ".cache", ".pytest_cache", "__pycache__",
    "node_modules", "dist", "build", "target", "coverage",
}
SKIP_FILES = {
    ".gstack-owned", ".DS_Store", "Thumbs.db", "support.env",
}
SKIP_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key", ".p12",
    ".pfx", ".crt", ".cer",
}
SKIP_NAMES = {".env", ".env.local", ".env.production", ".env.development"}
NAME_RE = re.compile(
    r"^name:[ \t]*(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^#\r\n]+))",
    re.MULTILINE,
)
HOME_RE = re.compile(re.escape(str(Path.home())), re.IGNORECASE)
OTHER_HOME_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:/Users/(?!Shared(?:/|$))|/home/)[^/\\\s`\"']+|"
    r"[A-Za-z]:\\Users\\[^\\\s`\"']+",
    re.IGNORECASE,
)
DB_PASSWORD_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://)[^@\n]{1,200}@",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"sk-[0-9a-fA-F]{32,}"),
    re.compile(r"(?:ghp|github_pat|xox[baprs])_[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


@dataclass
class Record:
    name: str
    source_file: Path
    source_dir: Path
    source_label: str
    digest: str
    status: str = ""
    project_name: str = ""
    output_dir: str = ""
    files: int = 0
    excluded: int = 0


def skill_name(skill_file: Path) -> str | None:
    try:
        text = skill_file.read_text(encoding="utf-8-sig")[:32768]
    except (OSError, UnicodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    match = NAME_RE.search(text[3:end])
    return next((value.strip() for value in match.groups() if value), None) if match else None


def safe_part(path: Path) -> bool:
    return not any(part in SKIP_DIRS for part in path.parts)


def excluded(path: Path) -> bool:
    if path.name in SKIP_FILES or path.name in SKIP_NAMES or path.name.startswith(".env"):
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def iter_files(root: Path, nested_skills: set[Path] | None = None):
    """Yield files below root without following links outside the skill tree."""
    visited: set[Path] = set()
    nested_skills = nested_skills or set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            real = current.resolve(strict=True)
        except OSError:
            continue
        if real in visited:
            continue
        visited.add(real)
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name.casefold(), reverse=True)
        except OSError:
            continue
        for entry in entries:
            relative = entry.relative_to(root)
            if not safe_part(relative):
                continue
            try:
                resolved_entry = entry.resolve(strict=True)
            except OSError:
                continue
            if resolved_entry in nested_skills:
                continue
            if entry.is_symlink():
                # A link is useful only when it resolves to a regular file
                # inside the source skill directory. Never reproduce links.
                try:
                    target = entry.resolve(strict=True)
                except OSError:
                    continue
                if target.is_file() and root.resolve() in target.parents and not excluded(entry):
                    yield entry, target
                elif target.is_dir() and root.resolve() in target.parents:
                    stack.append(entry)
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file() and not excluded(entry):
                yield entry, entry


def tree_digest(directory: Path, nested_skills: set[Path] | None = None) -> str:
    digest = hashlib.sha256()
    for path, resolved in sorted(iter_files(directory, nested_skills), key=lambda pair: pair[0].relative_to(directory).as_posix()):
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(resolved.read_bytes())
    return digest.hexdigest()


def rewrite_public_text(text: str, old_name: str, new_name: str) -> str:
    text = HOME_RE.sub("<HOME>", text)
    text = OTHER_HOME_RE.sub("<HOME>", text)
    text = DB_PASSWORD_RE.sub(r"\1<REDACTED>@", text)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED CREDENTIAL EXAMPLE]", text)
    if old_name != new_name:
        pattern = re.compile(
            r"^(name:[ \t]*)(?:\"[^\"\n]+\"|'[^'\n]+'|[^#\r\n]+)([ \t]*(?:#.*)?)$",
            re.MULTILINE,
        )
        text = pattern.sub(lambda match: f'{match.group(1)}"{new_name}"{match.group(2)}', text, count=1)
    return text


def slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return result or "skill"


def copy_skill(source: Path, target: Path, old_name: str, new_name: str, nested_skills: set[Path]) -> tuple[int, int]:
    files = excluded_count = 0
    target.mkdir(parents=True, exist_ok=False)
    for path, resolved in iter_files(source, nested_skills):
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = resolved.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            shutil.copyfile(resolved, destination)
        else:
            destination.write_text(rewrite_public_text(text, old_name, new_name), encoding="utf-8")
        files += 1
    return files, excluded_count


def discover(roots: list[Path], labels: dict[Path, str]) -> list[Record]:
    records: list[Record] = []
    seen_dirs: set[Path] = set()
    seen_walk_dirs: set[tuple[int, int]] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root, followlinks=True):
            current_path = Path(current)
            try:
                stat = current_path.stat()
                identity = (stat.st_dev, stat.st_ino)
            except OSError:
                dirs[:] = []
                continue
            if identity in seen_walk_dirs:
                dirs[:] = []
                continue
            seen_walk_dirs.add(identity)
            # Do not descend into dependency/runtime trees or arbitrary
            # linked repositories. A linked directory is eligible only when
            # it is itself a skill directory with a direct SKILL.md.
            kept_dirs = []
            for name in dirs:
                if name in SKIP_DIRS:
                    continue
                candidate = current_path / name
                if candidate.is_symlink():
                    try:
                        target = candidate.resolve(strict=True)
                    except OSError:
                        continue
                    if not target.is_dir() or not (target / "SKILL.md").is_file():
                        continue
                kept_dirs.append(name)
            dirs[:] = kept_dirs
            skill_path = current_path / "SKILL.md"
            if not skill_path.is_file():
                continue
            try:
                resolved_file = skill_path.resolve(strict=True)
                resolved_dir = resolved_file.parent
            except OSError:
                continue
            if resolved_dir in seen_dirs:
                continue
            seen_dirs.add(resolved_dir)
            name = skill_name(resolved_file) or resolved_dir.name
            try:
                relative = resolved_dir.relative_to(root.resolve())
                label = f"{labels.get(root, '~/.skills')}/{relative.as_posix()}"
            except ValueError:
                label = f"{labels.get(root, '~/.skills')}/linked/{resolved_dir.name}"
            records.append(Record(name, resolved_file, resolved_dir, label, ""))
    skill_dirs = {record.source_dir for record in records}
    for record in records:
        nested = {directory for directory in skill_dirs if directory != record.source_dir and record.source_dir in directory.parents}
        record.digest = tree_digest(record.source_dir, nested)
    return records


def write_inventory(path: Path, records: list[Record], roots: list[Path], excluded_summary: list[str]) -> None:
    copied = sum(record.status in {"copied", "renamed"} for record in records)
    duplicates = sum(record.status == "identical-duplicate" for record in records)
    renamed = sum(record.status == "renamed" for record in records)
    lines = [
        "# Project Skill Inventory",
        "",
        "This file is generated by `scripts/sync-skills.py`.",
        "It inventories the public project-local bundle in this directory.",
        "",
        f"- Copied skill directories: {copied}",
        f"- Identical duplicates omitted: {duplicates}",
        f"- Divergent variants renamed: {renamed}",
        "- Source roots scanned: `~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills`",
        "- Absolute home paths are redacted as `<HOME>` when found in text files.",
        "- Credentials, local runtime state, dependencies, and repository metadata are excluded.",
        "- Third-party license and redistribution terms require human review.",
        "",
        "## Exclusions",
        "",
    ]
    lines.extend(f"- {item}" for item in excluded_summary) if excluded_summary else lines.append("- Standard runtime, dependency, credential, and cache patterns.")
    lines.extend([
        "",
        "## Skills",
        "",
        "| Project directory | Declared name | Status | Source label | Files |",
        "| --- | --- | --- | --- | ---: |",
    ])
    for record in sorted(records, key=lambda item: (item.project_name.casefold(), item.source_label.casefold())):
        lines.append(f"| `{record.output_dir or '-'}" + f"` | `{record.name}` | {record.status} | `{record.source_label}` | {record.files} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="project-local skills directory")
    parser.add_argument("--source", action="append", type=Path, dest="sources")
    args = parser.parse_args(argv)

    project_root = args.project_root.expanduser().resolve()
    output = (args.output or project_root / "skills").expanduser().resolve()
    source_specs = args.sources or [Path("~/.agents/skills"), Path("~/.claude/skills"), Path("~/.codex/skills")]
    labels: dict[Path, str] = {}
    roots: list[Path] = []
    for source in source_specs:
        expanded = source.expanduser()
        resolved = expanded.resolve()
        roots.append(resolved)
        labels.setdefault(resolved, source.as_posix())
    if output == project_root or project_root not in output.parents:
        print("error: output must be a child directory of the project root", file=sys.stderr)
        return 2
    if any(root == output or output in root.parents for root in roots):
        print("error: output cannot be inside a skill source root", file=sys.stderr)
        return 2
    if output.exists() and any(output.iterdir()):
        print(f"error: output is not empty: {output}; move it aside before syncing", file=sys.stderr)
        return 2

    records = discover(roots, labels)
    if not records:
        print("error: no SKILL.md files found in configured skill roots", file=sys.stderr)
        return 1

    by_name: dict[str, list[Record]] = {}
    for record in records:
        by_name.setdefault(record.name.casefold(), []).append(record)

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    used_dirs: set[str] = set()
    try:
        for group in sorted(by_name.values(), key=lambda items: items[0].name.casefold()):
            first_digest = group[0].digest
            seen_digests: dict[str, Record] = {}
            for index, record in enumerate(group):
                if record.digest in seen_digests:
                    record.status = "identical-duplicate"
                    duplicate_of = seen_digests[record.digest]
                    record.project_name = duplicate_of.project_name
                    record.output_dir = duplicate_of.output_dir
                    continue
                seen_digests[record.digest] = record
                record.status = "copied" if not seen_digests or len(seen_digests) == 1 else "renamed"
                record.project_name = record.name if record.status == "copied" else f"{record.name}--variant-{record.digest[:8]}"
                base = slug(record.project_name)
                target_name = base
                collision = 1
                while target_name.casefold() in used_dirs:
                    target_name = f"{base}-{record.digest[:8]}-{collision}"
                    collision += 1
                used_dirs.add(target_name.casefold())
                record.output_dir = target_name
                nested = {item.source_dir for item in records if item.source_dir != record.source_dir and record.source_dir in item.source_dir.parents}
                record.files, record.excluded = copy_skill(record.source_dir, temp / target_name, record.name, record.project_name, nested)
        write_inventory(temp / "LIST.md", records, roots, [])
        if output.exists():
            if any(output.iterdir()):
                raise RuntimeError(f"output became non-empty during sync: {output}")
            output.rmdir()
        temp.rename(output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise

    copied = sum(record.status in {"copied", "renamed"} for record in records)
    print(f"synced {copied} skill directories into {output}")
    print(f"wrote inventory {output / 'LIST.md'}")
    print(f"omitted identical duplicates: {sum(record.status == 'identical-duplicate' for record in records)}")
    print(f"renamed conflicting variants: {sum(record.status == 'renamed' for record in records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
