#!/usr/bin/env node
// Add android:theme="@android:style/Theme.Material.NoActionBar" to the <application> element
// of a binary AndroidManifest.xml (AXML) that lacks a theme attribute.
//
// We add a string-named "theme" attribute (same form that works in our WebView APK) and
// append the "theme" string to the string pool. The value is a reference to the system
// NoActionBar theme. This is what a normal build with Theme.NoActionBar produces.
//
// Usage: node axml_add_theme.js <input.xml> <output.xml>

const fs = require('fs');

const RES_STRING_POOL_TYPE = 0x001C0001;
const RES_XML_RESOURCE_MAP_TYPE = 0x00080180;
const RES_XML_START_ELEMENT_TYPE = 0x00100102;

const THEME_NO_ACTION_BAR = 0x01030360; // Theme.Material.NoActionBar

function r16(b, o) { return b.readUInt16LE(o); }
function r32(b, o) { return b.readUInt32LE(o); }
function w16(b, o, v) { b.writeUInt16LE(v, o); }
function w32(b, o, v) { b.writeUInt32LE(v, o); }

function findChunk(buf, type, from) {
  let pos = from;
  while (pos + 8 <= buf.length) {
    const t = r32(buf, pos);
    const size = r32(buf, pos + 4);
    if (t === type) return { pos, size };
    if (size <= 0) break;
    pos += size;
  }
  return null;
}

function decodeStrings(buf, sp) {
  const start = sp.pos;
  const count = r32(buf, start + 8);
  const flags = r32(buf, start + 16);
  const stringsStart = r32(buf, start + 20);
  const isUtf8 = (flags & 0x100) !== 0;
  const offsets = [];
  for (let i = 0; i < count; i++) offsets.push(r32(buf, start + 28 + i * 4));
  const base = start + stringsStart;
  const strs = [];
  for (let i = 0; i < count; i++) {
    let off = base + offsets[i];
    let s;
    if (isUtf8) {
      let len = buf[off], k = 1;
      if (len & 0x80) { len = ((len & 0x7f) << 8) | buf[off + 1]; k = 2; }
      s = buf.toString('utf8', off + k, off + k + len);
    } else {
      let len = r16(buf, off), k = 2;
      if (len & 0x8000) { len = ((len & 0x7fff) << 16) | r16(buf, off + 2); k = 4; }
      s = buf.toString('utf16le', off + k, off + k + len * 2);
    }
    strs.push(s);
  }
  return { strs, isUtf8, stringsStart: base, poolStart: start, headerSize: stringsStart };
}

function encodeString(s, isUtf8) {
  if (isUtf8) {
    const bytes = Buffer.from(s, 'utf8');
    const len = bytes.length;
    const head = len < 0x80 ? Buffer.from([len]) : Buffer.from([(len >> 8) | 0x80, len & 0xff]);
    return Buffer.concat([head, bytes]);
  } else {
    const wlen = Buffer.alloc(2);
    wlen.writeUInt16LE(s.length, 0);
    const body = Buffer.alloc(s.length * 2);
    for (let i = 0; i < s.length; i++) body.writeUInt16LE(s.charCodeAt(i), i * 2);
    return Buffer.concat([wlen, body]);
  }
}

