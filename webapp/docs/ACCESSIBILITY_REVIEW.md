# Accessibility review — JMeter Control Center

Scope: every page of the web app (WCAG 2.2 level AA as reference), with a focus on **reaching an execution
quickly and with the keyboard only**. Reviewed on macOS (Chrome) in light and dark themes.

## Fastest way to start a test

| Path | Steps |
|------|-------|
| **Quick run** (any page) | <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>K</kbd> → type part of the tag or project → <kbd>Enter</kbd> → <kbd>Enter</kbd> (focus lands on **Start execution**) |
| **Run again** (dashboard) | one click on a recent tag → <kbd>Enter</kbd>; the previous `-J` overrides are pre-filled |
| Project → Tags | ▶ Run on the tag → <kbd>Enter</kbd> |
| Schedules | *⏱* on a tag pre-selects project and tag in the schedule form |

Recently run tags appear first in Quick run (↻). Typing several words narrows the list (`login qa`).

## Findings and fixes

| # | Finding (before) | WCAG | Fix |
|---|------------------|------|-----|
| 1 | 111 form labels not associated with their fields (screen readers did not announce them; clicking a label did not focus the field) | 1.3.1, 4.1.2 | Every `.field` label is bound to its control (`for`/`id`); checkboxes already wrap their input |
| 2 | Icon-only buttons (✕, ⏱, ↗, ☆) named only by a tooltip | 4.1.2 | Explicit `aria-label` with the object they act on ("Remove tag login_qa"); automatic fallback from `title` |
| 3 | No visible keyboard focus | 2.4.7, 2.4.11 | `:focus-visible` ring (3 px, accent colour) on links, buttons, tabs, summaries, fields and the console |
| 4 | No way to skip the navigation | 2.4.1 | "Skip to content" link (first Tab stop) and `<main id="main">` landmark; `nav` labelled "Main" |
| 5 | Dialogs without accessible name | 4.1.2 | `aria-labelledby` → dialog title; native `<dialog>` keeps focus inside and closes with Esc |
| 6 | Charts (canvas) without text alternative | 1.1.1 | `role="img"` + label pointing to the KPI tiles / tables that contain the same values |
| 7 | Success / error messages not announced | 4.1.3 | Flash messages are `role="status"` (errors `role="alert"`); run status badge is `aria-live="polite"` |
| 8 | Execution console not identifiable | 1.3.1 | `role="log"`, label "Execution console", focusable for keyboard scrolling (`aria-live="off"` so it does not flood screen readers) |
| 9 | Pulsing "running" dot and transitions ignore motion preferences | 2.3.3 | `prefers-reduced-motion` disables animations and transitions |
| 10 | Grade "B" badge contrast 4.1:1 | 1.4.3 | Darker green (≥ 5.5:1); grades also show the letter, never colour alone |
| 11 | Windows High Contrast | 1.4.11 | `forced-colors` keeps borders on buttons and status dots visible |
| 12 | File inputs without name | 4.1.2 | `aria-label` "Choose files to upload" |
| 13 | *(second pass)* Primary buttons, Quick run and the skip link: white on light blue in **dark mode** = 3.2:1 | 1.4.3 | Primary buttons use a darker blue in both themes (≥ 5.1:1); chips use their own text colour (≥ 5.7:1) |
| 14 | *(second pass)* Master activity was a paragraph updated silently; the run dialog remembered *Distributed* | 4.1.3, 3.2.2 | `role="status"` list of the slots in use (n/3); the dialog always opens **Master only** (Run again restores the previous choice) |
| 15 | *(second pass)* Inline `onclick` handlers (blocked by the new Content-Security-Policy) | — | Declarative `data-*` attributes handled in `app.js`; same keyboard behaviour |

Already compliant and kept: language attribute, logical heading order per page, tables with header rows,
status never conveyed by colour only (badges include text), touch targets ≥ 24 px (`.btn.sm`), responsive layout
down to 360 px, both colour schemes with AA contrast for body text (muted text ≥ 5:1).

Second pass (after the multi-run and push-sync changes): every page (Projects, project/Tags, Quality, Servers,
Settings, Schedules, Executions, run, Live monitor, Compare, Git, Users, New project) checked for unnamed fields and
controls, duplicate ids, dialogs without name, tables without headers, heading order, landmarks and text contrast in
dark mode — no findings left besides the ones fixed above.

## Recommendations (not implemented)

* Translate the UI to Spanish (the guide and reports already are) or offer a language switch.
* Add a "results table" toggle next to each chart for users who prefer data over graphics.
* Run an automated audit (axe / Lighthouse) in CI against the main pages.
