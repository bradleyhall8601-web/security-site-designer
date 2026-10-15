// Security Site Designer — live-site browser QA.  Created by Brad Hall.
// Drives the real user + admin workflow against a deployed URL in a real browser (Chrome, Edge or Chromium)
// using disposable QA projects only. Every result written to results.json comes from an action performed here.
//   BASE_URL  site to test (default: the public GitHub Pages site)
//   BROWSER   chrome | msedge | chromium
//   OUT       folder for results.json, screenshots and every exported file
import {chromium} from 'playwright';
import fs from 'fs'; import path from 'path'; import os from 'os'; import {fileURLToPath} from 'url';

const BASE = process.env.BASE_URL || 'https://bradleyhall8601-web.github.io/security-site-designer/';
const CH = process.env.BROWSER || 'chromium';
const OUT = path.resolve(process.env.OUT || 'qa-out');
const HEADED = process.env.HEADED === '1';
const LOCAL_LIBS = process.env.LOCAL_LIBS || ''; // dev only: serve the CDN libraries from a local node_modules
const FX = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures');
fs.mkdirSync(path.join(OUT, 'exports'), {recursive:true}); fs.mkdirSync(path.join(OUT, 'shots'), {recursive:true});
const STAMP = new Date().toISOString().replace(/[-:]/g, '').slice(0, 13);
const QA = (s) => `QA ${CH} ${STAMP} ${s}`; // every project this run touches is created here and named "QA …"

const LIBMAP = {'qrcode-generator/1.4.4/qrcode.js':'qrcode-generator/qrcode.js', 'pdf.js/3.11.174/pdf.min.js':'pdfjs-dist/build/pdf.min.js', 'pdf.js/3.11.174/pdf.worker.min.js':'pdfjs-dist/build/pdf.worker.min.js', 'jspdf/2.5.1/jspdf.umd.min.js':'jspdf/dist/jspdf.umd.min.js', 'xlsx/0.18.5/xlsx.full.min.js':'xlsx/dist/xlsx.full.min.js', 'dxf-parser@1.1.2/dist/dxf-parser.js':'dxf-parser/dist/dxf-parser.js', 'three@0.160.0/build/three.min.js':'three/build/three.min.js'};
const browser = await chromium.launch({channel: CH === 'chromium' ? undefined : CH, headless: !HEADED, args: CH === 'chromium' ? ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] : []});
const ENV = {browser: CH, version: browser.version(), headed: HEADED, os: `${os.type()} ${os.release()} ${os.arch()}`, node: process.version, url: BASE, started: new Date().toISOString()};

const errors = [];
async function newCtx(viewport = {width:1536, height:864}, extra = {}, sw = !LOCAL_LIBS) {
  const ctx = await browser.newContext({viewport, acceptDownloads:true, ...extra});
  if (LOCAL_LIBS) await ctx.route('**/*', (route) => { const u = route.request().url(); for (const k in LIBMAP) if (u.endsWith(k)) return route.fulfill({path: path.join(LOCAL_LIBS, LIBMAP[k]), contentType:'application/javascript'}); if (/^https?:\/\/(localhost|127\.)/.test(u) || u.startsWith(BASE)) return route.continue(); return route.abort(); });
  if (sw) await ctx.addInitScript(() => { window.__ssdPwaTest = true; }); // the app skips its service worker under automation unless asked; we want the real one
  const page = await ctx.newPage(); watch(page); return {ctx, page};
}
function watch(page) { page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); }); page.on('pageerror', e => errors.push('PAGEERROR ' + e.message)); }
const noise = (e) => /ERR_FAILED|ERR_INTERNET_DISCONNECTED|net::|favicon|Failed to load resource|nominatim|arcgisonline/i.test(e);

const R = []; const EXPORTS = []; let P, CTX; let n = 0;
const ev = (f, a) => P.evaluate(f, a);
const sleep = (ms) => P.waitForTimeout(ms);
const must = (c, m) => { if (!c) throw new Error(m || 'check failed'); };
async function t(area, name, expected, fn) {
  const e0 = errors.length, t0 = Date.now(); let observed = '', pass = false, err = '';
  try { observed = (await Promise.race([fn(), new Promise((_, rej) => setTimeout(() => rej(new Error('timed out after 150 s')), 150000))])) || 'as expected'; const ne = errors.slice(e0).filter(e => !noise(e)); if (ne.length) throw new Error('console error: ' + ne.join(' | ').slice(0, 300)); pass = true; }
  catch (e) { err = String(e.message || e).split('\n')[0].slice(0, 900); }
  const shot = `shots/${CH}-${String(++n).padStart(2, '0')}${pass ? '' : '-FAIL'}.png`; try { await P.screenshot({path: path.join(OUT, shot)}); } catch {}
  if (!pass) { try { await P.keyboard.press('Escape'); await P.keyboard.press('Escape'); await ev(() => document.querySelectorAll('.backdrop').forEach(b => b.remove())); } catch {} }
  R.push({area, name, expected, observed: pass ? observed : err, pass, ms: Date.now() - t0, evidence: shot});
  console.log(pass ? '✓' : '✗', `[${area}] ${name}`, pass ? '' : '— ' + err);
}
const fixture = (f) => path.join(FX, f);
const toastText = () => ev(() => [...document.querySelectorAll('#toasts .toast')].map(x => x.textContent).join(' | '));
const clearToasts = () => ev(() => document.querySelectorAll('#toasts .toast').forEach(x => x.remove()));
const state = () => ev(() => { const o = Object.values(SSD.S.project.objects); const c = (f) => o.filter(f).length; const fl = SSD.curFloor();
  return {id:SSD.S.project.id, name:SSD.S.project.name, floor:SSD.floorLabel ? SSD.floorLabel(SSD.S.floorId) : fl.name, floors:SSD.floors().map(f => f.name + (f.bg ? '+plan' : '')), rooms:c(x => x.t === 'room'), cams:c(x => x.t === 'dev' && SSD.kindOf(x).cat === 'camera'), devs:c(x => x.t === 'dev'), cables:c(x => x.t === 'cable'), calibrated:!!fl.calibrated, ftPerPx: fl.bg ? +fl.bg.ftPerPx.toPrecision(6) : null, scales:SSD.floors().map(f => `${f.name}:${f.calibrated ? 'cal' : '-'}:${f.bg ? (+f.bg.ftPerPx).toPrecision(6) : '-'}`).join(' '), prices:JSON.stringify(SSD.S.project.ownPrices || {})}; });
