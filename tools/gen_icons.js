const sharp = require('sharp');
const path = require('path');
const fs = require('fs');

const SRC = 'E:/Program Files/Workspace/WorkBuddy/Claw/gold_monitor/app/icon-512.png';
const OUT = 'E:/Program Files/Workspace/WorkBuddy/Claw/gold_monitor/android-app/app/src/main/res';

const sizes = {
  mdpi: 48,
  hdpi: 72,
  xhdpi: 96,
  xxhdpi: 144,
  xxxhdpi: 192,
};

(async () => {
  for (const [d, s] of Object.entries(sizes)) {
    const dir = path.join(OUT, `mipmap-${d}`);
    fs.mkdirSync(dir, { recursive: true });
    await sharp(SRC).resize(s, s).png().toFile(path.join(dir, 'ic_launcher.png'));
    console.log('wrote', d, s + 'x' + s);
  }
  console.log('ALL ICONS DONE');
})().catch((e) => {
  console.error('ICON GEN FAILED:', e);
  process.exit(1);
});
