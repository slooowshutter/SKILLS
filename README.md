# Agent Skills

This repository is the single source of truth and GitHub backup for all personal
skills used by Codex, Claude Code, and OpenCode.

## The one command

After adding, importing, editing, renaming, or deleting any skill, run:

```bash
"/Users/marclamy/Documents/Code/skills/scripts/sync-skills.sh"
```

This one command handles both jobs:

1. It imports everything waiting in `skill-inbox.txt`.
2. It completely rebuilds the globally installed personal skills from this
   repository.

You do not need a separate command for Codex, Claude Code, OpenCode, or
Conductor.

## I edited a skill—what do I do now?

1. Make sure you edited the copy inside this repository, **not** a globally
   installed copy under `~/.agents/skills` or `~/.claude/skills`.
2. Save the files.
3. Run the one command shown above.
4. Open a new agent conversation.

The command removes the old global personal installation and rebuilds everything
from this repository. You do not need to identify which agent uses the skill or
install it separately for each agent.

### Where should I edit it?

| What you are doing | Where it belongs |
| --- | --- |
| Creating or editing your own skill | `custom/<skill-name>/` |
| Keeping an unmodified third-party skill | `community/<creator>/<skill-name>/` |
| Permanently customizing a third-party skill | Copy its **whole folder** to `custom/<skill-name>/`, then edit the custom copy |

Keep the same `name:` in `SKILL.md` when creating a customized copy. Both copies
may remain in the repository: `custom/` wins over `community/` during every
sync. This protects your changes if the community version is imported again.

Do not make lasting edits directly in `~/.agents/skills` or
`~/.claude/skills`. Those are generated installations and the next sync replaces
them.

## Add or update a skill from a URL

Open `skill-inbox.txt`. For one skill, add:

```text
skill-name | https://source-url
```

For a GitHub folder containing many skills, paste its URL by itself. You can
optionally put a publisher-style collection label on the left:

```text
https://github.com/owner/repository/tree/main/skills
owner-name | https://github.com/owner/repository/tree/main/skills
```

Both of these source types are understood automatically:

```text
my-skill | https://skills.sh/owner/repository/my-skill
my-skill | https://github.com/owner/repository/tree/main/path/to/skill
```

A GitHub repository URL, a GitHub collection-folder URL, a direct skill-folder
URL, and a direct GitHub file URL are supported. A URL-only collection imports
every valid skill below that folder. With `name | URL`, the importer first looks
for that exact skill; when the name identifies the GitHub owner or repository,
it treats the entry as a collection label and imports all of them.

Now run the one command. The importer will:

1. Detect whether the URL is from skills.sh or GitHub.
2. Download each unique GitHub repository only once for that batch.
3. Find one matching folder—or every valid folder for a collection—using each
   skill's declared frontmatter name.
4. Copy each **entire skill folder** into
   `community/<owner-or-collection>/<skill-name>/`.
5. Record its original URL, repository, folder, and exact commit in
   `scripts/skill-sources.json`.
6. Remove the line from `skill-inbox.txt` only after the folder was imported.
7. Rebuild all globally installed skills once, after the whole batch.

If an import fails, its line stays in `skill-inbox.txt` and the command prints
the reason. Other valid queued skills can still be imported. To refresh a skill
that was previously imported this way, add its name and URL to the inbox again;
the tracked destination will be replaced with the new upstream version.

The importer never executes code from a downloaded repository. A source that
contains symbolic links is rejected for manual review.

## Why some skills contain many files

`SKILL.md` is the required entry point. It declares the skill's name and when an
agent should use it, then gives the main instructions. Everything beside it is
part of that skill's package and must stay in the same folder.

| Item | Typical purpose |
| --- | --- |
| `SKILL.md` | Required agent instructions and links to supporting files |
| `rules/*.md`, `references/`, `resources/` | Detailed material loaded when the skill needs it |
| `scripts/` | Helper programs the skill may instruct an agent to run |
| `AGENTS.md` | Compiled or tool-specific agent guidance |
| `README.md` | Documentation for humans maintaining the source |
| `metadata.json` | Catalog, version, author, or build metadata |

Some skills need only `SKILL.md`; others split large instructions into dozens
of rule or resource files. Both are normal. The importer does not try to guess
which supporting files matter—it copies the complete selected folder so
relative links in `SKILL.md` continue to work.

## Edit, create, rename, or delete your own skill

Make the change directly under `custom/`, then run the one command.

The repository always wins. If a skill no longer exists here, the next run
removes it from the global personal installation. If two folders declare the
same skill name, `custom/` wins over `community/`; the command prints the source
it selected. If two community sources share a name, both folders and source
records are kept; the alphabetically first path is installed.

## What synchronization replaces

The command finds every valid `SKILL.md` in this repository and installs a real
directory copy into:

- `~/.agents/skills` for Codex and OpenCode
- `~/.claude/skills` for Claude Code

It also clears obsolete non-system skills from the old agent-specific Codex and
OpenCode locations. Hidden system folders such as `~/.codex/skills/.system` are
preserved. Project-specific skills inside individual code repositories are not
touched.

The replacement is prepared before the current installation is swapped. If the
swap fails, the previous installation is restored.

## Make an updated skill appear in an agent

After the command succeeds, open a **new conversation** in Codex, Claude Code,
or OpenCode. Skills are discovered for a conversation and an already-running
conversation can retain the old instructions.

You do **not** need to restart Conductor.

## Everyday workflow

1. Put URL imports in `skill-inbox.txt`, or change a skill directly in this
   repository.
2. Run the one command.
3. Open a new agent conversation and test the skill.
4. Commit and push this repository so GitHub remains the backup.

## Fresh machine

Clone this repository to `/Users/marclamy/Documents/Code/skills`, then run the
same one command. It reconstructs the complete personal skill installation for
all three agents.

## Repository structure

- `custom/` — skills authored or intentionally customized here
- `community/` — all third-party skills, URL imports, and recovered packages
- `community/recovered/` — packages recovered from old global installations
- `skill-inbox.txt` — temporary queue of skills to import
- `scripts/skill-sources.json` — provenance for imported skills
- `scripts/` — the importer and exact synchronization implementation