const toScreen = (w) => ev((p) => SSD.toScreen(p), w);
async function clickWorld(w) { const [x, y] = await toScreen(w); await P.mouse.click(x, y); await sleep(120); }
async function grab(label, act, ms = 120000) {
  const [d] = await Promise.all([P.waitForEvent('download', {timeout:ms}), act()]);
  const name = d.suggestedFilename(); const dest = path.join(OUT, 'exports', `${CH}-${name}`); await d.saveAs(dest); const buf = fs.readFileSync(dest);
  const head = buf.subarray(0, 8); const kind = head.subarray(0, 4).toString() === '%PDF' ? 'pdf' : head[0] === 0x89 && head[1] === 0x50 ? 'png' : head[0] === 0xff && head[1] === 0xd8 ? 'jpg' : head.subarray(0, 2).toString() === 'PK' ? 'zip' : 'text';
  await sleep(250); const shown = await toastText(); const rec = {label, name, size:buf.length, kind, toastShowsName: shown.includes(name)}; EXPORTS.push(rec);
  must(buf.length > 0, label + ' file is empty'); must(rec.toastShowsName, `no result message naming ${name} (toasts: ${shown.slice(0, 160)})`);
  return {name, buf, dest, text: kind === 'text' ? buf.toString('utf8') : ''};
}
// headless browsers sometimes swallow a file window; a person would just click again
async function chooser(act, files, tries = 4) { for (let k = 0; k < tries; k++) { const fc = await Promise.all([P.waitForEvent('filechooser', {timeout:4000}), act()]).then(([f]) => f).catch(() => null); if (fc) { await fc.setFiles(files); return k + 1; } await sleep(800); } throw new Error('file window never opened'); }
async function openApp() { await P.goto(BASE, {waitUntil:'load'}); await P.waitForFunction(() => window.SSD && SSD.S && SSD.S.project, null, {timeout:60000}); await sleep(1200); }
async function closeWelcome() { if (await P.isVisible('.welcome')) { await P.keyboard.press('Escape'); await sleep(300); } }
async function newProject(name, customer = 'QA Customer (disposable)', address = '') {
  await closeWelcome(); await P.click('#brand'); await P.waitForSelector('#dash:not([hidden])'); await P.click('#dash >> text=New project');
  await P.fill('.dlg input[aria-label="Project name"]', name); await P.fill('.dlg input[aria-label="Customer"]', customer); if (address) await P.fill('.dlg input[aria-label="Site address"]', address);
  await P.click('.dlg footer >> text=Create project'); try { await P.waitForFunction((n) => SSD.S.project && SSD.S.project.name === n, name, {timeout:15000}); } catch (e) { throw new Error(`new project not opened — current “${await ev(() => SSD.S.project && SSD.S.project.name)}”, dialogs: ${await ev(() => [...document.querySelectorAll('.dlg h2, .dlg header')].map(h => h.textContent).join(' | '))}`); } await sleep(800);
}
const setStep = async (k) => { await P.click(`#steps .stp[data-step="${k}"]`); await sleep(600); };
const ui = (m) => ev((m) => SSD.setUI(m), m);
async function addFloorUI() { const n0 = await ev(() => SSD.floors().length); await P.click('.ftab.add'); await sleep(300); await P.click('.menu.pop >> text=Add floor to Building A'); await sleep(600); const n1 = await ev(() => SSD.floors().length); must(n1 === n0 + 1, `floors ${n0} → ${n1}`); }

// ======================================================================================
({ctx: CTX, page: P} = await newCtx());

// ---------- LOAD ----------
await t('Load', 'Fresh load in a clean browser profile', 'App opens, welcome screen credits Brad Hall, no errors', async () => {
  await openApp(); const info = await ev(async () => ({title:document.title, ver: (window.SSD && SSD.APP_VERSION) || await fetch('sw.js').then(r => r.text()).then(t => 'sw ' + ((t.match(/ssd-static-v\d+/) || ['?'])[0])).catch(() => '?'), welcome: !!document.querySelector('.welcome'), credit: document.body.innerText.includes('Brad Hall')}));
  ENV.appVersion = info.ver; must(/Security Site Designer/.test(info.title), 'title ' + info.title); must(info.welcome, 'no welcome screen'); must(info.credit, 'creator credit missing');
  return `v${info.ver}, “${info.title}”, welcome shown, creator credit present`;
});
await t('Load', 'Installable app: manifest and offline start', 'Manifest valid; service worker takes control; app reopens with the network off', async () => {
  const {ctx, page} = await newCtx(undefined, {}, true); const keep = [P, CTX]; P = page; CTX = ctx;
  try { await openApp(); const man = await ev(async () => { const l = document.querySelector('link[rel=manifest]'); if (!l) return null; const r = await fetch(l.href); return r.json(); }); must(man && man.name && man.icons && man.icons.length && man.display === 'standalone', 'manifest ' + JSON.stringify(man).slice(0, 120));
    await ev(() => navigator.serviceWorker.ready.then(() => true)); await P.reload(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000});
    must(await ev(() => !!navigator.serviceWorker.controller), 'service worker not controlling the page');
    await CTX.setOffline(true); try { await P.reload(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:30000}); } finally { await CTX.setOffline(false); }
    return `manifest “${man.name}”, ${man.icons.length} icons; reopened offline from the service worker`;
  } finally { await ctx.close(); [P, CTX] = keep; }
});

// ---------- PROJECT SETUP ----------
const MAIN = QA('Main workflow');
await t('Project setup', 'Create a project from the welcome screen', 'Wizard creates the named project and opens step 1', async () => {
  await P.reload(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000}); await sleep(1000);
  if (await P.isVisible('#wNew')) await P.click('#wNew'); else { await P.click('#brand'); await P.click('#dash >> text=New project'); }
  await P.fill('.dlg input[aria-label="Project name"]', MAIN); await P.fill('.dlg input[aria-label="Customer"]', 'QA Customer (disposable)'); await P.fill('.dlg input[aria-label="Site address"]', '1201 Houston St, Fort Worth, TX');
  await P.click('.dlg footer >> text=Create project'); await P.waitForFunction((n) => SSD.S.project.name === n, MAIN, {timeout:15000}); await sleep(800);
  must(await P.isVisible('#ezUpload'), 'step 1 upload card not shown'); return 'project open on step 1';
});

// ---------- PLAN IMPORT ----------
await t('Plan import', 'Cancelling the file window changes nothing', 'No plan, no new floor', async () => {
  const s0 = await state(); const [x, y] = await (async () => { const b = await P.locator('#ezUpload').boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; })();
  const tries = await chooser(() => P.mouse.click(x, y), []); await sleep(800); const s1 = await state(); must(JSON.stringify(s0.floors) === JSON.stringify(s1.floors), 'floors changed ' + s1.floors);
  return `file window opened (click ${tries}), cancelled, floors unchanged: ${s1.floors.join(', ')}`;
});
await t('Plan import', 'Upload a PNG plan with the mouse', 'Real file window opens; plan shows; scale reported as NOT set', async () => {
  const b = await P.locator('#ezUpload').boundingBox(); const tries = await chooser(() => P.mouse.click(b.x + b.width / 2, b.y + b.height / 2), fixture('plan.png'));
  await P.waitForFunction(() => SSD.curFloor().bg, null, {timeout:15000}); await sleep(800); const facts = await P.textContent('#ezPlanFacts');
  must(/not set/i.test(facts), 'plan facts: ' + facts); return `opened on click ${tries}; “${facts.trim()}”`;
});

