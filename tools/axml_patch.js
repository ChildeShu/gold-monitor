#!/usr/bin/env node
// Proper AXML (binary AndroidManifest.xml) patcher.
// Removes the native ActionBar/title by changing android:theme to a NoActionBar system theme.
// This is exactly what a normal build with Theme.NoActionBar produces -- we just apply the
// same final manifest value to an existing APK so we can repackage without the Android SDK.
//
// Usage: node axml_patch.js <input.xml> <output.xml>
//
// Ref: android.R.attr.theme = 0x01010000
//      Theme.Material.NoActionBar        = 0x01030360  (dark)
//      Theme.Material.Light.NoActionBar  = 0x01030361  (light)
//      Theme.DeviceDefault.NoActionBar   = 0x01030348

const fs = require('fs');

const RES_STRING_POOL_TYPE = 0x001C0001;
const RES_XML_RESOURCE_MAP_TYPE = 0x00080180;
const RES_XML_START_ELEMENT_TYPE = 0x00100102;

const ATTR_THEME = 0x01010000;
const THEME_NO_ACTION_BAR = 0x01030360; // dark, no action bar

function readU16(buf, off) { return buf.readUInt16LE(off); }
function readU32(buf, off) { return buf.readUInt32LE(off); }
function writeU32(buf, off, v) { buf.writeUInt32LE(v, off); }

function decodeStringPool(buf, start) {
  const stringCount = readU32(buf, start + 8);
  const flags = readU32(buf, start + 16);
  const stringsStart = readU32(buf, start + 20);
  const isUtf8 = (flags & 0x100) !== 0;
  const offsets = [];
  for (let i = 0; i < stringCount; i++) offsets.push(readU32(buf, start + 28 + i * 4));
  const strings = [];
  const base = start + stringsStart;
  for (let i = 0; i < stringCount; i++) {
    let off = base + offsets[i];
    let str;
    if (isUtf8) {
      let len = buf[off], skip = 1;
      if (len & 0x80) { len = ((len & 0x7f) << 8) | buf[off + 1]; skip = 2; }
      str = buf.toString('utf8', off + skip, off + skip + len);
    } else {
      let len = readU16(buf, off), skip = 2;
      if (len & 0x8000) { len = ((len & 0x7fff) << 16) | readU16(buf, off + 2); skip = 4; }
      str = buf.toString('utf16le', off + skip, off + skip + len * 2);
    }
    strings.push(str);
  }
  return strings;
}

function findChunk(buf, type, from) {
  let pos = from;
  while (pos + 8 <= buf.length) {
    const t = readU32(buf, pos);
    const size = readU32(buf, pos + 4);
    if (t === type) return { pos, size };
    if (size <= 0) break;
    pos += size;
  }
  return null;
}

function main() {
  const [,, input, output] = process.argv;
  if (!input || !output) { console.error('usage: node axml_patch.js <input> <output>'); process.exit(1); }

  const buf = Buffer.from(fs.readFileSync(input)); // mutable copy

  // 1. String pool
  const sp = findChunk(buf, RES_STRING_POOL_TYPE, 8);
  if (!sp) { console.error('string pool not found'); process.exit(1); }
  const strings = decodeStringPool(buf, sp.pos);

  // 2. Resource map (attribute resource IDs in document order)
  const rm = findChunk(buf, RES_XML_RESOURCE_MAP_TYPE, sp.pos + sp.size);
  let resIds = [];
  if (rm) {
    const count = (rm.size - 8) / 4;
    for (let i = 0; i < count; i++) resIds.push(readU32(buf, rm.pos + 8 + i * 4));
  }

  // 3. Walk start elements. Match the theme attribute by its NAME string ("theme"),
  //    since the RES_XML_RESOURCE_MAP in this APK is sorted by resource ID (not document
  //    order) and therefore cannot be used to locate attributes positionally.
  let pos = 8;
  let patched = 0;
  while (pos + 8 <= buf.length) {
    const t = readU32(buf, pos);
    const size = readU32(buf, pos + 4);
    if (t === RES_XML_START_ELEMENT_TYPE) {
      const nameIdx = readU32(buf, pos + 20);
      const attrStart = readU16(buf, pos + 24);
      const attrSize = readU16(buf, pos + 26);
      const attrCount = readU16(buf, pos + 28);
      const elemName = strings[nameIdx] || `idx${nameIdx}`;
      const attrBase = pos + 16 + attrStart;
      for (let a = 0; a < attrCount; a++) {
        const ao = attrBase + a * attrSize;
        const nameField = readU32(buf, ao + 4);
        const attrName = (nameField !== 0xffffffff) ? strings[nameField] : null;
        if (attrName !== 'theme') continue;
        const valueDataOff = ao + 16;
        const valueType = buf[ao + 15];
        const valueData = readU32(buf, valueDataOff);
        console.log(`<${elemName}> android:theme: type=0x${valueType.toString(16)} data=0x${valueData.toString(16)}`);
        if (valueType === 0x01 || valueType === 0x02) { // TYPE_REFERENCE / TYPE_ATTRIBUTE
          writeU32(buf, valueDataOff, THEME_NO_ACTION_BAR);
          console.log(`  -> patched to 0x${THEME_NO_ACTION_BAR.toString(16)} (Theme.Material.NoActionBar)`);
          patched++;
        } else {
          console.log('  -> unexpected value type, skipping');
        }
      }
    }
    if (size <= 0) break;
    pos += size;
  }

  if (patched > 0) {
    fs.writeFileSync(output, buf);
    console.log(`OK: wrote ${output} (${patched} theme attr patched)`);
  } else {
    console.log('No android:theme reference attribute found to patch.');
  }
}
main();
