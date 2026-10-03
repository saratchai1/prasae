/* General 210-plot portfolio: precomputed verified satellite screening with conservative secondary QA. */
(() => {
  'use strict';
  const C=AllPlotsCore;
  const VERSION='20261003-qa3';
  const DATA_VERSION='20261003-qa3';
  const state={plots:[],filtered:[],pair:{before:'',after:''},selectedId:null,layer:'rgb',loaded:false,visualQa:{observations:{},summary:{}},imageToken:0};

  const el=id=>document.getElementById(id);
  const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const fmt=v=>C.number(v)===null?'—':Number(v).toLocaleString('th-TH',{maximumFractionDigits:2});
  const signed=v=>C.number(v)===null?'—':`${Number(v)>0?'+':''}${fmt(v)}`;
  const safeFile=v=>String(v||'').replace(/[\\/:*?"<>|]/g,'-').replace(/\s+/g,'_');
  const absUrl=path=>{if(!path)return'';try{return new URL(`${path}?v=${DATA_VERSION}`,document.baseURI).href}catch{return path}};
  const statusThai=s=>({
    REVIEW:'ควรตรวจการเปลี่ยนแปลง',
    NO_DECREASE:'ไม่พบการลดลงในคู่นี้',
    INSUFFICIENT:'ข้อมูลไม่พอ',
    NOT_COMPARABLE:'ยังเปรียบเทียบไม่ได้',
    ATMOSPHERE_REVIEW:'ตรวจเมฆ / หมอก',
    TIDE_WATER_REVIEW:'ตรวจน้ำ / น้ำขึ้นลง',
    VISUAL_REVIEW:'ตรวจภาพเพิ่มเติม'
  }[s]||String(s||'—'));
  const secondaryThai=s=>({
    CLEAR:'ผ่าน QA เพิ่มเติม',
    ATMOSPHERE_REVIEW:'ตรวจเมฆ / หมอก',
    TIDE_WATER_REVIEW:'ตรวจน้ำ / น้ำขึ้นลง',
    VISUAL_REVIEW:'ตรวจภาพเพิ่มเติม',
    INSUFFICIENT:'ข้อมูลไม่พอ'
  }[s]||String(s||'—'));

  function normalize(catalog,verified){
    const m=new Map(verified.map(p=>[Number(p.id),p]));
    return catalog.map(c=>{
      const v=m.get(Number(c.id))||{};
      const bm=new Map((v.timeseries||[]).map(o=>[o.month,o]));
      return {...c,...v,id:Number(c.id),name:c.name||v.name||c.code,
        timeseries:C.MONTHS.map(month=>({
          month,year:Number(month.slice(0,4)),month_num:Number(month.slice(5)),
          ...(bm.get(month)||{status:'no_data',clear_pixel_pct:0})
        }))};
    });
  }

  function secondaryQa(plot,month){
    return state.visualQa?.observations?.[`${plot.id}|${month}`] || {
      status:'INSUFFICIENT',reason:'ไม่มี secondary QA สำหรับ observation นี้',coverage_pct:0
    };
  }

  function screenedCompare(plot,before,after){
    const base=C.compare(plot,before,after);
    const beforeSecondary=secondaryQa(plot,before),afterSecondary=secondaryQa(plot,after);
    const result={...base,beforeSecondary,afterSecondary};
    if(base.status==='NOT_COMPARABLE'||base.status==='INSUFFICIENT')return result;
    const flagged=[beforeSecondary,afterSecondary].filter(q=>q.status!=='CLEAR');
    if(!flagged.length)return result;
    const order={TIDE_WATER_REVIEW:0,ATMOSPHERE_REVIEW:1,VISUAL_REVIEW:2,INSUFFICIENT:3};
    flagged.sort((a,b)=>(order[a.status]??9)-(order[b.status]??9));
    const q=flagged[0];
    return {...result,status:q.status,reason:`QA เพิ่มเติม: ${q.reason}`,deltaGreenArea:null,deltaGreenPct:null,deltaNdvi:null};
  }

  function screenedSummary(plots,before,after){
    const rows=plots.map(p=>screenedCompare(p,before,after));
    const matched=rows.filter(r=>r.deltaGreenArea!==null);
    const totalArea=plots.reduce((s,p)=>s+(C.number(p.area_rai)||0),0);
    const matchedArea=matched.reduce((s,r)=>s+(C.number(r.plot.area_rai)||0),0);
    return {
      rows,totalArea,matchedArea,matchedCount:matched.length,
      matchedAreaPct:totalArea?matchedArea/totalArea*100:null,
      deltaGreenArea:matched.length?Math.round(matched.reduce((s,r)=>s+r.deltaGreenArea,0)*100)/100:null,
      reviewCount:rows.filter(r=>r.status==='REVIEW').length,
      qaReviewCount:rows.filter(r=>['ATMOSPHERE_REVIEW','TIDE_WATER_REVIEW','VISUAL_REVIEW'].includes(r.status)).length,
      insufficientCount:rows.filter(r=>r.status==='INSUFFICIENT').length
    };
  }

  function screenedDefaultPair(){
    const pairs=[];
    for(const after of C.MONTHS)for(const before of C.MONTHS){
      if(before<after&&before.slice(5)===after.slice(5)){
        pairs.push({before,after,count:screenedSummary(state.plots,before,after).matchedCount});
      }
    }
    pairs.sort((a,b)=>b.count-a.count||b.after.localeCompare(a.after)||a.before.localeCompare(b.before));
    return pairs[0]||{before:C.MONTHS[0],after:C.MONTHS.at(-1),count:0};
  }

  function inject(){
    if(el('wtab-allplots'))return;
    const tabs=document.querySelector('.workspace-tabs'),detail=el('panel-detail');
    if(!tabs||!detail)return;
    const b=document.createElement('button');
    b.type='button';b.className='w-tab-btn';b.id='wtab-allplots';b.textContent='แปลงทั่วไป · กำลังโหลด';b.onclick=()=>switchWorkspaceTab('allplots');
    tabs.prepend(b);
    const p=document.createElement('section');p.className='tab-content-panel';p.id='panel-allplots';
    p.innerHTML=`
      <div class="allplots-heading">
        <div>
          <p class="allplots-eyebrow">PRECOMPUTED SENTINEL-2 SCREENING · VERIFIED 12-DATE</p>
          <h2>แปลงทั่วไปนอกชุด PDD22</h2>
          <p><strong>ผลวิเคราะห์ดาวเทียมที่ประมวลผลไว้ล่วงหน้า</strong> จาก Sentinel-2 L2A · Green Cover Proxy / NDVI · 209/210 แปลงยังไม่ได้ calibrate ด้วยข้อมูลภาคสนามรายแปลง</p>
        </div>
        <div class="allplots-actions"><button type="button" id="allplots-export">ส่งออก CSV ภาษาไทย</button><small id="allplots-export-note">กำลังโหลดข้อมูล</small></div>
      </div>
      <div class="allplots-method-warning">ค่า Δ จะแสดงเฉพาะเมื่อ <strong>ทั้งสองช่วงผ่าน coverage และ secondary visual QA</strong> เท่านั้น · observation ที่ติดเมฆ/หมอก น้ำผิดปกติ หรือควรตรวจภาพ จะไม่ถูกนำไปสรุปการเปลี่ยนแปลงอัตโนมัติ</div>
      <div class="allplots-filters">
        <label>จังหวัด<select id="allplots-province"><option value="ALL">ทุกจังหวัด</option></select></label>
        <label>ค้นหา<input id="allplots-search" type="search" placeholder="รหัสแปลง / ชื่อ / จังหวัด"></label>
        <label>ช่วงก่อน<select id="allplots-before"></select></label>
        <label>ช่วงหลัง<select id="allplots-after"></select></label>
        <label>สถานะ<select id="allplots-status">
          <option value="ALL">ทั้งหมด</option>
          <option value="REVIEW">ควรตรวจการเปลี่ยนแปลง</option>
          <option value="ATMOSPHERE_REVIEW">ตรวจเมฆ / หมอก</option>
          <option value="TIDE_WATER_REVIEW">ตรวจน้ำ / น้ำขึ้นลง</option>
          <option value="VISUAL_REVIEW">ตรวจภาพเพิ่มเติม</option>
          <option value="INSUFFICIENT">ข้อมูลไม่พอ</option>
          <option value="NOT_COMPARABLE">ยังเปรียบเทียบไม่ได้</option>
          <option value="NO_DECREASE">ไม่พบการลดลงในคู่นี้</option>
        </select></label>
      </div>
      <div class="allplots-cards" id="allplots-cards"></div>
      <p class="allplots-context" id="allplots-context" role="status">กำลังโหลดข้อมูล…</p>
      <section class="allplots-inspector" id="allplots-inspector">
        <div class="allplots-inspector-head">
          <div><span>แปลงที่เลือก</span><h3 id="allplots-selected-title">—</h3><p id="allplots-selected-sub">—</p></div>
          <div class="allplots-layer"><button type="button" data-allplots-layer="rgb" class="active">RGB</button><button type="button" data-allplots-layer="ndvi">NDVI</button></div>
        </div>
        <div id="allplots-qa-warning" class="allplots-qa-warning" hidden></div>
        <div class="allplots-compare-grid">
          <article><div class="allplots-image-title" id="allplots-before-title">ช่วงก่อน</div><div class="allplots-image-wrap"><img id="allplots-before-img" alt="ภาพช่วงก่อน"><div id="allplots-before-empty" class="allplots-image-empty">—</div></div><div id="allplots-before-meta" class="allplots-image-meta">—</div></article>
          <article><div class="allplots-image-title" id="allplots-after-title">ช่วงหลัง</div><div class="allplots-image-wrap"><img id="allplots-after-img" alt="ภาพช่วงหลัง"><div id="allplots-after-empty" class="allplots-image-empty">—</div></div><div id="allplots-after-meta" class="allplots-image-meta">—</div></article>
        </div>
        <div class="allplots-scale-note">ภาพสองฝั่งถูก crop จาก <strong>ขอบเขตแปลงเดียวกัน</strong> และแสดงด้วย scale เดียวกัน · ไม่มีการยืดภาพคนละสัดส่วน</div>
        <div class="allplots-metric-strip" id="allplots-metric-strip"></div>
      </section>
      <div class="table-container"><table class="plots-table allplots-table"><thead><tr><th>แปลง / จังหวัด</th><th>พื้นที่</th><th>Green Cover Proxy ก่อน → หลัง</th><th>Δ Green (ไร่)</th><th>NDVI ก่อน → หลัง</th><th>QA ก่อน → หลัง</th><th>สถานะ</th><th>ภาพ</th></tr></thead><tbody id="allplots-rows"></tbody></table></div>
      <p class="allplots-note">Green Cover Proxy เป็น satellite screening ไม่ใช่ canopy density ที่ยืนยันภาคสนาม และไม่ใช่คาร์บอนเครดิต · secondary QA เป็น conservative screening เพิ่มเติม ไม่ใช่หลักฐานยืนยันว่าเป็นเมฆหรือน้ำท่วม</p>`;
    detail.before(p);

    for(const m of C.MONTHS){el('allplots-before').add(new Option(C.monthLabel(m),m));el('allplots-after').add(new Option(C.monthLabel(m),m));}
    ['allplots-province','allplots-status'].forEach(id=>el(id).addEventListener('change',render));
    el('allplots-search').addEventListener('input',render);
    el('allplots-before').addEventListener('change',()=>{state.pair.before=el('allplots-before').value;render();});
    el('allplots-after').addEventListener('change',()=>{state.pair.after=el('allplots-after').value;render();});
    el('allplots-export').addEventListener('click',exportCsv);
    document.querySelectorAll('[data-allplots-layer]').forEach(btn=>btn.addEventListener('click',()=>{
      state.layer=btn.dataset.allplotsLayer;
      document.querySelectorAll('[data-allplots-layer]').forEach(x=>x.classList.toggle('active',x===btn));
      renderInspector();
    }));
  }

  function visible(){
    const province=el('allplots-province')?.value||'ALL';
    const q=(el('allplots-search')?.value||'').trim().toLowerCase();
    const status=el('allplots-status')?.value||'ALL';
    return state.plots.filter(p=>{
      if(province!=='ALL'&&(p.province||'ไม่ระบุ')!==province)return false;
      if(q&&!([C.displayCode(p),p.code,p.name,p.province].join(' ').toLowerCase().includes(q)))return false;
      return status==='ALL'||screenedCompare(p,state.pair.before,state.pair.after).status===status;
    });
  }

  function render(){
    if(!state.loaded)return;
    state.filtered=visible();
    const s=screenedSummary(state.filtered,state.pair.before,state.pair.after),status=el('allplots-status').value;
    el('allplots-cards').innerHTML=[
      ['แปลงในตัวกรอง',`${state.filtered.length} แปลง`,`${fmt(s.totalArea)} ไร่`],
      ['เปรียบเทียบได้หลัง QA',`${s.matchedCount} แปลง`,`${fmt(s.matchedArea)} ไร่ (${fmt(s.matchedAreaPct)}%)`],
      ['ควรตรวจการเปลี่ยนแปลง',`${s.reviewCount} แปลง`,'เฉพาะคู่ที่ผ่าน QA สองชั้น'],
      ['QA เพิ่มเติมต้องตรวจ',`${s.qaReviewCount} แปลง`,'ไม่ถูกนำไปคำนวณ Δ']
    ].map(([a,b,c])=>`<article><span>${a}</span><strong>${b}</strong><small>${c}</small></article>`).join('');
    el('allplots-context').textContent=`${C.monthLabel(state.pair.before)} → ${C.monthLabel(state.pair.after)} · Δ Green Cover Proxy รวม ${signed(s.deltaGreenArea)} ไร่ · ใช้เฉพาะแปลงชุดเดียวกันที่ผ่าน coverage + secondary QA ทั้งสองช่วง`;
    el('allplots-export').disabled=!state.filtered.length;
    el('allplots-export').textContent=`ส่งออก CSV ภาษาไทย · ${state.filtered.length} แปลง`;
    el('allplots-export-note').textContent=status==='ALL'?'ตามจังหวัด/ค้นหา/ช่วงเวลาที่เลือก':`เฉพาะสถานะ: ${statusThai(status)}`;
    if(!state.filtered.some(p=>p.id===state.selectedId))state.selectedId=state.filtered[0]?.id??null;
    renderRows();renderInspector();
  }

  function renderRows(){
    const body=el('allplots-rows');body.innerHTML='';const f=document.createDocumentFragment();
    for(const p of state.filtered){
      const r=screenedCompare(p,state.pair.before,state.pair.after),a=r.beforeObs,b=r.afterObs;
      const tr=document.createElement('tr');
      tr.innerHTML=`<td><strong>${esc(C.displayCode(p))}</strong><small>${esc(p.province||'ไม่ระบุ')} · ${esc(p.name||'')}</small></td>
        <td>${fmt(p.area_rai)} ไร่</td>
        <td>${fmt(C.greenPct(a))}% → ${fmt(C.greenPct(b))}%</td>
        <td>${signed(r.deltaGreenArea)}</td>
        <td>${fmt(C.ndvi(a))} → ${fmt(C.ndvi(b))}</td>
        <td>${secondaryThai(r.beforeSecondary.status)} → ${secondaryThai(r.afterSecondary.status)}</td>
        <td><span class="allplots-status ${r.status.toLowerCase()}">${statusThai(r.status)}</span><small>${esc(r.reason)}</small></td>
        <td><button type="button">ดูภาพก่อน–หลัง</button></td>`;
      tr.querySelector('button').addEventListener('click',()=>{state.selectedId=p.id;renderInspector();el('allplots-inspector').scrollIntoView({behavior:'smooth',block:'start'});});
      f.append(tr);
    }
    body.append(f);
    if(!state.filtered.length)body.innerHTML='<tr><td colspan="8">ไม่พบแปลงตามตัวกรอง</td></tr>';
  }

  function cropWindow(plot,nw,nh){
    const b=plot.bounds;
    if(!Array.isArray(b)||b.length!==4)return {x:0,y:0,w:nw,h:nh};
    const full=[Number(b[0])-.003,Number(b[1])-.003,Number(b[2])+.003,Number(b[3])+.003];
    const lon=full[2]-full[0],lat=full[3]-full[1];
    if(!(lon>0&&lat>0))return {x:0,y:0,w:nw,h:nh};
    let x0=(Number(b[0])-full[0])/lon*nw,x1=(Number(b[2])-full[0])/lon*nw;
    let y0=(full[3]-Number(b[3]))/lat*nh,y1=(full[3]-Number(b[1]))/lat*nh;
    const px=Math.max(3,(x1-x0)*.08),py=Math.max(3,(y1-y0)*.08);
    x0=Math.max(0,Math.floor(x0-px));y0=Math.max(0,Math.floor(y0-py));
    x1=Math.min(nw,Math.ceil(x1+px));y1=Math.min(nh,Math.ceil(y1+py));
    return {x:x0,y:y0,w:Math.max(1,x1-x0),h:Math.max(1,y1-y0)};
  }

  function setImage(imgId,emptyId,plot,o,token){
    const display=el(imgId),empty=el(emptyId),path=C.asset(plot,o,state.layer);
    display.removeAttribute('src');display.hidden=true;empty.hidden=false;
    if(!path){empty.textContent='ไม่มีภาพสำหรับช่วงนี้';return;}
    empty.textContent='กำลังโหลดภาพ…';
    const loader=new Image();
    loader.onload=()=>{
      if(token!==state.imageToken)return;
      const crop=cropWindow(plot,loader.naturalWidth,loader.naturalHeight);
      const canvas=document.createElement('canvas');canvas.width=crop.w;canvas.height=crop.h;
      const ctx=canvas.getContext('2d',{alpha:true});ctx.imageSmoothingEnabled=false;
      ctx.drawImage(loader,crop.x,crop.y,crop.w,crop.h,0,0,crop.w,crop.h);
      display.onload=()=>{
        if(token!==state.imageToken)return;
        display.hidden=false;empty.hidden=true;
        display.dataset.sourceWidth=String(loader.naturalWidth);display.dataset.sourceHeight=String(loader.naturalHeight);
        display.dataset.cropX=String(crop.x);display.dataset.cropY=String(crop.y);display.dataset.cropWidth=String(crop.w);display.dataset.cropHeight=String(crop.h);
        display.dataset.sourceUrl=path;
      };
      display.src=canvas.toDataURL('image/png');
    };
    loader.onerror=()=>{if(token===state.imageToken){display.hidden=true;empty.hidden=false;empty.textContent='โหลดภาพไม่สำเร็จ';}};
    loader.src=`${path}?v=${DATA_VERSION}`;
  }

  function qaMeta(q){
    const extras=[];
    if(C.number(q.cloud_like_pct)!==null)extras.push(`cloud-like ${fmt(q.cloud_like_pct)}%`);
    if(C.number(q.haze_like_pct)!==null)extras.push(`haze-like ${fmt(q.haze_like_pct)}%`);
    if(C.number(q.open_water_pct)!==null)extras.push(`น้ำ ${fmt(q.open_water_pct)}%`);
    return extras.length?` · ${extras.join(' · ')}`:'';
  }

  function renderInspector(){
    const p=state.plots.find(x=>x.id===state.selectedId);
    if(!p){el('allplots-selected-title').textContent='ไม่มีแปลงในตัวกรอง';el('allplots-selected-sub').textContent='—';return;}
    const r=screenedCompare(p,state.pair.before,state.pair.after),a=r.beforeObs,b=r.afterObs;
    el('allplots-selected-title').textContent=`${C.displayCode(p)} · ${p.province||'ไม่ระบุ'}`;
    el('allplots-selected-sub').textContent=`${p.name} · ${fmt(p.area_rai)} ไร่ · รหัสระบบ ${p.code}`;
    el('allplots-before-title').textContent=`ก่อน · ${C.monthLabel(state.pair.before)}`;
    el('allplots-after-title').textContent=`หลัง · ${C.monthLabel(state.pair.after)}`;
    el('allplots-before-meta').textContent=`${secondaryThai(r.beforeSecondary.status)} · coverage ${fmt(a?.clear_pixel_pct)}% · Green Cover Proxy ${fmt(C.greenPct(a))}% · NDVI ${fmt(C.ndvi(a))}${qaMeta(r.beforeSecondary)}`;
    el('allplots-after-meta').textContent=`${secondaryThai(r.afterSecondary.status)} · coverage ${fmt(b?.clear_pixel_pct)}% · Green Cover Proxy ${fmt(C.greenPct(b))}% · NDVI ${fmt(C.ndvi(b))}${qaMeta(r.afterSecondary)}`;
    const warning=el('allplots-qa-warning');
    if(['ATMOSPHERE_REVIEW','TIDE_WATER_REVIEW','VISUAL_REVIEW'].includes(r.status)){
      warning.hidden=false;warning.textContent=`${statusThai(r.status)} — ${r.reason} ค่า Δ ถูกระงับจนกว่าจะตรวจภาพ/สภาพน้ำ.`;
    }else{warning.hidden=true;warning.textContent='';}
    const token=++state.imageToken;
    setImage('allplots-before-img','allplots-before-empty',p,a,token);
    setImage('allplots-after-img','allplots-after-empty',p,b,token);
    el('allplots-metric-strip').innerHTML=`
      <div><span>สถานะ</span><strong>${statusThai(r.status)}</strong></div>
      <div><span>Δ Green Cover Proxy</span><strong>${signed(r.deltaGreenArea)} ไร่</strong></div>
      <div><span>Δ Green Cover Proxy</span><strong>${signed(r.deltaGreenPct)} จุด%</strong></div>
      <div><span>Δ NDVI</span><strong>${signed(r.deltaNdvi)}</strong></div>`;
  }

  function exportCsv(){
    if(!state.filtered.length)return;
    const header=['รหัสแปลง','รหัสระบบ','ชื่อแปลง','จังหวัด','พื้นที่ (ไร่)','ช่วงก่อน','ช่วงหลัง','เปรียบเทียบได้หลัง QA','QA เพิ่มเติมก่อน','QA เพิ่มเติมหลัง','เหตุผล QA ก่อน','เหตุผล QA หลัง','ความครอบคลุมก่อน (%)','ความครอบคลุมหลัง (%)','Green Cover Proxy ก่อน (%)','Green Cover Proxy หลัง (%)','พื้นที่ Green Cover Proxy ก่อน (ไร่)','พื้นที่ Green Cover Proxy หลัง (ไร่)','การเปลี่ยนแปลง Green Cover Proxy (ไร่)','การเปลี่ยนแปลง Green Cover Proxy (จุด%)','NDVI ก่อน','NDVI หลัง','การเปลี่ยนแปลง NDVI','พื้นที่น้ำก่อน (%)','พื้นที่น้ำหลัง (%)','สถานะ','เหตุผล','ลิงก์ภาพ RGB ก่อน','ลิงก์ภาพ RGB หลัง','ลิงก์ภาพ NDVI ก่อน','ลิงก์ภาพ NDVI หลัง','วิธีการ'];
    const rows=state.filtered.map(p=>{
      const r=screenedCompare(p,state.pair.before,state.pair.after),a=r.beforeObs,b=r.afterObs;
      return [C.displayCode(p),p.code,p.name,p.province||'ไม่ระบุ',p.area_rai,C.monthLabel(state.pair.before),C.monthLabel(state.pair.after),r.deltaGreenArea!==null?'ได้':'ไม่ได้',
        secondaryThai(r.beforeSecondary.status),secondaryThai(r.afterSecondary.status),r.beforeSecondary.reason,r.afterSecondary.reason,
        C.number(a?.clear_pixel_pct),C.number(b?.clear_pixel_pct),C.greenPct(a),C.greenPct(b),C.greenArea(p,a),C.greenArea(p,b),r.deltaGreenArea,r.deltaGreenPct,
        C.ndvi(a),C.ndvi(b),r.deltaNdvi,C.waterPct(a),C.waterPct(b),statusThai(r.status),r.reason,
        absUrl(C.asset(p,a,'rgb')),absUrl(C.asset(p,b,'rgb')),absUrl(C.asset(p,a,'ndvi')),absUrl(C.asset(p,b,'ndvi')),
        'ผลวิเคราะห์ดาวเทียมที่ประมวลผลไว้ล่วงหน้า · Verified 12-date v4 Green Cover Proxy + conservative secondary visual QA; ไม่ใช่ FCD V3 และไม่ใช่คาร์บอนเครดิต'];
    });
    const csv='\uFEFF'+[header,...rows].map(row=>row.map(C.csvCell).join(',')).join('\r\n');
    const u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');
    a.href=u;a.download=`แปลงทั่วไป_เปรียบเทียบ_${safeFile(C.monthLabel(state.pair.before))}_ถึง_${safeFile(C.monthLabel(state.pair.after))}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
  }

  async function load(){
    try{
      const paths=['data/plots_catalog.json','data/timeseries_verified_12.json','data/all_plots_visual_qa.json'];
      const rs=await Promise.all(paths.map(path=>fetch(`${path}?v=${DATA_VERSION}`,{cache:'no-store'})));
      if(rs.some(r=>!r.ok))throw new Error('โหลด dataset/secondary QA ไม่สำเร็จ');
      const [catalog,verified,visualQa]=await Promise.all(rs.map(r=>r.json()));
      if(!visualQa?.observations||Object.keys(visualQa.observations).length!==2520)throw new Error('secondary QA ไม่ครบ 2,520 observation');
      state.visualQa=visualQa;state.plots=normalize(catalog,verified);state.loaded=true;
      const pair=screenedDefaultPair();state.pair={before:pair.before,after:pair.after};
      el('allplots-before').value=pair.before;el('allplots-after').value=pair.after;
      const provinces=[...new Set(state.plots.map(p=>p.province||'ไม่ระบุ'))].sort((a,b)=>a.localeCompare(b,'th'));
      for(const province of provinces)el('allplots-province').add(new Option(`${province} (${state.plots.filter(p=>(p.province||'ไม่ระบุ')===province).length} แปลง)`,province));
      el('wtab-allplots').textContent=`แปลงทั่วไป · ${state.plots.length}`;
      render();window.__allPlotsReady=true;
    }catch(error){el('allplots-context').textContent=`โหลดข้อมูลแปลงทั่วไปไม่สำเร็จ: ${error.message}`;window.__allPlotsError=String(error);}
  }

  let savedHeader=null;
  function switchHeader(allMode){
    const title=document.querySelector('.brand-title'),sub=document.querySelector('.brand-subtitle'),pills=[...document.querySelectorAll('.header-meta .meta-pill')];
    if(allMode){
      if(!savedHeader)savedHeader={doc:document.title,title:title?.textContent||'',sub:sub?.textContent||'',pills:pills.map(x=>x.textContent)};
      const area=state.plots.reduce((sum,p)=>sum+(C.number(p.area_rai)||0),0);
      const known=new Set(state.plots.map(p=>p.province).filter(x=>x&&x!=='ไม่ระบุ')).size;
      document.title='แปลงทั่วไป · Prasae';
      if(title)title.textContent=`ติดตามแปลงป่าชายเลน · ${state.plots.length} แปลงทั่วไป`;
      if(sub)sub.textContent='ผลวิเคราะห์ Sentinel-2 ที่ประมวลผลไว้ล่วงหน้า · Green Cover Proxy / NDVI + secondary QA';
      if(pills[0])pills[0].textContent=`${state.plots.length} แปลง`;
      if(pills[1])pills[1].textContent=`${fmt(area)} ไร่`;
      if(pills[2])pills[2].textContent=`${known} จังหวัด + รายการไม่ระบุจังหวัด`;
    }else if(savedHeader){
      document.title=savedHeader.doc;if(title)title.textContent=savedHeader.title;if(sub)sub.textContent=savedHeader.sub;
      pills.forEach((x,i)=>{if(savedHeader.pills[i]!==undefined)x.textContent=savedHeader.pills[i]});
    }
  }

  const prior=window.switchWorkspaceTab;
  window.switchWorkspaceTab=function(tab){
    const allMode=tab==='allplots';document.body.classList.toggle('allplots-mode',allMode);switchHeader(allMode);prior(tab);
    if(allMode)setTimeout(renderInspector,50);
  };
  window.AllPlotsPortfolio={state,render,secondaryQa,screenedCompare,screenedSummary,selectById(id){state.selectedId=Number(id);renderInspector();},exportCsv};
  const start=()=>{inject();load();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();