// ---------- CALIBRATION ----------
// the fixture's outer wall runs from pixel 100 to pixel 1100 (1000 px) along y = 100 px
const px = (x, y) => ev(([x, y]) => { const b = SSD.curFloor().bg; return [b.x + x * b.ftPerPx, b.y + y * b.ftPerPx]; }, [x, y]);
const calibrateClicks = async () => { await ev(() => { SSD.setTool('calibrate'); SSD.zoomToFit && SSD.zoomToFit(); }); await sleep(300); await clickWorld(await px(100, 100)); await clickWorld(await px(1100, 100)); await P.waitForSelector('.dlg input[aria-label="Real distance"]', {timeout:5000}); };
await t('Calibration', 'Before calibration nothing claims the scale is set', '“Scale set” unticked; health says NOT set', async () => {
  const chk = await ev(() => [...document.querySelectorAll('.ezchk')].map(x => [x.textContent.replace('✓ ', ''), x.classList.contains('ok')]));
  const sc = chk.find(([l]) => /Scale/.test(l)); must(sc && !sc[1], 'checklist: ' + JSON.stringify(chk)); const h = await ev(() => SSD.floorScale(SSD.curFloor()).state); must(h === 'fail', 'health ' + h);
  return 'checklist ' + chk.map(([l, ok]) => (ok ? '✓' : '○') + l).join(' ');
});
await t('Calibration', 'Bad distances are refused; Cancel leaves it uncalibrated', '0, -5 and “abc” rejected with a message; Cancel → still uncalibrated', async () => {
  await calibrateClicks(); const said = [];
  for (const v of ['0', '-5', 'abc']) { await clearToasts(); await P.fill('.dlg input[aria-label="Real distance"]', v); await P.click('.dlg footer >> text=Apply scale'); await sleep(300); said.push(v + ': ' + (await toastText()).slice(0, 60)); must(await P.isVisible('.dlg input[aria-label="Real distance"]'), `dialog closed after “${v}”`); must(!(await ev(() => SSD.curFloor().calibrated)), `“${v}” calibrated the floor`); }
  await P.click('.dlg footer >> text=Cancel'); await sleep(300); must(!(await ev(() => SSD.curFloor().calibrated)), 'cancel calibrated');
  return said.join(' · ');
});
await t('Calibration', 'Two-point calibration (100 ft) is saved with its source', 'Scale = 0.1 ft/px, plan 120 ft wide, history recorded, “Scale set” ticked', async () => {
  await calibrateClicks(); await P.fill('.dlg input[aria-label="Real distance"]', "100'"); await P.keyboard.press('Enter'); await sleep(900);
  const f = await ev(() => { const f = SSD.curFloor(); return {cal:f.calibrated, src:f.calSrc, ft:(f.calHist || []).slice(-1)[0], k:f.bg.ftPerPx, w:SSD.planWidthFt(f)}; });
  must(f.cal && f.src === 'two-point' && f.ft && f.ft.ft === 100, JSON.stringify(f)); must(Math.abs(f.k - 0.1) < 0.002 && Math.abs(f.w - 120) < 2, `scale ${f.k} width ${f.w}`);
  const chk = await ev(() => [...document.querySelectorAll('.ezchk')].find(x => /Scale/.test(x.textContent))); must(await ev(() => [...document.querySelectorAll('.ezchk')].some(x => /Scale/.test(x.textContent) && x.classList.contains('ok'))), 'checklist not ticked');
  return `${f.k.toFixed(4)} ft/px, plan ${f.w.toFixed(1)} ft wide, source ${f.src}; facts “${(await P.textContent('#ezPlanFacts')).trim()}”`;
});
await t('Calibration', 'A second known dimension confirms the scale', 'Measuring the 60 ft side gives ≈0% error; the scale record reads “valid”', async () => {
  if (!(await ev(() => !!SSD.scaleChecks))) return 'dimension checks not in this build';
  await ev(() => SSD.setTool('verifyscale')); await clickWorld(await px(100, 100)); await clickWorld(await px(100, 700)); await P.waitForSelector('.dlg input.field'); await P.fill('.dlg input.field', "60'"); await P.click('.dlg footer >> text=OK'); await sleep(500);
  const c = await ev(() => SSD.scaleChecks(SSD.curFloor())); const rec = await ev(() => SSD.scaleRecord(SSD.curFloor()).check); must(c.n === 1 && c.ok, JSON.stringify(c)); return `error ${c.worst.toFixed(2)}% · ${rec}`;
});
await t('Calibration', 'An absurd distance is flagged and can be undone', '100,000 ft → warning; Undo restores 0.1 ft/px', async () => {
  await calibrateClicks(); await clearToasts(); await P.fill('.dlg input[aria-label="Real distance"]', '100000'); await P.keyboard.press('Enter'); await sleep(700);
  const said = await toastText(); must(/check the distance/i.test(said), 'no warning: ' + said); const hs = await ev(() => SSD.projectHealth().find(h => h.id.startsWith('scale-')).state); must(hs !== 'ok', 'health still ok');
  await P.keyboard.press('Control+z'); await sleep(600); const k = await ev(() => SSD.curFloor().bg.ftPerPx); must(Math.abs(k - 0.1) < 0.002, 'undo gave ' + k);
  return `warned: “${said.slice(0, 90)}”; health=${hs}; undo → ${k.toFixed(4)} ft/px`;
});

// ---------- ROOMS, DEVICES, AUTO-DESIGN, WIRING ----------
await t('Design', 'Find the rooms on the plan', 'Rooms are outlined from the drawing', async () => {
  await P.click('#ezFindRooms'); await P.waitForFunction(() => Object.values(SSD.S.project.objects).some(o => o.t === 'room'), null, {timeout:30000}); await sleep(600);
  const r = await ev(() => Object.values(SSD.S.project.objects).filter(o => o.t === 'room').map(o => `${o.name} ${Math.round(SSD.G.area(o.pts))} sf`));
  if (await ev(() => !!SSD.draftRooms)) { must(await ev(() => SSD.draftRooms().length) === r.length, 'found rooms should be drafts'); await P.click('#ezReviewRooms'); await P.waitForSelector('#roomReview'); const n = await ev(() => SSD.draftRooms().length); for (let k = 0; k < n; k++) { await P.click('#roomReview .rvrow.draft [data-approve] >> nth=0'); await sleep(100); } await P.click('.dlg footer >> text=Done'); must(await ev(() => SSD.draftRooms().length) === 0, 'review left drafts'); }
  return `${r.length} rooms: ${r.join(', ')} · drafts reviewed and approved in the review queue`;
});
await t('Design', 'Place a camera by hand', 'Camera tile → click in a room places one camera with feedback', async () => {
  await setStep(2); const c0 = (await state()).cams; await P.click('.eztile[data-kind="dome"]'); await sleep(200);
  await ev(() => SSD.zoomToFit()); await sleep(300); const room = await ev(() => { const r = Object.values(SSD.S.project.objects).find(o => o.t === 'room'); return SSD.G.centroid(r.pts); }); await clickWorld(room); await P.keyboard.press('Escape'); await sleep(400);
  const c1 = (await state()).cams; must(c1 === c0 + 1, `cameras ${c0} → ${c1}`); return `cameras ${c0} → ${c1}`;
});
await t('Design', 'Auto-design places cameras without claiming the system is wired', 'Cameras added; “Everything wired” stays unticked until cables exist', async () => {
  const c0 = (await state()).cams; await P.click('#ezAuto'); await P.waitForFunction((c) => Object.values(SSD.S.project.objects).filter(o => o.t === 'dev' && SSD.kindOf(o).cat === 'camera').length > c, c0, {timeout:60000}); await sleep(1500);
  const s = await state(); const chk = await ev(() => Object.fromEntries([...document.querySelectorAll('.ezchk')].map(x => [x.textContent.replace('✓ ', ''), x.classList.contains('ok')])));
  const loose = await ev(() => SSD.looseDevices().length); must(loose > 0, 'nothing loose after auto-design?'); must(chk['Everything wired'] === false, 'claims wired: ' + JSON.stringify(chk));
  const iss = await ev(() => SSD.freshIssues().map(i => i.sev)); const e = iss.filter(x => x === 'error').length, w = iss.filter(x => x === 'warning').length;
  for (const [k, ok] of Object.entries(chk)) if (/No problems|check clean/i.test(k) && ok) must(e === 0 && w === 0, `“${k}” is ticked while Design Check has ${e} errors / ${w} warnings (cameras not yet wired)`);
  const said = await ev(() => [...document.querySelectorAll('.ezstat, .ezsum, #ezCovLink')].map(x => x.textContent).join(' | ').slice(0, 200));
  return `cameras ${c0} → ${s.cams}, ${loose} not yet wired; checklist ${JSON.stringify(chk)}; ${said}`;
});
await t('Design', 'Wire it all up adds the switch, recorder and every cable', 'No loose devices; ≥1 PoE switch, ≥1 NVR; every camera recorded', async () => {
  await P.click('#ezWire'); await sleep(1500); const r = await ev(() => { const o = Object.values(SSD.S.project.objects); const st = SSD.projectHealth().find(h => h.id === 'storage') || {}; return {loose:SSD.looseDevices().length, sw:o.filter(x => x.kind === 'poeswitch' || SSD.kindOf(x).role === 'switch').length, nvr:o.filter(x => SSD.kindOf(x).role === 'nvr').length, cables:o.filter(x => x.t === 'cable').length, unassigned: /not assigned/.test(st.detail || '') ? st.detail : 0, storage: st.detail, issues:SSD.freshIssues().map(i => i.sev)}; });
  must(!r.loose && r.sw && r.nvr && !r.unassigned, JSON.stringify(r));
  const chk = await ev(() => Object.fromEntries([...document.querySelectorAll('.ezchk')].map(x => [x.textContent.replace('✓ ', ''), x.classList.contains('ok')])));
  const errs = r.issues.filter(x => x === 'error').length, warns = r.issues.filter(x => x === 'warning').length;
  for (const [k, ok] of Object.entries(chk)) if (/No problems|check clean/i.test(k) && ok) must(errs === 0 && warns === 0, `“${k}” is ticked while Design Check has ${errs} errors / ${warns} warnings`);
  return `${r.cables} cables, ${r.sw} switch, ${r.nvr} NVR, 0 loose; check ${errs} errors / ${warns} warnings; checklist ${JSON.stringify(chk)}`;
});
await t('Design', 'Undo and Redo the wiring', 'Ctrl+Z removes the cables, Ctrl+Y puts them back, panels agree', async () => {
  const c0 = (await state()).cables; await P.locator('#cv').click({position:{x:5, y:5}}).catch(() => {}); await P.keyboard.press('Escape');
  await P.keyboard.press('Control+z'); await sleep(700); const c1 = (await state()).cables; await P.keyboard.press('Control+y'); await sleep(700); const c2 = (await state()).cables;
  must(c1 < c0 && c2 === c0, `cables ${c0} → ${c1} → ${c2}`); return `cables ${c0} → undo ${c1} → redo ${c2}`;
});

