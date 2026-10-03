/* R2 release: exact-observation spectral visualization; analytical data is never written. */
(() => {
  'use strict';
  const S=Pdd22Spectral, M=Pdd22Observations;
  const DATA_VERSION='20260826-2125-10band';
  const cache=S.createCache(32*1024*1024), manifests=new Map();
  const desired={preset:'truecolor',channels:{r:'B04',g:'B03',b:'B02'},brightness:1,contrast:1,gamma:1,opacity:.9};
  let map=null,boundary=null,frame=null,displayed=null,queued=false;
  const el=id=>document.getElementById(id);
  const visible=()=>el('panel-spectral')?.classList.contains('active');
  const text=(id,value)=>{if(el(id))el(id).textContent=value;};
  const label=s=>`${s.code} · ${s.month} · ${S.PRESETS[s.preset]?.label||'Custom RGB'}`;
  const options=selected=>S.BANDS.map(b=>`<option value="${b}"${b===selected?' selected':''}>${b}</option>`).join('');
  const messages={NO_DATA:'ไม่มีชุดภาพที่ใช้ได้สำหรับเดือนนี้ — ไม่ใช้เดือนอื่นแทน',INVALID_PACKAGE:'ข้อมูลชุดภาพไม่ตรงกับแปลงที่เลือก',MISSING_BAND:'ไม่มี band ที่จำเป็นสำหรับชุดแสดงผลนี้',INVALID_BAND_PATH:'ชื่อไฟล์ band ไม่ตรงกับเดือนที่เลือก',INVALID_DIMENSIONS:'ขนาดภาพใน manifest ไม่ถูกต้อง',UNSUPPORTED_ENCODING:'รูปแบบค่าของชุดภาพไม่รองรับ',BAND_GRID_MISMATCH:'กริดของภาพแต่ละ band ไม่ตรงกัน',HTTP_ERROR:'โหลดชุดภาพไม่สำเร็จ',TIMEOUT:'หมดเวลารอชุดภาพ',INVALID_PRESET:'ชุดแสดงผลไม่ถูกต้อง'};
  function feedback(state,message){text('spectral-feedback',message);if(el('spectral-feedback'))el('spectral-feedback').dataset.state=state;el('panel-spectral')?.setAttribute('aria-busy',String(state==='LOADING'));}
  function clearFrame(){
    frame?.dispose();frame=null;displayed=null;
    if(boundary&&map?.hasLayer(boundary))map.removeLayer(boundary);boundary=null;
    const panel=el('panel-spectral');if(panel)for(const k of ['displayedPlot','displayedMonth','displayedPreset'])delete panel.dataset[k];
  }
  function ensureMap(){
    if(map||!el('pdd22-spectral-map'))return;
    map=L.map('pdd22-spectral-map',{scrollWheelZoom:false}).setView([9.2,100],6);
    L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(map);
  }
  async function jsonPackage(s,signal){
    const manifestKey=s.scope==='pdd'?`pdd|${s.code}`:`registry|${s.registryId}`;
    if(manifests.has(manifestKey))return manifests.get(manifestKey);
    const path=s.scope==='pdd'
      ? `data/pdd22_spectral/plots/${encodeURIComponent(s.code)}/spectral_manifest.json`
      : `data/plots/${encodeURIComponent(s.registryId)}/spectral_manifest.json`;
    const r=await fetch(`${path}?v=${DATA_VERSION}`,{signal,cache:'no-store'});
    if(r.status===404)throw S.failure('NO_DATA');
    if(!r.ok)throw S.failure('HTTP_ERROR');
    const result=await r.json();S.aborted(signal);
    const identityOk=s.scope==='pdd'?result.plot_code===s.code:Number(result.plot_id)===Number(s.registryId);
    if(!identityOk||result.asset_role!=='browser_visualization_only')throw S.failure('INVALID_PACKAGE');
    manifests.set(manifestKey,result);return result;
  }
  async function bandPixels(s,spec,band,signal){
    const key=`${s.scope}|${s.registryId}|${s.code}|${s.month}|${band}`;
    const cached=cache.get(key);if(cached)return cached;
    const filename=spec.date.files[band];
    const base=s.scope==='pdd'
      ? `data/pdd22_spectral/plots/${encodeURIComponent(s.code)}`
      : `data/plots/${encodeURIComponent(s.registryId)}`;
    const r=await fetch(`${base}/${encodeURIComponent(filename)}?v=${DATA_VERSION}`,{signal});
    if(!r.ok)throw S.failure('HTTP_ERROR');
    const blob=await r.blob();S.aborted(signal);
    const url=URL.createObjectURL(blob),image=new Image();
    try{
      image.src=url;await S.abortable(image.decode(),signal);S.aborted(signal);
      if(image.naturalWidth!==spec.width||image.naturalHeight!==spec.height)throw S.failure('BAND_GRID_MISMATCH');
      const canvas=document.createElement('canvas');canvas.width=spec.width;canvas.height=spec.height;
      const context=canvas.getContext('2d',{willReadFrequently:true});if(!context)throw new Error('CANVAS_UNAVAILABLE');
      context.drawImage(image,0,0);
      const rgba=context.getImageData(0,0,spec.width,spec.height).data;
      const luma=new Uint8Array(spec.width*spec.height),alpha=new Uint8Array(luma.length);
      for(let i=0;i<luma.length;i++){luma[i]=rgba[i*4];alpha[i]=rgba[i*4+3];}
      const value={width:spec.width,height:spec.height,luma,alpha};
      S.aborted(signal);cache.set(key,value,luma.byteLength+alpha.byteLength);return value;
    }finally{URL.revokeObjectURL(url);}
  }
  async function load(s,parentSignal,current){
    ensureMap();const controller=new AbortController(),signal=controller.signal;
    const abort=()=>controller.abort(parentSignal.reason);
    if(parentSignal.aborted)abort();else parentSignal.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(()=>controller.abort(S.failure('TIMEOUT')),20000);
    let url=null,loadedFrame=null;
    try{
      const manifest=await jsonPackage(s,signal),spec=S.selection(manifest,s),loaded={};
      // Sequential decoding bounds transient image memory; all requests are abortable.
      for(const band of spec.required){loaded[band]=await bandPixels(s,spec,band,signal);S.aborted(signal);}
      const rgba=await S.compose(spec,loaded,s,{signal});S.aborted(signal);
      const canvas=document.createElement('canvas');canvas.width=spec.width;canvas.height=spec.height;
      const context=canvas.getContext('2d');if(!context)throw new Error('CANVAS_UNAVAILABLE');
      const image=context.createImageData(spec.width,spec.height);image.data.set(rgba);context.putImageData(image,0,0);
      const png=await S.abortable(new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('PNG_ENCODE_FAILED')),'image/png')),signal);
      S.aborted(signal);url=URL.createObjectURL(png);
      const pending=M.loadLeafletFrame(L,map,{url,bounds:s.bounds},()=>current()&&!signal.aborted,{className:'spectral-observation-overlay'});
      pending.then(f=>{if(signal.aborted||!current())f.dispose();},()=>{});
      loadedFrame=await S.abortable(pending,signal);S.aborted(signal);
      const ownedUrl=url;url=null;const ownedFrame=loadedFrame;loadedFrame=null;
      return {overlay:ownedFrame.overlay,spec,dispose(){ownedFrame.dispose();URL.revokeObjectURL(ownedUrl);}};
    }catch(error){throw signal.aborted?(signal.reason||error):error;}
    finally{clearTimeout(timer);parentSignal.removeEventListener('abort',abort);loadedFrame?.dispose();if(url)URL.revokeObjectURL(url);}
  }
  const runner=S.createRunner({
    loading(s){
      if(displayed&&displayed.code!==s.code)clearFrame();
      el('spectral-retry').hidden=true;
      if(!displayed){text('spectral-status',`${label(s)} · กำลังโหลด`);text('spectral-qa','—');text('spectral-formula','รอภาพของช่วงที่เลือก');}
      feedback('LOADING',`กำลังโหลด ${label(s)}${displayed?` — ภาพที่ยังเห็นคือ ${label(displayed)}`:''}`);
    },
    load,
    commit(s,next){
      if(!visible()){next.dispose();return;}
      const nextBoundary=L.geoJSON({type:'Feature',properties:{},geometry:s.plot.geometry},{style:{color:'#e2e8f0',weight:2,fillOpacity:0}});
      const old=frame,oldBoundary=boundary;
      frame=next;boundary=nextBoundary;displayed=s;frame.overlay.setOpacity(desired.opacity);
      if(el('spectral-boundary').checked)boundary.addTo(map);
      const bounds=boundary.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[32,32],maxZoom:17,animate:false});
      old?.dispose();if(oldBoundary&&map.hasLayer(oldBoundary))map.removeLayer(oldBoundary);
      const panel=el('panel-spectral');panel.dataset.displayedPlot=s.code;panel.dataset.displayedMonth=s.month;panel.dataset.displayedPreset=s.preset;
      text('spectral-status',label(s));
      const coverage=M.number(next.spec.date.coverage_pct ?? next.spec.date.clear_pixel_pct);
      const qa=s.scope==='pdd'?M.qa(next.spec.date):(coverage===null||coverage<5?'NO_DATA':coverage>=95?'GOOD':coverage>=50?'PARTIAL':'LOW_QA');
      text('spectral-qa',`${qa} · ${coverage===null?'—':coverage}%`);
      text('spectral-formula',`${next.spec.preset.formula||next.spec.preset.bands.join(' / ')} · ภาพแสดงผล 8-bit ไม่ใช่ค่าวิเคราะห์ต้นฉบับ`);
      feedback('READY',`ภาพและข้อมูลตรงกัน · ${label(s)} · ความสว่าง ${Math.round(s.brightness*100)}% / contrast ${Math.round(s.contrast*100)}% / gamma ${s.gamma.toFixed(2)}`);
      map.invalidateSize();
    },
    failed(s,error){
      clearFrame();text('spectral-status',label(s));text('spectral-qa','—');text('spectral-formula','ไม่มีภาพที่ยืนยันสำหรับการเลือกนี้');
      const code=error.code||error.message;
      feedback(code==='NO_DATA'?'NO_DATA':'ERROR',messages[code]||'โหลดหรือถอดรหัสภาพไม่สำเร็จ — ล้างภาพเก่าแล้ว');
      el('spectral-retry').hidden=code==='NO_DATA';
    }
  });
  function refresh(){
    if(queued)return;queued=true;
    queueMicrotask(()=>{
      queued=false;
      if(!visible()||!activePlot){runner.cancel();clearFrame();return;}
      const item=activePlot.timeseries[currentMonthIndex];if(!item)return;
      if(el('spectral-month'))el('spectral-month').value=String(currentMonthIndex);
      const s={...desired,channels:{...desired.channels},plot:activePlot,scope:activePlot.scope||'pdd',registryId:activePlot.registryId??activePlot.id,code:activePlot.code,month:item.month,bounds:imageBoundsForPlot(activePlot)};
      runner.run(s);
    });
  }
  function syncControls(){
    document.querySelectorAll('#panel-spectral [data-preset]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.preset===desired.preset)));
    for(const c of ['r','g','b'])el(`spectral-${c}`).value=desired.channels[c];
    for(const k of ['brightness','contrast','gamma','opacity']){el(`spectral-${k}`).value=String(Math.round(desired[k]*100));text(`spectral-${k}-value`,k==='gamma'?desired[k].toFixed(2):`${Math.round(desired[k]*100)}%`);}
  }
  function preset(key){
    const p=S.PRESETS[key];if(!p)return;desired.preset=key;
    if(p.mode==='rgb')desired.channels={r:p.bands[0],g:p.bands[1],b:p.bands[2]};
    syncControls();refresh();
  }
  function inject(){
    if(el('panel-spectral'))return;
    const tabs=document.querySelector('.workspace-tabs'),table=el('panel-table');if(!tabs||!table)return;
    const button=document.createElement('button');button.type='button';button.id='wtab-spectral';button.className='w-tab-btn';button.textContent='Spectral Studio';button.onclick=()=>switchWorkspaceTab('spectral');tabs.insertBefore(button,el('wtab-table'));
    const panel=document.createElement('section');panel.className='tab-content-panel';panel.id='panel-spectral';
    const presetButtons=Object.entries(S.PRESETS).map(([key,p])=>`<button type="button" data-preset="${key}" aria-pressed="${key==='truecolor'}">${p.label}</button>`).join('');
    const sliders=[['brightness','ความสว่าง',50,200],['contrast','Contrast',50,200],['gamma','Gamma',50,250],['opacity','ความทึบ',0,100]].map(([key,name,min,max])=>`<label class="spectral-slider" for="spectral-${key}">${name}<input id="spectral-${key}" type="range" min="${min}" max="${max}" value="100"><output id="spectral-${key}-value"></output></label>`).join('');
    panel.innerHTML=`<div class="spectral-shell"><section class="spectral-canvas-card"><div class="spectral-toolbar"><strong id="spectral-status">เลือกภาพเพื่อเริ่มต้น</strong><span id="spectral-qa">—</span></div><p id="spectral-formula"></p><div id="pdd22-spectral-map"></div><div class="spectral-feedback-wrap"><p id="spectral-feedback" role="status" aria-live="polite" data-state="IDLE">ยังไม่โหลดภาพ</p><button type="button" id="spectral-retry" hidden>ลองใหม่</button></div><p class="spectral-basemap-note">Esri เป็นภาพพื้นหลัง ไม่ใช่ภาพตามเดือนที่เลือก</p></section><aside class="spectral-controls"><label for="spectral-month">เดือนของข้อมูล<select id="spectral-month"></select></label><div class="spectral-presets">${presetButtons}</div><details class="spectral-advanced"><summary>เครื่องมือขั้นสูง / ปรับภาพ</summary><div class="spectral-channel-grid"><label for="spectral-r">Red<select id="spectral-r">${options('B04')}</select></label><label for="spectral-g">Green<select id="spectral-g">${options('B03')}</select></label><label for="spectral-b">Blue<select id="spectral-b">${options('B02')}</select></label></div>${sliders}<label class="spectral-boundary"><input type="checkbox" id="spectral-boundary" checked> แสดงเส้นขอบแปลง</label><button type="button" id="spectral-reset">คืนค่าภาพเริ่มต้น</button></details><p class="spectral-warning">Visualization only: ภาพ PNG 8-bit ใช้ดูสีและเปรียบเทียบเชิงภาพเท่านั้น ค่าวิเคราะห์ NDVI/FCD มาจาก float reflectance pipeline เดิม ไม่ใช้ภาพนี้คำนวณคาร์บอน</p><p class="spectral-band-note">B02/B03/B04/B08 มีความละเอียดเดิม 10 เมตร ส่วน B05/B06/B07/B8A/B11/B12 มีความละเอียดเดิม 20 เมตร การปรับกริดไม่เพิ่มรายละเอียดจริง</p></aside></div>`;
    table.before(panel);
    MILESTONE_MONTHS.forEach((month,i)=>el('spectral-month').add(new Option(Pdd22Ui.monthLabel(month),String(i))));
    el('spectral-month').onchange=e=>setMonthIndex(Number(e.target.value));
    panel.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>preset(b.dataset.preset));
    for(const c of ['r','g','b'])el(`spectral-${c}`).onchange=e=>{desired.channels[c]=e.target.value;desired.preset='custom';syncControls();refresh();};
    for(const k of ['brightness','contrast','gamma','opacity'])el(`spectral-${k}`).oninput=e=>{desired[k]=Number(e.target.value)/100;syncControls();if(k==='opacity')frame?.overlay.setOpacity(desired.opacity);else refresh();};
    el('spectral-boundary').onchange=e=>{if(!boundary||!map)return;if(e.target.checked)boundary.addTo(map);else if(map.hasLayer(boundary))map.removeLayer(boundary);};
    el('spectral-reset').onclick=()=>{Object.assign(desired,{preset:'truecolor',channels:{r:'B04',g:'B03',b:'B02'},brightness:1,contrast:1,gamma:1,opacity:.9});syncControls();refresh();};
    el('spectral-retry').onclick=()=>{manifests.clear();cache.clear();refresh();};
    syncControls();
  }
  const previousSelect=selectPlot,previousMonth=setMonthIndex,previousTab=switchWorkspaceTab;
  selectPlot=function(id){const result=previousSelect(id);refresh();return result;};
  setMonthIndex=function(index){const result=previousMonth(index);refresh();return result;};
  switchWorkspaceTab=function(tab){
    if(tab!=='spectral'){runner.cancel();clearFrame();}
    const result=previousTab(tab);
    if(tab==='spectral'){ensureMap();map?.invalidateSize();refresh();}
    return result;
  };
  window.UnifiedSpectralRefresh=refresh;
  window.addEventListener('pagehide',()=>{runner.cancel();clearFrame();});
  window.addEventListener('pageshow',event=>{if(event.persisted)refresh();});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',inject);else inject();
})();
