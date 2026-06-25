import assert from "node:assert/strict";
import { summarizeAnnotatorProgress } from "../src/components/annotatorProgress";
import type { JobInfo } from "../src/api";

function job(partial: Partial<JobInfo>): JobInfo {
  return {
    job_id: partial.job_id ?? Math.random().toString(16).slice(2),
    annotator_id: partial.annotator_id ?? "annotator",
    status: partial.status ?? "pending",
    ...partial,
  };
}

const early = summarizeAnnotatorProgress([
  job({ job_id: "a", done: 80, total: 100 }),
  job({ job_id: "b" }),
]);

const later = summarizeAnnotatorProgress([
  job({ job_id: "a", done: 80, total: 100 }),
  job({ job_id: "b", done: 0, total: 200 }),
]);

assert.equal(early.pct, 40);
assert.ok(later.pct >= early.pct, `progress regressed from ${early.pct}% to ${later.pct}%`);

const done = summarizeAnnotatorProgress([
  job({ status: "done", done: 100, total: 100 }),
  job({ status: "done", done: 200, total: 200 }),
]);

assert.equal(done.pct, 100);
