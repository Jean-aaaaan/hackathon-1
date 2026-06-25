/**
 * zip.js — packages the built Chrome Extension into a .zip for Chrome Web Store upload
 *
 * Usage:
 *   npm run build    # builds dist/ first
 *   npm run zip      # creates vantage-extension-{version}.zip
 *
 * Output: packages/chrome-extension/vantage-extension-{version}.zip
 */

const archiver = require("archiver");
const fs = require("fs");
const path = require("path");

const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "../package.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "../dist/manifest.json"), "utf8"));

const version = manifest.version ?? pkg.version ?? "0.0.0";
const outFile = path.join(__dirname, `../vantage-extension-${version}.zip`);

const output = fs.createWriteStream(outFile);
const archive = archiver("zip", { zlib: { level: 9 } });

output.on("close", () => {
  const kb = Math.round(archive.pointer() / 1024);
  console.log(`✅  vantage-extension-${version}.zip  (${kb} KB)`);
  console.log(`   Upload to: https://chrome.google.com/webstore/devconsole`);
});

archive.on("error", (err) => {
  console.error("❌  Zip failed:", err.message);
  process.exit(1);
});

// Verify dist/ exists
if (!fs.existsSync(path.join(__dirname, "../dist"))) {
  console.error("❌  dist/ not found — run `npm run build` first");
  process.exit(1);
}

archive.pipe(output);
archive.directory(path.join(__dirname, "../dist"), false);
archive.finalize();
