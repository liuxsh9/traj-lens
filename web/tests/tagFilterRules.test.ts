import assert from "node:assert/strict";
import {
  applyFilters,
  clearTagFilters,
  FILTER_FIELDS,
  makeFilterRule,
  setTagFilterMode,
  toggleTagFilter,
  type FilterRule,
} from "../src/components/FilterBar";

const scoreRule: FilterRule = makeFilterRule("score", "≥", "80");
const first = toggleTagFilter([scoreRule], "前端");

assert.deepEqual(first, [
  scoreRule,
  { id: first[1].id, field: "tags", op: "∋", value: "前端" },
]);

assert.equal(first[1].id > scoreRule.id, true);

const second = toggleTagFilter(first, "后端");
assert.deepEqual(
  second.map((r) => [r.field, r.op, r.value]),
  [
    ["score", "≥", "80"],
    ["tags", "∋", "前端"],
    ["tags", "∋", "后端"],
  ],
);

assert.deepEqual(
  toggleTagFilter(second, "前端").map((r) => [r.field, r.op, r.value]),
  [
    ["score", "≥", "80"],
    ["tags", "∋", "后端"],
  ],
);

assert.deepEqual(clearTagFilters(second), [scoreRule]);

const anyTags = setTagFilterMode(second, "any");
assert.equal(anyTags[0].mode, undefined);
assert.deepEqual(
  anyTags.map((r) => [r.field, r.op, r.value, r.mode]),
  [
    ["score", "≥", "80", undefined],
    ["tags", "∋", "前端", "any"],
    ["tags", "∋", "后端", "any"],
  ],
);

const allTags = setTagFilterMode(anyTags, "all");
assert.deepEqual(
  allTags.map((r) => [r.field, r.op, r.value, r.mode]),
  [
    ["score", "≥", "80", undefined],
    ["tags", "∋", "前端", "all"],
    ["tags", "∋", "后端", "all"],
  ],
);

const frontendRows = [
  {
    content_hash: "a",
    items_count: 1,
    created_at: "",
    metrics: {},
    annotations: { tags: ["C#"] },
  },
  {
    content_hash: "b",
    items_count: 1,
    created_at: "",
    metrics: {},
    annotations: { tags: ["OpenAI"] },
  },
];

assert.deepEqual(
  applyFilters(frontendRows, [{ id: 999, field: "tags", op: "∋", value: "AI" }])
    .map((row) => row.content_hash),
  [],
);

const fieldKeys = FILTER_FIELDS.map((f) => f.key);
assert.ok(fieldKeys.includes("loop_count"));
assert.ok(fieldKeys.includes("recovery_count"));

const resolutionField = FILTER_FIELDS.find((f) => f.key === "resolution");
assert.deepEqual(resolutionField?.options, [
  "resolved",
  "unverified",
  "partially_resolved",
  "unresolved",
  "indeterminate",
]);

const acceptanceField = FILTER_FIELDS.find((f) => f.key === "acceptance");
assert.deepEqual(acceptanceField?.options, ["high", "medium", "low", "none"]);
assert.ok(fieldKeys.includes("acceptance_likelihood"));

const metricRows = [
  {
    content_hash: "loop",
    items_count: 1,
    created_at: "",
    metrics: { loop_count: 2, recovery_count: 0, acceptance_likelihood: 80 },
    annotations: { acceptance: "high" },
  },
  {
    content_hash: "recovery",
    items_count: 1,
    created_at: "",
    metrics: { loop_count: 0, recovery_count: 1, acceptance_likelihood: 40 },
    annotations: { acceptance: "none" },
  },
];

assert.deepEqual(
  applyFilters(metricRows, [{ id: 1000, field: "loop_count", op: "≥", value: "1" }])
    .map((row) => row.content_hash),
  ["loop"],
);
assert.deepEqual(
  applyFilters(metricRows, [{ id: 1001, field: "recovery_count", op: "≥", value: "1" }])
    .map((row) => row.content_hash),
  ["recovery"],
);
assert.deepEqual(
  applyFilters(metricRows, [{ id: 1002, field: "acceptance", op: "=", value: "none" }])
    .map((row) => row.content_hash),
  ["recovery"],
);
assert.deepEqual(
  applyFilters(metricRows, [{ id: 1003, field: "acceptance_likelihood", op: "≥", value: "50" }])
    .map((row) => row.content_hash),
  ["loop"],
);
