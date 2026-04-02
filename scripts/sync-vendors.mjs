import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const vendorDir = path.join(rootDir, "static", "vendor");

const vendors = [
  {
    from: path.join(rootDir, "node_modules", "chart.js", "dist", "chart.umd.js"),
    to: path.join(vendorDir, "chart.umd.js")
  },
  {
    from: path.join(rootDir, "node_modules", "fuse.js", "dist", "fuse.min.js"),
    to: path.join(vendorDir, "fuse.min.js")
  }
];

await mkdir(vendorDir, { recursive: true });

for (const vendor of vendors) {
  await copyFile(vendor.from, vendor.to);
  console.log(`synced ${path.relative(rootDir, vendor.to)}`);
}
