import assert from "node:assert/strict";
import {
  formatJobLabel,
  formatJobTiming,
  keepLatestJobsByAnnotator,
  summarizeAnnotatorProgress,
} from "../src/components/annotatorProgress";
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

assert.equal(early.pct, 0);
assert.ok(later.pct >= early.pct, `progress regressed from ${early.pct}% to ${later.pct}%`);

const weighted = summarizeAnnotatorProgress([
  job({ job_id: "small", done: 50, total: 100 }),
  job({ job_id: "large", done: 0, total: 900 }),
]);

assert.equal(weighted.finished, 50);
assert.equal(weighted.total, 1000);
assert.equal(weighted.pct, 5);

const done = summarizeAnnotatorProgress([
  job({ status: "done", done: 100, total: 100 }),
  job({ status: "done", done: 200, total: 200 }),
]);

assert.equal(done.pct, 100);

const deduped = keepLatestJobsByAnnotator([
  job({ job_id: "old", annotator_id: "loop_detect", status: "done", done: 0, skipped: 2, created_at: "2026-06-26T12:23:00Z" }),
  job({ job_id: "new", annotator_id: "loop_detect", status: "done", done: 2, skipped: 0, created_at: "2026-06-26T12:26:00Z" }),
  job({ job_id: "pb", annotator_id: "pushback", status: "done", done: 1, skipped: 0, created_at: "2026-06-26T12:24:00Z" }),
]);

assert.deepEqual(new Set(deduped.map((j) => j.job_id)), new Set(["pb", "new"]));
assert.equal(deduped.filter((j) => j.annotator_id === "loop_detect").length, 1);

const withFreshPending = keepLatestJobsByAnnotator([
  job({ job_id: "old", annotator_id: "topic", status: "done", done: 0, skipped: 1, created_at: "2026-06-26T12:23:00Z" }),
  job({ job_id: "fresh", annotator_id: "topic", status: "pending" }),
]);

assert.deepEqual(withFreshPending.map((j) => j.job_id), ["fresh"]);

assert.deepEqual(formatJobLabel(job({ status: "pending" })), {
  text: "preparing targets…",
  color: "var(--warn)",
});

assert.deepEqual(formatJobLabel(job({ status: "pending", total: 100, done: 25, skipped: 10 })), {
  text: "calling LLM… 35/100",
  color: "var(--warn)",
});

assert.deepEqual(formatJobLabel(job({ status: "pending", queued_behind: 2 })), {
  text: "queued behind 2 jobs",
  color: "var(--warn)",
});

assert.equal(formatJobTiming(job({
  status: "pending",
  created_at: "2026-06-27T00:00:00Z",
  updated_at: "2026-06-27T00:01:10Z",
}), Date.parse("2026-06-27T00:01:15Z")), "elapsed 1m · updated 5s ago");

assert.equal(formatJobTiming(job({
  status: "done",
  created_at: "2026-06-27T00:00:00Z",
  updated_at: "2026-06-27T00:02:30Z",
}), Date.parse("2026-06-27T00:03:00Z")), "took 2m");
