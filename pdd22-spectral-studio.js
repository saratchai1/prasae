// PDD22 Spectral Studio — browser-side six-band visualization from cleaned frozen scenes.
(() => {
  const VERSION = '20260826-1450';
  const BANDS = ['B02','B03','B04','B08','B11','B12'];
  const LABELS = {
    B02:'B02 • Blue • 490 nm', B03:'B03 • Green • 560 nm', B04:'B04 • Red • 665 nm',
    B08:'B08 • NIR • 842 nm', B11:'B11 • SWIR1 • 1610 nm', B12:'B12 • SWIR2 • 2190 nm'
  };
  const PRESETS = {
    truecolor:{label:'True Color',mode:'rgb',r:'B04',g:'B03',b:'B02'},
    cir:{label:'Color Infrared',mode:'rgb',r:'B08',g:'B04',b:'B03'},
    swir:{label:'SWIR Agriculture',mode:'rgb',r:'B11',g:'B08',b:'B02'},
    urban:{label:'SWIR / Urban',mode:'rgb',r:'B12',g:'B11',b:'B04'},
    ndwi:{label:'NDWI',mode:'index',a:'B03',b2:'B08'},
    mndwi:{label:'MNDWI',mode:'index',a:'B03',b2:'B11'},
    ndmi:{label:'NDMI',mode:'index',a:'B08',b2:'B11'}
  };

  let map=null, base=null, overlay=null, boundary=null;
  let currentPreset='truecolor';
  let channels={r:'B04',g:'B03',b:'B02'};
  let brightness=1, contrast=1, gamma=1, opacity=.9;
  let renderToken=0;
  const manifestCache=new Map();
  const pixelsCache=new Map();

  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const fmtPct=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(1)}%`:'—';
  const bandOptions=selected=>BANDS.map(b=>`<option value="${b}" ${b===selected?'selected':''}>${LABELS[b]}</option>`).join('');

  function injectStyles(){
    if(document.getElementById('pdd22-spectral-styles')) return;
    const s=document.createElement('style');
    s.id='pdd22-spectral-styles';
    s.textContent=`
      .spectral-shell{display:grid;grid-template-columns:330px minmax(0,1fr);gap:14px;padding:16px}
      .spectral-controls,.spectral-card{border:1px solid rgba(255,255,255,.08);background:rgba(15,23,42,.72);border-radius:12px;overflow:hidden}
      .spectral-controls{padding:14px;align-self:start}.spectral-section+.spectral-section{margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,.07)}
      .spectral-title{font-size:.88rem;font-weight:800;color:#f8fafc}.spectral-sub{font-size:.64rem;line-height:1.45;color:#94a3b8;margin-top:4px}
      .spectral-field{margin-top:9px}.spectral-field label{display:block;color:#94a3b8;font-size:.61rem;font-weight:700;margin-bottom:4px}
      .spectral-field select{width:100%;background:#0f172a;color:#e2e8f0;border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px 8px;font-size:.68rem}
      .spectral-presets{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:10px}.spectral-preset{border:1px solid rgba(255,255,255,.1);background:#111827;color:#cbd5e1;border-radius:8px;padding:8px 6px;font-size:.65rem;font-weight:700;cursor:pointer}.spectral-preset.active{border-color:#38bdf8;background:rgba(56,189,248,.14);color:#e0f2fe}
      .spectral-slider{display:grid;grid-template-columns:72px 1fr 48px;gap:8px;align-items:center;margin-top:8px}.spectral-slider label{font-size:.6rem;color:#94a3b8}.spectral-slider input{width:100%;accent-color:#38bdf8}.spectral-slider span{font-size:.6rem;color:#e2e8f0;text-align:right}
      .spectral-warning{margin-top:12px;padding:9px 10px;border-radius:8px;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);font-size:.61rem;line-height:1.45;color:#fcd34d}
      .spectral-toolbar{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.07);flex-wrap:wrap}.spectral-status{font-size:.68rem;color:#cbd5e1}.spectral-status strong{color:#fff}.spectral-qa{font-size:.61rem;border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:4px 8px;color:#cbd5e1}
      .spectral-map-wrap{position:relative}.spectral-map{height:620px;min-height:440px;background:#0b1120}.spectral-empty{position:absolute;inset:0;z-index:700;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;background:rgba(15,23,42,.45);color:#cbd5e1;font-size:.78rem}.spectral-empty.hidden{display:none}
      @media(max-width:1050px){.spectral-shell{grid-template-columns:1fr}.spectral-map{height:520px}}
    `;
    document.head.appendChild(s);
  }

  function injectUI(){
    injectStyles();
    if(document.getElementById('wtab-spectral')) return;
    const tabs=document.querySelector('.workspace-tabs');
    const table=document.getElementById('wtab-table');
    if(!tabs||!table) return;
    const btn=document.createElement('button');
    btn.className='w-tab-btn';btn.id='wtab-spectral';btn.textContent='Spectral Studio';
    btn.onclick=()=>{switchWorkspaceTab('spectral');setTimeout(()=>{ensureMap();map?.invalidateSize();refresh();},100);};
    tabs.insertBefore(btn,table);

    const tablePanel=document.getElementById('panel-table');
    const panel=document.createElement('div');
    panel.className='tab-content-panel';panel.id='panel-spectral';
    panel.innerHTML=`
      <div class="spectral-shell">
        <aside class="spectral-controls">
          <div class="spectral-section"><div class="spectral-title">Sentinel-2 Multi-band</div><div class="spectral-sub">สีหลาย band ที่ใช้ scene เดียวกับ cleaned PDD22 dataset • participating boundary only</div>
            <div class="spectral-field"><label>Observation month</label><select id="spectral-month"></select></div>
            <div class="spectral-presets">${Object.entries(PRESETS).map(([k,p])=>`<button class="spectral-preset ${k==='truecolor'?'active':''}" data-preset="${k}">${p.label}</button>`).join('')}</div>
          </div>
          <div class="spectral-section" id="spectral-rgb-section"><div class="spectral-title">Custom RGB Mixer</div>
            <div class="spectral-field"><label>Red channel</label><select id="spectral-r">${bandOptions('B04')}</select></div>
            <div class="spectral-field"><label>Green channel</label><select id="spectral-g">${bandOptions('B03')}</select></div>
            <div class="spectral-field"><label>Blue channel</label><select id="spectral-b">${bandOptions('B02')}</select></div>
          </div>
          <div class="spectral-section"><div class="spectral-title">Display tuning</div>
            <div class="spectral-slider"><label>Brightness</label><input id="spectral-brightness" type="range" min="50" max="200" value="100"><span id="spectral-brightness-v">100%</span></div>
            <div class="spectral-slider"><label>Contrast</label><input id="spectral-contrast" type="range" min="50" max="200" value="100"><span id="spectral-contrast-v">100%</span></div>
            <div class="spectral-slider"><label>Gamma</label><input id="spectral-gamma" type="range" min="50" max="250" value="100"><span id="spectral-gamma-v">1.00</span></div>
            <div class="spectral-slider"><label>Opacity</label><input id="spectral-opacity" type="range" min="0" max="100" value="90"><span id="spectral-opacity-v">90%</span></div>
          </div>
          <div class="spectral-warning">Visualization only — PNG band ถูก quantize 8-bit เพื่อผสมสีใน browser. ค่า NDVI/FCD/สถิติยังคำนวณจาก float reflectance pipeline เดิม ไม่ใช้ PNG ชุดนี้.</div>
        </aside>
        <section class="spectral-card"><div class="spectral-toolbar"><div class="spectral-status" id="spectral-status"><strong>Spectral Studio</strong> • กำลังโหลด</div><span class="spectral-qa" id="spectral-qa">—</span></div><div class="spectral-map-wrap"><div id="pdd22-spectral-map" class="spectral-map"></div><div id="spectral-empty" class="spectral-empty hidden"></div></div></section>
      </div>`;
    tablePanel.parentNode.insertBefore(panel,tablePanel);

    const sel=document.getElementById('spectral-month');
    MILESTONE_MONTHS.forEach((m,i)=>{const p=parseMonthKey(m),o=document.createElement('option');o.value=String(i);o.textContent=`${thaiMonths[p.month_num]} ${p.year}`;sel.appendChild(o);});
    sel.value=String(currentMonthIndex);sel.onchange=e=>{setMonthIndex(Number(e.target.value));refresh();};
    document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>applyPreset(b.dataset.preset));
    ['r','g','b'].forEach(c=>document.getElementById(`spectral-${c}`).onchange=e=>{channels[c]=e.target.value;currentPreset='custom';updatePresetButtons();render();});
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

  function updatePresetButtons(){document.querySelectorAll('[data-preset]').forEach(b=>b.classList.toggle('active',b.dataset.preset===currentPreset));}
  function applyPreset(key){
    const p=PRESETS[key];if(!p)return;currentPreset=key;
    if(p.mode==='rgb'){channels={r:p.r,g:p.g,b:p.b};document.getElementById('spectral-r').value=p.r;document.getElementById('spectral-g').value=p.g;document.getElementById('spectral-b').value=p.b;}
    document.getElementById('spectral-rgb-section').style.opacity=p.mode==='rgb'?'1':'.45';updatePresetButtons();render();
  }

  async function loadManifest(code){
    if(manifestCache.has(code)) return manifestCache.get(code);
    try{const r=await fetch(`data/pdd22_spectral/plots/${code}/spectral_manifest.json?v=${VERSION}`,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const m=await r.json();manifestCache.set(code,m);return m;}catch(e){manifestCache.set(code,null);return null;}
  }

  async function loadBand(code,month,file){
    const key=`${code}|${month}|${file}`;if(pixelsCache.has(key))return pixelsCache.get(key);
    const img=new Image();img.src=`data/pdd22_spectral/plots/${code}/${file}?v=${VERSION}`;await img.decode();
    const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;const x=c.getContext('2d',{willReadFrequently:true});x.drawImage(img,0,0);const d=x.getImageData(0,0,c.width,c.height).data;
    const l=new Uint8Array(c.width*c.height),a=new Uint8Array(c.width*c.height);for(let i=0,j=0;i<d.length;i+=4,j++){l[j]=d[i];a[j]=d[i+3];}
    const out={width:c.width,height:c.height,luma:l,alpha:a};pixelsCache.set(key,out);return out;
  }

  function indexColor(v){
    v=clamp(v,-1,1);
    if(v>=0){const t=v;return [Math.round(40*(1-t)),Math.round(160+85*t),Math.round(190+65*t)];}
    const t=-v;return [Math.round(210+35*t),Math.round(190-80*t),Math.round(90-40*t)];
  }

  async function render(){
    if(!activePlot) return;ensureMap();const token=++renderToken;const month=MILESTONE_MONTHS[currentMonthIndex];const manifest=await loadManifest(activePlot.code);if(token!==renderToken)return;
    const empty=document.getElementById('spectral-empty'),status=document.getElementById('spectral-status'),qa=document.getElementById('spectral-qa');
    const date=manifest?.dates?.find(d=>d.month===month);
    if(!manifest||!date||date.status!=='available'){
      if(overlay&&map.hasLayer(overlay))map.removeLayer(overlay);overlay=null;if(empty){empty.classList.remove('hidden');empty.textContent=`${activePlot.code} • ${month} ไม่มี spectral package ที่ผ่าน cleaned-scene pipeline`;}
      if(status)status.innerHTML=`<strong>${activePlot.code}</strong> • ${month} • No spectral data`;if(qa)qa.textContent=date?.qa||'NO_DATA';return;
    }
    empty?.classList.add('hidden');if(status)status.innerHTML=`<strong>${activePlot.code}</strong> • ${month} • ${PRESETS[currentPreset]?.label||'Custom RGB'}`;if(qa)qa.textContent=`${date.qa||'—'} • ${fmtPct(date.coverage_pct)}`;
    const needed=new Set();const p=PRESETS[currentPreset];if(p?.mode==='index'){needed.add(p.a);needed.add(p.b2);}else{needed.add(channels.r);needed.add(channels.g);needed.add(channels.b);}
    const loaded={};for(const b of needed){loaded[b]=await loadBand(activePlot.code,month,date.files[b]);if(token!==renderToken)return;}
    const first=loaded[[...needed][0]],w=first.width,h=first.height;const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d');const im=x.createImageData(w,h);const out=im.data;
    for(let i=0;i<w*h;i++){
      let r,g,b,a=255;
      for(const k of needed)a=Math.min(a,loaded[k].alpha[i]);
      if(p?.mode==='index'){
        const va=loaded[p.a].luma[i]/255*.40,vb=loaded[p.b2].luma[i]/255*.40,idx=(va-vb)/(va+vb+1e-6);[r,g,b]=indexColor(idx);
      }else{
        const chan=[loaded[channels.r].luma[i],loaded[channels.g].luma[i],loaded[channels.b].luma[i]];
        const tuned=chan.map(v=>{let q=v/255;q=(q-.5)*contrast+.5;q=clamp(q*brightness,0,1);q=Math.pow(q,1/Math.max(.05,gamma));return Math.round(clamp(q,0,1)*255);});[r,g,b]=tuned;
      }
      const j=i*4;out[j]=r;out[j+1]=g;out[j+2]=b;out[j+3]=a;
    }
    x.putImageData(im,0,0);const url=c.toDataURL('image/png');
    if(overlay&&map.hasLayer(overlay))map.removeLayer(overlay);overlay=L.imageOverlay(url,imageBoundsForPlot(activePlot),{opacity,interactive:false}).addTo(map);
    if(boundary&&map.hasLayer(boundary))map.removeLayer(boundary);boundary=L.geoJSON({type:'Feature',properties:{},geometry:activePlot.geometry},{style:{color:'#34d399',weight:2,fillOpacity:0}}).addTo(map);
    const bounds=boundary.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[35,35],maxZoom:17,animate:false});boundary.bringToFront();
  }

  async function refresh(){if(!activePlot)return;const sel=document.getElementById('spectral-month');if(sel)sel.value=String(currentMonthIndex);await render();}

  document.addEventListener('DOMContentLoaded',()=>{
    injectUI();
    const baseSelect=selectPlot;selectPlot=function(id){baseSelect(id);if(document.getElementById('panel-spectral')?.classList.contains('active'))setTimeout(refresh,0);};
    const baseMonth=setMonthIndex;setMonthIndex=function(i){baseMonth(i);const s=document.getElementById('spectral-month');if(s)s.value=String(currentMonthIndex);if(document.getElementById('panel-spectral')?.classList.contains('active'))setTimeout(refresh,0);};
  });
})();
