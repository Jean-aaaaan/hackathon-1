/**
 * esbuild bundler for Chrome Extension MV3.
 * Produces 4 outputs: background.js, content-hubspot.js, content-linkedin.js, popup.js
 * All land in dist/ alongside manifest.json and popup.html (copied by this script).
 */
const esbuild = require("esbuild");
const fs = require("fs");
const path = require("path");

const OUT = path.join(__dirname, "../dist");

// Clean dist
if (fs.existsSync(OUT)) fs.rmSync(OUT, { recursive: true });
fs.mkdirSync(OUT, { recursive: true });

const ENTRIES = [
  { in: "src/background.ts",       out: "background" },
  { in: "src/content-hubspot.ts",  out: "content-hubspot" },
  { in: "src/content-linkedin.ts", out: "content-linkedin" },
  { in: "src/popup.ts",            out: "popup" },
];

async function build() {
  for (const entry of ENTRIES) {
    await esbuild.build({
      entryPoints: [entry.in],
      bundle: true,
      outfile: `${OUT}/${entry.out}.js`,
      platform: "browser",
      target: "chrome120",
      format: "iife",
      minify: process.env.NODE_ENV === "production",
      sourcemap: process.env.NODE_ENV !== "production",
    });
    console.log(`✓ ${entry.out}.js`);
  }

  // Copy static files
  const STATIC = ["manifest.json", "popup.html"];
  for (const f of STATIC) {
    fs.copyFileSync(path.join(__dirname, `../${f}`), path.join(OUT, f));
    console.log(`✓ ${f}`);
  }

  // Copy icons dir if exists
  const iconsDir = path.join(__dirname, "../icons");
  if (fs.existsSync(iconsDir)) {
    fs.mkdirSync(path.join(OUT, "icons"), { recursive: true });
    for (const f of fs.readdirSync(iconsDir)) {
      fs.copyFileSync(path.join(iconsDir, f), path.join(OUT, "icons", f));
    }
    console.log("✓ icons/");
  }

  console.log("\n✅ Extension built → dist/");
  console.log("   Load as unpacked extension from: packages/chrome-extension/dist/");
}

build().catch(err => {
  console.error(err);
  process.exit(1);
});
