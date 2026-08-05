#!/usr/bin/env python3
"""Import queued GitHub and skills.sh skills into the central skills repository."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from sync_skills import (
    EXCLUDED_PARTS,
    SyncError,
    parse_frontmatter,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
INBOX_PATH = REPO_ROOT / "skill-inbox.txt"
MANIFEST_PATH = REPO_ROOT / "scripts" / "skill-sources.json"
COMMUNITY_ROOT = REPO_ROOT / "community"


class ImportError(RuntimeError):
    """Raised when a queued skill cannot be imported safely."""


@dataclass(frozen=True)
class QueueEntry:
    line_number: int
    raw_line: str
    requested_name: str | None
    lookup_name: str | None
    url: str

    @property
    def label(self) -> str:
        return self.requested_name or self.url


@dataclass(frozen=True)
class SourceSpec:
    provider: str
    owner: str
    repository: str
    ref: str | None
    subpath: PurePosixPath | None
    url_skill_name: str | None
    original_url: str

    @property
    def github_repository(self) -> str:
        return f"{self.owner}/{self.repository}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.github_repository}.git"

    @property
    def cache_key(self) -> tuple[str, str, str | None]:
        return self.owner.lower(), self.repository.lower(), self.ref


@dataclass(frozen=True)
class ResolvedSkill:
    directory: Path
    name: str
    description: str
    relative_path: str


def slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ImportError(f"Cannot turn '{value}' into a skill name")
    return slug


def parse_queue(inbox_path: Path) -> tuple[list[str], list[QueueEntry], list[str]]:
    if not inbox_path.exists():
        inbox_path.write_text(
            "# Add one skill per line: name | URL (or just a collection URL)\n",
            encoding="utf-8",
        )

    lines = inbox_path.read_text(encoding="utf-8").splitlines()
    entries: list[QueueEntry] = []
    errors: list[str] = []
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "|" not in stripped and stripped.startswith(("https://", "http://")):
            entries.append(
                QueueEntry(
                    line_number=index + 1,
                    raw_line=raw_line,
                    requested_name=None,
                    lookup_name=None,
                    url=stripped,
                )
            )
            continue
        if "|" not in stripped:
            errors.append(
                f"line {index + 1}: expected 'name | URL' or a URL (left unchanged)"
            )
            continue
        requested_name, url = (part.strip() for part in stripped.split("|", 1))
        if not requested_name or not url:
            errors.append(
                f"line {index + 1}: both name and URL are required (left unchanged)"
            )
            continue
        try:
            lookup_name = slugify_name(requested_name)
        except ImportError as error:
            errors.append(f"line {index + 1}: {error} (left unchanged)")
            continue
        entries.append(
            QueueEntry(
                line_number=index + 1,
                raw_line=raw_line,
                requested_name=requested_name,
                lookup_name=lookup_name,
                url=url,
            )
        )
    return lines, entries, errors


def clean_repository_name(value: str) -> str:
    repository = value.removesuffix(".git")
    if not repository:
        raise ImportError("The GitHub repository name is missing")
    return repository


def parse_source_url(url: str) -> SourceSpec:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [unquote(part) for part in parsed.path.split("/") if part]

    if parsed.scheme not in {"http", "https"}:
        raise ImportError("Only https:// or http:// source URLs are supported")

    if host in {"skills.sh", "www.skills.sh"}:
        if len(parts) < 3:
            raise ImportError(
                "A skills.sh URL must contain owner/repository/skill-name"
            )
        owner, repository, skill_name = parts[:3]
        return SourceSpec(
            provider="skills.sh",
            owner=owner,
            repository=clean_repository_name(repository),
            ref=None,
            subpath=None,
            url_skill_name=slugify_name(skill_name),
            original_url=url,
        )

    if host == "github.com":
        if len(parts) < 2:
            raise ImportError("A GitHub URL must contain owner/repository")
        owner, repository = parts[:2]
        repository = clean_repository_name(repository)
        ref: str | None = None
        subpath: PurePosixPath | None = None
        if len(parts) > 2:
            route = parts[2]
            if route in {"tree", "blob"}:
                if len(parts) < 4:
                    raise ImportError(f"The GitHub {route} URL is incomplete")
                ref = parts[3]
                remaining = parts[4:]
                if route == "blob" and remaining:
                    remaining = remaining[:-1]
                if remaining:
                    subpath = PurePosixPath(*remaining)
            else:
                raise ImportError(
                    "Use a GitHub repository, /tree/... folder, or /blob/... file URL"
                )
        return SourceSpec(
            provider="github",
            owner=owner,
            repository=repository,
            ref=ref,
            subpath=subpath,
            url_skill_name=None,
            original_url=url,
        )

    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            raise ImportError("The raw GitHub URL is incomplete")
        owner, repository, ref = parts[:3]
        remaining = parts[3:-1]
        return SourceSpec(
            provider="github",
            owner=owner,
            repository=clean_repository_name(repository),
            ref=ref,
            subpath=PurePosixPath(*remaining) if remaining else None,
            url_skill_name=None,
            original_url=url,
        )

    raise ImportError(
        f"Unsupported source '{host or url}'; use a GitHub or skills.sh URL"
    )


class CloneCache:
    """Shallow-clone each unique repository/ref at most once per batch."""

    def __init__(self, temporary_root: Path) -> None:
        self.temporary_root = temporary_root
        self._checkouts: dict[tuple[str, str, str | None], tuple[Path, str]] = {}

    def checkout(self, source: SourceSpec) -> tuple[Path, str]:
        cached = self._checkouts.get(source.cache_key)
        if cached:
            return cached

        checkout = self.temporary_root / f"repo-{len(self._checkouts) + 1}"
        command = ["git", "clone", "--depth", "1", "--no-tags"]
        if source.ref:
            command.extend(["--branch", source.ref])
        command.extend([source.clone_url, str(checkout)])

        print(f"Downloading {source.github_repository}...")
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                env=environment,
            )
        except FileNotFoundError as error:
            raise ImportError("git is required to import queued skills") from error
        except subprocess.TimeoutExpired as error:
            raise ImportError(
                f"Timed out downloading {source.github_repository}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            message = detail[-1] if detail else "git clone failed"
            raise ImportError(f"Could not download {source.github_repository}: {message}")

        commit_result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if commit_result.returncode != 0:
            raise ImportError(f"Could not identify {source.github_repository} commit")
        resolved = checkout, commit_result.stdout.strip()
        self._checkouts[source.cache_key] = resolved
        return resolved


def candidate_skill_files(base: Path) -> list[Path]:
    candidates: list[Path] = []
    direct = base / "SKILL.md"
    if direct.is_file():
        candidates.append(direct)
    for skill_file in sorted(base.rglob("SKILL.md")):
        if skill_file == direct:
            continue
        relative = skill_file.relative_to(base)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        candidates.append(skill_file)
    return candidates


def source_base_directory(checkout: Path, source: SourceSpec) -> tuple[Path, Path]:
    checkout_root = checkout.resolve()
    base = checkout_root
    if source.subpath:
        base = (checkout_root / Path(*source.subpath.parts)).resolve()
        try:
            base.relative_to(checkout_root)
        except ValueError as error:
            raise ImportError("The GitHub folder path escapes the repository") from error
    if not base.is_dir():
        label = source.subpath.as_posix() if source.subpath else "."
        raise ImportError(f"Source folder does not exist: {label}")
    return checkout_root, base


def resolve_all_skill_directories(
    checkout: Path,
    source: SourceSpec,
) -> tuple[list[ResolvedSkill], Path]:
    checkout_root, base = source_base_directory(checkout, source)
    resolved: list[ResolvedSkill] = []
    parse_failures: list[str] = []
    for skill_file in candidate_skill_files(base):
        try:
            name, description = parse_frontmatter(skill_file)
        except (OSError, SyncError) as error:
            parse_failures.append(str(error))
            continue
        resolved.append(
            ResolvedSkill(
                directory=skill_file.parent,
                name=name,
                description=description,
                relative_path=skill_file.parent.relative_to(checkout_root).as_posix(),
            )
        )

    if not resolved:
        detail = f" ({parse_failures[0]})" if parse_failures else ""
        raise ImportError(f"No valid SKILL.md found in the source folder{detail}")

    by_name: dict[str, list[ResolvedSkill]] = {}
    for skill in resolved:
        by_name.setdefault(skill.name, []).append(skill)
    duplicates = {name: skills for name, skills in by_name.items() if len(skills) > 1}
    if duplicates:
        name = sorted(duplicates)[0]
        paths = ", ".join(skill.relative_path for skill in duplicates[name])
        raise ImportError(f"Source declares '{name}' more than once: {paths}")
    return sorted(resolved, key=lambda skill: skill.name), base


def resolve_skill_directory(
    checkout: Path,
    source: SourceSpec,
    lookup_name: str,
) -> ResolvedSkill:
    resolved_skills, base = resolve_all_skill_directories(checkout, source)
    candidates: list[tuple[int, ResolvedSkill]] = []
    for skill in resolved_skills:
        directory_name = slugify_name(skill.directory.name)
        score = 0
        if skill.name == lookup_name:
            score = max(score, 100)
        if directory_name == lookup_name:
            score = max(score, 90)
        if source.url_skill_name and skill.name == source.url_skill_name:
            score = max(score, 80)
        if source.url_skill_name and directory_name == source.url_skill_name:
            score = max(score, 70)
        if skill.directory == base:
            score = max(score, 60)
        candidates.append((score, skill))

    best_score = max(score for score, _ in candidates)
    best = [skill for score, skill in candidates if score == best_score]
    if best_score == 0 and len(candidates) == 1:
        return candidates[0][1]
    if best_score == 0:
        names = ", ".join(sorted({skill.name for _, skill in candidates})[:8])
        raise ImportError(
            f"Could not match '{lookup_name}' to a skill. Found: {names}"
        )
    if len(best) > 1:
        paths = ", ".join(skill.relative_path for skill in best[:8])
        raise ImportError(f"Skill name is ambiguous; matching folders: {paths}")
    return best[0]


def compact_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def is_collection_label(entry: QueueEntry, source: SourceSpec) -> bool:
    if entry.lookup_name is None:
        return True
    requested = compact_name(entry.lookup_name)
    labels = {
        "all",
        "allskills",
        "skills",
        compact_name(source.owner),
        compact_name(source.repository),
        compact_name(f"{source.owner}-{source.repository}"),
    }
    return requested in labels


def resolve_entry_skills(
    entry: QueueEntry,
    checkout: Path,
    source: SourceSpec,
) -> tuple[list[ResolvedSkill], str]:
    if source.url_skill_name:
        return [
            resolve_skill_directory(checkout, source, source.url_skill_name)
        ], slugify_name(source.owner)

    if entry.lookup_name is None:
        all_skills, base = resolve_all_skill_directories(checkout, source)
        direct = [skill for skill in all_skills if skill.directory == base]
        if direct:
            return direct, slugify_name(source.owner)
        return all_skills, slugify_name(source.owner)

    try:
        return [
            resolve_skill_directory(checkout, source, entry.lookup_name)
        ], slugify_name(source.owner)
    except ImportError:
        if not is_collection_label(entry, source):
            raise

    all_skills, _ = resolve_all_skill_directories(checkout, source)
    print(
        f"  collection: '{entry.requested_name}' selects all "
        f"{len(all_skills)} skills in this folder"
    )
    return all_skills, entry.lookup_name


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {"version": 1, "skills": {}}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportError(f"Cannot read source manifest: {error}") from error
    if manifest.get("version") != 1 or not isinstance(manifest.get("skills"), dict):
        raise ImportError("scripts/skill-sources.json has an unsupported format")
    return manifest


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.new-{uuid.uuid4().hex[:12]}"
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def relative_manifest_destination(
    repo_root: Path,
    community_root: Path,
    source: SourceSpec,
    resolved: ResolvedSkill,
    manifest: dict,
    group_name: str,
) -> Path:
    previous = manifest["skills"].get(resolved.name)
    if previous:
        relative = Path(previous.get("destination", ""))
        if not relative.parts:
            raise ImportError(f"Stored destination for {resolved.name} is invalid")
    else:
        relative = (community_root / group_name / resolved.name).relative_to(repo_root)

    if relative.is_absolute() or ".." in relative.parts:
        raise ImportError(f"Stored destination for {resolved.name} is unsafe")
    if not relative.parts or relative.parts[0] != "community":
        raise ImportError(
            f"Stored destination for {resolved.name} is outside community"
        )
    return relative


def validate_source_tree(source_directory: Path) -> None:
    for path in source_directory.rglob("*"):
        if path.is_symlink():
            relative = path.relative_to(source_directory)
            raise ImportError(
                f"The skill contains a symbolic link ({relative}); import it manually after review"
            )


def ignore_download_noise(_directory: str, names: list[str]) -> set[str]:
    ignored = {".DS_Store", ".git", ".venv", "__pycache__", "node_modules"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def remove_exact_path(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def install_skill_directory(source_directory: Path, destination: Path) -> None:
    validate_source_tree(source_directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    candidate = destination.parent / f".{destination.name}.import-new-{token}"
    backup = destination.parent / f".{destination.name}.import-old-{token}"
    remove_exact_path(candidate)
    remove_exact_path(backup)

    try:
        shutil.copytree(
            source_directory,
            candidate,
            symlinks=False,
            ignore=ignore_download_noise,
        )
        if os.path.lexists(destination):
            if destination.is_symlink() or not destination.is_dir():
                raise ImportError(f"Destination is not a normal directory: {destination}")
            os.replace(destination, backup)
        os.replace(candidate, destination)
    except Exception:
        remove_exact_path(candidate)
        if os.path.lexists(backup):
            remove_exact_path(destination)
            os.replace(backup, destination)
        raise
    else:
        remove_exact_path(backup)


def import_entry(
    entry: QueueEntry,
    *,
    repo_root: Path,
    community_root: Path,
    manifest: dict,
    clones: CloneCache,
) -> tuple[list[tuple[str, Path]], list[str]]:
    source = parse_source_url(entry.url)
    checkout, commit = clones.checkout(source)
    resolved_skills, group_name = resolve_entry_skills(entry, checkout, source)
    imports: list[tuple[str, Path]] = []
    failures: list[str] = []
    for resolved in resolved_skills:
        try:
            relative_destination = relative_manifest_destination(
                repo_root,
                community_root,
                source,
                resolved,
                manifest,
                group_name,
            )
            destination = repo_root / relative_destination
            install_skill_directory(resolved.directory, destination)
            installed_name, _ = parse_frontmatter(destination / "SKILL.md")
            if installed_name != resolved.name:
                raise ImportError(
                    f"Imported skill changed name unexpectedly to '{installed_name}'"
                )
        except (ImportError, OSError, SyncError) as error:
            failures.append(f"{resolved.name}: {error}")
            continue

        manifest["skills"][resolved.name] = {
            "source_url": entry.url,
            "provider": source.provider,
            "repository": source.github_repository,
            "ref": source.ref,
            "source_path": resolved.relative_path,
            "commit": commit,
            "destination": relative_destination.as_posix(),
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
        imports.append((resolved.name, relative_destination))

    if len(resolved_skills) == 1 and entry.lookup_name not in {
        None,
        resolved_skills[0].name,
    }:
        print(
            f"  note: '{entry.requested_name}' resolved to declared skill name "
            f"'{resolved_skills[0].name}'"
        )
    return imports, failures


def run_imports(
    *,
    repo_root: Path = REPO_ROOT,
    inbox_path: Path = INBOX_PATH,
    manifest_path: Path = MANIFEST_PATH,
    community_root: Path = COMMUNITY_ROOT,
) -> int:
    lines, entries, format_errors = parse_queue(inbox_path)
    if not entries and not format_errors:
        return 0

    manifest = load_manifest(manifest_path)
    successful_lines: set[int] = set()
    failures = list(format_errors)
    imports: list[tuple[str, Path]] = []

    with tempfile.TemporaryDirectory(prefix="skill-imports-") as temporary:
        clones = CloneCache(Path(temporary))
        for entry in entries:
            try:
                entry_imports, entry_failures = import_entry(
                    entry,
                    repo_root=repo_root,
                    community_root=community_root,
                    manifest=manifest,
                    clones=clones,
                )
            except (ImportError, OSError, SyncError) as error:
                failures.append(
                    f"line {entry.line_number} ({entry.label}): {error}"
                )
                continue
            imports.extend(entry_imports)
            if entry_failures:
                for error in entry_failures:
                    failures.append(
                        f"line {entry.line_number} ({entry.label}): {error}"
                    )
            else:
                successful_lines.add(entry.line_number)

    if imports:
        atomic_write(
            manifest_path,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        remaining = [
            line
            for line_number, line in enumerate(lines, start=1)
            if line_number not in successful_lines
        ]
        atomic_write(inbox_path, "\n".join(remaining).rstrip() + "\n")
        print("Imported queued skills:")
        for skill_name, destination in imports:
            print(f"  {skill_name} -> {destination}")

    if failures:
        print("Queued skill imports with errors:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print("Failed lines remain in skill-inbox.txt.", file=sys.stderr)
        return 2
    return 0


def main() -> None:
    try:
        status = run_imports()
    except (ImportError, OSError) as error:
        print(f"Skill import failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    raise SystemExit(status)


if __name__ == "__main__":
    main()
