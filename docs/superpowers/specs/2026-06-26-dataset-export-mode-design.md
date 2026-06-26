# Dataset Export Mode Design

## Goal

Keep dataset pages in a clean preview state by default, and make export selection an explicit workflow.

## Behavior

- Dataset pages show trajectory rows without selection checkboxes by default.
- A visible `创建导出` action starts export mode.
- Export mode shows row checkboxes, the current-page checkbox, format selection, export action, and a cancel action.
- Entering export mode selects the current filtered dataset match set by default. Users can uncheck rows to exclude them.
- Export history stays visible whenever artifacts exist for the dataset, even before export mode is opened.
- Filter changes reset export exclusions and leave export mode, so a stale selection cannot be applied to a different match set.

## Constraints

- Keep the existing backend export contract: selected set is `filters - exclude_hashes`.
- Keep the existing export artifact history shape.
- Keep the change scoped to the existing `ListView` component and focused unit tests.

## Review Note

The normal spec-review subagent step was skipped because this environment only allows subagents when the user explicitly requests delegation.
