import assert from "node:assert/strict";
import {
  clearTagFilters,
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
