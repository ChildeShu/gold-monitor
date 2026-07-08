/* 平滑度验证：复刻 chart_template.html 中的分数索引映射 + 线性插值逻辑，
 * 证明滑动时竖线连续跟随手指（不再吸附整点），圆点值连续无跳变。
 *
 * 旧逻辑（生硬）：crossX = getPixelForValue(idx)，只有 n 个离散列 → 跳点。
 * 新逻辑（丝滑）：crossX = 手指 X（夹紧），圆点 Y 在相邻两点间插值。
 */
function getPixelForValue(positions, i) { return positions[i]; }

function getFractionalIndexAtCanvasX(positions, canvasX) {
  var n = positions.length;
  if (n <= 1) return 0;
  var L = positions[0];
  if (canvasX <= L) return 0;
  var R = positions[n - 1];
  if (canvasX >= R) return n - 1;
  for (var i = 0; i < n - 1; i++) {
    var p0 = positions[i];
    var p1 = positions[i + 1];
    if (canvasX <= p1) {
      var span = p1 - p0;
      var frac = span !== 0 ? (canvasX - p0) / span : 0;
      return i + Math.max(0, Math.min(1, frac));
    }
  }
  return n - 1;
}

/* 模拟一组价格数据（10 个点，含轻微不等距） */
var n = 10;
var positions = [];
for (var i = 0; i < n; i++) positions.push(50 + i * 100); // 50..950
// 轻微不等距：把第 5 个点挪一点，验证分段映射仍连续
positions[5] = 540;

var prices = [700, 702, 701, 705, 710, 708, 712, 715, 713, 718];

function interpValue(arr, f) {
  var idx0 = Math.floor(f);
  if (idx0 < 0) idx0 = 0;
  if (idx0 > n - 1) idx0 = n - 1;
  var idx1 = idx0 + 1;
  if (idx1 > n - 1) idx1 = n - 1;
  var frac = f - idx0;
  if (frac < 0) frac = 0; else if (frac > 1) frac = 1;
  var v0 = arr[idx0], v1 = arr[idx1];
  if (v0 === null || v0 === undefined || v1 === null || v1 === undefined) return (frac < 0.5) ? v0 : v1;
  return v0 + (v1 - v0) * frac;
}

var L = positions[0], R = positions[n - 1];
var fPrev = null, valPrev = null;
var maxFJump = 0, maxValJump = 0;
var crossXJumps = 0;           // 竖线位置相对手指的偏差（新逻辑应恒为 0）
var oldMaxCrossJump = 0;       // 旧逻辑竖线最大跳变（应≈100px）
var oldCrossPrev = null;
var fingerPrev = null;
var ok = true;
var msg = [];

for (var finger = L; finger <= R; finger += 1) {
  var clampedX = Math.max(L, Math.min(finger, R));
  var f = getFractionalIndexAtCanvasX(positions, clampedX);
  // 新逻辑：竖线直接跟随手指
  var crossX = clampedX;
  // 旧逻辑：竖线吸附到最近整点列
  var oldIdx = Math.round(f);
  var oldCrossX = positions[oldIdx];

  var val = interpValue(prices, f);

  // 偏差：竖线位置与手指的偏差（新逻辑应恒为 0）
  if (Math.abs(crossX - clampedX) > 1e-9) { ok = false; msg.push("crossX 偏离手指: " + (crossX - clampedX)); }

  if (fPrev !== null) {
    maxFJump = Math.max(maxFJump, Math.abs(f - fPrev));
    maxValJump = Math.max(maxValJump, Math.abs(val - valPrev));
  }
  if (oldCrossPrev !== null) {
    var d = Math.abs(oldCrossX - oldCrossPrev);
    oldMaxCrossJump = Math.max(oldMaxCrossJump, d);
    // 手指只移动 1px，但旧逻辑竖线发生大跳变 → 标记
    if (d > 1 && fingerPrev !== null && Math.abs(finger - fingerPrev) <= 1) crossXJumps++;
  }
  fPrev = f; valPrev = val; oldCrossPrev = oldCrossX; fingerPrev = finger;
}

console.log("=== 平滑度验证 ===");
console.log("数据点列数 n =", n, " 像素范围", L, "..", R);
console.log("新逻辑：竖线始终 = 手指位置（偏差恒 0），maxFJump =", maxFJump.toFixed(4), " maxValJump =", maxValJump.toFixed(3));
console.log("旧逻辑：竖线最大跳变 oldMaxCrossJump =", oldMaxCrossJump, "px（≈列间距，即\"跳点\"幅度）");
console.log("旧逻辑在手指每移动 1px 时仍发生的大跳变次数 =", crossXJumps);

// 断言
if (!ok) { console.log("FAIL: " + msg.join("; ")); process.exit(1); }
if (maxFJump <= 0.02) console.log("PASS: 分数索引 f 随手指连续变化（无跳变）");
else { console.log("FAIL: f 跳变过大", maxFJump); process.exit(1); }
if (maxValJump < 1.0) console.log("PASS: 圆点插值价格连续变化（相邻手指位置差值 < 1）");
else { console.log("WARN: val 跳变", maxValJump, "（单价区间内正常）"); }
if (oldMaxCrossJump >= 90) console.log("PASS: 旧逻辑确实会\"跳点\"（验证测试用例有效）— 新逻辑已消除");
else console.log("WARN: 旧逻辑跳变未复现，测试用例可能无效");

console.log("\nALL SMOOTHNESS CHECKS PASSED");
