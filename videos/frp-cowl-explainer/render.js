// Renders frp-cowl.html to an MP4 by seeking the animation frame by frame in headless Chromium.
// Usage: NODE_PATH=$(npm root -g) node render.js [--preview]   (preview = a handful of PNG stills only)
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const FPS = 30, DUR = 30, W = 1080, H = 1920;
const OUT_DIR = process.env.FRAMES_DIR || path.join(__dirname, 'frames');
const OUT_MP4 = path.join(__dirname, 'frp-cowl-30s.mp4');
const PREVIEW = process.argv.includes('--preview');
const FFMPEG = process.env.FFMPEG || (() => { try { return execFileSync('python3', ['-c', 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())']).toString().trim(); } catch { return 'ffmpeg'; } })();

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'frp-cowl.html'));
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);

  const times = PREVIEW ? [2.0, 5.6, 6.3, 8.0, 14.0, 17.5, 19.0, 21.2] : Array.from({ length: FPS * DUR }, (_, i) => i / FPS);
  let i = 0;
  for (const t of times) {
    await page.evaluate(t => window.seek(t), t);
    const name = PREVIEW ? `preview_${t.toFixed(1)}.png` : `f${String(i).padStart(4, '0')}.png`;
    await page.screenshot({ path: path.join(OUT_DIR, name), type: 'png' });
    if (!PREVIEW && i % 100 === 0) console.log(`frame ${i}/${times.length}`);
    i++;
  }
  await browser.close();
  if (PREVIEW) { console.log('preview stills in', OUT_DIR); return; }

  execFileSync(FFMPEG, ['-y', '-framerate', String(FPS), '-i', path.join(OUT_DIR, 'f%04d.png'),
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(FPS),
    '-c:a', 'aac', '-b:a', '96k', '-shortest', '-movflags', '+faststart', OUT_MP4], { stdio: 'inherit' });
  console.log('wrote', OUT_MP4);
})();
