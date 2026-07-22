#!/usr/bin/env node
/**
 * 部署「洛书」App 到 GitHub Pages 的 /app/ 子路径。
 *
 * 设计要点：
 * - 从当前 main 工作树的 app/ 读取最新源码（含笑脸 logo、当前消息）。
 * - 把绝对根路径改成相对路径，使 PWA 在 /app/ 子路径下能正确「添加到主屏幕」安装。
 * - 用 git worktree 检出 gh-pages 到临时目录，避免切换 main 工作树 / 动到未提交改动。
 * - 单分支 force-push gh-pages 的 app/ 目录，不触碰根路径的 K 线图。
 *
 * 用法：node tools/deploy_app.js
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const repo = path.resolve(__dirname, '..');
const appDir = path.join(repo, 'app');

function log(...a) { console.log('[deploy-app]', ...a); }

// ── 1. 构建可部署包（相对路径，子路径安全） ──
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'appbundle-'));
const bundle = path.join(tmp, 'appbundle');
fs.mkdirSync(bundle, { recursive: true });

function copyFromApp(name) {
  const s = path.join(appDir, name);
  if (fs.existsSync(s)) fs.copyFileSync(s, path.join(bundle, name));
}
function copyFromRoot(name) {
  const s = path.join(repo, name);
  if (fs.existsSync(s)) fs.copyFileSync(s, path.join(bundle, name));
}

// index.html：把绝对资源路径改相对
let html = fs.readFileSync(path.join(appDir, 'index.html'), 'utf8');
html = html
  .replace(/href="\/manifest\.json"/g, 'href="manifest.json"')
  .replace(/href="\/icon-192\.png"/g, 'href="icon-192.png"')
  .replace(/src="\/icon-192\.png"/g, 'src="icon-192.png"')
  .replace(/src="\.\.\/chart\.umd\.min\.js"/g, 'src="chart.umd.min.js"')
  .replace(/register\('\/sw\.js'\)/g, "register('./sw.js')");
fs.writeFileSync(path.join(bundle, 'index.html'), html);

// manifest.json：子路径正确的 PWA 配置
const manifest = {
  name: '洛书',
  short_name: '洛书',
  description: '黄金价格实时监控与消息推送',
  start_url: './',
  display: 'standalone',
  background_color: '#0a0a15',
  theme_color: '#0a0a15',
  orientation: 'portrait',
  scope: './',
  icons: [
    { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
    { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
  ],
};
fs.writeFileSync(path.join(bundle, 'manifest.json'), JSON.stringify(manifest, null, 2));

// sw.js：缓存资源改相对路径（保留 /api/ 检测不动）
let sw = fs.readFileSync(path.join(appDir, 'sw.js'), 'utf8');
sw = sw
  .replace("'/index.html'", "'./index.html'")
  .replace("'/manifest.json'", "'./manifest.json'")
  .replace("'/icon-192.png'", "'./icon-192.png'")
  .replace("'/icon-512.png'", "'./icon-512.png'")
  .replace("'/messages.json'", "'./messages.json'")
  .replace("'/'", "'./'");
fs.writeFileSync(path.join(bundle, 'sw.js'), sw);

// 静态资源 + 当前数据
copyFromApp('icon-192.png');
copyFromApp('icon-512.png');
copyFromApp('chart.umd.min.js');
copyFromRoot('chart.umd.min.js');
copyFromApp('messages.json');
copyFromRoot('latest.json');

const files = fs.readdirSync(bundle);
log('构建完成，包内容:', files.join(', '));

// ── 2. 用 worktree 安全推到 gh-pages 的 app/ ──
const wt = fs.mkdtempSync(path.join(os.tmpdir(), 'ghwt-'));
try {
  log('检出 gh-pages 到临时 worktree ...');
  execSync(`git worktree add "${wt}" gh-pages`, { cwd: repo, stdio: 'inherit' });

  const appDest = path.join(wt, 'app');
  fs.rmSync(appDest, { recursive: true, force: true });
  fs.cpSync(bundle, appDest, { recursive: true });
  log('已写入 app/ 目录');

  execSync('git add app', { cwd: wt, stdio: 'inherit' });
  const msg = 'Deploy app ' + new Date().toISOString().slice(0, 16).replace('T', ' ');
  try {
    execSync(`git commit -m "${msg}"`, { cwd: wt, stdio: 'inherit' });
  } catch (e) {
    log('没有变化，跳过提交');
  }
  log('推送到 gh-pages (force) ...');
  execSync('git push origin gh-pages --force', { cwd: wt, stdio: 'inherit' });
  log('✅ 推送成功');
} catch (e) {
  log('❌ 部署失败:', e.message);
  process.exitCode = 1;
} finally {
  try { execSync(`git worktree remove "${wt}" --force`, { cwd: repo, stdio: 'inherit' }); } catch (_) {}
  fs.rmSync(tmp, { recursive: true, force: true });
}

log('App 访问地址: https://childeShu.github.io/gold-monitor/app/');
