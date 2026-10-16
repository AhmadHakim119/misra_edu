---
name: "MISRA parallel marking ledger"
description: "Implemented visual system for the parallel instructor workspace; original frontend retained."
colors:
  primary: "#087177"
  ground: "#f7f8fa"
  surface: "#fff"
  secondary: "#f0f3f6"
  ink: "#18263a"
  muted: "#526079"
  line: "#dce3e9"
  active: "#e3f2f1"
  danger: "#a62c35"
  warning: "#7c5514"
  focus: "#00848b"
  dark-primary: "#77cfc5"
  dark-ground: "#080b0d"
  dark-surface: "#101619"
  dark-secondary: "#182025"
  dark-ink: "#e7eef3"
  dark-muted: "#a5b2bf"
  dark-line: "#303c44"
  dark-active: "#173330"
  dark-danger: "#ff9ea6"
  dark-warning: "#e9bc70"
  dark-focus: "#84e0d5"
  paper-ground: "#30373d"
  paper-white: "white"
  evidence-match: "#178659"
  evidence-approximate: "#a66a1b"
typography:
  headline:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "31px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.35
  question-title:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "23px"
    fontWeight: 700
    lineHeight: 1.35
  body:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
  question-copy:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "17px"
    lineHeight: 1.5
  ledger:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
  recorded-grade:
    fontFamily: 'Figtree, "Segoe UI", sans-serif'
    fontSize: "32px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.025em"
rounded:
  square: "0px"
  viewer: "5px"
  control: "6px"
  panel: "8px"
spacing:
  compact: "6px"
  related: "8px"
  field: "12px"
  inset: "16px"
  region: "20px"
  section: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary}"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 11px"
  task-tab:
    textColor: "{colors.muted}"
    rounded: "{rounded.square}"
    padding: "10px 6px 14px"
  task-tab-selected:
    textColor: "{colors.primary}"
  status:
    textColor: "{colors.ink}"
    typography: "{typography.ledger}"
  question-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
  paper-ledger:
    backgroundColor: "{colors.surface}"
    typography: "{typography.ledger}"
  paper-ledger-selected:
    backgroundColor: "{colors.active}"
  instructor-grade:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "16px"
---

# Design System: MISRA parallel marking ledger

## Overview

**Creative North Star: "Marking ledger"**

A restrained document workspace: cool paper surfaces, ink typography, ruled information and a muted teal selection language. It makes instructor decisions readable through ordinary controls and deliberate density rather than decorative dashboard tiles.

This is an extraction from the implemented parallel world in `misra-frontend/app/`, not a declaration that the original frontend was restyled. The original workspace retains its own Outfit/celadon system and remains the route to tools not yet ported. The selected direction is settled; current values are documented, not newly approved.

**Key Characteristics:**

- Cool document surfaces and quiet hairline partitions.
- One humanist UI family with native controls.
- Near-black dark ground with differentiated charcoal panels.
- Flat, information-led components and explicit selected states.

This is a functional parallel preview. Full feature parity, replacement readiness and instructor opt-in are not established; documenting the implemented system does not imply them.

## Colors

The frontmatter preserves the literal CSS values. Unsuffixed roles are light-theme values; `dark-*` values replace the corresponding CSS role under the dark-theme attribute. These are complete theme assignments, not independent accents. Sidecar tonal strips are synthesized OKLCH visualization metadata, not additional implemented theme tokens.

### Primary

- **Muted teal** (`primary`): actions, links, current tabs and ready-state dots.
- **Pale teal** (`dark-primary`): the same roles against charcoal in dark mode.
- **Teal selection wash** (`active` / `dark-active`): selected assessment entries and paper rows.
- **Focus teal** (`focus` / `dark-focus`): a visible keyboard outline.

### Neutral

- **Cool ground / near-black ground** (`ground` / `dark-ground`): working canvas and grade-form inset.
- **Document / charcoal surface** (`surface` / `dark-surface`): controls, question container, app bar and evidence inspector.
- **Cool partition / charcoal partition** (`secondary` / `dark-secondary`): assessment index, table headers, notices and job rows.
- **Ink / pale ink** (`ink` / `dark-ink`): main text; muted counterparts distinguish metadata without hiding it.
- **Hairline partition** (`line` / `dark-line`): structural borders and ruled rows.
- **Paper surround** (`paper-ground`): the original-page viewport in both themes. Original page pixels remain unaltered; the image's white fallback is `paper-white`.

### Semantic evidence and recovery

Danger and warning have theme-specific values and accompany written states, not color-only signals. Text-matched evidence uses `evidence-match`; approximate regions use `evidence-approximate` with dashed borders. Location matching does not verify a grade.

**The Role-Pair Rule.** Change the entire semantic role set for dark mode; do not invert submitted paper pixels or add a glowing treatment to the near-black workspace.

## Typography

