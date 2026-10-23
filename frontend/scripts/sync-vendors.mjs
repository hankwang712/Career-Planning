import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const vendorDir = path.join(rootDir, "static", "vendor");

const vendors = [
  {
    from: path.join(path.dirname(require.resolve("chart.js")), "chart.umd.js"),
    to: path.join(vendorDir, "chart.umd.js")
  }
];

await mkdir(vendorDir, { recursive: true });

for (const vendor of vendors) {
  await copyFile(vendor.from, vendor.to);
  console.log(`synced ${path.relative(rootDir, vendor.to)}`);
}

await build({
  configFile: false,
  build: {
    outDir: vendorDir,
    emptyOutDir: false,
    lib: {
      entry: fileURLToPath(import.meta.resolve("fuse.js/min")),
      name: "Fuse",
      formats: ["iife"],
      fileName: () => "fuse.min.js"
    }
  }
});
