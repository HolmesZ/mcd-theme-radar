/* 冒烟测试：不开浏览器，用桩件跑产物的初始化与关键渲染路径。
 * 自动识别模板：页面里有 provSel 就是全国级，否则城市级。
 *
 *   node smoke_test.mjs                    # 测 ../dist/nation.html
 *   node smoke_test.mjs ../dist/city.html  # 测城市级
 *   node smoke_test.mjs ../dist/nation.html
 *
 * 覆盖（城市级）：
 *   1. 页面初始化不抛错（Leaflet/DOM 全桩件）
 *   2. 城市下拉 = 缓存里全部城市
 *   3. 每个城市的 renderThemes 出主题卡
 *   4. 每个城市抽 1 个主题跑 renderStoreView 出门店行
 *   5. 场次提示按城市如实显示
 *   6. 抽 3 个主题跑 renderDetail（重点/详细页签）
 *
 * 覆盖（全国级）：以上 + 省份排行卡、省下拉 = 全国 + 全部省、城市下拉按省过滤
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, process.argv[2] || '../dist/nation.html');
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

const isNation = /id="provSel"/.test(html);
console.log(`模板：${isNation ? '全国级（省 › 市）' : '城市级（单城市）'}\n`);

const suffix = isNation
  ? '\n;globalThis.__T = { DATA, META, SLOTS, S, SPU, PROVS, PROV_OF, CITY_NAME, cityStatsOf, cityStores, renderThemes, renderStoreView, renderDetail, buildProvSelect, buildCitySelect };'
  : '\n;globalThis.__T = { DATA, META, SLOTS, S, SPU, cityStores, renderThemes, renderStoreView, renderDetail };';

try {
  // const/let 声明不会挂到全局，尾部追加导出句柄供断言使用
  (0, eval)(code + suffix);
  check('页面初始化', true);
} catch (e) {
  console.error('❌ 页面初始化抛错：', e.stack);
  process.exit(1);
}
const T = globalThis.__T;
const { DATA, META, SLOTS, S, SPU, cityStores, renderThemes, renderStoreView, renderDetail, cityStatsOf } = T;

/* ---------- 断言 ---------- */
const cityCodes = [...new Set(DATA.map(s => s.city))];
const slotsHintOK = (hint) => {
  const cityHasSlots = cityStores().some(st => Object.values(SLOTS.dates_by_spu || {})
    .some(m => m[st.code] && m[st.code].length));
  return cityHasSlots ? hint.includes('已接入') : hint.includes('未接入');
};
const detailCheck = () => {
  const hlIds = META.spus.filter(s => s.hl && Object.keys(s.hl).length).slice(0, 3).map(s => s.spu_id);
  let ok = 0;
  for (const id of hlIds) {
    try {
      renderDetail(id);
      const h = E('dHl').innerHTML;
      if (h.includes('套餐') || h.includes('赠品') || h.includes('预约')) ok++;
    } catch (e) { console.error(`   renderDetail(${id}) 抛错：`, e.message); }
  }
  return [ok, hlIds.length];
};

