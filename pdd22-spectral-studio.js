// PDD22 Spectral Studio — ten-band browser visualization from the frozen cleaned Sentinel-2 scenes.
(() => {
  const VERSION = '20260826-2125-10band';
  const BANDS = ['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12'];
  const LABELS = {
    B02:'B02 • Blue • 490 nm • 10 m',
    B03:'B03 • Green • 560 nm • 10 m',
    B04:'B04 • Red • 665 nm • 10 m',
    B05:'B05 • Red Edge 1 • 705 nm • 20 m',
    B06:'B06 • Red Edge 2 • 740 nm • 20 m',
    B07:'B07 • Red Edge 3 • 783 nm • 20 m',
    B08:'B08 • NIR • 842 nm • 10 m',
    B8A:'B8A • Narrow NIR • 865 nm • 20 m',
    B11:'B11 • SWIR1 • 1610 nm • 20 m',
    B12:'B12 • SWIR2 • 2190 nm • 20 m'
  };

  const PRESETS = {
    truecolor:{label:'True Color',group:'RGB',mode:'rgb',r:'B04',g:'B03',b:'B02',desc:'Natural color 4-3-2'},
    cir:{label:'Color Infrared',group:'RGB',mode:'rgb',r:'B08',g:'B04',b:'B03',desc:'Vegetation false color 8-4-3'},
    rededge:{label:'Red Edge False Color',group:'RGB',mode:'rgb',r:'B8A',g:'B05',b:'B04',desc:'Red-edge canopy/chlorophyll contrast'},
    swir:{label:'SWIR Agriculture',group:'RGB',mode:'rgb',r:'B11',g:'B08',b:'B02',desc:'Moisture / vegetation contrast 11-8-2'},
    urban:{label:'SWIR / Bare',group:'RGB',mode:'rgb',r:'B12',g:'B11',b:'B04',desc:'Dry soil / bare / built surface contrast'},
    moisture_rgb:{label:'NIR-SWIR-Red',group:'RGB',mode:'rgb',r:'B08',g:'B11',b:'B04',desc:'Canopy moisture false color'},

    ndvi:{label:'NDVI',group:'Index',mode:'index',kind:'nd',bands:['B08','B04'],palette:'vegetation',formula:'(B08 − B04) / (B08 + B04)'},
    ndre:{label:'NDRE',group:'Index',mode:'index',kind:'nd',bands:['B8A','B05'],palette:'vegetation',formula:'(B8A − B05) / (B8A + B05)'},
    ndwi:{label:'NDWI',group:'Index',mode:'index',kind:'nd',bands:['B03','B08'],palette:'water',formula:'(B03 − B08) / (B03 + B08)'},
    mndwi:{label:'MNDWI',group:'Index',mode:'index',kind:'nd',bands:['B03','B11'],palette:'water',formula:'(B03 − B11) / (B03 + B11)'},
    ndmi:{label:'NDMI',group:'Index',mode:'index',kind:'nd',bands:['B08','B11'],palette:'moisture',formula:'(B08 − B11) / (B08 + B11)'},
    evi:{label:'EVI',group:'Index',mode:'index',kind:'evi',bands:['B08','B04','B02'],palette:'vegetation',formula:'2.5 × (B08 − B04) / (B08 + 6B04 − 7.5B02 + 1)'},
    savi:{label:'SAVI',group:'Index',mode:'index',kind:'savi',bands:['B08','B04'],palette:'vegetation',formula:'1.5 × (B08 − B04) / (B08 + B04 + 0.5)'},
    nbr:{label:'NBR',group:'Index',mode:'index',kind:'nd',bands:['B08','B12'],palette:'disturbance',formula:'(B08 − B12) / (B08 + B12)'},
    bsi:{label:'BSI',group:'Index',mode:'index',kind:'bsi',bands:['B11','B04','B08','B02'],palette:'bare',formula:'((B11+B04) − (B08+B02)) / ((B11+B04) + (B08+B02))'}
  };

  let map = null;
  let base = null;
  let overlay = null;
  let boundary = null;
  let currentPreset = 'truecolor';
  let channels = {r:'B04',g:'B03',b:'B02'};
  let brightness = 1;
  let contrast = 1;
  let gamma = 1;
  let opacity = 0.9;
  let renderToken = 0;
  const manifestCache = new Map();
  const pixelsCache = new Map();

  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const finite = v => Number.isFinite(Number(v));
  const fmtPct = v => finite(v) ? `${Number(v).toFixed(1)}%` : '—';
  const reflectance = luma => Number(luma) / 255 * 0.40;
  const safeDiv = (a,b) => Math.abs(b) < 1e-9 ? 0 : a / b;
  const bandOptions = selected => BANDS.map(b => `<option value="${b}" ${b===selected?'selected':''}>${LABELS[b]}</option>`).join('');

  function injectStyles(){
    if(document.getElementById('pdd22-spectral-styles')) return;
    const s=document.createElement('style');
    s.id='pdd22-spectral-styles';
    s.textContent=`
      .spectral-shell{display:grid;grid-template-columns:350px minmax(0,1fr);gap:14px;padding:16px}
      .spectral-controls,.spectral-card{border:1px solid rgba(255,255,255,.08);background:rgba(15,23,42,.72);border-radius:12px;overflow:hidden}
      .spectral-controls{padding:14px;align-self:start;max-height:74vh;overflow:auto}
      .spectral-section+.spectral-section{margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,.07)}
      .spectral-title{font-size:.88rem;font-weight:800;color:#f8fafc}.spectral-sub{font-size:.64rem;line-height:1.5;color:#94a3b8;margin-top:4px}
      .spectral-field{margin-top:9px}.spectral-field label{display:block;color:#94a3b8;font-size:.61rem;font-weight:700;margin-bottom:4px}
      .spectral-field select{width:100%;background:#0f172a;color:#e2e8f0;border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px 8px;font-size:.68rem}
      .spectral-group-label{margin-top:11px;color:#64748b;font-size:.58rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      .spectral-presets{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:7px}
      .spectral-preset{border:1px solid rgba(255,255,255,.1);background:#111827;color:#cbd5e1;border-radius:8px;padding:8px 6px;font-size:.64rem;font-weight:700;cursor:pointer;line-height:1.25}
      .spectral-preset:hover{border-color:rgba(56,189,248,.45)}.spectral-preset.active{border-color:#38bdf8;background:rgba(56,189,248,.14);color:#e0f2fe}
      .spectral-slider{display:grid;grid-template-columns:72px 1fr 48px;gap:8px;align-items:center;margin-top:8px}.spectral-slider label{font-size:.6rem;color:#94a3b8}.spectral-slider input{width:100%;accent-color:#38bdf8}.spectral-slider span{font-size:.6rem;color:#e2e8f0;text-align:right}
      .spectral-warning{margin-top:12px;padding:9px 10px;border-radius:8px;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);font-size:.61rem;line-height:1.45;color:#fcd34d}
      .spectral-band-note{margin-top:8px;font-size:.58rem;line-height:1.45;color:#64748b}
      .spectral-toolbar{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.07);flex-wrap:wrap}.spectral-status{font-size:.68rem;color:#cbd5e1}.spectral-status strong{color:#fff}.spectral-qa{font-size:.61rem;border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:4px 8px;color:#cbd5e1}
      .spectral-formula{font-size:.61rem;color:#94a3b8;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.06);min-height:18px}.spectral-formula strong{color:#e2e8f0}
      .spectral-map-wrap{position:relative}.spectral-map{height:620px;min-height:440px;background:#0b1120}.spectral-empty{position:absolute;inset:0;z-index:700;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;background:rgba(15,23,42,.45);color:#cbd5e1;font-size:.78rem}.spectral-empty.hidden{display:none}
      @media(max-width:1050px){.spectral-shell{grid-template-columns:1fr}.spectral-controls{max-height:none}.spectral-map{height:520px}}
    `;
    document.head.appendChild(s);
  }

  function presetButtons(group){
    return Object.entries(PRESETS)
      .filter(([,p])=>p.group===group)
      .map(([k,p])=>`<button class="spectral-preset ${k==='truecolor'?'active':''}" data-preset="${k}">${p.label}</button>`)
      .join('');
  }

  function injectUI(){
    injectStyles();
    if(document.getElementById('wtab-spectral')) return;
    const tabs=document.querySelector('.workspace-tabs');
    const table=document.getElementById('wtab-table');
    if(!tabs||!table) return;

    const btn=document.createElement('button');
    btn.className='w-tab-btn';
    btn.id='wtab-spectral';
    btn.textContent='Spectral Studio';
    btn.onclick=()=>{
      switchWorkspaceTab('spectral');
      setTimeout(()=>{ensureMap();map?.invalidateSize();refresh();},100);
    };
    tabs.insertBefore(btn,table);

    const tablePanel=document.getElementById('panel-table');
    const panel=document.createElement('div');
    panel.className='tab-content-panel';
    panel.id='panel-spectral';
    panel.innerHTML=`
      <div class="spectral-shell">
        <aside class="spectral-controls">
          <div class="spectral-section">
            <div class="spectral-title">Sentinel-2 Multi-band • 10 bands</div>
            <div class="spectral-sub">ใช้ scene เดียวกับ cleaned PDD22 dataset และ PDD participating boundary เท่านั้น</div>
            <div class="spectral-field"><label>Observation month</label><select id="spectral-month"></select></div>
            <div class="spectral-group-label">False color / RGB</div>
            <div class="spectral-presets">${presetButtons('RGB')}</div>
            <div class="spectral-group-label">Spectral indices</div>
            <div class="spectral-presets">${presetButtons('Index')}</div>
          </div>

          <div class="spectral-section" id="spectral-rgb-section">
            <div class="spectral-title">Custom RGB Mixer</div>
            <div class="spectral-sub">เลือกได้ครบ B02/B03/B04/B05/B06/B07/B08/B8A/B11/B12</div>
            <div class="spectral-field"><label>Red channel</label><select id="spectral-r">${bandOptions('B04')}</select></div>
            <div class="spectral-field"><label>Green channel</label><select id="spectral-g">${bandOptions('B03')}</select></div>
            <div class="spectral-field"><label>Blue channel</label><select id="spectral-b">${bandOptions('B02')}</select></div>
          </div>

          <div class="spectral-section">
            <div class="spectral-title">Display tuning</div>
            <div class="spectral-slider"><label>Brightness</label><input id="spectral-brightness" type="range" min="50" max="200" value="100"><span id="spectral-brightness-v">100%</span></div>
            <div class="spectral-slider"><label>Contrast</label><input id="spectral-contrast" type="range" min="50" max="200" value="100"><span id="spectral-contrast-v">100%</span></div>
            <div class="spectral-slider"><label>Gamma</label><input id="spectral-gamma" type="range" min="50" max="250" value="100"><span id="spectral-gamma-v">1.00</span></div>
            <div class="spectral-slider"><label>Opacity</label><input id="spectral-opacity" type="range" min="0" max="100" value="90"><span id="spectral-opacity-v">90%</span></div>
          </div>

          <div class="spectral-warning">Visualization only — band PNG เป็น 8-bit fixed-scale. NDVI/FCD/ค่าที่ใช้ตัดสินเชิงวิเคราะห์ยังมาจาก float reflectance pipeline เดิม ไม่ใช้ PNG ชุดนี้คำนวณ carbon.</div>
          <div class="spectral-band-note">Native 10 m: B02/B03/B04/B08 • Native 20 m: B05/B06/B07/B8A/B11/B12. การ align ไป grid เดียวกันไม่ได้เพิ่มรายละเอียดจริงของ band 20 m.</div>
        </aside>

        <section class="spectral-card">
          <div class="spectral-toolbar"><div class="spectral-status" id="spectral-status"><strong>Spectral Studio</strong> • กำลังโหลด</div><span class="spectral-qa" id="spectral-qa">—</span></div>
          <div class="spectral-formula" id="spectral-formula">True Color • B04/B03/B02</div>
          <div class="spectral-map-wrap"><div id="pdd22-spectral-map" class="spectral-map"></div><div id="spectral-empty" class="spectral-empty hidden"></div></div>
        </section>
      </div>`;
    tablePanel.parentNode.insertBefore(panel,tablePanel);

    const sel=document.getElementById('spectral-month');
    MILESTONE_MONTHS.forEach((m,i)=>{
      const p=parseMonthKey(m),o=document.createElement('option');
      o.value=String(i);o.textContent=`${thaiMonths[p.month_num]} ${p.year}`;sel.appendChild(o);
    });
    sel.value=String(currentMonthIndex);
    sel.onchange=e=>{setMonthIndex(Number(e.target.value));refresh();};

    document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>applyPreset(b.dataset.preset));
    ['r','g','b'].forEach(c=>document.getElementById(`spectral-${c}`).onchange=e=>{
      channels[c]=e.target.value;currentPreset='custom';updatePresetButtons();render();
    });
    document.getElementById('spectral-brightness').oninput=e=>{brightness=Number(e.target.value)/100;document.getElementById('spectral-brightness-v').textContent=`${e.target.value}%`;render();};
    document.getElementById('spectral-contrast').oninput=e=>{contrast=Number(e.target.value)/100;document.getElementById('spectral-contrast-v').textContent=`${e.target.value}%`;render();};
    document.getElementById('spectral-gamma').oninput=e=>{gamma=Number(e.target.value)/100;document.getElementById('spectral-gamma-v').textContent=gamma.toFixed(2);render();};
    document.getElementById('spectral-opacity').oninput=e=>{opacity=Number(e.target.value)/100;document.getElementById('spectral-opacity-v').textContent=`${e.target.value}%`;overlay?.setOpacity(opacity);};
  }

  function ensureMap(){
    if(map||!document.getElementById('pdd22-spectral-map')) return;
    map=L.map('pdd22-spectral-map',{zoomControl:true,attributionControl:true}).setView([9.2,100],6);
    base=L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(map);
  }

  function updatePresetButtons(){
    document.querySelectorAll('[data-preset]').forEach(b=>b.classList.toggle('active',b.dataset.preset===currentPreset));
  }

  function updateFormula(){
    const el=document.getElementById('spectral-formula');if(!el)return;
    const p=PRESETS[currentPreset];
    if(!p){el.innerHTML=`<strong>Custom RGB</strong> • ${channels.r}/${channels.g}/${channels.b}`;return;}
    if(p.mode==='rgb') el.innerHTML=`<strong>${p.label}</strong> • ${p.desc}`;
    else el.innerHTML=`<strong>${p.label}</strong> • ${p.formula}`;
  }

  function applyPreset(key){
    const p=PRESETS[key];if(!p)return;currentPreset=key;
    if(p.mode==='rgb'){
      channels={r:p.r,g:p.g,b:p.b};
      document.getElementById('spectral-r').value=p.r;
      document.getElementById('spectral-g').value=p.g;
      document.getElementById('spectral-b').value=p.b;
    }
    document.getElementById('spectral-rgb-section').style.opacity=p.mode==='rgb'?'1':'.45';
    updatePresetButtons();updateFormula();render();
  }

  async function loadManifest(code){
    if(manifestCache.has(code)) return manifestCache.get(code);
    try{
      const r=await fetch(`data/pdd22_spectral/plots/${code}/spectral_manifest.json?v=${VERSION}`,{cache:'no-store'});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const m=await r.json();manifestCache.set(code,m);return m;
    }catch(e){manifestCache.set(code,null);return null;}
  }

  async function loadBand(code,month,file){
    if(!file) throw new Error(`Missing band file for ${code} ${month}`);
    const key=`${code}|${month}|${file}`;
    if(pixelsCache.has(key))return pixelsCache.get(key);
    const img=new Image();img.src=`data/pdd22_spectral/plots/${code}/${file}?v=${VERSION}`;await img.decode();
    const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;
    const x=c.getContext('2d',{willReadFrequently:true});x.drawImage(img,0,0);
    const d=x.getImageData(0,0,c.width,c.height).data;
    const l=new Uint8Array(c.width*c.height),a=new Uint8Array(c.width*c.height);
    for(let i=0,j=0;i<d.length;i+=4,j++){l[j]=d[i];a[j]=d[i+3];}
    const out={width:c.width,height:c.height,luma:l,alpha:a};pixelsCache.set(key,out);return out;
  }

  function lerp(a,b,t){return Math.round(a+(b-a)*t);}
  function threeStop(v,neg,mid,pos){
    v=clamp(v,-1,1);
    if(v<0){const t=v+1;return [lerp(neg[0],mid[0],t),lerp(neg[1],mid[1],t),lerp(neg[2],mid[2],t)];}
    return [lerp(mid[0],pos[0],v),lerp(mid[1],pos[1],v),lerp(mid[2],pos[2],v)];
  }
  function indexColor(v,palette){
    if(palette==='water') return threeStop(v,[180,95,45],[235,235,210],[20,130,255]);
    if(palette==='moisture') return threeStop(v,[190,105,45],[235,220,145],[15,150,175]);
    if(palette==='disturbance') return threeStop(v,[220,55,45],[245,210,70],[30,160,70]);
    if(palette==='bare') return threeStop(v,[35,135,70],[230,220,150],[215,105,45]);
    return threeStop(v,[155,85,45],[230,215,95],[25,165,65]);
  }

  function indexValue(p, loaded, i){
    const R = b => reflectance(loaded[b].luma[i]);
    if(p.kind==='nd'){
      const a=R(p.bands[0]),b=R(p.bands[1]);return safeDiv(a-b,a+b);
    }
    if(p.kind==='evi'){
      const nir=R('B08'),red=R('B04'),blue=R('B02');
      return safeDiv(2.5*(nir-red),nir+6*red-7.5*blue+1);
    }
    if(p.kind==='savi'){
      const nir=R('B08'),red=R('B04');return safeDiv(1.5*(nir-red),nir+red+0.5);
    }
    if(p.kind==='bsi'){
      const swir=R('B11'),red=R('B04'),nir=R('B08'),blue=R('B02');
      return safeDiv((swir+red)-(nir+blue),(swir+red)+(nir+blue));
    }
    return 0;
  }

  function tuneChannel(value){
    let v=value/255;
    v=((v-.5)*contrast+.5)*brightness;
    v=Math.pow(clamp(v,0,1),1/Math.max(.05,gamma));
    return Math.round(clamp(v,0,1)*255);
  }

  async function render(){
    if(!activePlot)return;
    ensureMap();
    const token=++renderToken;
    const month=MILESTONE_MONTHS[currentMonthIndex];
    const manifest=await loadManifest(activePlot.code);
    if(token!==renderToken)return;

    const empty=document.getElementById('spectral-empty');
    const status=document.getElementById('spectral-status');
    const qa=document.getElementById('spectral-qa');
    const date=manifest?.dates?.find(d=>d.month===month);

    if(!manifest||!date||date.status!=='available'){
      if(overlay&&map.hasLayer(overlay))map.removeLayer(overlay);overlay=null;
      if(empty){empty.classList.remove('hidden');empty.textContent=`${activePlot.code} • ${month} ไม่มี spectral package ที่ผ่าน cleaned-scene pipeline`;}
      if(status)status.innerHTML=`<strong>${activePlot.code}</strong> • ${month} • No spectral data`;
      if(qa)qa.textContent=date?.qa||'NO_DATA';
      return;
    }

    const missing=BANDS.filter(b=>!manifest.bands?.includes(b)||!date.files?.[b]);
    if(missing.length){
      if(overlay&&map.hasLayer(overlay))map.removeLayer(overlay);overlay=null;
      if(empty){empty.classList.remove('hidden');empty.textContent=`Spectral package รุ่นเก่ายังขาด ${missing.join(', ')} — รอ 10-band rebuild`;}
      if(status)status.innerHTML=`<strong>${activePlot.code}</strong> • ${month} • 10-band package pending`;
      if(qa)qa.textContent=date.qa||'—';
      return;
    }

    empty?.classList.add('hidden');
    const preset=PRESETS[currentPreset];
    const label=preset?.label||'Custom RGB';
    if(status)status.innerHTML=`<strong>${activePlot.code}</strong> • ${month} • ${label}`;
    if(qa)qa.textContent=`${date.qa||'—'} • ${fmtPct(date.coverage_pct)}`;
    updateFormula();

    const needed=new Set();
    if(preset?.mode==='index') preset.bands.forEach(b=>needed.add(b));
    else {needed.add(channels.r);needed.add(channels.g);needed.add(channels.b);}

    const loaded={};
    try{
      for(const band of needed){loaded[band]=await loadBand(activePlot.code,month,date.files[band]);if(token!==renderToken)return;}
    }catch(error){
      if(token!==renderToken)return;
      if(empty){empty.classList.remove('hidden');empty.textContent=`โหลด band ไม่สำเร็จ: ${error.message}`;}
      return;
    }

    const first=loaded[[...needed][0]],w=first.width,h=first.height;
    const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
    const ctx=canvas.getContext('2d');const image=ctx.createImageData(w,h);const out=image.data;

    for(let i=0;i<w*h;i++){
      let rr=0,gg=0,bb=0,aa=255;
      for(const band of needed) aa=Math.min(aa,loaded[band].alpha[i]);
      if(preset?.mode==='index'){
        const idx=clamp(indexValue(preset,loaded,i),-1,1);
        [rr,gg,bb]=indexColor(idx,preset.palette);
      }else{
        rr=loaded[channels.r].luma[i];gg=loaded[channels.g].luma[i];bb=loaded[channels.b].luma[i];
      }
      rr=tuneChannel(rr);gg=tuneChannel(gg);bb=tuneChannel(bb);
      const j=i*4;out[j]=rr;out[j+1]=gg;out[j+2]=bb;out[j+3]=aa;
    }
    ctx.putImageData(image,0,0);
    const dataUrl=canvas.toDataURL('image/png');
    if(token!==renderToken)return;

    const next=L.imageOverlay(dataUrl,imageBoundsForPlot(activePlot),{opacity,interactive:false,className:'sentinel-overlay'}).addTo(map);
    if(overlay&&map.hasLayer(overlay))map.removeLayer(overlay);overlay=next;

    if(boundary&&map.hasLayer(boundary))map.removeLayer(boundary);
    boundary=L.geoJSON({type:'Feature',properties:{},geometry:activePlot.geometry},{style:{color:'#34d399',weight:2,fillOpacity:0}}).addTo(map);
    const bounds=boundary.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[38,38],maxZoom:17,animate:false});
    boundary.bringToFront?.();
  }

  function refresh(){
    const select=document.getElementById('spectral-month');if(select)select.value=String(currentMonthIndex);
    if(document.getElementById('panel-spectral')?.classList.contains('active')) render();
  }

  const previousSelectPlot=selectPlot;
  selectPlot=function spectralWrappedSelectPlot(id){previousSelectPlot(id);refresh();};
  const previousSetMonthIndex=setMonthIndex;
  setMonthIndex=function spectralWrappedSetMonthIndex(index){previousSetMonthIndex(index);refresh();};

  const start=()=>{injectUI();updateFormula();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
