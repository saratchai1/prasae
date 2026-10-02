/* PDD22 production adapter: one QA policy and explicit observation-frame ownership. */
(() => {
  'use strict';
  const M = Pdd22Observations;
  const VERSION = '20260930-integrity-1';
  const DATA_VERSION = '20260826-1405'; // Frozen source data, not a new observation run.
  let visiblePlots = [], pair = {before:'',after:''}, detailController = null;
  const el = id => document.getElementById(id);
  const text = (id,value) => { if (el(id)) el(id).textContent = value; };
  const fmt = value => M.number(value) === null ? '—' : Number(value).toLocaleString('th-TH',{maximumFractionDigits:2});
  const monthLabel = month => /^\d{4}-\d{2}$/.test(month || '')
    ? `${thaiMonths[Number(month.slice(5))]} ${Number(month.slice(0,4)) + 543}` : '—';
  const title = plot => `${plot.code} · ${plot.province}`;
  const sign = value => value === null ? '—' : `${value > 0 ? '+' : ''}${fmt(value)}`;
  const states = {REVIEW:'ควรตรวจการเปลี่ยนแปลง',INSUFFICIENT:'ข้อมูลไม่พอ',NOT_COMPARABLE:'ยังเปรียบเทียบไม่ได้',NO_DECREASE:'ไม่พบการลดลงในคู่นี้'};
  const qaThai = value => ({GOOD:'ดี',PARTIAL:'บางส่วน',LOW_QA:'คุณภาพต่ำ',NO_DATA:'ไม่มีข้อมูล'}[value] || String(value || '—'));
  const filterThai = value => ({ALL:'ทั้งหมด',REVIEW:'ควรตรวจการเปลี่ยนแปลง',INSUFFICIENT:'ข้อมูลไม่พอ',NOT_COMPARABLE:'ยังเปรียบเทียบไม่ได้',NO_DECREASE:'ไม่พบการลดลงในคู่นี้'}[value] || String(value || 'ทั้งหมด'));
  const safeFilePart = value => String(value || '').replace(/[\\/:*?"<>|]/g,'-').replace(/\s+/g,'_');
  const setSub = (id,value) => { const n=el(id)?.parentElement?.querySelector('.kpi-sub'); if(n)n.textContent=value; };

  function csvRows(source) {
    // RFC 4180 quoting, including commas/newlines in quoted fields.
    const rows=[]; let row=[],field='',quoted=false;
    const input=source.replace(/^\uFEFF/,'');
    for(let i=0;i<input.length;i++) {
      const c=input[i];
      if(c==='"') { if(quoted&&input[i+1]==='"'){field+='"';i++;}else quoted=!quoted; }
      else if(c===','&&!quoted){row.push(field);field='';}
      else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&input[i+1]==='\n')i++;row.push(field);if(row.some(Boolean))rows.push(row);row=[];field='';}
      else field+=c;
    }
    if(quoted) throw new Error('Malformed coverage CSV');
    row.push(field);if(row.some(Boolean))rows.push(row);
    const headers=rows.shift()||[];
    return rows.map(r=>Object.fromEntries(headers.map((h,i)=>[h,r[i]??''])));
  }
  loadData = async function loadPdd22Data() {
    const paths=['data/pdd22/plots_catalog.json','data/pdd22_satellite/coverage_report.csv','data/pdd22_v3/plots_result.json'];
    const responses=await Promise.all(paths.map(async path=>{
      const r=await fetch(`${path}?v=${DATA_VERSION}`,{cache:'no-store'});
      if(!r.ok)throw new Error(`${path}: HTTP ${r.status}`);return r;
    }));
    const [catalog,coverageSource,fcd]=await Promise.all([responses[0].json(),responses[1].text(),responses[2].json()]);
    if(!Array.isArray(catalog)||!catalog.length||!Array.isArray(fcd))throw new Error('Invalid PDD22 catalog');
    const rows=new Map(csvRows(coverageSource).map(r=>[`${r.plot_code}|${r.month}`,r]));
    const fcdByCode=new Map(fcd.map(p=>[p.code,p]));
    const seen=new Set();
    plotsCatalog=catalog.map((p,i)=>{
      if(!p.code||seen.has(p.code)||M.number(p.area_rai)===null||Number(p.area_rai)<=0||!p.geometry)throw new Error('Invalid/duplicate PDD22 plot');
      seen.add(p.code);return {...p,id:Number(p.id)||i+1,name:p.code,area_rai:Number(p.area_rai)};
    });
    allPlotsData=plotsCatalog.map(p=>{
      const fcd_by_month=Object.fromEntries((fcdByCode.get(p.code)?.observations||[]).map(o=>[o.month,{...o,
        ...Object.fromEntries(['green_rai','yellow_rai','red_rai','green_observed_rai','yellow_observed_rai','red_observed_rai','coverage_pct'].map(k=>[k,M.number(o[k])]))}]));
      const timeseries=MILESTONE_MONTHS.map(month=>{
        const r=rows.get(`${p.code}|${month}`)||{};
        return {...parseMonthKey(month),mean_ndvi_inside:M.number(r.mean_ndvi),median_ndvi_inside:M.number(r.median_ndvi),
          clear_pixel_pct:M.number(r.coverage_pct),qa:r.qa||'NO_DATA',status:r.qa||'NO_DATA',analysis_mode:r.analysis_mode||'no_data',
          scenes_used:M.number(r.scene_count)||0,source:'PDD22 cleaned Sentinel-2 L2A',scene_ids:[],
          vegetation_coverage_proxy_pct:M.goodFcd(fcd_by_month[month]) ? fcd_by_month[month].green_rai/p.area_rai*100 : null};
      });
      return {...p,timeseries,fcd_by_month,initial_ndvi:null,current_ndvi:null,gain_ndvi:null,growth_pct:null,current_vegetation_proxy_pct:null};
    });
    visiblePlots=allPlotsData;pair=M.defaultPair(allPlotsData);
    currentMonthIndex=Math.max(0,MILESTONE_MONTHS.indexOf(pair.after));
    verifiedDatasetLoaded=true;
  };

  updateStaticCopy = function initializePdd22Workspace() {
    document.title='PDD22 · ภาพรวมและการตรวจแปลง';
    document.querySelector('.brand-title').textContent=`ติดตามป่าชายเลน PDD22 · ${allPlotsData.length} แปลง`;
    document.querySelector('.brand-subtitle').textContent='ภาพตามช่วงเวลาจริง · แยกคุณภาพข้อมูลจากสัญญาณเปลี่ยนแปลง';
    const pills=document.querySelectorAll('.header-meta .meta-pill');
    if(pills[0])pills[0].textContent=`${allPlotsData.length} แปลง · ${fmt(M.summarize(allPlotsData,pair.before,pair.after).totalArea)} ไร่`;
    if(pills[1])pills[1].textContent='ขอบเขตเข้าร่วม PDD เท่านั้น';
    if(pills[2])pills[2].textContent=`ชุดข้อมูลถึง ${monthLabel(MILESTONE_MONTHS.at(-1))}`;
    const slider=el('month-slider');slider.min='0';slider.max=String(MILESTONE_MONTHS.length-1);slider.value=String(currentMonthIndex);
    slider.setAttribute('aria-label','เลือกช่วงข้อมูลดาวเทียม');
    document.querySelector('.slider-ticks').textContent='เลือกเฉพาะเดือนในชุดข้อมูล · เดือนที่ไม่มีข้อมูลแสดงตามจริง';
    text('kpi-total-area',`${fmt(M.summarize(allPlotsData,pair.before,pair.after).totalArea)} ไร่`);
    el('kpi-plot-canopy-pct').parentElement.querySelector('.kpi-label').textContent='FCD เขียว · ช่วงที่แสดง';
    el('kpi-plot-ndvi-gain').classList.remove('text-success');
    document.querySelector('.chart-box-subtitle').textContent='แสดงค่าที่ผ่าน QA GOOD เท่านั้น · เว้นช่องว่างเมื่อข้อมูลไม่พอ · ไม่สร้างค่าทดแทน';
    document.querySelector('.chart-badge-tag').textContent='ค่าจาก pipeline ต้นฉบับ';
    const bands=document.querySelector('.band-btn-group');
    const basemap=bands.querySelector('[data-layer="esri"]');if(basemap)basemap.textContent='ภาพพื้นหลัง (ไม่อิงเดือน)';
    if(!bands.querySelector('[data-layer="fcd"]')){
      const b=document.createElement('button');b.className='band-btn';b.dataset.layer='fcd';b.textContent='FCD เขียว / เหลือง / แดง';b.onclick=()=>setPlotMapLayer('fcd');bands.append(b);
    }
    if(!el('comp-mode-select').querySelector('[value="fcd"]')){const o=new Option('FCD vs FCD','fcd');el('comp-mode-select').add(o);}
    const status=document.createElement('div');status.id='observation-status';status.className='observation-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    document.querySelector('.viewer-toolbar').after(status);
    const panel=document.createElement('div');panel.id='fcd-summary-panel';panel.className='fcd-summary-panel';
    panel.innerHTML='<div><span>เขียว</span><strong id="fcd-green-value">—</strong></div><div><span>เหลือง</span><strong id="fcd-yellow-value">—</strong></div><div><span>แดง</span><strong id="fcd-red-value">—</strong></div><div><span>QA / Coverage</span><strong id="fcd-qa-value">—</strong></div><p id="fcd-note"></p>';
    status.after(panel);
    // Put plot-only KPIs inside the plot tab; the landing page is portfolio-only.
    el('panel-detail').prepend(document.querySelector('.national-kpi-grid'));
    const picker=el('plot-picker-toggle');
    if(picker)picker.onclick=()=>{const sidebar=el('plot-sidebar');sidebar.classList.toggle('mobile-open');picker.setAttribute('aria-expanded',String(sidebar.classList.contains('mobile-open')));};
    injectOverview();
    switchWorkspaceTab('overview');
  };

  function injectOverview() {
    const button=document.createElement('button');button.className='w-tab-btn';button.id='wtab-overview';button.textContent='ภาพรวม / เลือกแปลงตรวจ';button.onclick=()=>switchWorkspaceTab('overview');
    document.querySelector('.workspace-tabs').prepend(button);
    const panel=document.createElement('section');panel.id='panel-overview';panel.className='tab-content-panel';
    panel.innerHTML=`<div class="overview-heading"><div><p class="eyebrow">PDD22 · OBSERVATION REVIEW</p><h2>เริ่มจากแปลงที่ควรเปิดตรวจต่อ</h2><p>แยกสัญญาณเปลี่ยนแปลงออกจากข้อมูลไม่พอ โดยไม่สรุปว่าป่าเสียหายจากสีเพียงอย่างเดียว</p></div><div class="overview-actions"><button type="button" id="overview-export-csv" class="overview-export-btn">ส่งออก CSV ก่อน–หลัง</button><small>ตามช่วงเวลาและตัวกรองที่เลือก</small></div></div>
      <div class="overview-dates"><label>ช่วงก่อน<select id="overview-before"></select></label><label>ช่วงหลัง<select id="overview-after"></select></label><label>รายการที่ต้องการดู<select id="overview-filter"><option value="ALL">ทั้งหมด</option><option value="REVIEW">ควรตรวจการเปลี่ยนแปลง</option><option value="INSUFFICIENT">ข้อมูลไม่พอ</option><option value="NOT_COMPARABLE">ยังเปรียบเทียบไม่ได้</option><option value="NO_DECREASE">ไม่พบการลดลงในคู่นี้</option></select></label></div>
      <div class="overview-cards" id="overview-cards"></div><p class="overview-context" id="overview-context" role="status"></p>
      <div class="table-container"><table class="plots-table review-table"><thead><tr><th>แปลง / จังหวัด</th><th>สถานะ / เหตุผล</th><th>Δ เขียว (ไร่)</th><th>QA ก่อน → หลัง</th><th>ตรวจประกอบ</th></tr></thead><tbody id="overview-rows"></tbody></table></div>
      <p class="screening-note">ผล FCD เป็น screening ไม่ใช่คาร์บอนเครดิตหรือคำยืนยันความเสียหาย · เลือกเดือนเดียวกันต่างปีและ QA GOOD ทั้งสองช่วงเพื่อลดความต่างฤดูกาล แต่ยังไม่ได้จับคู่น้ำขึ้นลงหรือยืนยันภาคสนาม · ค่า Δ ไม่ใช่การทดสอบนัยสำคัญ</p>`;
    el('panel-detail').before(panel);
    for(const id of ['overview-before','overview-after']){
      M.months(allPlotsData).forEach(m=>el(id).add(new Option(monthLabel(m),m)));
      el(id).value=id.endsWith('before')?pair.before:pair.after;
      el(id).onchange=()=>{pair={before:el('overview-before').value,after:el('overview-after').value};renderOverview();initTable(visiblePlots);refreshMapStyles();if(activePlot)updatePairKpi(activePlot);};
    }
    el('overview-filter').onchange=renderOverview;
    el('overview-export-csv').onclick=exportOverviewComparisonCSV;
    renderOverview();
  }

  function overviewRows(summary=M.summarize(visiblePlots,pair.before,pair.after)) {
    const filter=el('overview-filter')?.value || 'ALL';
    return summary.rows.filter(r=>filter==='ALL'||r.status===filter).sort((a,b)=>{
      const order={REVIEW:0,INSUFFICIENT:1,NOT_COMPARABLE:2,NO_DECREASE:3};
      return order[a.status]-order[b.status] || (a.delta??0)-(b.delta??0) || a.plot.code.localeCompare(b.plot.code);
    });
  }

  function absoluteFcdImageUrl(plot,month) {
    const item=plot.timeseries?.find(x=>x.month===month);
    if(!item)return '';
    const spec=M.asset(plot,item,'fcd');
    if(spec.state!=='AVAILABLE'||!spec.url)return '';
    try{return new URL(`${spec.url}?v=${DATA_VERSION}`,document.baseURI).href;}
    catch{return spec.url;}
  }

  function exportOverviewComparisonCSV() {
    const filter=el('overview-filter')?.value || 'ALL';
    const rows=overviewRows();
    if(!rows.length)return;

    const header=[
      'รหัสแปลง','จังหวัด','พื้นที่ PDD (ไร่)',
      'ช่วงก่อน','ช่วงหลัง','เปรียบเทียบได้',
      'คุณภาพข้อมูลก่อน','คุณภาพข้อมูลหลัง','ความครอบคลุมก่อน (%)','ความครอบคลุมหลัง (%)',
      'พื้นที่สีเขียวก่อน (ไร่)','พื้นที่สีเขียวหลัง (ไร่)','การเปลี่ยนแปลงสีเขียว (ไร่)',
      'พื้นที่สีเหลืองก่อน (ไร่)','พื้นที่สีเหลืองหลัง (ไร่)','การเปลี่ยนแปลงสีเหลือง (ไร่)',
      'พื้นที่สีแดงก่อน (ไร่)','พื้นที่สีแดงหลัง (ไร่)','การเปลี่ยนแปลงสีแดง (ไร่)',
      'สถานะ','เหตุผล','ลิงก์ภาพ FCD ก่อน','ลิงก์ภาพ FCD หลัง','วิธีการ'
    ];
    const delta=(a,b,key)=>M.goodFcd(a)&&M.goodFcd(b)
      ? Math.round((M.number(b[key])-M.number(a[key]))*100)/100 : null;
    const value=(obs,key)=>M.goodFcd(obs)?M.number(obs[key]):null;
    const records=rows.map(r=>{
      const plot=r.plot,a=plot.fcd_by_month?.[pair.before],b=plot.fcd_by_month?.[pair.after];
      return [
        plot.code,plot.province,plot.area_rai,
        monthLabel(pair.before),monthLabel(pair.after),r.delta!==null?'ได้':'ไม่ได้',
        qaThai(r.beforeQa),qaThai(r.afterQa),M.coverage(a),M.coverage(b),
        value(a,'green_rai'),value(b,'green_rai'),delta(a,b,'green_rai'),
        value(a,'yellow_rai'),value(b,'yellow_rai'),delta(a,b,'yellow_rai'),
        value(a,'red_rai'),value(b,'red_rai'),delta(a,b,'red_rai'),
        states[r.status] || r.status,r.reason,absoluteFcdImageUrl(plot,pair.before),absoluteFcdImageUrl(plot,pair.after),
        'การคัดกรอง PDD22 ด้วย FCD V3; พื้นที่จำแนกทั้งแปลงและค่าการเปลี่ยนแปลงคำนวณเฉพาะเมื่อทั้งสองช่วงผ่านเกณฑ์คุณภาพข้อมูลระดับดี; ไม่ใช่การคำนวณคาร์บอนเครดิต'
      ];
    });
    const csv='\uFEFF'+[header,...records].map(row=>row.map(M.csvCell).join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;
    a.download=`PDD22_เปรียบเทียบ_${safeFilePart(monthLabel(pair.before))}_ถึง_${safeFilePart(monthLabel(pair.after))}_${safeFilePart(filterThai(filter))}.csv`;
    a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  function renderOverview() {
    if(!el('overview-rows'))return;
    const summary=M.summarize(visiblePlots,pair.before,pair.after);
    const latest=M.months(allPlotsData).at(-1);
    const latestCount=visiblePlots.filter(p=>M.goodFcd(p.fcd_by_month[latest])).length;
    el('overview-cards').innerHTML=[
      ['แปลงในตัวกรอง',`${visiblePlots.length} แปลง`,`${fmt(summary.totalArea)} ไร่`],
      ['ควรตรวจการเปลี่ยนแปลง',`${summary.reviewCount} แปลง`,'พบพื้นที่จัดกลุ่มเขียวลดลงในคู่ที่เทียบได้'],
      ['ข้อมูลไม่พอ',`${summary.insufficientCount} แปลง`,'ไม่ใช้แทนคำว่าป่าดีหรือป่าเสียหาย'],
      [`QA GOOD รอบ ${monthLabel(latest)}`,`${latestCount} / ${visiblePlots.length} แปลง`,'เป็นรอบล่าสุดในชุดข้อมูล ไม่ใช่ค่าของเดือนที่เลือก']
    ].map(([label,value,note])=>`<article><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`).join('');
    text('overview-context',`${monthLabel(pair.before)} → ${monthLabel(pair.after)} · เทียบได้ ${summary.matchedCount}/${visiblePlots.length} แปลง · ${fmt(summary.matchedArea)} ไร่ (${fmt(summary.matchedAreaPct)}%) · Δ เขียว ${sign(summary.delta)} ไร่ — คำนวณทั้งสองฝั่งจากแปลงชุดเดียวกันเท่านั้น`);
    const rows=overviewRows(summary);
    const exportButton=el('overview-export-csv');
    if(exportButton){
      exportButton.disabled=rows.length===0;
      exportButton.textContent=`ส่งออก CSV ก่อน–หลัง · ${rows.length} แปลง`;
      exportButton.title=rows.length
        ? `ส่งออก ${monthLabel(pair.before)} → ${monthLabel(pair.after)} ตามตัวกรองที่เลือก`
        : 'ไม่มีแปลงในตัวกรองสำหรับส่งออก';
    }
    const tbody=el('overview-rows');tbody.innerHTML='';
    for(const r of rows){const tr=document.createElement('tr');tr.innerHTML=`<td><strong>${escapeHtml(r.plot.code)}</strong><small>${escapeHtml(r.plot.province)} · ${fmt(r.plot.area_rai)} ไร่</small></td><td><span class="review-status ${r.status.toLowerCase()}">${states[r.status]}</span><small>${r.reason}</small></td><td>${sign(r.delta)}</td><td>${r.beforeQa} → ${r.afterQa}</td><td><button type="button">เปิดภาพก่อน–หลัง</button></td>`;
      tr.querySelector('button').onclick=()=>openComparison(r.plot.id);tbody.append(tr);}
    if(!rows.length)tbody.innerHTML='<tr><td colspan="5">ไม่พบแปลงตามตัวกรองนี้</td></tr>';
  }
  function openComparison(id){
    selectPlot(id);const index=MILESTONE_MONTHS.indexOf(pair.after);if(index>=0)setMonthIndex(index);
    el('comp-left-select').value=String(MILESTONE_MONTHS.indexOf(pair.before));el('comp-right-select').value=String(index);
    el('comp-mode-select').value='fcd';switchWorkspaceTab('compare');
  }

  renderSidebarList = function renderPdd22Sidebar(plots) {
    visiblePlots=plots;const container=el('plot-list-container');container.innerHTML='';
    text('sidebar-count-display',`แสดง ${plots.length} จาก ${allPlotsData.length} แปลง`);
    plots.forEach(p=>{const b=document.createElement('button');b.type='button';b.className=`plot-card-item ${activePlot?.id===p.id?'active':''}`;b.id=`sidebar-card-${p.id}`;
      b.innerHTML=`<span class="p-card-header"><strong>${escapeHtml(p.code)}</strong><span class="p-prov-tag">${escapeHtml(p.province)}</span></span><span class="p-card-body">พื้นที่ ${fmt(p.area_rai)} ไร่</span>`;
      b.onclick=()=>{selectPlot(p.id);switchWorkspaceTab('detail');el('plot-sidebar')?.classList.remove('mobile-open');el('plot-picker-toggle')?.setAttribute('aria-expanded','false');};container.append(b);});
    renderOverview();initTable(plots);refreshMapStyles();
  };
  function refreshMapStyles(){
    thailandGeojsonLayer?.eachLayer(layer=>{
      const plot=allPlotsData.find(p=>p.id===layer.feature.properties.id);if(!plot)return;
      const status=M.compare(plot,pair.before,pair.after).status;
      const color={REVIEW:'#fbbf24',INSUFFICIENT:'#94a3b8',NOT_COMPARABLE:'#a78bfa',NO_DECREASE:'#38bdf8'}[status];
      layer.setStyle({color,fillColor:color,weight:activePlot?.id===plot.id?5:2,fillOpacity:.12,dashArray:status==='INSUFFICIENT'?'5 5':null});
      if(activePlot?.id===plot.id)layer.bringToFront();
    });
    const hint=document.querySelector('.map-hint');if(hint)hint.textContent=`${monthLabel(pair.before)} → ${monthLabel(pair.after)} · เหลือง: ควรตรวจ · เทาประ: ข้อมูลไม่พอ · ม่วง: เทียบไม่ได้ · ฟ้า: ไม่พบการลดลงในคู่นี้`;
  }
  initLeafletThailandMap = function initializePdd22Map(){
    leafletMap=L.map('thailand-map').setView([9.2,100],6);
    L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(leafletMap);
    thailandGeojsonLayer=L.geoJSON({type:'FeatureCollection',features:allPlotsData.map(p=>({type:'Feature',properties:{id:p.id},geometry:p.geometry}))},{
      onEachFeature(feature,layer){const p=allPlotsData.find(p=>p.id===feature.properties.id);
        layer.bindTooltip(escapeHtml(title(p)));layer.on('click',()=>{selectPlot(p.id);});}
    }).addTo(leafletMap);refreshMapStyles();resetMapZoom();
  };
  resetMapZoom = function fitPdd22(){const bounds=thailandGeojsonLayer?.getBounds();if(bounds?.isValid())leafletMap.fitBounds(bounds,{padding:[20,20]});};

  function clearDetail(){
    if(currentSentinelOverlay&&plotSatelliteMap?.hasLayer(currentSentinelOverlay))plotSatelliteMap.removeLayer(currentSentinelOverlay);
    currentSentinelOverlay=null;
  }
  function renderSnapshot(s,error=false){
    const {plot,item,layer}=s, fcd=plot.fcd_by_month[item.month];
    text('hud-month-label',layer==='esri'?'ภาพพื้นหลัง · ไม่อิงเดือน':monthLabel(item.month));
    text('hud-plot-label',title(plot));
    text('hud-coords-label',`${title(plot)} · ${fmt(plot.area_rai)} ไร่`);
    text('hud-in-ndvi',error||M.ndvi(item)===null?'—':M.ndvi(item).toFixed(3));
    const equivalent=!error&&M.goodFcd(fcd);
    text('hud-in-cover',equivalent?`${fmt(fcd.green_rai/plot.area_rai*100)}%`:'—');
    text('kpi-plot-canopy-pct',equivalent?`${fmt(fcd.green_rai/plot.area_rai*100)}%`:'—');
    setSub('kpi-plot-canopy-pct',`${monthLabel(item.month)} · ${error?'ภาพโหลดไม่สำเร็จ':M.qa(fcd)}`);
    ['green','yellow','red'].forEach(k=>{
      const value=error||!fcd||M.qa(fcd)==='NO_DATA'?null:equivalent?fcd[`${k}_rai`]:fcd[`${k}_observed_rai`];
      text(`fcd-${k}-value`,value===null?'—':`${fmt(value)} ไร่`);
    });
    text('fcd-qa-value',`${fcd?M.qa(fcd):'ไม่มี FCD'} · ${fmt(M.coverage(fcd))}%`);
    const latest=M.latestGood(plot);
    text('fcd-note',`${monthLabel(item.month)}: ${equivalent?'equivalent class area ตามโมเดล QA GOOD; water/bare แยกต่างหาก':'แสดงเฉพาะพื้นที่สังเกตได้เมื่อมีข้อมูล; ไม่ขยายเต็มแปลง'} · ผล FCD ล่าสุดที่ผ่านเกณฑ์: ${latest?monthLabel(latest.month):'ไม่มี'} (ไม่ได้ใช้แทนค่าของเดือนที่เลือก)`);
    const tag=document.querySelector('.stage-hud.top-right .hud-tag');
    if(tag)tag.textContent=layer==='esri'?'Esri World Imagery':layer==='fcd'?'FCD V3 screening':'Sentinel-2 · '+M.qa(item);
    const sub=document.querySelector('.stage-hud.top-right .hud-sub');
    if(sub)sub.textContent=layer==='esri'?'ไม่ใช่ภาพของเดือนที่เลือก':`${monthLabel(item.month)} · coverage ${fmt(M.coverage(layer==='fcd'?fcd:item))}%`;
    if(!error)text('observation-status',layer==='esri'?`ค่าด้านล่างอ้างอิง ${monthLabel(item.month)} แต่ภาพพื้นหลังไม่อิงเดือนนี้`:s.state==='AVAILABLE'?`${title(plot)} · ${monthLabel(item.month)} · ภาพและค่าตรงช่วงเดียวกัน · ${M.qa(layer==='fcd'?fcd:item)} · coverage ${fmt(M.coverage(layer==='fcd'?fcd:item))}%`:s.state==='NO_FCD'?`${monthLabel(item.month)} ไม่มีผล FCD — ไม่ใช้เดือนอื่นแทน`:`${monthLabel(item.month)} ข้อมูลไม่พอ — ไม่แสดงภาพหรือค่าแทน`);
    el('observation-status').dataset.state=error?'ERROR':s.state;
    updatePairKpi(plot);
  }
  function updatePairKpi(plot){
    const a=plot.timeseries.find(i=>i.month===pair.before),b=plot.timeseries.find(i=>i.month===pair.after);
    const comparable=M.compare(plot,pair.before,pair.after).status!=='NOT_COMPARABLE'&&pair.before<pair.after&&pair.before.slice(5)===pair.after.slice(5);
    const delta=comparable&&M.ndvi(a)!==null&&M.ndvi(b)!==null?M.ndvi(b)-M.ndvi(a):null;
    text('kpi-plot-ndvi-gain',delta===null?'—':`${delta>=0?'+':''}${delta.toFixed(3)}`);
    setSub('kpi-plot-ndvi-gain',`${monthLabel(pair.before)} → ${monthLabel(pair.after)} · QA GOOD ทั้งสองช่วงเท่านั้น`);
  }
  function controller(){
    if(detailController)return detailController;
    detailController=M.createFrameController({
      load:(s,current)=>M.loadLeafletFrame(L,plotSatelliteMap,s,current,{className:'sentinel-overlay'}),
      loading(s,displayed){
        if(displayed&&currentSentinelOverlay)renderSnapshot(displayed);
        else {['hud-in-ndvi','hud-in-cover','kpi-plot-canopy-pct','fcd-green-value','fcd-yellow-value','fcd-red-value','fcd-qa-value'].forEach(id=>text(id,'—'));text('hud-month-label','กำลังโหลดภาพ');text('hud-plot-label',title(s.plot));setSub('kpi-plot-canopy-pct',`${monthLabel(s.item.month)} · กำลังโหลด`);text('fcd-note','รอภาพและข้อมูลของช่วงที่เลือก');}
        text('observation-status',`กำลังโหลด ${title(s.plot)} · ${monthLabel(s.item.month)}${displayed&&currentSentinelOverlay?` — ภาพและค่าที่ยังแสดงเป็น ${monthLabel(displayed.item.month)}`:''}`);el('observation-status').dataset.state='LOADING';
      },
      commit(s,frame){if(frame){const old=currentSentinelOverlay;currentSentinelOverlay=frame.overlay;frame.overlay.setOpacity(.94);if(old&&plotSatelliteMap.hasLayer(old))plotSatelliteMap.removeLayer(old);plotBoundaryLayer?.bringToFront();}renderSnapshot(s);},
      clear:clearDetail,
      failed(s){renderSnapshot(s,true);text('observation-status',`${title(s.plot)} · ${monthLabel(s.item.month)} โหลดภาพไม่สำเร็จ — ล้างภาพเก่าแล้ว`);const b=document.createElement('button');b.type='button';b.textContent='ลองใหม่';b.onclick=()=>updateGeeOverlay();el('observation-status').append(' ',b);}
    });return detailController;
  }
  updateGeeOverlay = function requestPdd22Frame(){
    if(!activePlot||!plotSatelliteMap)return;
    const item=activePlot.timeseries[currentMonthIndex];if(!item)return;
    const spec=M.asset(activePlot,item,currentPlotLayerKey);
    const snapshot={...spec,url:spec.url?`${spec.url}?v=${DATA_VERSION}`:null,plot:activePlot,item,layer:currentPlotLayerKey,bounds:imageBoundsForPlot(activePlot)};
    return controller().request(snapshot);
  };
  setPlotMapLayer = function selectPdd22Layer(layer){
    currentPlotLayerKey=layer;
    document.querySelectorAll('.band-btn-group .band-btn').forEach(b=>b.classList.toggle('active',b.dataset.layer===layer));
    updateGeeOverlay();
  };
  setMonthIndex = function selectPdd22Month(value){
    if(!activePlot)return;
    currentMonthIndex=Math.max(0,Math.min(activePlot.timeseries.length-1,Math.trunc(Number(value)||0)));
    const item=activePlot.timeseries[currentMonthIndex];text('playback-date-display',monthLabel(item.month));el('month-slider').value=String(currentMonthIndex);
    if(plotNdviChart){plotNdviChart.setActiveElements([{datasetIndex:0,index:currentMonthIndex}]);plotNdviChart.update('none');}
    return updateGeeOverlay();
  };
  const baseSelectPlot=selectPlot;
  selectPlot = function selectPdd22Plot(id){
    if(!allPlotsData.some(p=>p.id===Number(id)))return;
    detailController?.invalidate();clearDetail();baseSelectPlot(id);refreshMapStyles();updatePairKpi(activePlot);
  };
  initCompareSelectors = function initializePdd22Compare(plot){
    ['comp-left-select','comp-right-select'].forEach(id=>{const select=el(id);select.innerHTML='';plot.timeseries.forEach((o,i)=>select.add(new Option(`${monthLabel(o.month)} · ${M.qa(o)}`,String(i))));});
    el('comp-left-select').value=String(Math.max(0,MILESTONE_MONTHS.indexOf(pair.before)));
    el('comp-right-select').value=String(Math.max(0,MILESTONE_MONTHS.indexOf(pair.after)));
  };
  initTable = function renderPdd22Table(plots){
    if(!el('table-body'))return;
    text('table-count-label',`${plots.length} แปลงในตัวกรอง · ${monthLabel(pair.before)} → ${monthLabel(pair.after)}`);
    el('plots-data-table').querySelector('thead').innerHTML='<tr><th>รหัสแปลง</th><th>จังหวัด</th><th>พื้นที่ (ไร่)</th><th>เขียวก่อน (ไร่)</th><th>เขียวหลัง (ไร่)</th><th>Δ เขียว (ไร่)</th><th>QA ก่อน → หลัง</th><th>สถานะ</th><th>การกระทำ</th></tr>';
    const tbody=el('table-body');tbody.innerHTML='';
    plots.forEach(p=>{const r=M.compare(p,pair.before,pair.after),a=p.fcd_by_month[pair.before],b=p.fcd_by_month[pair.after],tr=document.createElement('tr');
      tr.innerHTML=`<td>${escapeHtml(p.code)}</td><td>${escapeHtml(p.province)}</td><td>${fmt(p.area_rai)}</td><td>${M.goodFcd(a)?fmt(a.green_rai):'—'}</td><td>${M.goodFcd(b)?fmt(b.green_rai):'—'}</td><td>${sign(r.delta)}</td><td>${r.beforeQa} → ${r.afterQa}</td><td>${states[r.status]}</td><td><button type="button">ตรวจภาพ</button></td>`;tr.querySelector('button').onclick=()=>openComparison(p.id);tbody.append(tr);});
  };
  exportPlotsCSV = function exportPdd22VisibleRows(){
    const header=['รหัสแปลง','จังหวัด','พื้นที่ PDD (ไร่)','ช่วงก่อน','ช่วงหลัง','คุณภาพข้อมูลก่อน','คุณภาพข้อมูลหลัง','ความครอบคลุมก่อน (%)','ความครอบคลุมหลัง (%)','พื้นที่สีเขียวก่อน (ไร่)','พื้นที่สีเขียวหลัง (ไร่)','การเปลี่ยนแปลงสีเขียว (ไร่)','สถานะ','เหตุผล','วิธีการ'];
    const rows=visiblePlots.map(p=>{const r=M.compare(p,pair.before,pair.after),a=p.fcd_by_month[pair.before],b=p.fcd_by_month[pair.after];return [p.code,p.province,p.area_rai,monthLabel(pair.before),monthLabel(pair.after),qaThai(r.beforeQa),qaThai(r.afterQa),M.coverage(a),M.coverage(b),M.goodFcd(a)?a.green_rai:null,M.goodFcd(b)?b.green_rai:null,r.delta,states[r.status] || r.status,r.reason,'การคัดกรอง PDD22 ด้วย FCD V3; ไม่ใช่การคำนวณคาร์บอนเครดิต'];});
    const csv='\uFEFF'+[header,...rows].map(r=>r.map(M.csvCell).join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`PDD22_ตาราง_FCD_${safeFilePart(monthLabel(pair.before))}_ถึง_${safeFilePart(monthLabel(pair.after))}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  window.Pdd22Ui={monthLabel,format:fmt,getPair:()=>({...pair}),getVisiblePlots:()=>visiblePlots.slice(),exportOverviewComparisonCSV,version:VERSION};
})();
