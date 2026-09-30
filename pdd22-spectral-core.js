/* Browser visualization only. Scientific NDVI/FCD continue to use float source data. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./pdd22-observations.js'));
  else root.Pdd22Spectral=factory(root.Pdd22Observations);
})(typeof globalThis!=='undefined'?globalThis:this,function(M){
  'use strict';
  const BANDS=['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12'];
  const PRESETS={
    truecolor:{label:'ภาพสีจริง',mode:'rgb',bands:['B04','B03','B02']},
    cir:{label:'Color Infrared',mode:'rgb',bands:['B08','B04','B03']},
    rededge:{label:'Red Edge False Color',mode:'rgb',bands:['B8A','B05','B04']},
    swir:{label:'SWIR Agriculture',mode:'rgb',bands:['B11','B08','B02']},
    urban:{label:'SWIR / Bare',mode:'rgb',bands:['B12','B11','B04']},
    moisture_rgb:{label:'NIR–SWIR–Red',mode:'rgb',bands:['B08','B11','B04']},
    ndvi:{label:'NDVI',mode:'index',kind:'nd',bands:['B08','B04'],palette:'vegetation',formula:'(B08 − B04) / (B08 + B04)'},
    ndre:{label:'NDRE',mode:'index',kind:'nd',bands:['B8A','B05'],palette:'vegetation',formula:'(B8A − B05) / (B8A + B05)'},
    ndwi:{label:'NDWI',mode:'index',kind:'nd',bands:['B03','B08'],palette:'water',formula:'(B03 − B08) / (B03 + B08)'},
    mndwi:{label:'MNDWI',mode:'index',kind:'nd',bands:['B03','B11'],palette:'water',formula:'(B03 − B11) / (B03 + B11)'},
    ndmi:{label:'NDMI',mode:'index',kind:'nd',bands:['B08','B11'],palette:'moisture',formula:'(B08 − B11) / (B08 + B11)'},
    evi:{label:'EVI',mode:'index',kind:'evi',bands:['B08','B04','B02'],palette:'vegetation',formula:'2.5 × (B08 − B04) / (B08 + 6B04 − 7.5B02 + 1)'},
    savi:{label:'SAVI',mode:'index',kind:'savi',bands:['B08','B04'],palette:'vegetation',formula:'1.5 × (B08 − B04) / (B08 + B04 + 0.5)'},
    nbr:{label:'NBR',mode:'index',kind:'nd',bands:['B08','B12'],palette:'disturbance',formula:'(B08 − B12) / (B08 + B12)'},
    bsi:{label:'BSI',mode:'index',kind:'bsi',bands:['B11','B04','B08','B02'],palette:'bare',formula:'((B11+B04) − (B08+B02)) / ((B11+B04) + (B08+B02))'}
  };
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  function failure(code){const e=new Error(code);e.code=code;return e;}
  function aborted(signal){if(signal?.aborted)throw signal.reason||failure('ABORTED');}
  function selection(manifest,s){
    if(!manifest||manifest.plot_code!==s.code||manifest.asset_role!=='browser_visualization_only')throw failure('INVALID_PACKAGE');
    const preset=s.preset==='custom'?{label:'Custom RGB',mode:'rgb',bands:[s.channels.r,s.channels.g,s.channels.b]}:PRESETS[s.preset];
    if(!preset||preset.bands.some(b=>!BANDS.includes(b)))throw failure('INVALID_PRESET');
    const date=manifest.dates?.find(d=>d.month===s.month);
    if(!date||date.status!=='available'||M.qa(date)==='NO_DATA')throw failure('NO_DATA');
    const required=[...new Set(preset.bands)];
    for(const b of required){
      if(!manifest.bands?.includes(b)||!date.files?.[b])throw failure('MISSING_BAND');
      // Paths must name this exact observation; never a URL, adjacent month, or traversal.
      if(date.files[b]!==`band_${b}_${s.month}.png`)throw failure('INVALID_BAND_PATH');
    }
    const width=manifest.width,height=manifest.height;
    if(!Number.isSafeInteger(width)||!Number.isSafeInteger(height)||width<1||height<1||width*height>16777216)throw failure('INVALID_DIMENSIONS');
    const min=M.number(manifest.encoding?.reflectance_min),max=M.number(manifest.encoding?.reflectance_max);
    if(min===null||max===null||min!==0||max!==0.4)throw failure('UNSUPPORTED_ENCODING');
    return {preset,required,date,width,height,min,max};
  }
  function validateBands(spec,loaded){
    for(const b of spec.required){const v=loaded[b],size=spec.width*spec.height;
      if(!v||v.width!==spec.width||v.height!==spec.height||v.luma?.length!==size||v.alpha?.length!==size)throw failure('BAND_GRID_MISMATCH');
    }
  }
  const divide=(a,b)=>Math.abs(b)<1e-9?NaN:a/b;
  function indexValue(p,values){
    const R=b=>values[b];
    if(p.kind==='nd')return divide(R(p.bands[0])-R(p.bands[1]),R(p.bands[0])+R(p.bands[1]));
    if(p.kind==='evi')return divide(2.5*(R('B08')-R('B04')),R('B08')+6*R('B04')-7.5*R('B02')+1);
    if(p.kind==='savi')return divide(1.5*(R('B08')-R('B04')),R('B08')+R('B04')+0.5);
    if(p.kind==='bsi')return divide(R('B11')+R('B04')-R('B08')-R('B02'),R('B11')+R('B04')+R('B08')+R('B02'));
    return NaN;
  }
  function color(value,palette){
    const palettes={water:[[180,95,45],[235,235,210],[20,130,255]],moisture:[[190,105,45],[235,220,145],[15,150,175]],disturbance:[[220,55,45],[245,210,70],[30,160,70]],bare:[[35,135,70],[230,220,150],[215,105,45]],vegetation:[[155,85,45],[230,215,95],[25,165,65]]};
    const [neg,mid,pos]=palettes[palette]||palettes.vegetation,v=clamp(value,-1,1);
    const a=v<0?neg:mid,b=v<0?mid:pos,t=v<0?v+1:v;
    return a.map((x,i)=>Math.round(x+(b[i]-x)*t));
  }
  function tune(value,tuning){
    const {brightness,contrast,gamma}=tuning;
    return Math.round(clamp(Math.pow(clamp(((value/255-.5)*contrast+.5)*brightness,0,1),1/gamma),0,1)*255);
  }
  async function compose(spec,loaded,tuning,{signal,yieldControl=()=>new Promise(r=>setTimeout(r,0))}={}){
    validateBands(spec,loaded);
    for(const k of ['brightness','contrast','gamma'])if(!Number.isFinite(tuning[k])||tuning[k]<=0||tuning[k]>3)throw failure('INVALID_TUNING');
    aborted(signal);
    const out=new Uint8ClampedArray(spec.width*spec.height*4),p=spec.preset,values={};
    for(let i=0;i<spec.width*spec.height;i++){
      if(i&&i%32768===0){await yieldControl();aborted(signal);}
      let alpha=255;
      for(const b of spec.required)alpha=Math.min(alpha,loaded[b].alpha[i]);
      if(!alpha)continue;
      let rgb;
      if(p.mode==='index'){
        for(const b of spec.required)values[b]=loaded[b].luma[i]/255*spec.max;
        const value=indexValue(p,values);if(!Number.isFinite(value))continue;
        rgb=color(value,p.palette);
      }else rgb=p.bands.map(b=>loaded[b].luma[i]);
      const j=i*4;out[j]=tune(rgb[0],tuning);out[j+1]=tune(rgb[1],tuning);out[j+2]=tune(rgb[2],tuning);out[j+3]=alpha;
    }
    aborted(signal);return out;
  }
  function createCache(limit=32*1024*1024){
    if(!Number.isSafeInteger(limit)||limit<1)throw failure('INVALID_CACHE_LIMIT');
    const entries=new Map();let bytes=0;
    return {
      get size(){return entries.size;},get bytes(){return bytes;},
      get(key){const entry=entries.get(key);if(!entry)return;entries.delete(key);entries.set(key,entry);return entry.value;},
      set(key,value,size){
        if(!Number.isSafeInteger(size)||size<0)throw failure('INVALID_CACHE_SIZE');
        const old=entries.get(key);if(old){entries.delete(key);bytes-=old.size;}
        if(size>limit)return;
        while(bytes+size>limit){const first=entries.keys().next().value;bytes-=entries.get(first).size;entries.delete(first);}
        entries.set(key,{value,size});bytes+=size;
      },
      clear(){entries.clear();bytes=0;}
    };
  }
  function abortable(promise,signal){
    return new Promise((resolve,reject)=>{
      const abort=()=>reject(signal.reason||failure('ABORTED'));
      // Observe the original promise even when already aborted (no unhandled late rejection).
      promise.then(v=>{signal.removeEventListener('abort',abort);if(!signal.aborted)resolve(v);},e=>{signal.removeEventListener('abort',abort);reject(e);});
      if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});
    });
  }
  function createRunner(hooks){
    let generation=0,controller=null;
    function cancel(){generation++;controller?.abort();controller=null;}
    return {cancel,async run(snapshot){
      cancel();const token=generation,current=()=>token===generation;
      controller=new AbortController();const signal=controller.signal;
      hooks.loading(snapshot);let frame;
      try{frame=await hooks.load(snapshot,signal,current);if(!current()){frame?.dispose?.();return;}hooks.commit(snapshot,frame);}
      catch(error){frame?.dispose?.();if(current())hooks.failed(snapshot,error);}
      finally{if(current())controller=null;}
    }};
  }
  return {BANDS,PRESETS,selection,validateBands,indexValue,compose,createCache,abortable,createRunner,aborted,failure};
});