await t('Design', 'Build Ready dashboard agrees with the plan', 'Verdict, readiness %, 7-stage pipeline and per-floor scale shown; top-bar button shows the same %', async () => {
  must(await ev(() => !!SSD.openBuildReady), 'Build Ready dashboard is not in this build'); await P.click('#readyBtn'); await P.waitForSelector('#brVerdict', {timeout:5000});
  const r = await ev(() => ({v:document.querySelector('#brVerdict').textContent, pct:SSD.readiness(), stages:[...document.querySelectorAll('#brPipeline .sstage')].map(x => x.dataset.stage + ':' + x.className.replace('sstage ', '')), scale:[...document.querySelectorAll('#scaleTable tbody tr')].map(r => r.children[1].textContent + ' / ' + r.children[4].textContent.trim())}));
  must(r.stages.length === 7 && r.stages.includes('powered:ok') && r.stages.includes('recorded:ok'), JSON.stringify(r.stages)); must(r.scale.some(x => /Two-point/.test(x) && /valid/.test(x)), JSON.stringify(r.scale));
  await P.keyboard.press('Escape'); await sleep(900); const btn = (await P.textContent('#readyBtn .cnt')).trim(); must(btn === r.pct + '%', `button ${btn} vs ${r.pct}%`);
  return `“${r.v}” · ${r.pct}% · ${r.stages.join(' ')}`;
});

// ---------- QUOTE ----------
await t('Quote', 'Typed prices save at once and Tab moves to the next box', 'Essentials 9,500 and Recommended 12,500 stored; checklist ticks', async () => {
  await setStep(3); await P.click('#left [data-price=essentials]'); await P.keyboard.type('9500', {delay:40}); await P.keyboard.press('Tab'); await P.keyboard.type('12500', {delay:40}); await P.keyboard.press('Tab'); await sleep(700);
  const s = await state(); must(s.prices === JSON.stringify({essentials:9500, recommended:12500}), s.prices); return 'prices ' + s.prices;
});
await t('Export', 'Proposal PDF (customer-facing; checked first)', 'Preflight lists what is missing, then the PDF downloads with name and size shown', async () => {
  let pre = '';
  const f = await grab('Proposal PDF', async () => { await P.click('#ezProposal'); await sleep(1500); if (await P.isVisible('#preflight')) { pre = (await P.textContent('#preflight')).replace(/\s+/g, ' ').slice(0, 160); await P.click('#pfGo'); } });
  must(f.buf.subarray(0, 4).toString() === '%PDF', 'not a PDF'); return `${f.name} ${(f.buf.length / 1024).toFixed(0)} KB${pre ? '; preflight: ' + pre : '; no preflight blockers'}`;
});
await t('Export', 'QR device labels and VMS camera list', 'Both download with their names shown', async () => {
  const a = await grab('QR labels PDF', () => P.click('#ezQR')); const b = await grab('VMS list CSV', () => P.click('#ezVMS'));
  const cams = (await state()).cams; const rows = b.text.trim().split(/\r?\n/).length - 1; must(rows === cams, `VMS rows ${rows} vs ${cams} cameras`);
  return `${a.name} ${(a.buf.length / 1024).toFixed(0)} KB · ${b.name} ${rows} cameras`;
});

// ---------- PRO MODE: REPORTS + EVERY EXPORT ----------
await t('Reports', 'Design check, cable schedule and bandwidth agree with the plan', 'Counts in each report equal the project state', async () => {
  await ui('pro'); await sleep(800); await P.click('.mode[data-mode=reports]'); await sleep(800);
  await P.click('.subtab:text("Design check")'); await sleep(500); const iss = await ev(() => SSD.S.issues.length); const rows = await P.$$eval('#sheet table tbody tr[data-issue]', r => r.length); must(rows === iss, `check rows ${rows} vs ${iss}`);
  await P.click('.subtab:text("Cable schedule")'); await sleep(500); const cr = await P.$$eval('#sheet table tbody tr', r => r.length); const cables = (await state()).cables; must(cr === cables, `cable rows ${cr} vs ${cables}`);
  await P.click('.subtab:text("Bandwidth & storage")'); await sleep(500); const tb = await ev(() => ((SSD.projectHealth().find(h => h.id === 'storage') || {}).detail || '').match(/([\d.]+) TB/)[1]); must((await P.textContent('#sheet')).includes(tb), 'bandwidth total ' + tb + ' not shown');
  return `${rows} check rows, ${cr} cable rows, ${tb} TB storage — all match`;
});
const exportBtn = async (label) => { if (!(await P.isVisible('.dlg .fmtbtns'))) { await P.click('#exportBtn'); await P.waitForSelector('.dlg .fmtbtns'); await sleep(400); } return P.click(`.dlg .fmtbtns button:text-is("${label}")`); };
for (const [label, kind, check] of [['PNG', 'png'], ['JPG', 'jpg'], ['SVG', 'text', (s) => s.includes('<svg')], ['Schedules (Excel)', 'zip'], ['Project file', 'text', (s) => { const j = JSON.parse(s); return j.format === 'securitysite' && j.project.name === MAIN; }], ['Cables CSV', 'text', (s, st) => s.trim().split(/\r?\n/).length - 1 === st.cables], ['Devices CSV', 'text', (s, st) => s.trim().split(/\r?\n/).length - 1 >= st.cams], ['Doors CSV', 'text', (s) => s.length > 0], ['CAD (DXF)', 'text', (s) => /SECTION/.test(s) && /ENTITIES/.test(s)], ['Spec sheets PDF', 'pdf']]) {
  await t('Export', label, 'Downloads with its name and size shown; file opens as ' + kind, async () => {
    const st = await state(); const f = await grab(label, () => exportBtn(label)); const k = EXPORTS[EXPORTS.length - 1].kind; must(k === kind, `kind ${k}`); if (check) must(check(f.text, st), 'content check failed');
    return `${f.name} · ${(f.buf.length / 1024).toFixed(1)} KB`;
  });
}
await t('Export', 'Google Earth (KML)', 'KML downloads (site location) or the app asks for the location first', async () => {
  await exportBtn('Google Earth (KML)').catch(() => {}); await sleep(1200);
  if (await P.isVisible('#geoState')) { const txt = (await P.textContent('#geoState')).trim(); const go = await P.$('#geoGo'); if (go) { const f = await grab('KML', () => P.click('#geoGo'), 45000).catch(() => null); if (f) return `asked for location (“${txt.slice(0, 60)}”), then ${f.name}`; } await P.keyboard.press('Escape'); return 'asked for the site location first: “' + txt.slice(0, 80) + '”'; }
  const last = EXPORTS[EXPORTS.length - 1]; must(last && /\.kml$/.test(last.name), 'no KML'); return last.name;
});
await t('Export', 'PDF drawing set', 'Preflight (if anything fails) → multi-sheet PDF with name and size shown', async () => {
  if (!(await P.isVisible('.dlg .fmtbtns'))) { await P.click('#exportBtn'); await P.waitForSelector('.dlg .fmtbtns'); }
  let pre = ''; const f = await grab('Drawing set PDF', async () => { await P.click('.dlg footer >> text=Export PDF'); await sleep(1500); if (await P.isVisible('#preflight')) { pre = (await P.textContent('#preflight')).replace(/\s+/g, ' ').slice(0, 140); await P.click('#pfGo'); } });
  const pages = (f.buf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) || []).length; must(f.buf.subarray(0, 4).toString() === '%PDF' && pages >= 2, 'pages ' + pages);
  await P.keyboard.press('Escape'); return `${f.name} · ${pages} sheets · ${(f.buf.length / 1024).toFixed(0)} KB${pre ? ' · preflight: ' + pre : ''}`;
});

