#!/usr/bin/env node
// Rebuild the embedded-WebView APK (app/洛书.apk) from scratch, guaranteeing:
//   1. Latest app/ assets are embedded (index.html / sw.js / manifest.json / etc.)
//   2. Native ActionBar/title is removed (android:theme -> Theme.Material.NoActionBar)
//   3. Re-signed with the persistent LUOSHU keystore
//
// This avoids needing the Android SDK: we take the existing signed APK as a template,
// swap in fresh assets + a patched AndroidManifest, repack with `jar`, and re-sign
// with `jarsigner`. Because we always patch the theme, repackaging never re-introduces
// the title bar.
//
// Usage: node tools/build_webview_apk.js
//   (run from gold_monitor/; requires JDK on PATH: jar/keytool/jarsigner)

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const APK = path.join(ROOT, 'app', '洛书.apk');
const WORK = path.join(ROOT, '.webview_build');
const KEYSTORE = path.join(ROOT, 'app', 'luoshu.keystore'); // persistent, tracked-ignored
const KS_PASS = 'luoshu123';
const ALIAS = 'luoshu';

// Assets to refresh from app/ into the APK's assets/ dir.
// NOTE: embedded index.html uses FLAT paths (chart.umd.min.js, not ../), so we rewrite.
const ASSET_FILES = ['index.html', 'sw.js', 'manifest.json', 'messages.json', 'latest.json', 'chart.umd.min.js', 'icon-192.png', 'icon-512.png'];

function sh(cmd, opts = {}) {
  return execSync(cmd, { stdio: 'pipe', encoding: 'utf8', ...opts });
}

function main() {
  if (!fs.existsSync(APK)) { console.error('template APK not found:', APK); process.exit(1); }

  // 1. Clean + unzip template
  fs.rmSync(WORK, { recursive: true, force: true });
  fs.mkdirSync(path.join(WORK, 'work'), { recursive: true });
  sh(`unzip -o -q "${APK}" -d "${path.join(WORK, 'work')}"`);
  console.log('[1] unpacked template APK');

  const work = path.join(WORK, 'work');
  const assetsDir = path.join(work, 'assets');

  // 2. Refresh assets from app/
  for (const f of ASSET_FILES) {
    const src = path.join(ROOT, 'app', f);
    if (!fs.existsSync(src)) { console.log(`    skip missing ${f}`); continue; }
    let dst = path.join(assetsDir, f);
    if (f === 'index.html') {
      // rewrite ../chart -> chart (flat) for embedded layout
      let html = fs.readFileSync(src, 'utf8');
      html = html.replace(/\.\.\/chart\.umd\.min\.js/g, 'chart.umd.min.js')
                 .replace(/src="\.\.\//g, 'src="')
                 .replace(/href="\.\.\//g, 'href="');
      fs.writeFileSync(dst, html);
      console.log('    embedded index.html (flat paths)');
    } else {
      fs.copyFileSync(src, dst);
      console.log(`    embedded ${f}`);
    }
  }

  // 3. Patch AndroidManifest.xml theme -> NoActionBar
  const manifest = path.join(work, 'AndroidManifest.xml');
  sh(`node "${path.join(__dirname, 'axml_patch.js')}" "${manifest}" "${manifest}"`);
  console.log('[3] patched AndroidManifest theme -> NoActionBar');

  // 4. Remove old signature
  fs.rmSync(path.join(work, 'META-INF'), { recursive: true, force: true });

  // 5. Repack with jar
  const unsigned = path.join(WORK, 'luoshu-unsigned.apk');
  sh(`jar cfM "${unsigned}" -C "${work}" .`);
  console.log('[5] repacked APK');

  // 6. Ensure keystore exists (persist so signature is stable across rebuilds)
  if (!fs.existsSync(KEYSTORE)) {
    sh(`keytool -genkeypair -v -keystore "${KEYSTORE}" -alias ${ALIAS} -keyalg RSA -keysize 2048 -validity 10000 -storepass ${KS_PASS} -keypass ${KS_PASS} -dname "CN=Luoshu, OU=Dev, O=Luoshu, L=Shanghai, S=Shanghai, C=CN"`);
    console.log('[6] generated persistent keystore');
  } else {
    console.log('[6] reusing persistent keystore');
  }

  // 7. Sign
  sh(`jarsigner -keystore "${KEYSTORE}" -storepass ${KS_PASS} -keypass ${KS_PASS} "${unsigned}" ${ALIAS}`);
  fs.copyFileSync(unsigned, APK);
  const sz = fs.statSync(APK).size;
  console.log(`[7] signed and wrote ${APK} (${sz} bytes)`);

  // 8. Cleanup
  fs.rmSync(WORK, { recursive: true, force: true });
  console.log('[8] done');
}

main();
