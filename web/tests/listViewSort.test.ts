import assert from "node:assert/strict";
import { resetDatasetListScrollOnOpen } from "../src/App";
import {
  formatListResolution,
  getListAcceptClass,
  getListColumnIds,
  getListScoreClass,
  getListSortParams,
  LIST_SORT_DESC_FIRST,
  EXPORT_MODE_HINT,
  getListScrollKey,
  readListScrollPosition,
  resetListScrollPosition,
  saveListScrollPosition,
  shouldResetListScrollForChange,
  shouldResetListForExternalFilters,
  shouldShowExportSelection,
} from "../src/components/ListView";

assert.deepEqual(getListSortParams([]), { sortBy: "score", sortDir: "desc" });
assert.equal(LIST_SORT_DESC_FIRST, true);

assert.deepEqual(
  Object.fromEntries(getListColumnIds().map((id) => [id, getListSortParams([{ id, desc: true }]).sortBy])),
  {
    title: "title",
    turns: "turns",
    steps: "steps",
    tools: "tools",
    resolution: "resolution",
    acceptance: "acceptance",
    pb: "pushback_count",
    errors: "error_steps",
    loop: "loop_count",
    recovery: "recovery_count",
    sec: "security_findings",
    score: "score",
    created_at: "created_at",
  },
);

assert.deepEqual(getListColumnIds(), [
  "title",
  "turns",
  "steps",
  "tools",
  "resolution",
  "acceptance",
  "pb",
  "errors",
  "loop",
  "recovery",
  "sec",
  "score",
  "created_at",
]);

assert.equal(getListScoreClass(90), "res-ok");
assert.equal(getListScoreClass(45), "res-part");
assert.equal(getListScoreClass(30), "res-fail");

assert.equal(formatListResolution("resolved"), "resolved");
assert.equal(formatListResolution("partially_resolved"), "partially");
assert.equal(formatListResolution("unresolved"), "unresolved");

assert.equal(getListAcceptClass("high"), "res-ok");
assert.equal(getListAcceptClass("medium"), "res-part");
assert.equal(getListAcceptClass("low"), "res-fail");

assert.equal(
  EXPORT_MODE_HINT,
  "基于当前筛选后的样本集创建，进入后可勾选或取消再导出。",
);

assert.equal(shouldShowExportSelection({
  datasetId: "dataset-1",
  total: 2,
  exportMode: false,
}), false);
assert.equal(shouldShowExportSelection({
  datasetId: "dataset-1",
  total: 2,
  exportMode: true,
}), true);
assert.equal(shouldShowExportSelection({
  datasetId: undefined,
  total: 2,
  exportMode: true,
}), false);
assert.equal(shouldShowExportSelection({
  datasetId: "dataset-1",
  total: 0,
  exportMode: true,
}), false);

assert.equal(shouldResetListForExternalFilters({
  hasControlledFilters: true,
  previousKey: null,
  nextKey: "[]",
}), false);
assert.equal(shouldResetListForExternalFilters({
  hasControlledFilters: true,
  previousKey: "[]",
  nextKey: "[tags]",
}), true);
assert.equal(shouldResetListForExternalFilters({
  hasControlledFilters: false,
  previousKey: "[]",
  nextKey: "[tags]",
}), false);

const scrollStore = new Map<string, string>();
const scrollStorage = {
  getItem: (key: string) => scrollStore.get(key) ?? null,
  setItem: (key: string, value: string) => { scrollStore.set(key, value); },
  removeItem: (key: string) => { scrollStore.delete(key); },
};

assert.equal(getListScrollKey("dataset-1"), "list:dataset-1:scroll");
assert.equal(getListScrollKey(undefined), "list:_all:scroll");
assert.equal(readListScrollPosition(scrollStorage, "list:dataset-1:scroll"), 0);

saveListScrollPosition(scrollStorage, "list:dataset-1:scroll", 240);
assert.equal(readListScrollPosition(scrollStorage, "list:dataset-1:scroll"), 240);

saveListScrollPosition(scrollStorage, "list:dataset-1:scroll", -10);
assert.equal(readListScrollPosition(scrollStorage, "list:dataset-1:scroll"), 0);

saveListScrollPosition(scrollStorage, "list:dataset-1:scroll", Number.NaN);
assert.equal(readListScrollPosition(scrollStorage, "list:dataset-1:scroll"), 0);

saveListScrollPosition(scrollStorage, "list:dataset-1:scroll", 120);
resetListScrollPosition(scrollStorage, "list:dataset-1:scroll");
assert.equal(readListScrollPosition(scrollStorage, "list:dataset-1:scroll"), 0);

assert.equal(shouldResetListScrollForChange("page"), true);
assert.equal(shouldResetListScrollForChange("pageSize"), true);
assert.equal(shouldResetListScrollForChange("filter"), true);
assert.equal(shouldResetListScrollForChange("sort"), false);

saveListScrollPosition(scrollStorage, getListScrollKey("dataset-2"), 360);
resetDatasetListScrollOnOpen(scrollStorage, "dataset-2");
assert.equal(readListScrollPosition(scrollStorage, getListScrollKey("dataset-2")), 0);
