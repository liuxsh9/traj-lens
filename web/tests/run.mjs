import { build } from "esbuild";
import { pathToFileURL } from "node:url";

const outfile = "/tmp/trajlens-web-tests.mjs";

await build({
  entryPoints: ["tests/all.test.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  outfile,
  logLevel: "silent",
});

await import(pathToFileURL(outfile).href);
