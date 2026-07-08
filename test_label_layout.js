// 单元测试 layoutLabels 防重叠算法（与 chart_template.html 内实现保持一致）
function layoutLabels(items, ca, lh, minGap) {
  var n = items.length;
  if (n === 0) return [];
  var tops = new Array(n);
  for (var i = 0; i < n; i++) tops[i] = items[i].ptY - lh / 2;
  for (var i = 1; i < n; i++) {
    if (tops[i] < tops[i - 1] + lh + minGap) tops[i] = tops[i - 1] + lh + minGap;
  }
  var overflow = (tops[n - 1] + lh) - (ca.bottom - 2);
  if (overflow > 0) {
    for (var j = 0; j < n; j++) tops[j] -= overflow;
  }
  if (tops[0] < ca.top + 2) {
    var shift = (ca.top + 2) - tops[0];
    for (var k = 0; k < n; k++) tops[k] += shift;
    for (var m = 1; m < n; m++) {
      if (tops[m] < tops[m - 1] + lh + minGap) tops[m] = tops[m - 1] + lh + minGap;
    }
  }
  return tops;
}

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exitCode = 1; } else { console.log("PASS: " + msg); } }

var ca = { top: 50, bottom: 400 }; // 高度 350
var lh = 20, minGap = 2;

// 1) 全部同价（真实 bug：周大福/潮宏基/金至尊…同价）-> 必须全部错开且不溢出
var samePrice = [];
for (var i = 0; i < 8; i++) samePrice.push({ ptY: 200 });
var t1 = layoutLabels(samePrice, ca, lh, minGap);
var ok = true;
for (var i = 1; i < t1.length; i++) if (t1[i] - t1[i-1] < lh + minGap - 0.001) ok = false;
assert(ok, "同价 8 项：纵向全部错开 (gap >= lh+minGap)");
assert(t1[0] >= ca.top + 2 - 0.001, "同价 8 项：顶部不越界");
assert(t1[t1.length-1] + lh <= ca.bottom - 2 + 0.001, "同价 8 项：底部不越界 (8*22=176 <= 350)");

// 2) 聚集在底部（ptY=390 接近 bottom=400）
var bottomCluster = [];
for (var i = 0; i < 6; i++) bottomCluster.push({ ptY: 390 });
var t2 = layoutLabels(bottomCluster, ca, lh, minGap);
var ok2 = true;
for (var i = 1; i < t2.length; i++) if (t2[i] - t2[i-1] < lh + minGap - 0.001) ok2 = false;
assert(ok2, "底部聚集 6 项：仍错开");
assert(t2[t2.length-1] + lh <= ca.bottom - 2 + 0.001, "底部聚集 6 项：整体被上移不溢出 (6*22=132 <= 350)");

// 3) 自然分散（间隔 > lh+minGap）-> 保持原样，不强行推开
var spread = [
  { ptY: 60 }, { ptY: 120 }, { ptY: 300 }, { ptY: 380 }
];
var t3 = layoutLabels(spread, ca, lh, minGap);
assert(Math.abs((t3[1] - t3[0]) - (120 - 20 - (60 - 20))) < 0.001, "分散项：保持原始间距不被推开");
// ptY=60 -> top=50 会贴住图表上沿(ca.top=50)，算法会下移到 ca.top+2=52 防裁切，这是期望行为
assert(Math.abs(t3[0] - Math.max(60 - lh/2, ca.top + 2)) < 0.001, "分散项[0]：top 不裁切上沿");

// 4) 边界：top 紧贴上沿
var topEdge = [{ ptY: 55 }, { ptY: 55 }];
var t4 = layoutLabels(topEdge, ca, lh, minGap);
assert(t4[0] >= ca.top + 2 - 0.001, "上沿两同价：第1项不越上界");
assert(t4[1] - t4[0] >= lh + minGap - 0.001, "上沿两同价：仍错开");

console.log(process.exitCode ? "\n=== 有失败用例 ===" : "\n=== 全部标签布局用例通过 ===");
