import assert from "node:assert/strict";
import {
  formatListResolution,
  getListAcceptClass,
  getListColumnIds,
  getListScoreClass,
  getListSortParams,
  EXPORT_MODE_HINT,
  shouldShowExportSelection,
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
