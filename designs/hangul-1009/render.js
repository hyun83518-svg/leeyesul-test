const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' }).catch(() => chromium.launch());
  const jobs = [['thumb.html',1600,900,'hangul-1009-package-thumb-1600x900.png'],['ig-package.html',1080,1350,'hangul-1009-ig-package-1080x1350.png'],['ig-ride.html',1080,1350,'hangul-1009-ig-ride-1080x1350.png'],['ig-hour.html',1080,1350,'hangul-1009-ig-onehour-1080x1350.png']];
  for (const [f,w,h,o] of jobs) {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await p.goto('file://' + __dirname + '/' + f, { waitUntil: 'networkidle' });
    await p.evaluate(async () => { const t = document.body.innerText + '0123456789,%원'; for (const fam of ["Black Han Sans", "Anton", "Noto Sans KR", "Playfair Display", "Montserrat"]) for (const w of ['400','700','900','300']) { try { await document.fonts.load(`${w} 40px "${fam}"`, t); await document.fonts.load(`italic 900 40px "${fam}"`, 'arte'); } catch (e) {} } await document.fonts.ready; });
    await p.waitForLoadState('networkidle'); await p.waitForTimeout(1500);
    await p.screenshot({ path: __dirname + '/export/' + o, clip: { x: 0, y: 0, width: w, height: h } });
  }
  await b.close();
})();
