/* Shared PDD22 display policy. Never alters observations or scientific rasters. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Pdd22Observations = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const number = value => value === null || value === undefined || String(value).trim() === ''
    ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const coverage = obs => number(obs?.coverage_pct ?? obs?.clear_pixel_pct);
  const qa = obs => {
    const value = coverage(obs);
    if (!obs || value === null || value < 5 || obs.qa === 'NO_DATA') return 'NO_DATA';
    if (obs.qa === 'GOOD' && value >= 95 && value <= 100) return 'GOOD';
    if (obs.qa === 'PARTIAL' && value >= 50 && value < 95) return 'PARTIAL';
    return 'LOW_QA';
  };
  const good = obs => qa(obs) === 'GOOD';
  const ndvi = obs => good(obs) ? number(obs.mean_ndvi_inside ?? obs.mean_ndvi) : null;
  const goodFcd = obs => good(obs) && ['green_rai','yellow_rai','red_rai'].every(k => number(obs[k]) !== null && number(obs[k]) >= 0);
  const months = plots => [...new Set(plots.flatMap(p => Object.keys(p.fcd_by_month || {})))].sort();
  const latestGood = plot => Object.entries(plot?.fcd_by_month || {}).filter(([,o]) => goodFcd(o))
    .sort(([a],[b]) => b.localeCompare(a)).map(([month,observation]) => ({month,observation}))[0] || null;
  function compare(plot, before, after) {
    const a = plot.fcd_by_month?.[before], b = plot.fcd_by_month?.[after];
    const common = {plot, before, after, beforeQa:qa(a), afterQa:qa(b), delta:null};
    if (!goodFcd(a) || !goodFcd(b)) return {...common,status:'INSUFFICIENT',reason:'ข้อมูลไม่พอ: ต้องผ่าน QA GOOD ทั้งสองช่วง'};
    if (!before || !after || before >= after) return {...common,status:'NOT_COMPARABLE',reason:'เลือกช่วงก่อนให้เก่ากว่าช่วงหลัง'};
    if (before.slice(5) !== after.slice(5)) return {...common,status:'NOT_COMPARABLE',reason:'ต่างเดือน: ไม่ใช้สรุปแนวโน้มแบบฤดูกาลเดียวกัน'};
    const delta = Math.round((number(b.green_rai) - number(a.green_rai)) * 100) / 100;
    return {...common,delta,status:delta < 0 ? 'REVIEW' : 'NO_DECREASE',
      reason:delta < 0 ? 'พื้นที่จัดกลุ่มเขียวลดลง: เปิดภาพตรวจประกอบ' : 'ไม่พบการลดลงของพื้นที่จัดกลุ่มเขียวในคู่นี้'};
  }
  function summarize(plots, before, after) {
    const rows = plots.map(p => compare(p,before,after));
    const matched = rows.filter(r => r.delta !== null);
    const totalArea = plots.reduce((s,p) => s + (number(p.area_rai) || 0),0);
    const matchedArea = matched.reduce((s,r) => s + (number(r.plot.area_rai) || 0),0);
    return {rows,matchedCount:matched.length,totalArea,matchedArea,
      matchedAreaPct:totalArea ? matchedArea / totalArea * 100 : null,
      beforeGreen:matched.length ? matched.reduce((s,r) => s + number(r.plot.fcd_by_month[before].green_rai),0) : null,
      afterGreen:matched.length ? matched.reduce((s,r) => s + number(r.plot.fcd_by_month[after].green_rai),0) : null,
      delta:matched.length ? Math.round(matched.reduce((s,r) => s + r.delta,0) * 100) / 100 : null,
      reviewCount:rows.filter(r => r.status === 'REVIEW').length,
      insufficientCount:rows.filter(r => r.status === 'INSUFFICIENT').length};
  }
  function defaultPair(plots) {
    const dates = months(plots), pairs = [];
    for (const after of dates) for (const before of dates) {
      if (before < after && before.slice(5) === after.slice(5)) {
        pairs.push({before,after,count:summarize(plots,before,after).matchedCount});
      }
    }
    pairs.sort((a,b) => b.count-a.count || b.after.localeCompare(a.after) || a.before.localeCompare(b.before));
    return pairs[0] || {before:dates[0] || '',after:dates.at(-1) || '',count:0};
  }
  function asset(plot, item, layer) {
    if (layer === 'esri') return {state:'BASEMAP',url:null};
    if (!plot || !item) return {state:'NO_DATA',url:null};
    const obs = layer === 'fcd' ? plot.fcd_by_month?.[item.month] : item;
    if (!obs) return {state:layer === 'fcd' ? 'NO_FCD' : 'NO_DATA',url:null};
    if (qa(obs) === 'NO_DATA') return {state:'NO_DATA',url:null};
    const code = encodeURIComponent(plot.code), month = encodeURIComponent(item.month);
    if (layer === 'fcd') return {state:'AVAILABLE',url:`data/pdd22_v3/maps/${code}/fcd_${month}.png`};
    if (!['gee_rgb','gee_ndvi'].includes(layer)) throw new Error('Unknown observation layer');
    return {state:'AVAILABLE',url:`data/pdd22_satellite/plots/${code}/${month}/${layer === 'gee_ndvi' ? 'ndvi' : 'rgb'}.png`};
  }
  // Last request wins. The old *labelled* frame survives loading, never an error.
  // Both metadata and imagery commit together after a decoded, hidden frame is ready.
  function createFrameController({load,commit,clear,loading,failed}) {
    let generation = 0, displayed = null;
    return {
      get displayed() { return displayed; },
      invalidate() { generation++; displayed = null; },
      async request(snapshot) {
        const token = ++generation;
        const current = () => token === generation;
        if (!snapshot.url) { clear(snapshot); displayed = null; commit(snapshot,null); return; }
        loading(snapshot,displayed);
        let frame;
        try {
          frame = await load(snapshot,current);
          if (!current()) { frame?.dispose?.(); return; }
          commit(snapshot,frame); displayed = snapshot;
        } catch (error) {
          frame?.dispose?.();
          if (!current()) return;
          clear(snapshot); displayed = null; failed(snapshot,error);
        }
      }
    };
  }
  function loadLeafletFrame(L,map,snapshot,isCurrent,options={}) {
    return new Promise((resolve,reject) => {
      const overlay = L.imageOverlay(snapshot.url,snapshot.bounds,{...options,opacity:0,interactive:false});
      let settled = false;
      const dispose = () => { if (map.hasLayer(overlay)) map.removeLayer(overlay); };
      const finish = (error) => {
        if (settled) return; settled=true; clearTimeout(timeout);
        overlay.off('load',loaded); overlay.off('error',errored);
        if (error) { dispose(); reject(error); }
        else resolve({overlay,dispose});
      };
      const loaded = async () => {
        try { await overlay.getElement()?.decode?.(); if (!isCurrent()) dispose(); finish(); }
        catch (error) { finish(error); }
      };
      const errored = () => finish(new Error('IMAGE_UNAVAILABLE'));
      const timeout = setTimeout(() => finish(new Error('IMAGE_TIMEOUT')),15000);
      overlay.once('load',loaded); overlay.once('error',errored); overlay.addTo(map);
    });
  }
  function csvCell(value) {
    let text = value === null || value === undefined ? '' : String(value);
    if (typeof value === 'string' && /^[\s]*[=+\-@\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"','""') + '"';
  }
  return {number,coverage,qa,good,ndvi,goodFcd,months,latestGood,compare,summarize,defaultPair,asset,createFrameController,loadLeafletFrame,csvCell};
});