Figtree is the implemented display and body family; the native fallback is Segoe UI, then sans-serif. The HTML requests weights 400, 500, 600 and 700 from Google Fonts with `display=swap`. The font is identified as OFL in [official Google Fonts metadata](https://raw.githubusercontent.com/google/fonts/main/ofl/figtree/METADATA.pb), with the [SIL Open Font License 1.1 text](https://raw.githubusercontent.com/google/fonts/main/ofl/figtree/OFL.txt). No font file, npm package or Python dependency was added by this documentation pass.

The hierarchy is compact rather than a geometric modular scale. Frontmatter carries the current headline, title, question title, body, question copy, ledger, label and recorded-grade roles. Criterion feedback is slightly larger than ledger text (15px); criterion names use bold body text (16px). Assessment context uses the question-copy size. Long ordinary paragraphs are bounded (72ch); question text is narrower (58ch).

At the first compact breakpoint, the main heading reduces (25px). On mobile, question copy reduces (14px), criterion names reduce (13px) and the recorded grade reduces (25px). Labels and viewer controls use compact text (12px). Scores use tabular numerals; extracted text and retained JSON are rendered in the UI family rather than an invented mono face.

**The Evidence-Legibility Rule.** Keep question text, criterion deductions, source context and model-estimate caveats readable together; do not treat small type or a high confidence estimate as permission to hide uncertainty.

## Layout

This world's spatial grammar is a narrow index, a working record area and a persistent evidence inspector, separated by ruled edges. The surface's assessment-first sequencing belongs to its private brief, not a global ban on other layouts.

Desktop uses a three-column grid: 214px index, a flexible 1.3fr working area and a flexible inspector with a 440px minimum. The app bar is 50px high; index and inspector are sticky below it. Main and inspector insets are approximately one region step, with section breaks near one section step. The inspector has an independent vertical scroll area; a full-page image may exceed its bounded viewport and is intentionally scrollable.

At 1200px and below, the grid becomes 180px / 1fr / minmax(350px, .85fr), and headers and grade controls can wrap. At 1000px and below, the inspector moves below the working area in the second column, loses stickiness and gains an in-page evidence jump. At 700px and below, everything stacks, app navigation wraps and the assessment index becomes a horizontal strip; main insets are 14px. Source/marking-guide context becomes one column. The ledger's recorded-grade column is hidden on mobile, while the selected question's grade remains in the editor; this is observed behavior, not a completed accessibility/parity endorsement.

## Elevation & Depth

Flat tonal layering and borders define depth. There are no component box shadows in the ledger stylesheet. White/charcoal surfaces sit against the ground; selected rows use a wash rather than lift. The native expanded-paper dialog dims the workspace using a dark translucent backdrop (`rgb(8 11 13 / .7)`), not a glow.

State transitions affect backgrounds and border colors (160ms, ease-out). No entrance choreography or looping animation is used. Reduced motion removes transitions, animations and smooth scrolling.

**The Flat Working-Surface Rule.** Distinguish regions with semantic surfaces and hairlines; reserve modal dimming for the expanded original paper.

## Shapes

Controls are gently squared with the control radius. Question panels, grade insets and the expanded dialog share the panel radius; viewer corners are smaller. Assessment entries and task tabs remain square and flush to their regions. Tables use collapsed rules rather than isolated cards. Status dots are circular (7px); evidence rectangles preserve source geometry, with a solid or dashed 2px boundary.

## Components

### Buttons

Direct and ordinary. Primary actions use teal and surface-colored text with bold weight; secondary actions use surface, ink and a thin line border. Hover changes a secondary control's surface/border, while primary hover darkens via brightness (.9). Disabled buttons retain their label, use a default cursor and fade (.55 opacity). Keyboard focus is a 2px role-colored outline with a 3px offset. Viewer and account variants are smaller controls, not a separate visual family.

### Fields

Native search, number, select, textarea and checkbox controls inherit the UI font. Fields use surface/ink/line roles, a control radius and compact padding. Placeholder text uses muted ink at full opacity; caret and native accent color use teal. Score fields are bounded by the selected question's maximum. Textareas resize vertically. Labels remain explicit; validation and connection errors are written messages.

### Navigation

A compact brand and text navigation bar uses an accent underline for the current workspace. Assessment task tabs have transparent surfaces, muted labels and an accent underline plus bold weight when selected. The index uses whole-row selection wash, title and course/paper metadata. Mobile wraps top navigation and scrolls the assessment strip horizontally. Original-workspace links remain explicit.

### Status indicators and job rows

Written status plus a dot distinguishes ready, warning, failed and processing. Neutral job rows carry actual job state, native progress and a retry action for failure. A connection-interrupted notice warns that work may still run; it is not a completion badge. No loop is needed to communicate processing.

### Ruled ledger and question container

The paper ledger uses neutral headers, selected-row wash, tabular grades and an explicit next-action button. The question container has a bordered panel shape, source/guide context, criterion/mark/feedback rows and readable rationale. Native disclosures retain extracted text and approved snapshots without making them the first scan target.

### Paper inspector and grade inset

The viewport retains a complete original page, page selection, previous/next navigation, fit-width, zoom (100–300% in 25% steps) and a native expanded dialog. Solid/dashed location overlays are non-interactive. The grade inset places the recorded mark, editable score and save action together, then the uncalibrated model estimate, decision reason, optional criterion edits, instructor note and saved/unsaved status. Grade changes require a reason; pending saves disable form controls and failed saves keep entries. These are implemented UI behaviors, not a guarantee of grading accuracy.

## Do's and Don'ts

### Do:

- **Do** use the documented light/dark role pairs and native focus treatment.
- **Do** preserve full original-page access and distinguish matched from approximate regions.
- **Do** keep saved state, unsaved edits, job failures and uncalibrated model estimates explicit.
- **Do** apply this world only to the parallel workspace and intentionally ported future surfaces.

### Don't:

- **Don't** treat this document as approval of feature parity, replacement readiness or production readiness.
- **Don't** silently restyle the retained original Outfit/celadon workspace.
- **Don't** replace paper evidence with cropped highlights or present locations as verified marks.
- **Don't** use private student papers or synthetic captures as shipping decorative assets.
