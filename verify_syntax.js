// Extract inline <script> from chart_template.html and syntax-check it via vm.
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("chart_template.html", "utf8");
// Find the inline script: the one without src attribute.
// Strategy: grab content between the LAST <script> (no src) and its matching </script>.
const re = /<script>([\s\S]*?)<\/script>/g;
let m, js = null;
while ((m = re.exec(html)) !== null) {
  js = m[1]; // last one wins (the inline block)
}
if (js === null) {
  console.error("NO INLINE SCRIPT FOUND");
  process.exit(2);
}
try {
  new vm.Script(js, { filename: "inline.js" });
  console.log("SYNTAX OK; inline script length =", js.length, "chars");
  // Sanity checks for the DPR fix
  const hasBadMult = /\bcssX\s*\*\s*dpr\b|\bdprX\b/.test(js);
  const hasGetPixel = (js.match(/getPixelForValue/g) || []).length;
  console.log("contains 'cssX * dpr' / dprX (should be false):", hasBadMult);
  console.log("getPixelForValue occurrences:", hasGetPixel);
} catch (e) {
  console.error("SYNTAX ERROR:", e.message);
  process.exit(1);
}
