import assert from "node:assert/strict";
import {
  getListAcceptClass,
  getListColumnIds,
  getListScoreClass,
  getListSortParams,
} from "../src/components/ListView";

assert.deepEqual(getListSortParams([]), { sortBy: "score", sortDir: "desc" });

assert.deepEqual(getListColumnIds(), [
  "title",
  "turns",
  "steps",
  "tools",
  "resolution",
  "acceptance",
  "pb",
  "errors",
  "sec",
  "score",
  "created_at",
]);

assert.equal(getListScoreClass(90), "res-ok");
assert.equal(getListScoreClass(45), "res-part");
assert.equal(getListScoreClass(30), "res-fail");

assert.equal(getListAcceptClass("high"), "res-ok");
assert.equal(getListAcceptClass("medium"), "res-part");
assert.equal(getListAcceptClass("low"), "res-fail");
