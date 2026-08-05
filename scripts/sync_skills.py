#!/usr/bin/env python3
"""Rebuild global agent skills from this repository."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXCLUDED_TOP_LEVEL = {
    ".agents",
    ".claude",
    ".codex",
    ".conductor",
    ".context",
    ".git",
    ".opencode",
    "node_modules",
    "scripts",
    "skills",
}
EXCLUDED_PARTS = {
    ".context",
    ".git",
    "__pycache__",
    "node_modules",
}


class SyncError(RuntimeError):
    """Raised when a safe exact sync cannot be completed."""


@dataclass(frozen=True)
class SkillSource:
    name: str
    directory: Path
    relative_skill_file: Path
    priority: int


@dataclass
class Replacement:
    target: Path
    candidate: Path
    backup: Path | None = None


def parse_frontmatter(skill_file: Path) -> tuple[str, str]:
    lines = skill_file.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SyncError(f"Missing YAML frontmatter: {skill_file}")

    fields: dict[str, str] = {}
    multiline_key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if match:
            key, value = match.groups()
            normalized = value.strip().strip("'\"")
            fields[key] = normalized
            multiline_key = key if normalized in {"", "|", "|-", ">", ">-"} else None
            continue
        if multiline_key and line[:1].isspace() and line.strip():
            existing = fields[multiline_key]
            if existing in {"", "|", "|-", ">", ">-"}:
                existing = ""
            fields[multiline_key] = f"{existing} {line.strip()}".strip()
    else:
        raise SyncError(f"Unclosed YAML frontmatter: {skill_file}")

    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name:
        raise SyncError(f"Missing frontmatter name: {skill_file}")
    if not description:
        raise SyncError(f"Missing frontmatter description: {skill_file}")
    if not NAME_PATTERN.fullmatch(name):
        raise SyncError(f"Invalid skill name '{name}': {skill_file}")
    return name, description


def source_priority(relative_path: Path) -> int:
    if relative_path.parts[0] == "custom":
        return 0
    if relative_path.parts[0] == "community":
        return 1
    return 2


def discover_skills() -> tuple[dict[str, SkillSource], dict[str, list[SkillSource]]]:
    candidates: dict[str, list[SkillSource]] = {}

    for skill_file in sorted(REPO_ROOT.rglob("SKILL.md")):
        relative = skill_file.relative_to(REPO_ROOT)
        if relative.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue

        name, _ = parse_frontmatter(skill_file)
        source = SkillSource(
            name=name,
            directory=skill_file.parent,
            relative_skill_file=relative,
            priority=source_priority(relative),
        )
        candidates.setdefault(name, []).append(source)

    if not candidates:
        raise SyncError(f"No skills found under {REPO_ROOT}")

    selected: dict[str, SkillSource] = {}
    duplicates: dict[str, list[SkillSource]] = {}
    for name, sources in candidates.items():
        ordered = sorted(
            sources,
            key=lambda source: (source.priority, source.relative_skill_file.as_posix()),
        )
        selected[name] = ordered[0]
        if len(ordered) > 1:
            duplicates[name] = ordered

    return selected, duplicates


def ignore_generated(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in EXCLUDED_PARTS or name == ".DS_Store" or name.endswith(".pyc")
    }


def copy_path(source: Path, destination: Path) -> None:
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(
            source,
            destination,
            symlinks=False,
            ignore=ignore_generated,
        )
    elif source.is_symlink():
        resolved = source.resolve(strict=True)
        copy_path(resolved, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def build_catalog(selected: dict[str, SkillSource], staging_root: Path) -> Path:
    catalog = staging_root / "catalog"
    catalog.mkdir()
    for name in sorted(selected):
        copy_path(selected[name].directory, catalog / name)
    return catalog


def path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def remove_path(path: Path) -> None:
    if not path_exists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def preserve_hidden_entries(target: Path, candidate: Path) -> None:
    if not target.is_dir() or target.is_symlink():
        return
    for child in target.iterdir():
        if child.name.startswith(".") and not path_exists(candidate / child.name):
            copy_path(child, candidate / child.name)


def prepare_replacement(
    target: Path,
    *,
    catalog: Path | None,
    token: str,
) -> Replacement:
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate = target.parent / f".{target.name}.sync-new-{token}"
    remove_path(candidate)

    if catalog is None:
        candidate.mkdir()
    else:
        shutil.copytree(catalog, candidate, symlinks=False)
    preserve_hidden_entries(target, candidate)
    return Replacement(target=target, candidate=candidate)


def apply_replacements(replacements: list[Replacement], token: str) -> None:
    started: list[Replacement] = []
    try:
        for replacement in replacements:
            started.append(replacement)
            if path_exists(replacement.target):
                replacement.backup = replacement.target.parent / (
                    f".{replacement.target.name}.sync-old-{token}"
                )
                remove_path(replacement.backup)
                os.replace(replacement.target, replacement.backup)
            os.replace(replacement.candidate, replacement.target)
    except Exception:
        for replacement in reversed(started):
            remove_path(replacement.target)
            if replacement.backup and path_exists(replacement.backup):
                os.replace(replacement.backup, replacement.target)
        raise
    else:
        for replacement in replacements:
            if replacement.backup:
                remove_path(replacement.backup)
    finally:
        for replacement in replacements:
            remove_path(replacement.candidate)


def reset_installer_lock(target_home: Path) -> None:
    lock_path = target_home / ".agents" / ".skill-lock.json"
    if not lock_path.parent.is_dir():
        return
    lock = {"version": 3, "skills": {}, "dismissed": {}}
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def sync(target_home: Path) -> int:
    if not target_home.is_absolute():
        raise SyncError("The target home must be an absolute path")

    selected, duplicates = discover_skills()
    if duplicates:
        print("Duplicate names found; deterministic precedence was applied:")
        for name in sorted(duplicates):
            chosen = selected[name].relative_skill_file
            skipped = [
                source.relative_skill_file
                for source in duplicates[name]
                if source != selected[name]
            ]
            print(f"  {name}: using {chosen}")
            for path in skipped:
                print(f"    skipped {path}")
        print()

    with tempfile.TemporaryDirectory(prefix="skills-sync-") as temporary:
        staging_root = Path(temporary)
        catalog = build_catalog(selected, staging_root)
        token = uuid.uuid4().hex[:12]
        replacements = [
            prepare_replacement(
                target_home / ".agents" / "skills",
                catalog=catalog,
                token=token,
            ),
            prepare_replacement(
                target_home / ".claude" / "skills",
                catalog=catalog,
                token=token,
            ),
            prepare_replacement(
                target_home / ".codex" / "skills",
                catalog=None,
                token=token,
            ),
            prepare_replacement(
                target_home / ".config" / "opencode" / "skills",
                catalog=None,
                token=token,
            ),
        ]
        apply_replacements(replacements, token)

    reset_installer_lock(target_home)
    print(f"Synced {len(selected)} skills from {REPO_ROOT}")
    print(f"  Codex and OpenCode: {target_home / '.agents' / 'skills'}")
    print(f"  Claude Code:        {target_home / '.claude' / 'skills'}")
    print("Open a new agent conversation to use the rebuilt skill set.")
    print("You do not need to restart Conductor.")
    return len(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="Override the target home directory (intended for isolated testing)",
    )
    args = parser.parse_args()

    try:
        sync(args.home.expanduser().resolve())
    except (OSError, SyncError) as error:
        print(f"Sync failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
