import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const vendorDir = path.join(rootDir, "static", "vendor");

const vendors = [
  {
    from: path.join(path.dirname(require.resolve("chart.js")), "chart.umd.js"),
    to: path.join(vendorDir, "chart.umd.js")
  },
  {
    from: path.join(path.dirname(require.resolve("gsap")), "gsap.min.js"),
    to: path.join(vendorDir, "gsap.min.js")
  },
  {
    from: path.join(path.dirname(require.resolve("lenis")), "lenis.min.js"),
    to: path.join(vendorDir, "lenis.min.js")
  }
];

await mkdir(vendorDir, { recursive: true });

for (const vendor of vendors) {
  await copyFile(vendor.from, vendor.to);
  console.log(`synced ${path.relative(rootDir, vendor.to)}`);
}
