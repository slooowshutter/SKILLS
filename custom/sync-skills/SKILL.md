---
name: sync-skills
description: Import queued skills and rebuild all personal Codex, Claude Code, and OpenCode skills from the central skills repository. Use this skill whenever the user asks to add a skill from GitHub or skills.sh, or asks to sync, refresh, reinstall, rebuild, update, add, or remove global agent skills.
compatibility: macOS with Python 3 and the skills repository at /Users/marclamy/Documents/Code/skills
---

# Sync Skills

Use the central repository at `/Users/marclamy/Documents/Code/skills`.

When the user asks to install one skill from GitHub or skills.sh, add one line to
`skill-inbox.txt` in this form:

```text
skill-name | https://source-url
```

For a GitHub folder containing a collection of skills, add its URL alone. A
publisher-style collection label is also accepted:

```text
https://github.com/owner/repository/tree/main/skills
owner-name | https://github.com/owner/repository/tree/main/skills
```

Do not add a URL when the user says it is only an example or explicitly says
not to install it. Do not manually download individual files or run scripts from
the source repository.

Then run the repository's single synchronization command:

```bash
"/Users/marclamy/Documents/Code/skills/scripts/sync-skills.sh"
```

The command imports every selected skill's entire folder. A collection entry
imports all valid skills found below that URL. It removes successful lines from
the inbox, leaves failed lines there with an error, and then treats the repository
as the complete source of truth. It replaces the installed personal skill sets
for Codex, Claude Code, and OpenCode with real directory copies. Skills removed
from the repository disappear from the global installation.

Do not recreate the synchronization logic manually and do not modify
project-specific skill directories in other repositories.

After a successful run, report imported skill names and the installed skill
count. Tell the user to open a new agent conversation. A Conductor restart is
not required.
