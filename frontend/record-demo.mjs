/**
 * Renaissance 9:16 Instagram Reel — chill sidebar tab tour
 * Click sidebar links (SPA navigation), scroll each page gently.
 */
import { chromium } from 'playwright';
import { execSync } from 'child_process';
import { mkdirSync, existsSync, rmSync, readdirSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FFMPEG = path.join(__dirname, 'node_modules', 'ffmpeg-static', 'ffmpeg.exe');
const FRAMES_DIR = path.join(__dirname, 'demo-frames');
const OUTPUT = path.join(__dirname, 'renaissance-demo-9x16.mp4');

const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 24;
const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.demo';

const MOCK_USER = { id: 'u1', email: 'admin@renaissance.ai', name: 'Admin', role: 'admin', org_id: 'o1' };
const MOCK_ORG = { id: 'o1', name: 'Renaissance Demo', slug: 'demo', plan: 'pro' };

// Sidebar link hrefs to click (no flywheel)
const TABS = [
  '/dashboard',
  '/brain',
  '/saturation',
  '/radar',
  '/opportunities',
  '/alerts',
  '/creatives',
  '/content-studio',
  '/analytics',
  '/data-room',
  '/decisions',
  '/control-panel',
  '/brand-profile',
  '/settings',
  '/help',
];

let frameIndex = 0;
function pad(n) { return String(n).padStart(6, '0'); }

async function snap(page) {
  try {
    await page.screenshot({ path: path.join(FRAMES_DIR, `frame_${pad(frameIndex++)}.png`), timeout: 5000 });
  } catch { frameIndex--; }
}

async function hold(page, seconds) {
  const n = Math.round(seconds * FPS);
  for (let i = 0; i < n; i++) { await snap(page); await page.waitForTimeout(42); }
}

async function smoothScroll(page, distance, durationSec) {
  const n = Math.round(durationSec * FPS);
  for (let i = 0; i < n; i++) {
    const t = i / n, nt = (i + 1) / n;
    const e = t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2,3)/2;
    const ne = nt < 0.5 ? 4*nt*nt*nt : 1 - Math.pow(-2*nt+2,3)/2;
    await page.evaluate(s => window.scrollBy(0, s), (ne - e) * distance);
    await snap(page);
    await page.waitForTimeout(35);
  }
}

function mockAllAPIs(route) {
  const url = route.request().url();
  if (url.includes('/auth/me'))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER) });
  if (url.includes('/auth/bootstrap-check'))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ needs_bootstrap: false }) });
  if (url.includes('/auth/refresh'))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: FAKE_JWT, refresh_token: FAKE_JWT, user: MOCK_USER }) });
  if (url.includes('/orgs'))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_ORG]) });
  if (url.includes('/onboarding/status'))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ completed: true }) });
  // Everything else → empty but valid
  return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
}

async function main() {
  if (existsSync(FRAMES_DIR)) rmSync(FRAMES_DIR, { recursive: true });
  mkdirSync(FRAMES_DIR, { recursive: true });

  console.log('Launching browser...');
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 })).newPage();

  // ── 1. Login page ──
  console.log('Recording: Login');
  await page.route('**/api/**', route => {
    if (route.request().url().includes('/auth/bootstrap-check'))
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ needs_bootstrap: false }) });
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);
  await hold(page, 3.5);

  // ── 2. Auth + navigate to dashboard via full page load ──
  console.log('Authenticating...');
  await page.unrouteAll();
  await page.route('**/api/**', mockAllAPIs);
  await page.evaluate(t => {
    localStorage.setItem('meta_ops_access_token', t);
    localStorage.setItem('meta_ops_refresh_token', t);
  }, FAKE_JWT);

  await page.goto('http://localhost:5173/dashboard', { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2500);

  const url0 = page.url();
  console.log(`  Initial page: ${url0}`);

  if (url0.includes('/login') || url0.includes('/onboarding')) {
    console.log('  Still redirected — aborting auth pages, recording what we have.');
  }

  // ── 3. Click through sidebar tabs (SPA client-side nav) ──
  for (const href of TABS) {
    const label = href.replace('/', '');
    console.log(`Recording: ${label}`);

    // Click the sidebar NavLink
    try {
      await page.click(`a.sidebar-link[href="${href}"]`, { timeout: 3000 });
    } catch {
      console.log(`  → sidebar link not found for ${href}, trying direct nav`);
      await page.evaluate(h => window.history.pushState({}, '', h), href);
      // Trigger React Router by dispatching popstate
      await page.evaluate(() => window.dispatchEvent(new PopStateEvent('popstate')));
    }
    await page.waitForTimeout(1200);

    console.log(`  → ${page.url()}`);

    // Scroll to top first
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);

    // Hold at top
    await hold(page, 2.5);

    // Gentle scroll if page has content
    const bodyH = await page.evaluate(() => document.body.scrollHeight);
    const dist = Math.min(bodyH - HEIGHT, 1800);
    if (dist > 100) {
      await smoothScroll(page, dist, 1.5);
      await hold(page, 0.6);
      await smoothScroll(page, -dist, 1.0);
    }

    await hold(page, 0.3);
  }

  // ── 4. Outro — back to login ──
  console.log('Recording: Outro');
  await page.unrouteAll();
  await page.route('**/api/**', route => {
    if (route.request().url().includes('/auth/bootstrap-check'))
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ needs_bootstrap: false }) });
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
  await page.evaluate(() => { localStorage.removeItem('meta_ops_access_token'); localStorage.removeItem('meta_ops_refresh_token'); });
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded', timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(1500);
  await hold(page, 3);

  await browser.close();

  const total = readdirSync(FRAMES_DIR).filter(f => f.endsWith('.png')).length;
  const dur = (total / FPS).toFixed(1);
  console.log(`\n${total} frames → ~${dur}s at ${FPS}fps`);

  console.log('Encoding MP4...');
  execSync([
    `"${FFMPEG}"`, '-y', `-framerate ${FPS}`,
    `-i "${path.join(FRAMES_DIR, 'frame_%06d.png')}"`,
    '-c:v libx264 -preset medium -crf 18',
    `-vf "fps=${FPS},format=yuv420p"`,
    '-movflags +faststart',
    `"${OUTPUT}"`,
  ].join(' '), { stdio: 'inherit', timeout: 600000 });

  console.log(`\nDone! → ${OUTPUT}`);
  console.log(`${WIDTH}x${HEIGHT} (9:16) | ~${dur}s`);
  rmSync(FRAMES_DIR, { recursive: true });
}

main().catch(e => { console.error(e); process.exit(1); });
