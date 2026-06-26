# Dataset Export Mode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dataset export controls opt-in while preserving all existing export behavior once export mode starts.

**Architecture:** Add local export-mode state to `ListView`, gate selection cells behind it, and split export history rendering from the export action controls. Add focused pure helper tests because the current web test harness is Node-only and does not mount React DOM.

**Tech Stack:** React, TypeScript, TanStack Query/Table, existing Node/esbuild web test runner.

---

## Chunk 1: Dataset Export Mode

### Task 1: Test Mode Gating

**Files:**
- Modify: `web/tests/listViewSort.test.ts`
- Modify: `web/src/components/ListView.tsx`
- Modify: `web/tests/run.mjs`

- [ ] **Step 1: Write the failing test**

Add assertions for a helper that says selection controls appear only when a dataset has rows and export mode is active.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test`

Expected: FAIL because the helper is not exported yet.

- [ ] **Step 3: Implement minimal UI state**

In `ListView`, add `exportMode` state. Show `创建导出` and history for dataset pages. Show checkboxes and export action controls only when `exportMode` is true. Reset exclusions and close export mode on filter changes.

If the Node/esbuild test runner evaluates Vite-only `import.meta.env` access from `api.ts`, define `import.meta.env.BASE_URL` as `/` in `web/tests/run.mjs`.

- [ ] **Step 4: Run focused tests**

Run: `cd web && npm test`

Expected: PASS.

- [ ] **Step 5: Build frontend**

Run: `cd web && npm run build`

Expected: PASS.

## Review Note

The normal plan-review subagent step was skipped because this environment only allows subagents when the user explicitly requests delegation.