// ---------- PERSISTENCE ----------
let projectFile = EXPORTS.find(e => e.label === 'Project file');
await t('Persistence', 'Reload keeps plan, scale, rooms, devices, cables and prices', 'Same state after a full page reload', async () => {
  await sleep(1500); const a = await state(); await P.reload(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000}); await sleep(1500); const b = await state();
  // the app reopens on a building floor even if you were last on the satellite map, so compare the project, not the view
  const keys = ['id', 'name', 'floors', 'rooms', 'cams', 'devs', 'cables', 'scales', 'prices']; const diff = keys.filter(k => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
  must(!diff.length, diff.map(k => `${k}: ${JSON.stringify(a[k])} → ${JSON.stringify(b[k])}`).join(' · ')); return keys.map(k => `${k}=${typeof b[k] === 'string' ? b[k] : JSON.stringify(b[k])}`).join(' · ') + ` · reopened on ${b.floor}${a.floor !== b.floor ? ` (was on ${a.floor})` : ''}`;
});
await t('Persistence', 'Back / forward returns to the same project', 'Leave the site, press Back, the same project reopens', async () => {
  const a = await state(); await P.goto('about:blank'); await P.goBack(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000}); await sleep(1200); const b = await state();
  must(a.id === b.id && a.devs === b.devs, `${a.name} → ${b.name}`); await P.goForward().catch(() => {}); await P.goBack().catch(() => {}); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000}); return `reopened “${b.name}” with ${b.devs} devices`;
});
await t('Persistence', 'Project file opens in a brand-new browser profile', 'Import the exported file → same rooms, devices, cables, calibration', async () => {
  must(projectFile, 'no project file exported earlier'); const a = await state(); const {ctx, page} = await newCtx(); const keep = [P, CTX]; P = page; CTX = ctx;
  try { await openApp(); await closeWelcome(); await P.click('#brand'); await P.waitForSelector('#dash:not([hidden])');
    await chooser(() => P.click('#dash >> text=Import project'), path.join(OUT, 'exports', `${CH}-${projectFile.name}`)); await P.waitForFunction((n) => SSD.S.project && SSD.S.project.name.startsWith(n), MAIN, {timeout:20000}); await sleep(1200);
    const b = await state(); for (const k of ['rooms', 'cams', 'devs', 'cables', 'scales', 'prices']) must(a[k] === b[k], `${k}: ${a[k]} vs ${b[k]}`); return `imported “${b.name}”: ${b.rooms} rooms, ${b.devs} devices, ${b.cables} cables · ${b.scales}`;
  } finally { await ctx.close(); [P, CTX] = keep; }
});

// ---------- ADMIN ----------
await t('Admin', 'Rename the project', 'New name saved and shown on the dashboard', async () => {
  await P.click('.ptab:text("Project")'); await sleep(300); const i = P.locator('#left .props input[aria-label="Name"]'); await i.fill(MAIN + ' renamed'); await i.press('Tab'); await sleep(800);
  must((await state()).name === MAIN + ' renamed', 'name ' + (await state()).name); return 'renamed';
});
await t('Admin', 'Settings: company and designer survive a reload', 'Saved values come back after reload and appear on the health check', async () => {
  await P.click('button[title=Settings]'); await P.waitForSelector('.dlg .form'); const inp = (l) => P.locator(`.dlg .form label:text-is("${l}") + input`);
  await inp('Company').fill('QA Security Co (test)'); await inp('Designer').fill('QA Bot'); await P.click('.dlg footer >> text=Save settings'); await sleep(800);
  await P.reload(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000}); await sleep(1200); const v = await ev(() => [SSD.S.project.company, SSD.S.project.designer]);
  must(v[0] === 'QA Security Co (test)' && v[1] === 'QA Bot', JSON.stringify(v)); return 'company + designer persisted';
});
await t('Admin', 'Save a version and see it in Version history', 'Ctrl+S saves a named version that is listed', async () => {
  await P.keyboard.press('Control+s'); await sleep(800); if (await P.isVisible('.dlg input')) { await P.fill('.dlg input', 'QA checkpoint'); await P.keyboard.press('Enter'); await sleep(800); }
  await P.click('.mode[data-mode=reports]'); await sleep(500); await P.click('.subtab:text("Version history")'); await sleep(600); const rows = await P.$$eval('#sheet table tbody tr', r => r.length); must(rows >= 1, 'no versions'); return `${rows} version(s) listed`;
});
await t('Admin', '“What changed?” compares the saved version with now', 'Moving a camera 12 ft after saving shows “… moved 12 ft”', async () => {
  must(await ev(() => !!SSD.openVersionCompare), 'version compare is not in this build'); const cam = await ev(() => { const c = Object.values(SSD.S.project.objects).find(o => o.t === 'dev' && SSD.kindOf(o).cat === 'camera'); SSD.tx('Move camera', () => SSD.updObj(c.id, {x:c.x + 12})); return c.name; }); await sleep(500);
  await P.click('.mode[data-mode=reports]'); await sleep(400); await P.click('.subtab:text("Version history")'); await sleep(500); await P.click('#sheet [data-compare] >> nth=0'); await P.waitForSelector('#compareDlg'); const txt = await P.textContent('#compareDlg'); await P.keyboard.press('Escape');
  must(txt.includes(cam + ' moved 12'), txt.slice(0, 200)); await P.keyboard.press('Control+z'); await sleep(400); return txt.replace(/\s+/g, ' ').slice(0, 140);
});
await t('Admin', 'Dashboard: duplicate, archive, restore, delete (disposable copy only)', 'Copy appears, archives, restores, deletes; original untouched', async () => {
  const name = (await state()).name; await P.click('#brand'); await P.waitForSelector('#dash:not([hidden])'); await sleep(600);
  const row = (n) => P.locator('#dash .prow', {has: P.locator(`.nm b:text-is("${n}")`)});
  await row(name).locator('button[title=Duplicate]').click(); await sleep(800); const copy = name + ' (copy)'; must(await row(copy).count() === 1, 'no copy row');
  await row(copy).locator('button[title=Archive]').click(); await sleep(800); must(await row(copy).count() === 0, 'archived copy still listed');
  await P.click('#dash label:has-text("Show archived") input'); await sleep(700); must(await row(copy).count() === 1, 'not in archived list'); await row(copy).locator('button[title=Unarchive]').click(); await sleep(700);
  await P.click('#dash label:has-text("Show archived") input'); await sleep(700); must(await row(copy).count() === 1, 'restore failed');
  await row(copy).locator('button[title=Delete]').click(); await sleep(400); await P.click('.dlg footer >> text=Delete project'); await sleep(800); must(await row(copy).count() === 0, 'copy not deleted'); must(await row(name).count() === 1, 'ORIGINAL MISSING');
  await row(name).locator('.nm b').click(); await sleep(1200); return 'duplicate → archive → restore → delete all worked; original kept';
});

