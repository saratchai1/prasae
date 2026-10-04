/* Unified 210-plot workspace. One registry identity per plot; PDD is an optional scope, never a duplicate plot. */
(() => {
  'use strict';
  const U=UnifiedData, C=AllPlotsCore, P=Pdd22Observations;
  const DATA_VERSION='20261004-local-ingest-1';
  let masters=[], masterById=new Map(), pair={before:'2024-03',after:'2026-03'}, visiblePlots=[];

  const el=id=>document.getElementById(id);
  const text=(id,value)=>{const n=el(id);if(n)n.textContent=value;};
  const fmt=v=>U.number(v)===null?'—':Number(v).toLocaleString('th-TH',{maximumFractionDigits:2});
  const sign=v=>U.number(v)===null?'—':`${Number(v)>0?'+':''}${fmt(v)}`;
  const title=p=>`${p.code} · ${p.province||'ไม่ระบุ'}`;
  const masterFor=id=>masterById.get(Number(id))||null;
  const currentMaster=()=>activePlot?masterFor(activePlot.registryId??activePlot.id):null;
  const currentScope=()=>activePlot?.scope||'registry';
  const secondaryLabel=q=>({
    CLEAR:'ผ่าน QA เพิ่มเติม',COVERAGE_ONLY:'QA coverage',ATMOSPHERE_REVIEW:'ตรวจเมฆ / หมอก',
    TIDE_WATER_REVIEW:'ตรวจน้ำ / น้ำขึ้นลง',VISUAL_REVIEW:'ตรวจภาพเพิ่มเติม',INSUFFICIENT:'ข้อมูลไม่พอ'
  }[q]||q||'—');
  const statusLabel=s=>U.labels[s]||({
    GOOD:'ผ่าน QA',REVIEW:'ควรตรวจการเปลี่ยนแปลง',NO_DECREASE:'ไม่พบการลดลงในคู่นี้',
    INSUFFICIENT:'ข้อมูลไม่พอ',NOT_COMPARABLE:'เทียบไม่ได้',MISSING_ANALYSIS:'ยังไม่มีผลวิเคราะห์'
  }[s]||String(s||'—'));

  function withSummaryFields(plot){
    const a=plot.timeseries.find(o=>o.month==='2024-03'),b=plot.timeseries.find(o=>o.month==='2026-03');
    const qa=U.quality(plot,a),qb=U.quality(plot,b);
    const na=qa.eligible?U.number(a?.mean_ndvi_inside):null,nb=qb.eligible?U.number(b?.mean_ndvi_inside):null;
    const current=plot.timeseries.find(o=>o.month==='2026-08');
    return {...plot,
      initial_ndvi:na,current_ndvi:nb,gain_ndvi:na!==null&&nb!==null?Math.round((nb-na)*10000)/10000:null,
      current_vegetation_proxy_pct:current?U.greenPct(plot,current):null};
  }

  loadData=async function loadUnified210(){
    const paths=[
      'data/plots_catalog.json','data/timeseries_verified_12.json','data/pdd22/plots_catalog.json',
      'data/pdd22_v3/plots_result.json','data/pdd22_satellite/coverage_report.csv','data/all_plots_visual_qa.json'
    ];
    const rs=await Promise.all(paths.map(async path=>{
      const r=await fetch(`${path}?v=${DATA_VERSION}`,{cache:'no-store'});
      if(!r.ok)throw new Error(`${path}: HTTP ${r.status}`);
      return r;
    }));
    const [catalog,verified,pddCatalog,fcd,coverageText,visualQa]=await Promise.all([
      rs[0].json(),rs[1].json(),rs[2].json(),rs[3].json(),rs[4].text(),rs[5].json()
    ]);
    const coverage=U.parseCsv(coverageText);
    masters=U.merge(catalog,verified,pddCatalog,fcd,coverage,visualQa);
    masterById=new Map(masters.map(m=>[m.id,m]));
    plotsCatalog=masters.map(m=>m.registry);
    allPlotsData=masters.map(m=>withSummaryFields({...m.registry,hasPdd:!!m.pdd}));
    visiblePlots=allPlotsData.slice();
    verifiedDatasetLoaded=true;
    const candidates=[];
    for(const after of MILESTONE_MONTHS)for(const before of MILESTONE_MONTHS){
      if(before<after&&before.slice(5)===after.slice(5)){
        const s=U.summarize(allPlotsData,before,after);candidates.push({before,after,count:s.matched});
      }
    }
    candidates.sort((a,b)=>b.count-a.count||b.after.localeCompare(a.after)||a.before.localeCompare(b.before));
    if(candidates[0])pair={before:candidates[0].before,after:candidates[0].after};
    currentMonthIndex=Math.max(0,MILESTONE_MONTHS.indexOf(pair.after));
    window.UnifiedWorkspace={masters,masterById,getPair:()=>({...pair}),getMaster:id=>masterFor(id),version:DATA_VERSION};
  };

  function injectScopeControl(){
    if(el('analysis-scope-select'))return;
    const toolbar=document.querySelector('.viewer-toolbar');if(!toolbar)return;
    const wrap=document.createElement('div');wrap.className='unified-scope-control';wrap.id='analysis-scope-wrap';
    wrap.innerHTML='<label for="analysis-scope-select">ขอบเขตวิเคราะห์</label><select id="analysis-scope-select"><option value="registry">ขอบเขตทะเบียนแปลง</option><option value="pdd">พื้นที่เข้าร่วม PDD</option></select><small id="analysis-scope-note"></small>';
    toolbar.prepend(wrap);
    el('analysis-scope-select').onchange=e=>setAnalysisScope(e.target.value);
  }

  function injectStatusPanel(){
    if(el('unified-observation-status'))return;
    const stage=document.querySelector('.satellite-stage');if(!stage)return;
    const p=document.createElement('div');p.id='unified-observation-status';p.className='unified-observation-status';
    stage.after(p);
  }

  updateStaticCopy=function unifiedStaticCopy(){
    document.title='ติดตามป่าชายเลน · 210 แปลง';
    const total=allPlotsData.reduce((s,p)=>s+(U.number(p.area_rai)||0),0);
    const provinces=new Set(allPlotsData.map(p=>p.province).filter(p=>p&&p!=='ไม่ระบุ')).size;
    document.querySelector('.brand-title').textContent=`ติดตามป่าชายเลน · ${allPlotsData.length} แปลง`;
    document.querySelector('.brand-subtitle').textContent='Sentinel-2 L2A · Green Cover Proxy / NDVI · PDD22 FCD เฉพาะเมื่อเลือกขอบเขต PDD';
    const pills=[...document.querySelectorAll('.header-meta .meta-pill')];
    if(pills[0])pills[0].textContent=`${allPlotsData.length} แปลง`;
    if(pills[1])pills[1].textContent=`${fmt(total)} ไร่`;
    if(pills[2])pills[2].textContent=`${provinces} จังหวัด + รายการไม่ระบุจังหวัด`;
    text('kpi-total-area',`${fmt(total)} ไร่`);
    const totalSub=el('kpi-total-area')?.parentElement?.querySelector('.kpi-sub');if(totalSub)totalSub.textContent='พื้นที่ทะเบียน 210 แปลง';
    el('wtab-table').textContent='ตารางผลวิเคราะห์';
    document.querySelector('.chart-badge-tag').textContent='210 plots';
    document.querySelector('.chart-box-subtitle').textContent='ผล precomputed จาก Sentinel-2 · เว้นค่าเมื่อไม่ผ่าน QA · ไม่มี nearest-month substitution';
    const bands=document.querySelector('.band-btn-group');
    if(bands&&!bands.querySelector('[data-layer="fcd"]')){
      const b=document.createElement('button');b.className='band-btn';b.dataset.layer='fcd';b.textContent='FCD เขียว / เหลือง / แดง';b.onclick=()=>setPlotMapLayer('fcd');bands.append(b);
    }
    injectScopeControl();injectStatusPanel();
  };

  renderSidebarList=function unifiedSidebar(plots){
    visiblePlots=plots.slice();const container=el('plot-list-container');container.innerHTML='';
    text('sidebar-count-display',`แสดง ${plots.length} จาก ${allPlotsData.length} แปลง`);
    for(const p of plots){
      const m=masterFor(p.id),card=document.createElement('div');
      card.className=`plot-card-item ${activePlot?.registryId===p.id||activePlot?.id===p.id?'active':''}`;
      card.id=`sidebar-card-${p.id}`;card.tabIndex=0;card.setAttribute('role','button');
      const choose=()=>selectPlot(p.id);card.onclick=choose;card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}};
      const latest=p.timeseries.find(o=>o.month==='2026-08'),q=U.quality(p,latest);
      card.innerHTML=`<div class="p-card-header"><span class="p-card-title">${escapeHtml(p.code)}</span><span class="p-prov-tag">${escapeHtml(p.province||'ไม่ระบุ')}</span></div>
        <div class="p-card-body"><span>พื้นที่ <strong>${fmt(p.area_rai)} ไร่</strong></span><span>${secondaryLabel(q.secondary)}${m?.pdd?' · PDD':''}</span></div>`;
      container.append(card);
    }
  };

  function syncScopeUi(){
    const m=currentMaster(),sel=el('analysis-scope-select'),wrap=el('analysis-scope-wrap');
    if(!sel||!m)return;
    sel.value=currentScope();sel.querySelector('option[value="pdd"]').disabled=!m.pdd;
    wrap.classList.toggle('has-pdd',!!m.pdd);
    text('analysis-scope-note',m.pdd?'แปลงนี้มีทั้งขอบเขตทะเบียนและขอบเขตเข้าร่วม PDD — เลือกได้โดยไม่สร้างแปลงซ้ำ':'แปลงนี้ไม่มีขอบเขต PDD22');
    const fcdBtn=document.querySelector('[data-layer="fcd"]');
    if(fcdBtn){fcdBtn.disabled=currentScope()!=='pdd';fcdBtn.title=currentScope()==='pdd'?'FCD V3 สำหรับขอบเขตเข้าร่วม PDD':'FCD มีเฉพาะขอบเขตเข้าร่วม PDD';}
    const bottom=document.querySelector('.stage-hud.bottom-left .hud-sub:last-child');
    if(bottom)bottom.textContent=U.scopeLabel(activePlot);
  }

  window.setAnalysisScope=function(scope){
    const m=currentMaster();if(!m)return;
    const next=scope==='pdd'&&m.pdd?m.pdd:m.registry;
    activePlot=next;
    if(currentPlotLayerKey==='fcd'&&next.scope!=='pdd')currentPlotLayerKey='gee_rgb';
    applyActivePlot();
  };

  selectPlot=function unifiedSelectPlot(id){
    const m=masterFor(id);if(!m)return;
    activePlot=m.registry;applyActivePlot();
    document.querySelectorAll('.plot-card-item').forEach(c=>c.classList.toggle('active',Number(c.dataset.plotId)===Number(id)));
    el(`sidebar-card-${id}`)?.scrollIntoView({behavior:'smooth',block:'nearest'});
  };

  function applyActivePlot(){
    const p=activePlot;if(!p)return;
    syncScopeUi();
    text('kpi-current-plot-name',p.code);
    text('kpi-current-plot-sub',`${U.scopeLabel(p)} · ${fmt(p.area_rai)} ไร่ · ${p.province||'ไม่ระบุ'}`);
    text('chart-plot-title',`NDVI + ${U.methodLabel(p)} — ${p.code}`);
    renderPlotChart(p);updatePlotSatelliteViewer(p);initCompareSelectors(p);comparePlotId=null;setMonthIndex(currentMonthIndex);
    if(el('panel-compare')?.classList.contains('active'))setTimeout(updateCompareView,0);
    refreshMapStyles();
    window.UnifiedSpectralRefresh?.();
  }

  renderPlotChart=function unifiedChart(p){
    const labels=p.timeseries.map(o=>U.monthLabel(o.month));
    const ndvi=p.timeseries.map(o=>U.ndvi(p,o));
    const green=p.timeseries.map(o=>U.greenPct(p,o));
    if(plotNdviChart)plotNdviChart.destroy();
    plotNdviChart=new Chart(el('plotNdviChart').getContext('2d'),{
      type:'line',data:{labels,datasets:[
        {label:'NDVI · ผ่าน QA',data:ndvi,borderColor:'#10b981',backgroundColor:'transparent',spanGaps:false,tension:0,pointRadius:4,yAxisID:'y'},
        {label:U.methodLabel(p)+' (%)',data:green,borderColor:'#38bdf8',backgroundColor:'transparent',spanGaps:false,tension:0,pointRadius:3,yAxisID:'y1'}
      ]},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},onClick:(e,items)=>{if(items?.length)setMonthIndex(items[0].index);},
        scales:{y:{min:-.1,max:.9,position:'left',ticks:{color:'#94a3b8'},grid:{color:'rgba(255,255,255,.05)'}},y1:{min:0,max:100,position:'right',ticks:{color:'#94a3b8',callback:v=>v+'%'},grid:{drawOnChartArea:false}},x:{ticks:{color:'#64748b'},grid:{color:'rgba(255,255,255,.04)'}}},
        plugins:{legend:{labels:{color:'#cbd5e1'}}}}
    });
  };

  updatePlotSatelliteViewer=function unifiedViewer(p){
    if(!plotSatelliteMap||!p.geometry)return;
    if(plotBoundaryLayer&&plotSatelliteMap.hasLayer(plotBoundaryLayer))plotSatelliteMap.removeLayer(plotBoundaryLayer);
    plotBoundaryLayer=L.geoJSON({type:'Feature',properties:{},geometry:p.geometry},{style:{color:'#34d399',weight:2,fillOpacity:0}}).addTo(plotSatelliteMap);
    const b=plotBoundaryLayer.getBounds();if(b.isValid())plotSatelliteMap.fitBounds(b,{padding:[45,45],maxZoom:17,animate:false});
    togglePlotBoundary(el('toggle-boundary-check')?.checked!==false);
  };

  function clearOverlay(){
    sentinelSwapToken++;
    if(pendingSentinelOverlay&&plotSatelliteMap?.hasLayer(pendingSentinelOverlay))plotSatelliteMap.removeLayer(pendingSentinelOverlay);
    pendingSentinelOverlay=null;
    if(currentSentinelOverlay&&plotSatelliteMap?.hasLayer(currentSentinelOverlay))plotSatelliteMap.removeLayer(currentSentinelOverlay);
    currentSentinelOverlay=null;
  }

  setPlotMapLayer=function unifiedLayer(layer){
    if(layer==='fcd'&&activePlot?.scope!=='pdd')return;
    currentPlotLayerKey=layer;document.querySelectorAll('.band-btn').forEach(b=>b.classList.toggle('active',b.dataset.layer===layer));
    if(layer==='esri'){clearOverlay();renderCurrentStatus();return;}
    updateGeeOverlay();
  };

  function renderCurrentStatus(error=''){
    if(!activePlot)return;const item=activePlot.timeseries[currentMonthIndex],q=U.quality(activePlot,item),g=U.greenPct(activePlot,item),n=U.ndvi(activePlot,item);
    text('hud-month-label',currentPlotLayerKey==='esri'?'ภาพพื้นหลัง · ไม่อิงเดือน':U.monthLabel(item.month));
    text('hud-plot-label',title(activePlot));
    text('hud-coords-label',`${fmt(activePlot.area_rai)} ไร่ · ${U.scopeLabel(activePlot)}`);
    text('hud-in-ndvi',n===null?'—':n.toFixed(3));
    text('hud-in-cover',g===null?'—':`${fmt(g)}%`);
    text('kpi-plot-canopy-pct',g===null?'—':`${fmt(g)}%`);
    const k=el('kpi-plot-canopy-pct')?.parentElement?.querySelector('.kpi-label');if(k)k.textContent=U.methodLabel(activePlot)+' · ช่วงที่แสดง';
    const sub=el('kpi-plot-canopy-pct')?.parentElement?.querySelector('.kpi-sub');if(sub)sub.textContent=`${U.monthLabel(item.month)} · ${q.label}`;
    const tag=document.querySelector('.stage-hud.top-right .hud-tag');if(tag)tag.textContent=currentPlotLayerKey==='esri'?'Esri World Imagery':currentPlotLayerKey==='fcd'?'FCD V3':`Sentinel-2 · ${q.label}`;
    const ts=document.querySelector('.stage-hud.top-right .hud-sub');if(ts)ts.textContent=error||`coverage ${fmt(item.clear_pixel_pct)}% · ${secondaryLabel(q.secondary)}`;
    text('unified-observation-status',error||`${title(activePlot)} · ${U.monthLabel(item.month)} · ${q.label} · ${q.reason||''}`);
  }

  updateGeeOverlay=async function unifiedOverlay(){
    if(!activePlot||!plotSatelliteMap||currentPlotLayerKey==='esri')return;
    const item=activePlot.timeseries[currentMonthIndex];if(!item)return;
    const spec=U.asset(activePlot,item,currentPlotLayerKey);
    if(spec.state!=='AVAILABLE'||!spec.url){clearOverlay();renderCurrentStatus(spec.state==='MISSING_ANALYSIS'?'ไม่มี FCD สำหรับขอบเขตทะเบียนนี้':'ไม่มีภาพที่ใช้ได้ในเดือนนี้ — ไม่ใช้เดือนอื่นแทน');return;}
    const url=`${spec.url}?v=${DATA_VERSION}`,token=++sentinelSwapToken;
    try{await preloadImage(url);}catch{if(token===sentinelSwapToken){clearOverlay();renderCurrentStatus('โหลดภาพไม่สำเร็จ');}return;}
    if(token!==sentinelSwapToken)return;
    const old=currentSentinelOverlay,next=L.imageOverlay(url,imageBoundsForPlot(activePlot),{opacity:0,interactive:false,className:'sentinel-overlay'});pendingSentinelOverlay=next;
    next.once('load',()=>{if(token!==sentinelSwapToken)return;requestAnimationFrame(()=>next.setOpacity(.94));setTimeout(()=>{if(old&&old!==next&&plotSatelliteMap.hasLayer(old))plotSatelliteMap.removeLayer(old);currentSentinelOverlay=next;pendingSentinelOverlay=null;plotBoundaryLayer?.bringToFront();},260);});
    next.addTo(plotSatelliteMap);plotBoundaryLayer?.bringToFront();renderCurrentStatus();
  };

  setMonthIndex=function unifiedMonth(index){
    if(!activePlot)return;currentMonthIndex=Math.max(0,Math.min(MILESTONE_MONTHS.length-1,Number(index)||0));
    const item=activePlot.timeseries[currentMonthIndex];el('month-slider').value=String(currentMonthIndex);
    text('playback-date-display',U.monthLabel(item.month));renderCurrentStatus();
    if(currentPlotLayerKey!=='esri')updateGeeOverlay();
    if(plotNdviChart){plotNdviChart.setActiveElements([{datasetIndex:0,index:currentMonthIndex}]);plotNdviChart.update('none');}
    window.UnifiedSpectralRefresh?.();
  };

  initCompareSelectors=function unifiedCompareSelectors(p){
    const l=el('comp-left-select'),r=el('comp-right-select');l.innerHTML='';r.innerHTML='';
    p.timeseries.forEach((o,i)=>{const q=U.quality(p,o),opt=new Option(`${U.monthLabel(o.month)} · ${q.label}`,String(i));l.add(opt);r.add(opt.cloneNode(true));});
    l.value=String(Math.max(0,MILESTONE_MONTHS.indexOf(pair.before)));r.value=String(Math.max(0,MILESTONE_MONTHS.indexOf(pair.after)));
  };

  // One map keeps both dates on exactly the same geographic transform. Clip
  // both rasters: transparent pixels on the left must not reveal the right date.
  let compareMap=null,compareFrames=null,compareController=null,comparePercent=50,compareFramingKey=null;

  function setComparePosition(value){
    comparePercent=Math.max(0,Math.min(100,Number(value)||0));
    const divider=el('unified-compare-divider'),handle=el('unified-compare-handle'),range=el('compare-position');
    if(divider)divider.style.left=`${comparePercent}%`;
    if(handle)handle.setAttribute('aria-valuenow',String(Math.round(comparePercent)));
    if(range)range.value=String(comparePercent);
    if(!compareFrames||!compareMap)return;
    const area=compareMap.getContainer().getBoundingClientRect(),split=area.left+area.width*comparePercent/100;
    for(const [side,frame] of [['before',compareFrames.before],['after',compareFrames.after]]){
      const image=frame.overlay.getElement(),rect=image.getBoundingClientRect();if(!rect.width)continue;
      const x=Math.max(0,Math.min(100,(split-rect.left)/rect.width*100));
      image.style.clipPath=side==='before'?`polygon(0 0, ${x}% 0, ${x}% 100%, 0 100%)`:`polygon(${x}% 0, 100% 0, 100% 100%, ${x}% 100%)`;
      image.style.webkitClipPath=image.style.clipPath;
    }
  }

  function clearCompareFrames(){
    compareFrames?.dispose();compareFrames=null;compareLeftOverlay=null;compareRightOverlay=null;
  }

  function showCompareBoundary(snapshot){
    if(compareLeftBoundary&&compareMap.hasLayer(compareLeftBoundary))compareMap.removeLayer(compareLeftBoundary);
    compareLeftBoundary=L.geoJSON({type:'Feature',properties:{},geometry:snapshot.plot.geometry},{
      pane:'unifiedCompareBoundary',style:{color:'#34d399',weight:2,fillOpacity:0}
    });
    if(el('comp-boundary-toggle')?.checked!==false)compareLeftBoundary.addTo(compareMap);
    const key=`${snapshot.plot.registryId??snapshot.plot.id}|${snapshot.plot.scope}`;
    if(key!==compareFramingKey){
      const bounds=compareLeftBoundary.getBounds();
      if(bounds.isValid())compareMap.fitBounds(bounds,{padding:[38,38],maxZoom:17,animate:false});
      compareFramingKey=key;
    }
  }

  function renderCompareSnapshot(snapshot,available){
    const {plot,before,after,mode}=snapshot;
    text('comp-label-before',`ก่อน · ${U.monthLabel(before.month)} · ${snapshot.beforeLayer} · ${U.quality(plot,before).label}`);
    text('comp-label-after',`หลัง · ${U.monthLabel(after.month)} · ${snapshot.afterLayer} · ${U.quality(plot,after).label}`);
    el('comp-ndvi-legend').hidden=mode!=='ndvi'&&mode!=='rgb_vs_ndvi';
    const cmp=U.compare(plot,before.month,after.month,mode==='fcd');
    text('comp-in-stat-text',available?(cmp.delta===null?cmp.reason:`${U.methodLabel(plot)}: Δ ${sign(cmp.delta)} ไร่`):'ไม่มีภาพที่ใช้ได้ครบทั้งสองฝั่ง');
    text('comp-gain-pill',available?statusLabel(cmp.status):'ยังเปรียบเทียบไม่ได้');
    comparePlotId=plot.id;
  }

  ensureCompareMaps=function unifiedCompareMaps(){
    if(compareMap)return;
    const stage=el('compare-container');stage.classList.add('unified-compare-stage');
    stage.innerHTML=`<div id="unified-compare-map"></div>
      <div class="unified-compare-label before" id="comp-label-before">ก่อน</div>
      <div class="unified-compare-label after" id="comp-label-after">หลัง</div>
      <div id="unified-compare-divider"><button type="button" id="unified-compare-handle" role="slider" aria-label="เลื่อนเส้นเปรียบเทียบภาพก่อนและหลัง" aria-valuemin="0" aria-valuemax="100" aria-valuenow="50" aria-orientation="horizontal">↔</button></div>
      <div id="unified-compare-status" role="status" aria-live="polite"></div>
      <label class="unified-compare-range" for="compare-position">เส้นเปรียบเทียบ<input id="compare-position" type="range" min="0" max="100" step="1" value="50"></label>`;
    compareMap=L.map('unified-compare-map',{scrollWheelZoom:false,zoomAnimation:false}).setView([10,100],8);
    // Keep the existing tab resize hook attached to this single map.
    compareLeftMap=compareMap;compareRightMap=null;
    [['unifiedCompareAfter',410],['unifiedCompareBefore',420],['unifiedCompareBoundary',430]].forEach(([name,z])=>{
      compareMap.createPane(name);compareMap.getPane(name).style.zIndex=z;
    });
    compareMap.attributionControl.addAttribution('Sentinel-2 · ภาพตามเดือนที่เลือก');
    compareMap.on('zoom move resize',()=>setComparePosition(comparePercent));
    new ResizeObserver(()=>{compareMap.invalidateSize();setComparePosition(comparePercent);}).observe(stage);
    el('compare-position').oninput=e=>setComparePosition(e.target.value);
    const handle=el('unified-compare-handle');let dragging=false;
    handle.onpointerdown=e=>{
      if(e.button!==0)return;dragging=true;compareMap.dragging.disable();
      handle.setPointerCapture(e.pointerId);e.stopPropagation();e.preventDefault();
    };
    handle.onpointermove=e=>{
      if(!dragging)return;
      const rect=compareMap.getContainer().getBoundingClientRect();setComparePosition((e.clientX-rect.left)/rect.width*100);
      e.preventDefault();
    };
    const stopDrag=()=>{dragging=false;compareMap.dragging.enable();};
    handle.onpointerup=e=>{if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);stopDrag();};
    handle.onpointercancel=handle.onlostpointercapture=stopDrag;
    handle.onkeydown=e=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
      e.preventDefault();setComparePosition(e.key==='Home'?0:e.key==='End'?100:comparePercent+(e.key==='ArrowRight'?5:-5));
    };
    compareController=P.createFrameController({
      async load(snapshot,current){
        const results=await Promise.allSettled([
          P.loadLeafletFrame(L,compareMap,{url:snapshot.beforeUrl,bounds:snapshot.bounds},current,{pane:'unifiedCompareBefore',className:'compare-before-raster'}),
          P.loadLeafletFrame(L,compareMap,{url:snapshot.afterUrl,bounds:snapshot.bounds},current,{pane:'unifiedCompareAfter',className:'compare-after-raster'})
        ]);
        const failure=results.find(r=>r.status==='rejected');
        if(failure){results.forEach(r=>{if(r.status==='fulfilled')r.value.dispose();});throw failure.reason;}
        const before=results[0].value,after=results[1].value;
        return {before,after,dispose(){before.dispose();after.dispose();}};
      },
      loading(snapshot,displayed){
        stage.setAttribute('aria-busy','true');
        text('unified-compare-status',`กำลังโหลด ${snapshot.plot.code} · ${U.monthLabel(snapshot.before.month)} → ${U.monthLabel(snapshot.after.month)}${displayed?' · ภาพและป้ายที่เห็นยังเป็นคู่ก่อนหน้า':''}`);
      },
      commit(snapshot,next){
        stage.setAttribute('aria-busy','false');
        if(next){
          const old=compareFrames;compareFrames=next;
          compareLeftOverlay=next.before.overlay;compareRightOverlay=next.after.overlay;
          showCompareBoundary(snapshot);setComparePosition(comparePercent);
          next.before.overlay.setOpacity(1);next.after.overlay.setOpacity(1);old?.dispose();
        }else showCompareBoundary(snapshot);
        renderCompareSnapshot(snapshot,!!next);
        text('unified-compare-status',next?`${snapshot.plot.code} · ซ้าย: ก่อน ${snapshot.beforeLayer} · ขวา: หลัง ${snapshot.afterLayer}`:'ไม่มีภาพที่ใช้ได้ครบทั้งสองฝั่ง · ไม่ใช้ภาพจากเดือนอื่นแทน');
        requestAnimationFrame(()=>{compareMap.invalidateSize();setComparePosition(comparePercent);});
      },
      clear:clearCompareFrames,
      failed(snapshot){
        stage.setAttribute('aria-busy','false');showCompareBoundary(snapshot);renderCompareSnapshot(snapshot,false);
        text('unified-compare-status','โหลดภาพไม่สำเร็จ · ล้างภาพเก่าทั้งสองฝั่งแล้ว');
        const retry=document.createElement('button');retry.type='button';retry.textContent='ลองใหม่';retry.onclick=()=>updateCompareView();el('unified-compare-status').append(' ',retry);
      }
    });
    const hint=document.querySelector('.compare-hint');
    if(hint)hint.textContent='ลากปุ่ม ↔ หรือเลื่อนแถบเพื่อแบ่งภาพก่อนทางซ้าย / หลังทางขวา · ลากพื้นที่ภาพเพื่อเลื่อนแผนที่ · พื้นที่ว่างคือไม่มีพิกเซลภาพที่ใช้ได้';
  };

  updateCompareView=function unifiedCompare(){
    if(!activePlot)return;ensureCompareMaps();
    const last=activePlot.timeseries.length-1;
    const li=Math.max(0,Math.min(last,Number(el('comp-left-select').value)||0));
    const ri=Math.max(0,Math.min(last,Number(el('comp-right-select').value)||0));
    const before=activePlot.timeseries[li],after=activePlot.timeseries[ri],mode=el('comp-mode-select')?.value||'rgb';
    pair={before:before.month,after:after.month};
    const leftLayer=mode==='fcd'?'fcd':mode==='ndvi'?'gee_ndvi':'gee_rgb';
    const rightLayer=mode==='rgb_vs_ndvi'?'gee_ndvi':leftLayer;
    const a=U.asset(activePlot,before,leftLayer),b=U.asset(activePlot,after,rightLayer);
    const available=a.state==='AVAILABLE'&&b.state==='AVAILABLE';
    return compareController.request({plot:activePlot,before,after,mode,state:available?'AVAILABLE':'NO_DATA',url:available?'pair':null,
      beforeLayer:leftLayer==='fcd'?'FCD':leftLayer==='gee_ndvi'?'NDVI':'RGB',afterLayer:rightLayer==='fcd'?'FCD':rightLayer==='gee_ndvi'?'NDVI':'RGB',
      beforeUrl:a.url?`${a.url}?v=${DATA_VERSION}`:null,afterUrl:b.url?`${b.url}?v=${DATA_VERSION}`:null,bounds:imageBoundsForPlot(activePlot)});
  };

  toggleCompareBoundary=function unifiedCompareBoundary(show){
    if(!compareMap||!compareLeftBoundary)return;
    if(show&&!compareMap.hasLayer(compareLeftBoundary))compareLeftBoundary.addTo(compareMap);
    if(!show&&compareMap.hasLayer(compareLeftBoundary))compareMap.removeLayer(compareLeftBoundary);
  };

  initLeafletThailandMap=function unifiedGis(){
    leafletMap=L.map('thailand-map').setView([10.5,100.5],6);L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(leafletMap);
    thailandGeojsonLayer=L.geoJSON({type:'FeatureCollection',features:allPlotsData.map(p=>({type:'Feature',properties:{id:p.id,code:p.code,province:p.province,area_rai:p.area_rai},geometry:p.geometry}))},{
      style:{color:'#10b981',weight:2,fillOpacity:.04},
      onEachFeature:(f,l)=>{l.bindTooltip(`${escapeHtml(f.properties.code)} · ${escapeHtml(f.properties.province||'ไม่ระบุ')}`);l.on('click',()=>{selectPlot(f.properties.id);switchWorkspaceTab('detail');});}
    }).addTo(leafletMap);refreshMapStyles();resetMapZoom();
  };
  resetMapZoom=function unifiedReset(){const b=thailandGeojsonLayer?.getBounds();if(b?.isValid())leafletMap.fitBounds(b,{padding:[20,20]});};

  window.refreshMapStyles=function(){
    thailandGeojsonLayer?.eachLayer(l=>{
      const p=allPlotsData.find(x=>x.id===l.feature.properties.id);if(!p)return;
      const r=U.compare(p,pair.before,pair.after),color={REVIEW:'#fbbf24',NO_DECREASE:'#38bdf8',INSUFFICIENT:'#94a3b8',NOT_COMPARABLE:'#a78bfa',ATMOSPHERE_REVIEW:'#f97316',TIDE_WATER_REVIEW:'#22d3ee',VISUAL_REVIEW:'#e879f9'}[r.status]||'#64748b';
      l.setStyle({color,fillColor:color,weight:(activePlot?.registryId??activePlot?.id)===p.id?5:2,fillOpacity:.10,dashArray:r.delta===null?'5 5':null});
    });
    const h=document.querySelector('.map-hint');if(h)h.textContent=`${U.monthLabel(pair.before)} → ${U.monthLabel(pair.after)} · สีคือสถานะ screening/QA ไม่ใช่การยืนยันความเสียหาย`;
  };

  initTable=function unifiedTable(plots){
    const th=el('plots-data-table').querySelector('thead');th.innerHTML='<tr><th>รหัสแปลง</th><th>จังหวัด</th><th>พื้นที่</th><th>วิธี</th><th>ค่าก่อน → หลัง</th><th>Δ (ไร่)</th><th>QA</th><th>สถานะ</th><th></th></tr>';
    text('table-count-label',`แสดง ${plots.length} แปลง · ${U.monthLabel(pair.before)} → ${U.monthLabel(pair.after)}`);
    const body=el('table-body');body.innerHTML='';
    for(const p of plots){const r=U.compare(p,pair.before,pair.after),a=U.observation(p,pair.before),b=U.observation(p,pair.after),ga=U.green(p,a),gb=U.green(p,b),tr=document.createElement('tr');
      tr.innerHTML=`<td><strong>${escapeHtml(p.code)}</strong></td><td>${escapeHtml(p.province||'ไม่ระบุ')}</td><td>${fmt(p.area_rai)} ไร่</td><td>${escapeHtml(U.methodLabel(p))}</td><td>${ga===null?'—':fmt(ga)} → ${gb===null?'—':fmt(gb)}</td><td>${sign(r.delta)}</td><td>${escapeHtml(r.qa.label)} → ${escapeHtml(r.qb.label)}</td><td>${escapeHtml(statusLabel(r.status))}</td><td><button type="button">ดูแปลง</button></td>`;
      tr.querySelector('button').onclick=()=>{selectPlot(p.id);switchWorkspaceTab('detail');};body.append(tr);}
  };

  exportPlotsCSV=function unifiedCsv(){
    const rows=visiblePlots.length?visiblePlots:allPlotsData;
    const head=['รหัสแปลง','จังหวัด','พื้นที่ทะเบียน (ไร่)','ช่วงก่อน','ช่วงหลัง','วิธี','QA ก่อน','QA หลัง','ค่าพื้นที่กลุ่มพืชก่อน (ไร่)','ค่าพื้นที่กลุ่มพืชหลัง (ไร่)','Δ (ไร่)','NDVI ก่อน','NDVI หลัง','สถานะ','เหตุผล'];
    const data=rows.map(p=>{const r=U.compare(p,pair.before,pair.after),a=U.observation(p,pair.before),b=U.observation(p,pair.after);return [p.code,p.province,p.area_rai,U.monthLabel(pair.before),U.monthLabel(pair.after),U.methodLabel(p),r.qa.label,r.qb.label,U.green(p,a),U.green(p,b),r.delta,U.ndvi(p,a),U.ndvi(p,b),statusLabel(r.status),r.reason];});
    const csv='\uFEFF'+[head,...data].map(row=>row.map(U.csvCell).join(',')).join('\r\n'),url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');
    a.href=url;a.download=`mangrove_210_${pair.before}_to_${pair.after}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };

  const oldFilter=filterPlots;
  filterPlots=function unifiedFilter(province,query){
    let f=allPlotsData;if(province!=='ALL')f=f.filter(p=>p.province===province);if(query)f=f.filter(p=>[p.code,p.fullName,p.province,p.registryCode].join(' ').toLowerCase().includes(query));
    renderSidebarList(f);visiblePlots=f;initTable(f);
  };

  window.addEventListener('DOMContentLoaded',()=>{setTimeout(()=>{const allBtn=el('wtab-allplots');if(allBtn)allBtn.remove();const allPanel=el('panel-allplots');if(allPanel)allPanel.remove();},0);});
})();
