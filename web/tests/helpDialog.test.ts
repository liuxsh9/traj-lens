import assert from "node:assert/strict";
import { HELP_BUTTON_CLASS, HELP_SECTIONS, SCORE_FORMULA_TEXT } from "../src/components/HelpDialog";

assert.equal(SCORE_FORMULA_TEXT, "基础分 resolved=90，unverified=70，partially_resolved=45，unresolved=0；再叠加 change_acceptance、pushback、error_recovery、loop、hard_interruption 等调整，封顶 100。");

assert.deepEqual(
  HELP_SECTIONS.map((section) => section.title),
  ["系统定位", "关键能力", "分数计算", "标注与指标"],
);

assert.ok(
  HELP_SECTIONS.find((section) => section.title === "关键能力")?.items.some((item) =>
    item.includes("多来源日志")
  ),
);

assert.ok(
  HELP_SECTIONS.find((section) => section.title === "分数计算")?.items.some((item) =>
    item.includes("overall_score")
  ),
);

assert.equal(HELP_BUTTON_CLASS, "btn btn-sm btn-ghost");