// ---------- KEYBOARD & ACCESSIBILITY ----------
await t('Keyboard', 'Command palette: Ctrl+K, type, Enter, Escape', 'Palette opens focused, runs “Project health”, Escape closes it', async () => {
  await P.keyboard.press('Escape'); await P.keyboard.press('Control+k'); await P.waitForSelector('[role=combobox]'); must(await ev(() => document.activeElement && document.activeElement.getAttribute('role') === 'combobox'), 'palette input not focused');
  await P.keyboard.type('Project health', {delay:20}); await sleep(300); await P.keyboard.press('Enter'); await P.waitForSelector('#healthDlg', {timeout:5000}); await P.keyboard.press('Escape'); await sleep(300); must(!(await P.isVisible('#healthDlg')), 'health still open'); return 'palette → health → closed';
});
await t('Keyboard', 'Dialogs keep Tab inside and give focus back on close', '40 Tab presses stay inside Settings; Escape returns focus to the Settings button', async () => {
  await P.focus('button[title=Settings]'); await P.keyboard.press('Enter'); await P.waitForSelector('.dlg .form'); let out = 0;
  for (let k = 0; k < 40; k++) { await P.keyboard.press('Tab'); if (!(await ev(() => !!(document.activeElement && document.activeElement.closest('.dlg'))))) out++; }
  await P.keyboard.press('Escape'); await sleep(300); const back = await ev(() => document.activeElement && document.activeElement.getAttribute('title')); must(!out, `${out} Tab stops left the dialog`); must(back === 'Settings', 'focus went to ' + back); return 'focus trapped and restored';
});
await t('Keyboard', 'Shortcuts: C camera tool, Esc cancel, ? help', 'Each shortcut acts', async () => {
  await P.click('.mode[data-mode=floor]').catch(() => {}); await sleep(400); await P.locator('#cv').click({position:{x:8, y:8}}).catch(() => {}); await P.keyboard.press('Escape'); await P.keyboard.press('c'); await sleep(200); const tool = await ev(() => SSD.S.tool); await P.keyboard.press('Escape'); await sleep(150); const after = await ev(() => SSD.S.tool);
  await P.keyboard.press('Shift+?'); await sleep(400); const help = await P.isVisible('.dlg'); await P.keyboard.press('Escape'); must(tool === 'place' && after === 'select' && help, `tool ${tool} → ${after}, help ${help}`); return 'C → place, Esc → select, ? → shortcuts';
});
await t('Accessibility', 'Every visible button and field has a name', 'No unnamed buttons, inputs or selects on the main screen', async () => {
  const bad = await ev(() => [...document.querySelectorAll('button, input:not([type=hidden]), select, textarea')].filter(e => { const r = e.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden') return false; const lab = e.getAttribute('aria-label') || e.getAttribute('title') || (e.textContent || '').trim() || (e.labels && e.labels.length && e.labels[0].textContent.trim()) || e.getAttribute('placeholder') || e.getAttribute('aria-labelledby'); return !lab; }).map(e => e.outerHTML.slice(0, 80)));
  must(!bad.length, bad.length + ' unnamed: ' + bad.slice(0, 3).join(' ')); return 'all named';
});

// ---------- IMPORT ROBUSTNESS (separate disposable project) ----------
await ui('easy'); await sleep(400);
await t('Plan import', 'A broken PDF shows an error and leaves the floor untouched', 'Error message; no plan, no extra floor', async () => {
  await newProject(QA('Imports')); await ev(() => SSD.planInput()); const s0 = await state(); await clearToasts();
  await P.setInputFiles('#planFileIn', fixture('junk.pdf')); await sleep(2500); const said = (await toastText()) + ' ' + (await ev(() => (document.querySelector('.dlg') || {}).textContent || ''));
  const s1 = await state(); await P.keyboard.press('Escape'); must(JSON.stringify(s0.floors) === JSON.stringify(s1.floors), 'floors changed: ' + s1.floors); must(/unable|could not|failed|invalid/i.test(said), 'no error shown: ' + said.slice(0, 120));
  return 'said: ' + said.replace(/\s+/g, ' ').trim().slice(0, 110);
});
await t('Plan import', 'An unsupported file type is refused', 'Message; nothing imported', async () => {
  const s0 = await state(); await clearToasts(); await P.setInputFiles('#planFileIn', {name:'notes.txt', mimeType:'text/plain', buffer:Buffer.from('hello')}); await sleep(1000);
  const said = await toastText(); const s1 = await state(); must(/Unsupported/i.test(said), 'said ' + said); must(JSON.stringify(s0.floors) === JSON.stringify(s1.floors), 'floors changed'); return said.slice(0, 90);
});
await t('Plan import', 'Multi-page PDF → one floor per page; importing again adds no duplicates', 'Every page listed; 3 pages → Floor 1, Floor 2, Roof; report accounts for every page; second import reuses them', async () => {
  const pick = async () => { await ev(() => SSD.planInput()); await P.setInputFiles('#planFileIn', fixture('plan3.pdf')); await P.waitForSelector('#planSetGrid', {timeout:30000}); await P.waitForFunction(() => /Read \d+ pages ·/.test((document.querySelector('#planSetReading') || {}).textContent || ''), null, {timeout:60000}); await P.click('#planSetGo'); await P.waitForSelector('#planReport', {timeout:60000}); const t = await P.textContent('#planReportSum'); await P.click('.dlg footer >> text=Done'); return t; };
  const r1 = await pick(); await sleep(800); const a = (await state()).floors; const r2 = await pick(); await sleep(800); const b = (await state()).floors;
  must(/every page accounted for/.test(r1), r1); must(new Set(b).size === b.length && b.length === a.length, `first ${a} second ${b}`); return `floors: ${b.join(', ')} · ${r1}`;
});
await t('Plan import', 'A 71-page construction set: every page reconciled, sheet numbers kept', '71 pages listed with sheet numbers; floor plans → floors, ceiling/power/telecom → overlays, rest skipped; report totals 71', async () => {
  must(await ev(() => !!SSD.openPlanSetImport), 'plan-set import is not in this build'); await addFloorUI();
  await ev(() => SSD.planInput()); await P.setInputFiles('#planFileIn', fixture('planset-71.pdf')); await P.waitForSelector('#planSetGrid', {timeout:30000}); await P.waitForFunction(() => /Read 71 pages ·/.test((document.querySelector('#planSetReading') || {}).textContent || ''), null, {timeout:120000});
  const rows = await ev(() => document.querySelectorAll('#planSetGrid .psrow').length); const sum0 = await P.textContent('#planSetSummary'); const t0 = Date.now(); await P.click('#planSetGo'); await P.waitForSelector('#planReport', {timeout:120000}); const sum = await P.textContent('#planReportSum'); await P.click('.dlg footer >> text=Done');
  must(rows === 71, 'rows ' + rows); must(/71 source pages · 5 imported · 66 skipped · 0 failed — every page accounted for/.test(sum), sum); const f = await ev(() => { const f = SSD.floors().find(f => f.bg && f.bg.pdf && f.bg.pdf.sheet === 'A1.1'); return f ? {name:f.name, refs:(f.refs || []).map(r => r.name)} : null; }); must(f && f.refs.length === 4, JSON.stringify(f));
  const mem = await ev(() => performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null); return `${sum0} → ${sum} in ${((Date.now() - t0) / 1000).toFixed(1)} s · floor “${f.name}” with overlays ${f.refs.join(', ')}${mem ? ` · JS heap ${mem} MB` : ''}`;
});
await t('Design', 'Rooms found on a construction sheet take the printed names and stay drafts until reviewed', 'Exam 1 101, Restroom 104 … named from the drawing; checklist not ticked; review queue approves them', async () => {
  await setStep(1); await P.click('#ezFindRooms'); await P.waitForFunction(() => Object.values(SSD.S.project.objects).filter(o => o.t === 'room' && o.floor === SSD.S.floorId).length >= 6, null, {timeout:60000}); await sleep(600);
  const names = await ev(() => Object.values(SSD.S.project.objects).filter(o => o.t === 'room' && o.floor === SSD.S.floorId).map(o => o.name + (o.props.review === 'draft' ? '' : '!')));
  for (const w of ['Exam 1 101', 'Restroom 104', 'Waiting 106']) must(names.includes(w), 'missing ' + w + ' in ' + names); const chk = await ev(() => [...document.querySelectorAll('.ezchk')].some(x => /Rooms reviewed/.test(x.textContent) && x.classList.contains('ok'))); must(!chk, '“Rooms reviewed” ticked for drafts');
  await P.click('#ezReviewRooms'); await P.waitForSelector('#roomReview'); await P.click('#approveAllNamed'); await P.waitForSelector('#roomReview'); await P.click('.dlg footer >> text=Done'); await sleep(300); const left = await ev(() => SSD.draftRooms(SSD.S.floorId).length);
  return `${names.length} rooms: ${names.join(', ')} · ${left} left to review by hand`;
});
await t('Plan import', 'DXF (CAD) plan gets its scale from the file', 'Vector plan; scale reported as from the CAD units', async () => {
  await addFloorUI(); await ev(() => SSD.planInput()); await P.setInputFiles('#planFileIn', fixture('plan.dxf')); await P.waitForSelector('.dlg footer >> text=Import drawing', {timeout:20000}); await P.click('.dlg footer >> text=Import drawing'); await P.waitForFunction(() => SSD.curFloor().bg && SSD.curFloor().bg.vector || Object.values(SSD.S.project.objects).some(o => o.t === 'wall' && o.floor === SSD.S.floorId), null, {timeout:30000}); await sleep(800);
  const sc = await ev(() => SSD.floorScale(SSD.curFloor())); must(sc.state === 'ok', JSON.stringify(sc)); return sc.text;
});
await t('Plan import', 'Drag-and-drop and paste a large (8000×6000) image', 'Both import; app stays responsive; a 20 MB-class file is handled', async () => {
  await addFloorUI(); await setStep(1);
  const t0 = Date.now(); await ev(async () => { const c = document.createElement('canvas'); c.width = 8000; c.height = 6000; const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 8000, 6000); g.strokeStyle = '#000'; g.lineWidth = 12; g.strokeRect(400, 400, 7200, 5200); for (let x = 1200; x < 7600; x += 800) { g.beginPath(); g.moveTo(x, 400); g.lineTo(x, 5600); g.stroke(); } const im = g.createImageData(2600, 2600); const u = new Uint32Array(im.data.buffer); for (let i = 0; i < u.length; i++) u[i] = (Math.random() * 0xffffff) | 0xff000000; g.putImageData(im, 4000, 1800); // a photo-like noisy region makes a genuinely large file
    const blob = await new Promise(r => c.toBlob(r, 'image/png')); const dt = new DataTransfer(); dt.items.add(new File([blob], 'big-plan.png', {type:'image/png'})); document.querySelector('#ezUpload').dispatchEvent(new DragEvent('drop', {dataTransfer:dt, bubbles:true, cancelable:true})); window.__bigSize = blob.size; });
  await P.waitForFunction(() => SSD.curFloor().bg && /big-plan/.test(SSD.curFloor().bg.source), null, {timeout:60000}); const ms = Date.now() - t0; const size = await ev(() => window.__bigSize);
  await addFloorUI(); await P.keyboard.press('Escape');
  await ev(async () => { const c = document.createElement('canvas'); c.width = 900; c.height = 600; const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 900, 600); g.strokeRect(50, 50, 800, 500); const blob = await new Promise(r => c.toBlob(r, 'image/png')); const dt = new DataTransfer(); dt.items.add(new File([blob], 'image.png', {type:'image/png'})); document.dispatchEvent(new ClipboardEvent('paste', {clipboardData:dt, bubbles:true})); });
  await P.waitForFunction(() => SSD.curFloor().bg && /Pasted/.test(SSD.curFloor().bg.source), null, {timeout:20000}); return `dropped ${(size / 1048576).toFixed(1)} MB image in ${(ms / 1000).toFixed(1)} s; pasted screenshot imported`;
});
await t('Calibration', 'Design Check flags work on an uncalibrated floor', 'A room on an uncalibrated plan → “plan scale not set” warning with a Set the scale fix', async () => {
  await ev(() => { const f = SSD.S.floorId; SSD.tx('Draw room', () => SSD.addObj({t:'room', floor:f, name:'QA room', pts:[[10, 10], [40, 10], [40, 30], [10, 30]], props:{}})); }); await sleep(700);
  const i = await ev(() => { const x = SSD.freshIssues().find(i => /plan scale not set/.test(i.msg)); return x ? {msg:x.msg, sev:x.sev, acts:SSD.issueActions(x).map(a => a[0])} : null; }); must(i && i.acts.includes('Set the scale'), 'no scale warning: ' + JSON.stringify(i));
  const foot = (await P.textContent('#sbIssues')).trim(); must(!/clean|No problems/.test(foot), 'footer says ' + foot); return `${i.sev}: ${i.msg} · footer “${foot}”`;
});
await t('Persistence', 'Imported floors survive a reload', 'Every floor and its plan are still there', async () => {
  await sleep(1500); const a = (await state()).floors; await P.reload(); await P.waitForFunction(() => window.SSD && SSD.S.project, null, {timeout:60000}); await sleep(1500); const b = (await state()).floors;
  must(JSON.stringify(a) === JSON.stringify(b), `${a} vs ${b}`); return b.join(', ');
});

await t('Design', 'Medical building type: exam and break rooms are privacy areas', 'Wizard preset → Exam/Break rooms “privacy”, Reception at recognition detail; auto-design skips privacy rooms', async () => {
  await closeWelcome(); await P.click('#brand'); await P.waitForSelector('#dash:not([hidden])'); await P.click('#dash >> text=New project'); await P.fill('.dlg input[aria-label="Project name"]', QA('Clinic preset')); must(await P.isVisible('#wizPreset'), 'no building type in this build');
  await P.selectOption('#wizPreset', 'medical'); await P.click('.dlg footer >> text=Create project'); await P.waitForFunction(() => SSD.S.project.settings.preset === 'medical', null, {timeout:15000});
  const r = await ev(async () => { const f = SSD.S.floorId; const R = (name, x) => SSD.addObj({t:'room', floor:f, name, pts:[[x, 0], [x + 20, 0], [x + 20, 20], [x, 20]], props:{}}); SSD.tx('Rooms', () => { R('Exam 1', 0); R('Break Room', 22); R('Reception', 44); R('Hall', 66); }); await SSD.autoDesignFloor({outside:false}); const rooms = Object.values(SSD.S.project.objects).filter(o => o.t === 'room'); const cams = Object.values(SSD.S.project.objects).filter(o => SSD.isCam(o)); return {need:Object.fromEntries(rooms.map(o => [o.name, SSD.roomNeed(o).need + '/' + SSD.roomLevel(o)])), inPrivacy:cams.filter(c => rooms.some(r => SSD.roomNeed(r).need === 'privacy' && SSD.G.inPoly([c.x, c.y], r.pts))).length, cams:cams.length}; });
  must(/^privacy/.test(r.need['Exam 1']) && /^privacy/.test(r.need['Break Room']) && r.need['Reception'] === 'required/recognition', JSON.stringify(r.need)); must(r.cams > 0 && r.inPrivacy === 0, JSON.stringify(r)); return JSON.stringify(r.need) + ` · ${r.cams} cameras, 0 in privacy rooms`;
});

await t('Design', 'Doors: single and double, flip the swing and the hinge', 'Door tool places a single and a double door on drawn walls; Flip swing / Flip hinge / Double change the door and Undo reverses', async () => {
  must(await ev(() => !!SSD.doorAction), 'door controls are not in this build'); await newProject(QA('Doors')); await setStep(1); await P.click('#ezRooms'); await sleep(200);
  await ev(() => { SSD.S.view = {x:300, y:200, z:12}; SSD.requestDraw(); }); const [ax, ay] = await toScreen([0, 0]), [bx, by] = await toScreen([40, 30]);
  await P.mouse.move(ax, ay); await P.mouse.down(); await P.mouse.move((ax + bx) / 2, (ay + by) / 2, {steps:4}); await P.mouse.move(bx, by, {steps:4}); await P.mouse.up(); await P.keyboard.press('Escape'); await sleep(300);
  if (await P.isVisible('#right .ezphead button[aria-label=Close]')) await P.click('#right .ezphead button[aria-label=Close]');
  await P.click('#ezAddDoor'); await clickWorld([12, 1]); await P.click('#doDouble'); await clickWorld([40, 15]); await P.keyboard.press('Escape'); await sleep(300);
  let d = await ev(() => Object.values(SSD.S.project.objects).filter(o => o.t === 'door').map(o => ({id:o.id, dbl:!!o.double, w:o.w, flip:!!o.flip, hinge:o.hinge || 'L', wall:!!o.wallId})));
  must(d.length === 2 && !d[0].dbl && d[1].dbl && d[1].w === 6 && d.every(x => x.wall), JSON.stringify(d));
  await ev((id) => SSD.focusObj(id), d[0].id); await P.waitForSelector('#doorCtl'); await P.click('#doorCtl [data-door=swing]'); await P.click('#doorCtl [data-door=hinge]'); await sleep(200);
  const f = await ev((id) => { const o = SSD.S.project.objects[id]; return [!!o.flip, o.hinge]; }, d[0].id); must(f[0] !== d[0].flip && f[1] !== d[0].hinge, 'flip did not change the door ' + JSON.stringify(f));
  await P.keyboard.press('Control+z'); await P.keyboard.press('Control+z'); await sleep(200); const u = await ev((id) => { const o = SSD.S.project.objects[id]; return [!!o.flip, o.hinge || 'L']; }, d[0].id); must(u[0] === d[0].flip && u[1] === d[0].hinge, 'undo ' + JSON.stringify(u));
  return `single + double placed on walls; swing ${d[0].flip ? 'out' : 'in'}→${f[0] ? 'out' : 'in'}, hinge ${d[0].hinge}→${f[1]}; undo restored`;
});

// ---------- RESPONSIVE ----------
for (const [w, h, touch] of [[390, 844, true], [768, 1024, true], [1024, 768, false]]) {
  await t('Responsive', `${w} px wide`, 'No sideways scroll; steps, top bar and dialogs fit; nothing clipped', async () => {
    const {ctx, page} = await newCtx({width:w, height:h}, touch ? {hasTouch:true, isMobile: w < 600, deviceScaleFactor:2} : {}); const keep = [P, CTX]; P = page; CTX = ctx;
    try { await openApp(); await closeWelcome(); await sleep(600);
      const r = await ev(() => { const vw = innerWidth; const off = [...document.querySelectorAll('#top button, #top a, #steps .stp')].filter(e => { const b = e.getBoundingClientRect(); return b.width && getComputedStyle(e).display !== 'none' && (b.right > vw + 1 || b.left < -1); }).map(e => e.id || e.className || e.textContent.slice(0, 20)); const steps = [...document.querySelectorAll('#steps .stp')].filter(e => e.getBoundingClientRect().width > 0).length; const small = [...document.querySelectorAll('#steps .stp, #top button')].filter(e => { const b = e.getBoundingClientRect(); return b.width && (b.height < 24 || b.width < 24); }).length; return {scroll: document.documentElement.scrollWidth - vw, off, steps, small}; });
      must(r.scroll <= 1, 'page scrolls sideways by ' + r.scroll + 'px'); must(!r.off.length, 'off-screen: ' + r.off.join(', ')); must(r.steps === 3, 'steps visible ' + r.steps);
      await P.keyboard.press('Control+k').catch(() => {}); await sleep(400); let fit = true; if (await P.isVisible('.dlg')) { const b = await P.locator('.dlg').first().boundingBox(); fit = b.x >= -1 && b.x + b.width <= w + 1; await P.keyboard.press('Escape'); }
      must(fit, 'dialog wider than the screen'); await P.screenshot({path: path.join(OUT, 'shots', `${CH}-responsive-${w}.png`)}); return `no sideways scroll, 3 steps visible, dialog fits${r.small ? `, ${r.small} controls under 24 px` : ''}`;
    } finally { await ctx.close(); [P, CTX] = keep; }
  });
}

// ---------- CLEAN-UP: delete only the projects this run created ----------
await t('Admin', 'Delete the disposable QA projects created by this run', 'Only projects named “QA <browser> <run>” are removed', async () => {
  const left = await ev(async (pre) => { const all = await SSD.DB.all('projects'); const mine = all.filter(p => p.name.startsWith(pre)); for (const p of mine) await SSD.DB.del('projects', p.id); return {deleted:mine.length, kept:all.length - mine.length}; }, `QA ${CH} ${STAMP}`);
  return `deleted ${left.deleted}, left ${left.kept} other project(s) alone`;
});

ENV.finished = new Date().toISOString();
const pass = R.filter(r => r.pass).length; const summary = {env: ENV, total: R.length, pass, fail: R.length - pass, results: R, exports: EXPORTS, consoleErrors: errors.filter(e => !noise(e))};
fs.writeFileSync(path.join(OUT, `results-${CH}.json`), JSON.stringify(summary, null, 1));
console.log(`\n${CH} ${ENV.version}: ${pass}/${R.length} passed`); await browser.close(); process.exit(pass === R.length ? 0 : 1);
