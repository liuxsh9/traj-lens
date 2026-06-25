import assert from "node:assert/strict";
import { getListSortParams } from "../src/components/ListView";

assert.deepEqual(getListSortParams([]), { sortBy: "score", sortDir: "desc" });
