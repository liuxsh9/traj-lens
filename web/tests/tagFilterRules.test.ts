import assert from "node:assert/strict";
import {
  clearTagFilters,
  makeFilterRule,
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