function main() {
  const [,, input, output] = process.argv;
  if (!input || !output) { console.error('usage: node axml_add_theme.js <input> <output>'); process.exit(1); }

  let buf = Buffer.from(fs.readFileSync(input));

  // --- 1. String pool ---
  const sp = findChunk(buf, RES_STRING_POOL_TYPE, 8);
  const { strs, isUtf8, stringsStart, poolStart } = decodeStrings(buf, sp);
  if (strs.includes('theme')) { console.log('theme string already present'); }
  else {
    // Append "theme" string to the pool.
    const encoded = encodeString('theme', isUtf8);
    const count = r32(buf, poolStart + 8);
    const flags = r32(buf, poolStart + 16);
    const strStart = r32(buf, poolStart + 20); // offset of string data from poolStart
    const offsetsEnd = poolStart + 28 + count * 4; // end of offset array
    const strDataStart = poolStart + strStart;     // absolute start of string data
    const newOffset = (offsetsEnd - strDataStart); // offset of new string relative to string data start

    // Build new offset array (old offsets + new offset), then new string data
    const newOffsets = Buffer.alloc((count + 1) * 4);
    for (let i = 0; i < count; i++) w32(newOffsets, i * 4, r32(buf, poolStart + 28 + i * 4));
    w32(newOffsets, count * 4, newOffset);

    // Old string data region: [strDataStart, strDataStart + oldDataLen]
    const oldDataLen = sp.size - (strDataStart - poolStart);
    const oldData = buf.slice(strDataStart, strDataStart + oldDataLen);

    // New pool body after the 28-byte header: offsetArray + stringData
    const newPoolBody = Buffer.concat([newOffsets, oldData, encoded]);
    const newPoolSize = 28 + newPoolBody.length;

    // Replace the pool chunk
    const newPool = Buffer.alloc(newPoolSize);
    buf.slice(poolStart, poolStart + 28).copy(newPool, 0); // copy header
    newPoolBody.copy(newPool, 28);
    w32(newPool, 8, count + 1);     // string count
    w32(newPool, 4, newPoolSize);   // chunk size
    // stringsStart unchanged (string data still starts at same relative offset within header? NO - offset array grew)

    // The offset array grew by 4, so string data shifts by +4 -> stringsStart += 4
    const newStrStart = strStart + 4;
    w32(newPool, 20, newStrStart);

    // Splice: replace old pool [poolStart, poolStart+sp.size) with newPool
    buf = Buffer.concat([buf.slice(0, poolStart), newPool, buf.slice(poolStart + sp.size)]);
    console.log(`[pool] added "theme" string; pool ${sp.size} -> ${newPoolSize}`);
  }

  // --- 2. Find <application> and add theme attribute ---
  // Re-locate string pool after potential edit
  const sp2 = findChunk(buf, RES_STRING_POOL_TYPE, 8);
  const dec2 = decodeStrings(buf, sp2);
  const themeIdx = dec2.strs.indexOf('theme');
  if (themeIdx < 0) { console.error('theme string not found after add'); process.exit(1); }

  let pos = 8;
  while (pos + 8 <= buf.length) {
    const t = r32(buf, pos);
    const size = r32(buf, pos + 4);
    if (t === RES_XML_START_ELEMENT_TYPE) {
      const nameIdx = r32(buf, pos + 20);
      const elemName = dec2.strs[nameIdx] || `idx${nameIdx}`;
      if (elemName === 'application') {
        const attrStart = r16(buf, pos + 24);
        const attrSize = r16(buf, pos + 26);
        const attrCount = r16(buf, pos + 28);
        const attrBase = pos + 16 + attrStart;
        const attrEnd = attrBase + attrCount * attrSize;

        // New attribute: ns(4)=0xffffffff, name(4)=themeIdx, rawValue(4)=0xffffffff,
        //   value_size(2)=8, value_res0(1)=0, value_type(1)=1, value_data(4)=THEME
        const newAttr = Buffer.alloc(20);
        w32(newAttr, 0, 0xffffffff);        // ns
        w32(newAttr, 4, themeIdx);          // name -> "theme" string
        w32(newAttr, 8, 0xffffffff);        // rawValue
        w16(newAttr, 12, 8);                // value_size
        newAttr[14] = 0;                     // value_res0
        newAttr[15] = 0x01;                  // value_type = TYPE_REFERENCE
        w32(newAttr, 16, THEME_NO_ACTION_BAR);

        buf = Buffer.concat([buf.slice(0, attrEnd), newAttr, buf.slice(attrEnd)]);

        // Update attrCount
        w16(buf, pos + 28, attrCount + 1);
        // Update element chunk size
        w32(buf, pos + 4, size + 20);
        console.log(`[application] added theme attribute (themeIdx=${themeIdx}, value=0x${THEME_NO_ACTION_BAR.toString(16)})`);
        break;
      }
    }
    if (size <= 0) break;
    pos += size;
  }

  fs.writeFileSync(output, buf);
  console.log(`OK: wrote ${output}`);
}
main();
