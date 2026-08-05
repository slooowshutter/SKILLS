---
name: multi-debate
description: Multi-model debate workflow where multiple AI sessions converge on an answer through written files in a shared folder. Each session reads peers' previous-turn files, refines its position, writes its own. Use when the user invokes /multi-debate with a folder path, asks to run a multi-model debate, parallel-model deliberation, or multi-agent consensus building across separate sessions.
---

# Multi-Debate

Multiple model sessions debate the same task by writing files to a shared folder. Each turn, every session reads peers' previous-turn files, refines its position, writes its own. Repeats until convergence.

## Invocation

User passes a folder path (slash arg or in-message). The first message contains the task. Each subsequent invocation advances one turn — user typically just types "next turn" or similar.

## Identify yourself

Pick a stable filename slug from your own model identifier:
- Lowercase, hyphens only, no spaces, no dots (replace dots with hyphens)
- Examples: `opus-4-7`, `sonnet-4-6`, `gpt-5-5`, `gemini-3`

Use the same slug every turn in the same folder.

## Determine the turn

1. List the folder (Bash `ls <folder>`).
2. Count files matching `turn-*-<my-slug>.md`.
3. My turn `N` = count + 1.
4. If `N == 1` → turn 1 flow. Else → turn `N>1` flow.

## Turn 1 flow

No peers to read. Write `<folder>/turn-1-<my-slug>.md`:

    # Turn 1 — <my-slug>

    ## Reasoning
    <thinking, plan, why this approach>

    ## Answer
    <direct answer to the task>

    ## Confidence
    <0-100>

    ## Converged
    no

Reply to user, 1-3 lines: `Turn 1 written. Answer: <one-line summary>. Awaiting peers.`

## Turn N>1 flow

1. List folder. Read every `turn-{N-1}-*.md` file except your own.
2. Compare your turn N-1 to each peer's. Note where you agree, where you disagree, and what they raise that's new.
3. Refine your answer based on their reasoning. Genuine refinement — change your mind when their argument is stronger; hold your ground when it isn't.
4. Write `<folder>/turn-{N}-<my-slug>.md`:

    # Turn N — <my-slug>

    ## Reasoning
    <refined thinking, what changed since your last turn and why>

    ## Answer
    <refined direct answer>

    ## Agreements
    - With <peer-slug>: <point>

    ## Disagreements
    - With <peer-slug>: they argued X, I hold Y because Z

    ## Confidence
    <0-100>

    ## Converged
    yes | no — <one-line reason>

5. Reply to user, 1-3 lines: debate state. Example: `Turn 3 written. Converged with gpt-5-5 on approach A. Still diverging from sonnet-4-6 on B — they argue X, I argue Y. Confidence 75.`

## Rules

- Filename format strict: `turn-{N}-{model-slug}.md`. Never overwrite a prior turn's file.
- Use the exact section headers shown — peers parse them.
- `Converged: yes` only when you genuinely agree with every peer's most recent answer.
- Full thinking goes in the file. User reply stays short — the file is the artifact, the reply is the status.
- Read only the previous turn (`N-1`). Do not peek at peers' current-turn files even if they appear mid-run.
- If peer files for `N-1` are missing for some peers, proceed with the ones present and note the absence in `## Disagreements`.
