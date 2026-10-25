/* 冒烟测试：不开浏览器，用桩件跑 dist/index.html 的初始化与关键渲染路径。
 *
 *   node smoke_test.mjs            # 测 dist/index.html
 *   node smoke_test.mjs ../dist/index.html
 *
 * 覆盖：
 *   1. 页面初始化不抛错（Leaflet/DOM 全桩件）
 *   2. 城市下拉 = 缓存里全部城市
 *   3. 每个城市 renderThemes 都能出主题卡
 *   4. 每个城市抽 1 个主题跑 renderStoreView 出门店行
 *   5. 抽 3 个主题跑 renderDetail（重点/详细页签）
 *   6. 场次提示按城市如实显示
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, process.argv[2] || '../dist/index.html');
const html = readFileSync(dist, 'utf-8');

/* ---------- 桩件 ---------- */
function makeEl(id = '') {
  const el = {
    id, dataset: {}, style: {}, value: '', src: '', textContent: '',
    children: [], _html: '',
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    setAttribute(){}, appendChild(c){ this.children.push(c); }, focus(){}, blur(){},
    getBoundingClientRect(){ return { width: 800, height: 600, left: 0, top: 0, right: 800, bottom: 600 }; },
    addEventListener(){}, removeEventListener(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    closest(){ return null; }, scrollIntoView(){}, click(){},
  };
  Object.defineProperty(el, 'innerHTML', {
    get(){ return this._html; },
    set(v){ this._html = String(v); },
  });
  return el;
}
const els = new Map();
const E = id => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };

const markerStub = () => ({
  addTo(){ return this; }, bindPopup(){ return this; }, bindTooltip(){ return this; },
  on(){ return this; }, off(){ return this; }, setStyle(){ return this; },
  setLatLng(){ return this; }, openPopup(){ return this; }, closePopup(){ return this; },
  remove(){ return this; }, getElement(){ return null; }, getLatLng(){ return { lat: 0, lng: 0 }; },
  clearLayers(){ return this; }, addLayer(){ return this; }, eachLayer(){ return this; },
});
globalThis.L = {
  map: () => ({
    setView(){ return this; }, on(){ return this; }, off(){ return this; },
    getZoom(){ return 13; }, setZoom(){ return this; },
    project(ll, z){ return { x: ll[1] * 1e5, y: ll[0] * 1e5 }; },
    unproject(pt, z){ return { lat: pt.y / 1e5, lng: pt.x / 1e5 }; },
    removeLayer(){ return this; }, addLayer(){ return this; },
    fitBounds(){ return this; }, flyBounds(){ return this; },
    flyTo(){ return this; }, flyToBounds(){ return this; }, panTo(){ return this; },
    closePopup(){ return this; }, remove(){ return this; },
    attributionControl: { setPrefix(){} },
  }),
  tileLayer: () => markerStub(),
  layerGroup: () => markerStub(),
  circleMarker: markerStub,
  marker: markerStub,
  divIcon: o => o,
  point: (x, y) => ({ x, y }),
  latLngBounds: pts => ({ pad(){ return { isValid(){ return true; } }; }, isValid(){ return true; } }),
  latLng: (a, b) => ({ lat: a, lng: b }),
};

globalThis.document = {
  getElementById: E,
  querySelector: sel => E('q:' + sel),
  querySelectorAll(){ return []; },
  createElement(tag){ return makeEl(tag); },
  addEventListener(){}, removeEventListener(){},
  body: makeEl('body'),
  documentElement: makeEl('html'),
};
globalThis.window = globalThis;
globalThis.location = { hash: '', href: 'file:///dist/index.html' };
globalThis.history = { replaceState(){}, pushState(){} };
Object.defineProperty(globalThis, 'navigator', { value: {
  geolocation: { getCurrentPosition(ok, err){ err({ code: 1, message: 'denied' }); } },
  userAgent: 'node-smoke',
}, configurable: true });
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);

/* ---------- 抽出页面脚本并执行 ---------- */
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (!scripts.length) { console.error('❌ dist 里没有内联 <script>'); process.exit(1); }
const code = scripts[scripts.length - 1];

let failures = 0;
const check = (name, cond, extra = '') => {
  console.log(`${cond ? '✅' : '❌'} ${name}${extra ? '  ' + extra : ''}`);
  if (!cond) failures++;
};

try {
  // const/let 声明不会挂到全局，尾部追加导出句柄供断言使用
  (0, eval)(code + '\n;globalThis.__T = { DATA, META, SLOTS, S, SPU, cityStores, renderThemes, renderStoreView, renderDetail };');
  check('页面初始化', true);
} catch (e) {
  console.error('❌ 页面初始化抛错：', e.stack);
  process.exit(1);
}
const { DATA, META, SLOTS, S, SPU, cityStores, renderThemes, renderStoreView, renderDetail } = globalThis.__T;

/* ---------- 断言 ---------- */
const optCount = (E('citySel').innerHTML.match(/<option/g) || []).length;
check('城市下拉覆盖全部缓存城市', optCount === [...new Set(DATA.map(s => s.city))].length,
      `${optCount} 城`);

const cityCodes = [...new Set(DATA.map(s => s.city))];
let themesOK = 0, storesOK = 0, hintOK = 0;
for (const c of cityCodes) {
  S.city = c; S.spu = 0; S.sel = 0; S.store = null; S.loc = null;
  renderThemes();
  const cards = (E('themes').innerHTML.match(/class="tcard/g) || []).length;
  if (cards > 0) themesOK++; else console.error(`   ${c} 无主题卡`);
  // 场次提示
  const hint = E('slotHint').innerHTML;
  const cityHasSlots = cityStores().some(st => Object.values(SLOTS.dates_by_spu || {})
    .some(m => m[st.code] && m[st.code].length));
  if ((cityHasSlots && hint.includes('已接入')) || (!cityHasSlots && hint.includes('未接入'))) hintOK++;
  // 抽一个主题跑门店列表
  const spu = cityStores()[0].spus[0];
  S.spu = spu; S.sel = spu;
  try { renderStoreView(); if ((E('svList').innerHTML.match(/svrow/g) || []).length > 0) storesOK++; }
  catch (e) { console.error(`   ${c} renderStoreView 抛错：`, e.message); }
  S.spu = 0;
}
check('全部城市 renderThemes 出卡', themesOK === cityCodes.length, `${themesOK}/${cityCodes.length}`);
check('全部城市 renderStoreView 出行', storesOK === cityCodes.length, `${storesOK}/${cityCodes.length}`);
check('场次提示按城市如实显示', hintOK === cityCodes.length, `${hintOK}/${cityCodes.length}`);

// 详情卡：抽 3 个有「重点」的主题（hl 是 {meals/gifts/booking...} 对象）
const hlIds = META.spus.filter(s => s.hl && Object.keys(s.hl).length).slice(0, 3).map(s => s.spu_id);
let detailOK = 0;
for (const id of hlIds) {
  try { renderDetail(id);
    const h = E('dHl').innerHTML;
    if (h.includes('套餐') || h.includes('赠品') || h.includes('预约')) detailOK++;
  } catch (e) { console.error(`   renderDetail(${id}) 抛错：`, e.message); }
}
check('renderDetail 出重点内容', detailOK === hlIds.length, `${detailOK}/${hlIds.length}`);

console.log(failures ? `\n${failures} 项未通过` : '\n全部通过');
process.exit(failures ? 1 : 0);
