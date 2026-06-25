# Dataset Display Metadata Design

## Goal

Allow users to rename a dataset and edit its note without changing which dataset it is.

## Design

`datasets.id` remains the stable identity for batches, ingestions, exports, jobs, cache keys, and URLs. Renaming updates only `datasets.name`; note edits update only `datasets.description`. A rename never recomputes the slug and never migrates related rows.

The backend exposes `PATCH /api/v1/datasets/{dataset_id}` with a JSON body containing `name` and/or `description`. `name`, when present, must be non-empty after trimming. `description` defaults to an empty string when cleared. Missing datasets return 404.

The frontend adds an edit action on dataset cards. Editing reuses the existing name and description inputs, saves through the PATCH endpoint, refreshes dataset queries, and keeps the detail page title aligned with the updated display name.

## Testing

Add backend tests for updating both fields, preserving the dataset id, rejecting empty names, and returning 404 for missing datasets. Build the frontend to verify TypeScript and bundling.
