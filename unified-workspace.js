/* Unified 210-plot workspace: registry identity + optional PDD participating scope. */
(() => {
  'use strict';
  const U=window.UnifiedData,C=window.AllPlotsCore;
  if(!U||!C){window.__unifiedWorkspaceError='UnifiedData unavailable';return;}
  const S={masters:[],filtered:[],before:'2024-03',after:'2025-03',id:null,scope:'registry',loaded:false};
  const e=id=>document.getElementById(id),fmt=v=>U.number(v)===null?'—':Number(v).toLocaleString('th-TH',{maximumFractionDigits:2});
  const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  const thai=s=>({REVIEW:'ควรตรวจ',NO_DECREASE:'ไม่พบการลดลง',INSUFFICIENT:'ข้อมูลไม่พอ',NOT_COMPARABLE:'เทียบไม่ได้',ATMOSPHERE_REVIEW:'ตรวจเมฆ/หมอก',TIDE_WATER_REVIEW:'ตรวจน้ำ',VISUAL_REVIEW:'ตรวจภาพ',MISSING_ANALYSIS:'ยังไม่มีผลวิเคราะห์'}[s]||s||'—');
  const plot=m=>S.scope==='pdd'&&m.pdd?m.pdd:m.registry;
  function inject(){
    if(e('wtab-unified210'))return;
    const tabs=document.querySelector('.workspace-tabs'),detail=e('panel-detail');if(!tabs||!detail)return;
    const b=document.createElement('button');b.id='wtab-unified210';b.className='w-tab-btn';b.textContent='210 แปลงรวม';b.onclick=()=>switchWorkspaceTab('unified210');tabs.prepend(b);
    const p=document.createElement('section');p.id='panel-unified210';p.className='tab-content-panel';
    p.innerHTML='<div class="allplots-heading"><div><p class="allplots-eyebrow">UNIFIED REGISTRY + PDD SCOPE</p><h2>210 แปลงทะเบียน</h2><p>หนึ่ง identity ต่อแปลง; 22 แปลง PDD เป็น scope ภายในแปลงเดิม ไม่สร้างรายการซ้ำ</p></div></div>'+
    '<div class="allplots-method-warning">PDD raster ใช้ซ้ำเฉพาะเมื่อ scope + เดือน + scene + asset ตรงกันจริง; raster เฉพาะ PDD ห้ามแทนขอบเขตทะเบียน</div>'+
    '<div class="allplots-filters"><label>จังหวัด<select id="u-province"><option value="ALL">ทุกจังหวัด</option></select></label><label>ค้นหา<input id="u-search" type="search"></label><label>ก่อน<select id="u-before"></select></label><label>หลัง<select id="u-after"></select></label><label>สมาชิก<select id="u-member"><option value="ALL">ทั้งหมด</option><option value="PDD">PDD22</option><option value="NON">ไม่ใช่ PDD22</option></select></label></div>'+
    '<div class="allplots-cards" id="u-cards"></div><p class="allplots-context" id="u-context"></p>'+
    '<section class="allplots-inspector"><div class="allplots-inspector-head"><div><span>แปลงที่เลือก</span><h3 id="u-title">—</h3><p id="u-sub">—</p></div><div class="allplots-layer"><button data-u-scope="registry" class="active">ขอบเขตทะเบียน</button><button data-u-scope="pdd">ขอบเขต PDD</button></div></div><div class="allplots-compare-grid"><article><div id="u-bt" class="allplots-image-title"></div><div class="allplots-image-wrap"><img id="u-bi"><div id="u-be" class="allplots-image-empty"></div></div></article><article><div id="u-at" class="allplots-image-title"></div><div class="allplots-image-wrap"><img id="u-ai"><div id="u-ae" class="allplots-image-empty"></div></div></article></div><div class="allplots-metric-strip" id="u-metrics"></div></section>'+
    '<div class="table-container"><table class="plots-table allplots-table"><thead><tr><th>แปลง</th><th>พื้นที่ทะเบียน</th><th>PDD22</th><th>ทะเบียน</th><th>PDD</th><th></th></tr></thead><tbody id="u-rows"></tbody></table></div>';
    detail.before(p);
    C.MONTHS.forEach(m=>{e('u-before').add(new Option(C.monthLabel(m),m));e('u-after').add(new Option(C.monthLabel(m),m));});
    e('u-before').value=S.before;e('u-after').value=S.after;
    e('u-before').onchange=()=>{S.before=e('u-before').value;render();};e('u-after').onchange=()=>{S.after=e('u-after').value;render();};
    e('u-province').onchange=render;e('u-member').onchange=render;e('u-search').oninput=render;
    document.querySelectorAll('[data-u-scope]').forEach(x=>x.onclick=()=>{const m=S.masters.find(v=>v.id===S.id);if(x.dataset.uScope==='pdd'&&!m?.pdd)return;S.scope=x.dataset.uScope;inspect();});
  }
  function visible(){
    const pr=e('u-province').value,mem=e('u-member').value,q=e('u-search').value.trim().toLowerCase();
    return S.masters.filter(m=>(pr==='ALL'||m.registry.province===pr)&&(mem==='ALL'||(mem==='PDD'?!!m.pdd:!m.pdd))&&(!q||[m.code,m.registry.fullName,m.registry.province].join(' ').toLowerCase().includes(q)));
  }
  function render(){
    if(!S.loaded)return;S.filtered=visible();if(!S.filtered.some(m=>m.id===S.id)){S.id=S.filtered[0]?.id??null;S.scope='registry';}
    const rs=U.summarize(S.filtered.map(m=>m.registry),S.before,S.after),pc=S.filtered.filter(m=>m.pdd).length;
    e('u-cards').innerHTML=[['แปลง',S.filtered.length],['PDD22',pc],['ทะเบียนเทียบได้',rs.matched],['ควรตรวจ',rs.review]].map(x=>'<article><span>'+x[0]+'</span><strong>'+x[1]+'</strong></article>').join('');
    e('u-context').textContent=C.monthLabel(S.before)+' → '+C.monthLabel(S.after)+' · ขาดข้อมูลคงเป็นขาดข้อมูล ไม่มี nearest-month substitution';
    const body=e('u-rows');body.innerHTML='';S.filtered.forEach(m=>{const rr=U.compare(m.registry,S.before,S.after),pp=m.pdd?U.compare(m.pdd,S.before,S.after):null,tr=document.createElement('tr');tr.innerHTML='<td><strong>'+esc(m.code)+'</strong><small>'+esc(m.registry.province)+'</small></td><td>'+fmt(m.registry.area_rai)+' ไร่</td><td>'+(m.pdd?fmt(m.pdd.area_rai)+' ไร่':'—')+'</td><td>'+thai(rr.status)+'</td><td>'+(pp?thai(pp.status):'—')+'</td><td><button>เปิด</button></td>';tr.querySelector('button').onclick=()=>{S.id=m.id;S.scope='registry';inspect();};body.append(tr);});inspect();
  }
  function img(id,empty,p,o){
    const sp=U.asset(p,o,'gee_rgb'),i=e(id),z=e(empty);i.hidden=true;z.hidden=false;
    if(!sp||sp.state!=='AVAILABLE'||!sp.url){z.textContent='ไม่มีภาพเดือนนี้';return;}z.textContent='กำลังโหลด…';i.onload=()=>{i.hidden=false;z.hidden=true;};i.onerror=()=>{i.hidden=true;z.textContent='โหลดภาพไม่สำเร็จ';};i.src=sp.url+'?v=20261003-u1';
  }
  function inspect(){
    const m=S.masters.find(v=>v.id===S.id);if(!m)return;if(S.scope==='pdd'&&!m.pdd)S.scope='registry';
    document.querySelectorAll('[data-u-scope]').forEach(x=>{x.classList.toggle('active',x.dataset.uScope===S.scope);x.hidden=x.dataset.uScope==='pdd'&&!m.pdd;});
    const p=plot(m),a=U.observation(p,S.before),b=U.observation(p,S.after),r=U.compare(p,S.before,S.after);
    e('u-title').textContent=m.code+' · '+p.province;e('u-sub').textContent=U.scopeLabel(p)+' · '+fmt(p.area_rai)+' ไร่ · '+U.methodLabel(p);
    e('u-bt').textContent='ก่อน · '+C.monthLabel(S.before);e('u-at').textContent='หลัง · '+C.monthLabel(S.after);img('u-bi','u-be',p,a);img('u-ai','u-ae',p,b);
    e('u-metrics').innerHTML='<div><span>สถานะ</span><strong>'+thai(r.status)+'</strong></div><div><span>Δ เขียว</span><strong>'+fmt(r.delta)+' ไร่</strong></div><div><span>Δ NDVI</span><strong>'+fmt(r.deltaNdvi)+'</strong></div><div><span>Scope</span><strong>'+esc(U.scopeLabel(p))+'</strong></div>';
  }
  async function load(){
    try{
      const paths=['data/plots_catalog.json','data/timeseries_verified_12.json','data/pdd22/plots_catalog.json','data/pdd22_v3/plots_result.json','data/pdd22_satellite/coverage_report.csv','data/all_plots_visual_qa.json'];
      const r=await Promise.all(paths.map(x=>fetch(x+'?v=20261003-u1',{cache:'no-store'})));if(r.some(x=>!x.ok))throw Error('dataset load failed');
      const catalog=await r[0].json(),verified=await r[1].json(),pdd=await r[2].json(),fcd=await r[3].json(),cov=U.parseCsv(await r[4].text()),qa=await r[5].json();
      S.masters=U.merge(catalog,verified,pdd,fcd,cov,qa);if(S.masters.length!==210||S.masters.filter(m=>m.pdd).length!==22)throw Error('identity mapping invariant failed');
      [...new Set(S.masters.map(m=>m.registry.province))].sort((a,b)=>a.localeCompare(b,'th')).forEach(x=>e('u-province').add(new Option(x,x)));
      S.loaded=true;S.id=S.masters[0].id;e('wtab-unified210').textContent='210 แปลงรวม · 210';render();window.__unifiedWorkspaceReady=true;setTimeout(()=>switchWorkspaceTab('unified210'),0);
    }catch(err){window.__unifiedWorkspaceError=String(err);if(e('u-context'))e('u-context').textContent='Unified workspace error: '+err.message;}
  }
  const start=()=>{inject();load();};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();