if (!isNation) {
  /* ===== 城市级模板 ===== */
  const optCount = (E('citySel').innerHTML.match(/<option/g) || []).length;
  check('城市下拉覆盖全部缓存城市', optCount === cityCodes.length, `${optCount} 城`);

  let themesOK = 0, storesOK = 0, hintOK = 0;
  for (const c of cityCodes) {
    S.city = c; S.spu = 0; S.sel = 0; S.store = null; S.loc = null;
    renderThemes();
    if ((E('themes').innerHTML.match(/class="tcard/g) || []).length > 0) themesOK++;
    else console.error(`   ${c} 无主题卡`);
    if (slotsHintOK(E('slotHint').innerHTML)) hintOK++;
    const spu = cityStores()[0].spus[0];
    S.spu = spu; S.sel = spu;
    try { renderStoreView(); if ((E('svList').innerHTML.match(/svrow/g) || []).length > 0) storesOK++; }
    catch (e) { console.error(`   ${c} renderStoreView 抛错：`, e.message); }
    S.spu = 0;
  }
  check('全部城市 renderThemes 出卡', themesOK === cityCodes.length, `${themesOK}/${cityCodes.length}`);
  check('全部城市 renderStoreView 出行', storesOK === cityCodes.length, `${storesOK}/${cityCodes.length}`);
  check('场次提示按城市如实显示', hintOK === cityCodes.length, `${hintOK}/${cityCodes.length}`);

  const [dOk, dAll] = detailCheck();
  check('renderDetail 出重点内容', dOk === dAll, `${dOk}/${dAll}`);
} else {
  /* ===== 全国级模板 ===== */
  const { PROVS, PROV_OF, buildProvSelect, buildCitySelect } = T;

  // 1. 全国视图 = 省份排行
  S.prov = ''; S.city = ''; S.spu = 0; S.sel = 0; S.store = null; S.loc = null;
  buildProvSelect(); buildCitySelect();
  renderThemes();
  const html0 = E('themes').innerHTML;
  const zeroCards = (html0.match(/class="pcard zero"/g) || []).length;
  const allCards = (html0.match(/class="pcard( zero)?"/g) || []).length;
  const missing = [...(META.missing_provs || [])];
  // 省份卡 = 有数据的省 + 零覆盖的省（后者灰显，必须露脸）
  check('全国视图出省份排行', allCards === PROVS.length + missing.length,
        `${allCards} 卡 = ${PROVS.length} 有数据 + ${zeroCards} 零覆盖`);
  check('零覆盖省份如实显示', zeroCards === missing.length && missing.length > 0,
        `${zeroCards}/${missing.length}：${missing.map(m => m.name).join('、') || '无'}`);
  // 零覆盖省份不可点：不应带 data-prov 或带 zero 类（点击处理会跳过）
  const zeroClickable = (html0.match(/class="pcard zero"[^>]*data-prov=/g) || []).length;
  check('零覆盖省份不可点', zeroClickable === 0);
  const provOpts = (E('provSel').innerHTML.match(/<option/g) || []).length;
  check('省下拉 = 内地 + 全部省', provOpts === PROVS.length + 1, `${provOpts} 项`);
  check('全国层级禁用城市下拉', E('citySel').disabled === true);

  // 1.5 城市聚合：每个省的城市气泡数与门店数对得上
  if (cityStatsOf){
    let aggOK = 0;
    for (const p of PROVS){
      const rows = cityStatsOf(p.code, 0);
      const sum = rows.reduce((a, r) => a + r.n, 0);
      const expect = DATA.filter(s => PROV_OF[s.city] === p.code).length;
      const nCity = new Set(DATA.filter(s => PROV_OF[s.city] === p.code).map(s => s.city)).size;
      if (sum === expect && rows.length === nCity) aggOK++;
      else console.error(`   ${p.name}: 气泡 ${rows.length} 城（应 ${nCity}）/ 门店合计 ${sum}（应 ${expect}）`);
    }
    check('城市气泡聚合数与门店数一致', aggOK === PROVS.length, `${aggOK}/${PROVS.length} 省`);
  }

  // 2. 每个省：全省主题卡 + 城市下拉按省过滤
  let provOK = 0, provCityOptOK = 0;
  for (const p of PROVS) {
    S.prov = p.code; S.city = ''; S.spu = 0; S.sel = 0; S.store = null; S.loc = null;
    buildCitySelect();
    renderThemes();
    if ((E('themes').innerHTML.match(/class="tcard/g) || []).length > 0) provOK++;
    else console.error(`   ${p.name} 无主题卡`);
    const nCity = new Set(DATA.filter(s => PROV_OF[s.city] === p.code).map(s => s.city)).size;
    const opts = (E('citySel').innerHTML.match(/<option/g) || []).length;
    if (opts === nCity + 1) provCityOptOK++;
    else console.error(`   ${p.name} 城市下拉 ${opts} 项，应为 ${nCity + 1}`);
  }
  check('全部省 renderThemes 出卡', provOK === PROVS.length, `${provOK}/${PROVS.length}`);
  check('城市下拉按省过滤', provCityOptOK === PROVS.length, `${provCityOptOK}/${PROVS.length}`);

  // 3. 每个城市：主题卡 + 门店列表 + 场次提示
  let themesOK = 0, storesOK = 0, hintOK = 0;
  for (const c of cityCodes) {
    S.prov = PROV_OF[c]; S.city = c; S.spu = 0; S.sel = 0; S.store = null; S.loc = null;
    renderThemes();
    if ((E('themes').innerHTML.match(/class="tcard/g) || []).length > 0) themesOK++;
    else console.error(`   ${c} 无主题卡`);
    if (slotsHintOK(E('slotHint').innerHTML)) hintOK++;
    const spu = cityStores()[0].spus[0];
    S.spu = spu; S.sel = spu;
    try { renderStoreView(); if ((E('svList').innerHTML.match(/svrow/g) || []).length > 0) storesOK++; }
    catch (e) { console.error(`   ${c} renderStoreView 抛错：`, e.message); }
    S.spu = 0;
  }
  check('全部城市 renderThemes 出卡', themesOK === cityCodes.length, `${themesOK}/${cityCodes.length}`);
  check('全部城市 renderStoreView 出行', storesOK === cityCodes.length, `${storesOK}/${cityCodes.length}`);
  check('场次提示按城市如实显示', hintOK === cityCodes.length, `${hintOK}/${cityCodes.length}`);

  const [dOk, dAll] = detailCheck();
  check('renderDetail 出重点内容', dOk === dAll, `${dOk}/${dAll}`);
}

console.log(failures ? `\n${failures} 项未通过` : '\n全部通过');
process.exit(failures ? 1 : 0);
