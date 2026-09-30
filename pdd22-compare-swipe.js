/* Atomic Before/After frames: no date substitution, no stale imagery after errors. */
(() => {
  'use strict';
  const M=Pdd22Observations;
  let map=null,boundary=null,frames=null,controller=null,percent=50;
  const el=id=>document.getElementById(id);
  const text=(id,value)=>{if(el(id))el(id).textContent=value;};
  const actualQa=(s,item)=>M.qa(s.mode==='fcd'?s.plot.fcd_by_month[item.month]:item);
  function setPosition(value){
    percent=Math.max(0,Math.min(100,Number(value)||0));
    if(el('pdd22-swipe-divider'))el('pdd22-swipe-divider').style.left=`${percent}%`;
    if(el('compare-position'))el('compare-position').value=String(Math.round(percent));
    const image=frames?.before.overlay.getElement(),stage=el('compare-container');if(!image||!stage)return;
    const rect=image.getBoundingClientRect(),area=stage.getBoundingClientRect();if(!rect.width)return;
    const relative=Math.max(0,Math.min(100,(area.left+area.width*percent/100-rect.left)/rect.width*100));
    image.style.clipPath=`polygon(0 0, ${relative}% 0, ${relative}% 100%, 0 100%)`;
    image.style.webkitClipPath=image.style.clipPath;
  }
  function clear(){frames?.dispose();frames=null;if(boundary&&map.hasLayer(boundary))map.removeLayer(boundary);boundary=null;}
  function showBoundary(plot){
    if(boundary&&map.hasLayer(boundary))map.removeLayer(boundary);
    boundary=L.geoJSON({type:'Feature',properties:{},geometry:plot.geometry},{pane:'pddBoundary',style:{color:'#e2e8f0',weight:2,fillOpacity:0}});
    if(el('comp-boundary-toggle')?.checked!==false)boundary.addTo(map);
    const bounds=boundary.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[38,38],maxZoom:17,animate:false});
  }
  function renderLabels(s,unavailable=false){
    text('comp-label-before',`${Pdd22Ui.monthLabel(s.before.month)} · ${actualQa(s,s.before)}`);
    text('comp-label-after',`${Pdd22Ui.monthLabel(s.after.month)} · ${actualQa(s,s.after)}`);
    text('comp-in-stat-text','—');text('comp-gain-pill','ยังไม่สรุปการเปลี่ยนแปลง');
    if(unavailable)return;
    if(s.mode==='fcd'){
      const result=M.compare(s.plot,s.before.month,s.after.month);
      if(result.delta!==null){
        text('comp-in-stat-text',`FCD เขียว: ${Pdd22Ui.format(s.plot.fcd_by_month[s.before.month].green_rai)} → ${Pdd22Ui.format(s.plot.fcd_by_month[s.after.month].green_rai)} ไร่`);
        text('comp-gain-pill',`Δ ${result.delta>=0?'+':''}${Pdd22Ui.format(result.delta)} ไร่`);
      } else text('comp-in-stat-text',result.reason);
    } else {
      const a=M.ndvi(s.before),b=M.ndvi(s.after);
      if(a===null||b===null)text('comp-in-stat-text','ข้อมูลไม่พอ: NDVI ต้องผ่าน QA GOOD ทั้งสองช่วง');
      else if(s.before.month>=s.after.month||s.before.month.slice(5)!==s.after.month.slice(5))text('comp-in-stat-text','ดูภาพได้ แต่ไม่สรุปแนวโน้ม: ต้องเลือกเดือนเดียวกันต่างปีและเรียงก่อน → หลัง');
      else {text('comp-in-stat-text',`NDVI: ${a.toFixed(3)} → ${b.toFixed(3)}`);text('comp-gain-pill',`Δ ${b-a>=0?'+':''}${(b-a).toFixed(3)}`);}
    }
  }
  window.ensureCompareMaps=function initializeAtomicCompare(){
    if(map)return;
    const stage=el('compare-container');if(!stage)return;
    stage.innerHTML='<div id="pdd22-swipe-map"></div><div id="comp-label-before" class="pdd22-swipe-label before">ก่อน</div><div id="comp-label-after" class="pdd22-swipe-label after">หลัง</div><div id="pdd22-swipe-divider"><button type="button" id="pdd22-swipe-handle" aria-label="เลื่อนเส้นเปรียบเทียบ">↔</button></div><div id="compare-loading" role="status" aria-live="polite"></div><label class="compare-range-label">เส้นเปรียบเทียบ<input id="compare-position" type="range" min="0" max="100" value="50"></label>';
    map=L.map('pdd22-swipe-map',{scrollWheelZoom:false}).setView([12.75,101.8],15);
    L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(map);
    [['pddAfter',410],['pddBefore',420],['pddBoundary',430]].forEach(([name,z])=>{map.createPane(name);map.getPane(name).style.zIndex=z;});
    map.on('zoom move resize',()=>requestAnimationFrame(()=>setPosition(percent)));
    el('compare-position').oninput=e=>setPosition(e.target.value);
    const handle=el('pdd22-swipe-handle');let dragging=false;
    handle.onpointerdown=e=>{dragging=true;map.dragging.disable();handle.setPointerCapture(e.pointerId);e.preventDefault();};
    handle.onpointermove=e=>{if(dragging){const r=stage.getBoundingClientRect();setPosition((e.clientX-r.left)/r.width*100);}};
    handle.onpointerup=handle.onpointercancel=()=>{dragging=false;map.dragging.enable();};
    handle.onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();setPosition(percent+(e.key==='ArrowRight'?5:-5));}};
    controller=M.createFrameController({
      async load(s,current){
        const results=await Promise.allSettled([
          M.loadLeafletFrame(L,map,{url:s.beforeUrl,bounds:s.bounds},current,{pane:'pddBefore'}),
          M.loadLeafletFrame(L,map,{url:s.afterUrl,bounds:s.bounds},current,{pane:'pddAfter'})
        ]);
        const failure=results.find(r=>r.status==='rejected');
        if(failure){results.forEach(r=>{if(r.status==='fulfilled')r.value.dispose();});throw failure.reason;}
        const before=results[0].value,after=results[1].value;
        return {before,after,dispose(){before.dispose();after.dispose();}};
      },
      loading(s,displayed){stage.setAttribute('aria-busy','true');text('compare-loading',`กำลังโหลด ${s.plot.code} · ${Pdd22Ui.monthLabel(s.before.month)} → ${Pdd22Ui.monthLabel(s.after.month)}${displayed?' — ภาพและค่าที่เห็นยังเป็นคู่ก่อนหน้า':''}`);},
      commit(s,next){
        stage.setAttribute('aria-busy','false');
        if(next){const old=frames;frames=next;setPosition(percent);next.after.overlay.setOpacity(.94);next.before.overlay.setOpacity(.94);old?.dispose();}
        showBoundary(s.plot);renderLabels(s,!next);
        text('compare-loading',next?`${s.plot.code} · ${s.mode.toUpperCase()} · ภาพตรงกับวันที่ของแต่ละฝั่ง`:'ไม่มีภาพที่ใช้ได้ครบทั้งสองฝั่ง — ไม่ใช้เดือนอื่นหรือภาพเก่าแทน');
        requestAnimationFrame(()=>{map.invalidateSize();setPosition(percent);});
      },
      clear,
      failed(s){stage.setAttribute('aria-busy','false');showBoundary(s.plot);renderLabels(s,true);text('compare-loading','โหลดภาพไม่สำเร็จ — ล้างภาพเก่าทั้งสองฝั่งแล้ว');const b=document.createElement('button');b.type='button';b.textContent='ลองใหม่';b.onclick=()=>updateCompareView();el('compare-loading').append(' ',b);}
    });
    const hint=document.querySelector('.compare-hint');if(hint)hint.textContent='เลื่อนเส้นหรือใช้ปุ่มลูกศรเพื่อเปรียบเทียบ · Esri เป็นภาพพื้นหลังไม่อิงเดือน · same-month QA GOOD ยังไม่ใช่การจับคู่ระดับน้ำหรือการยืนยันภาคสนาม';
  };
  window.updateCompareView=function requestAtomicComparison(){
    if(!activePlot)return;ensureCompareMaps();if(!controller)return;
    const mode=el('comp-mode-select').value;
    const layer=mode==='fcd'?'fcd':mode==='ndvi'?'gee_ndvi':'gee_rgb';
    const rightLayer=mode==='rgb_vs_ndvi'?'gee_ndvi':layer;
    const left=el('comp-left-select'),right=el('comp-right-select');
    [left,right].forEach((select,side)=>Array.from(select.options).forEach(o=>{
      const item=activePlot.timeseries[Number(o.value)],spec=M.asset(activePlot,item,side?rightLayer:layer);
      o.disabled=spec.state!=='AVAILABLE';
      o.textContent=`${Pdd22Ui.monthLabel(item.month)} · ${M.qa(mode==='fcd'?activePlot.fcd_by_month[item.month]:item)}${o.disabled?' · ไม่มีภาพที่ใช้ได้':''}`;
    }));
    const before=activePlot.timeseries[Number(left.value)],after=activePlot.timeseries[Number(right.value)];if(!before||!after)return;
    const a=M.asset(activePlot,before,layer),b=M.asset(activePlot,after,rightLayer);
    const available=a.state==='AVAILABLE'&&b.state==='AVAILABLE';
    const legend=el('comp-ndvi-legend');if(legend)legend.hidden=mode!=='ndvi'&&mode!=='rgb_vs_ndvi';
    comparePlotId=activePlot.id;
    return controller.request({plot:activePlot,before,after,mode,state:available?'AVAILABLE':'NO_DATA',url:available?'pair':null,
      beforeUrl:a.url?`${a.url}?v=20260826-1405`:null,afterUrl:b.url?`${b.url}?v=20260826-1405`:null,bounds:imageBoundsForPlot(activePlot)});
  };
  window.toggleCompareBoundary=function toggleBoundary(show){if(!map||!boundary)return;if(show)boundary.addTo(map);else if(map.hasLayer(boundary))map.removeLayer(boundary);};
})();
