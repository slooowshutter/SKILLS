---
name: ui-variant-explorer
description: Frontend-only workflow that builds multiple visual variants of the same component, page, or section and ships a draggable on-page picker overlay so the user can swap between them with one click. Content/data stays identical across variants — only the visual treatment changes. Use when the user asks for "multiple designs," "5 variants," "different versions of this UI," "options for this hero/button/section," or wants to A/B explore the look of an existing or new piece of UI without touching its data layer.
---

# UI Variant Explorer

Build N visual variants of one piece of UI. Ship a draggable picker so the user flips between them live.

## Triggers

- "Make me N designs of X"
- "Multiple variants of this hero/button/section/page"
- "Different UI options for Y"
- "Try a few visual takes on Z"

## Scope rule

- **Frontend visual only.** Same content, same data, same props, same copy across all variants. Only layout, typography, color, motion, ornamentation differ.
- If the user does NOT specify, only generate variants for the visual layer. Never branch business logic or data shape.

## Path rule

- **No existing UI yet** (greenfield) → put everything in `app/test/<feature-name>/`.
- **Existing component the user pointed at** → build variants alongside it in the same folder. Don't move the file.
- Either way, never touch unrelated production code.

## Variant count

Default guidance, never enforced:

- Small thing (button, card, chip, badge, single section): **5–20** variants.
- Medium thing (full hero, full feature block, modal): **5–10**.
- Large thing (full page): **5**.

If the user names a number, use that.
If they don't, pick a number from the band above and say so before generating.

## Required structure

Every invocation produces three categories of file:

1. **Variants** — one file per variant, all rendering the same shared content. Use any naming convention; numeric prefix optional.
2. **Variant switcher** — one floating draggable picker.
3. **Dispatcher** — one parent that holds the chosen variant ID, renders the active variant + the switcher.

Extract any copy/data the variants share into a single source of truth (a shared component, constants file, or props passed from the dispatcher) so swapping variants never changes content.

## Switcher contract

The picker MUST:

- Render fixed-position, floating, default bottom-right corner.
- Be draggable anywhere on screen using Framer Motion `drag` + `useMotionValue` (never React state for the position — animation rules forbid re-renders during drag).
- Distinguish drag from click via a ~6px movement threshold so dragging doesn't accidentally open the menu.
- **Trigger appearance and navigation:**
  - The switcher trigger must always be exactly 200px wide. Do not allow the width to vary depending on the variant name/text. Style the trigger so its width is fixed, regardless of the content inside.
  - On the left and right sides of the trigger, render clickable arrow buttons for previous and next variant. Clicking the left arrow selects the previous variant, clicking the right arrow selects the next.
  - Support keyboard navigation: when the switcher is focused, pressing the left/right keyboard arrow keys should also step to the previous/next variant, wrapping around if needed.
- Open a popup listing all variants with the active one marked. Click a variant → swap + close.
- Persist to `localStorage`:
  - `<feature>.variant` — selected variant ID
  - `<feature>.switcherPos` — `{x, y}` position
- Hidden in production builds via `process.env.NODE_ENV === "development"`. Never ships to real visitors.
- Respect `prefers-reduced-motion`: skip drag spring + entry animations if reduced.
- Never trap keyboard focus when closed; close on Escape when open.
- Mount only after hydration (check a `mounted` flag) to avoid SSR mismatch.

## Workflow

1. **Confirm the target.** Read the existing component if one was pointed at, or pick the path under `app/test/<feature>/` if greenfield.
2. **Lock the shared content.** Identify every piece of copy/data/prop that must stay constant. Extract if not already.
3. **Pick variant count.** Use the band above unless the user named one. Say the count out loud before generating.
4. **Generate variants.** Each is a self-contained component receiving the shared content. Vary only: layout, typography scale, color treatment, motion, ornamentation, density. Keep the public API (props in/out) identical so the dispatcher swaps cleanly.
5. **Add the switcher + dispatcher.** Wire `localStorage` persistence and the dev-only gate.
6. **Set the default.** First variant unless the user said otherwise.
7. **Verify.** TypeScript clean, no production code touched, mobile breakpoints handled per variant, no `h-screen` (use `min-h-[100dvh]`), no emojis.

## What to never do

- Never change data shape, business logic, or copy across variants.
- Never call `process.env.NODE_ENV` outside the switcher render gate (don't gate the variants themselves on env).
- Never spam: if you're tempted to pad to a count by repeating treatments, stop one short instead.
- Never ship the picker to production. The graduation step is a separate cutover that deletes the switcher and pins one variant.
