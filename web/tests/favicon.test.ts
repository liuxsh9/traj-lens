import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const indexHtml = readFileSync("index.html", "utf8");

assert.match(indexHtml, /<link rel="icon" type="image\/svg\+xml" href="\/favicon\.svg" \/>/);
assert.equal(existsSync("public/favicon.svg"), true);
