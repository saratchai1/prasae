/* One registry identity per plot. PDD participating scope is not an extra plot. */
(function(root,factory){
  const node=typeof module==='object'&&module.exports;
  const api=factory(node?require('./all-plots-core.js'):root.AllPlotsCore,node?require('./pdd22-observations.js'):root.Pdd22Observations);
  if(node)module.exports=api;else root.UnifiedData=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(C,M){
  'use strict';
  const number=M.number;
  const labels={REVIEW:'ควรตรวจการเปลี่ยนแปลง',NO_DECREASE:'ไม่พบการลดลงในคู่นี้',INSUFFICIENT:'ข้อมูลไม่พอ',NOT_COMPARABLE:'ยังเปรียบเทียบไม่ได้',ATMOSPHERE_REVIEW:'ต้องตรวจเมฆ / หมอก',TIDE_WATER_REVIEW:'ต้องตรวจสภาพน้ำ',VISUAL_REVIEW:'ต้องตรวจภาพเพิ่มเติม',RADIOMETRY_REVIEW:'ต้องตรวจความสอดคล้องสูตรสะท้อนแสง',MISSING_ANALYSIS:'ยังไม่มีผลวิเคราะห์ชนิดนี้'};
  const reviewStatuses=new Set(['ATMOSPHERE_REVIEW','TIDE_WATER_REVIEW','VISUAL_REVIEW','RADIOMETRY_REVIEW']);
  const method=p=>p.scope==='pdd'?'FCD_EQUIVALENT':'GREEN_COVER_PROXY';
  const methodLabel=p=>p.scope==='pdd'?'FCD พื้นที่เทียบเท่า PDD':'พื้นที่พืชโดยประมาณ (Green Cover Proxy)';
  const scopeLabel=p=>p.scope==='pdd'?'พื้นที่เข้าร่วม PDD':'ขอบเขตทะเบียนแปลง';
  const observation=(p,m)=>p?.timeseries?.find(o=>o.month===m)||null;
  function parseCsv(source){
    const rows=[];let row=[],field='',quoted=false;
    const s=source.replace(/^\uFEFF/,'');
    for(let i=0;i<s.length;i++){
      const c=s[i];
      if(c==='"'){if(quoted&&s[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}
      else if(c===','&&!quoted){row.push(field);field='';}
      else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&s[i+1]==='\n')i++;row.push(field);if(row.some(Boolean))rows.push(row);row=[];field='';}
      else field+=c;
    }
    if(quoted)throw new Error('Invalid CSV quoting');
    row.push(field);if(row.some(Boolean))rows.push(row);
    const headers=rows.shift()||[];return rows.map(r=>Object.fromEntries(headers.map((h,i)=>[h,r[i]??''])));
  }
  function merge(catalog,verified,pddCatalog,fcd,coverage,visualQa){
    if(!Array.isArray(catalog)||!Array.isArray(verified)||!Array.isArray(pddCatalog))throw new Error('Invalid registry dataset');
    const ids=new Set(), byVerified=new Map(verified.map(p=>[Number(p.id),p]));
    const byPdd=new Map(pddCatalog.map(p=>[p.code,p]));
    const byFcd=new Map(fcd.map(p=>[p.code,p]));
    const byCoverage=new Map(coverage.map(r=>[`${r.plot_code}|${r.month}`,r]));
    const businessCounts=new Map();catalog.forEach(c=>{const code=C.displayCode(c);businessCounts.set(code,(businessCounts.get(code)||0)+1);});
    const masters=catalog.map(c=>{
      const id=Number(c.id), code=C.displayCode(c),v=byVerified.get(id)||{};
      if(!Number.isInteger(id)||ids.has(id)||!c.geometry||!Array.isArray(c.bounds)||number(c.area_rai)===null)throw new Error('Invalid or duplicate registry plot');
      ids.add(id);
      const common={...c,id,registryId:id,registryCode:c.code,registryArea:Number(c.area_rai),code,name:code,fullName:c.name,province:c.province||'ไม่ระบุ'};
      const registry={...common,scope:'registry',fcd_by_month:{},green_proxy_threshold:v.green_proxy_threshold,
        timeseries:C.MONTHS.map(month=>{
          const source=v.timeseries?.find(o=>o.month===month)||{status:'no_data',clear_pixel_pct:null};
          return {...source,month,year:Number(month.slice(0,4)),month_num:Number(month.slice(5)),
            secondary:visualQa?.observations?.[`${id}|${month}`]||{status:'INSUFFICIENT',reason:'ยังไม่มีผลตรวจคุณภาพภาพเพิ่มเติม'}};
        })};
      const pc=businessCounts.get(code)===1?byPdd.get(code):null;
      let pdd=null;
      if(pc){
        if(pc.province!==common.province)throw new Error(`PDD province mismatch: ${code}`);
        pdd={...common,...pc,id,registryId:id,registryCode:c.code,registryArea:Number(c.area_rai),name:code,fullName:c.name,scope:'pdd',
          fcd_by_month:Object.fromEntries((byFcd.get(code)?.observations||[]).map(o=>[o.month,o])),
          timeseries:C.MONTHS.map(month=>{
            const r=byCoverage.get(`${code}|${month}`)||{};
            const related=registry.timeseries.find(o=>o.month===month)?.secondary;
            return {month,year:Number(month.slice(0,4)),month_num:Number(month.slice(5)),qa:r.qa||'NO_DATA',status:r.qa||'NO_DATA',
              clear_pixel_pct:number(r.coverage_pct),mean_ndvi_inside:number(r.mean_ndvi),median_ndvi_inside:number(r.median_ndvi),
              analysis_mode:r.analysis_mode||'no_data',scenes_used:number(r.scene_count)||0,
              secondary:related?.status!=='RADIOMETRY_REVIEW'&&reviewStatuses.has(related?.status)?{...related,reason:`ต้องตรวจภาพบริเวณเดียวกันเพิ่มเติม: ${related.reason}`}:{status:'COVERAGE_ONLY',reason:'QA ของ PDD เป็นความครอบคลุมภาพ ไม่ใช่การยืนยันสภาพจริงภาคสนาม'}};
          })};
      }
      return {id,code,registry,pdd};
    });
    for(const pc of pddCatalog)if(!masters.some(m=>m.pdd?.code===pc.code))throw new Error(`Unresolved PDD identity: ${pc.code}`);
    return masters;
  }
  function quality(p,o){
    const base=p.scope==='pdd'?M.qa(o):(C.observed(o)?C.qa(o):'NO_DATA');
    const secondary=o?.secondary||{status:'INSUFFICIENT'};
    const review=reviewStatuses.has(secondary.status);
    const eligible=base==='GOOD'&&!review&&(p.scope==='pdd'||secondary.status==='CLEAR');
    return {base,secondary:secondary.status,eligible,status:review?secondary.status:eligible?'GOOD':'INSUFFICIENT',
      label:review?labels[secondary.status]:eligible?(p.scope==='pdd'?'ผ่านเกณฑ์ความครอบคลุม':'ผ่านเกณฑ์คัดกรองภาพ'):'ข้อมูลไม่พอ',reason:secondary.reason||'ยังไม่ผ่านการตรวจคุณภาพภาพ'};
  }
  function green(p,o){
    if(!o||!quality(p,o).eligible)return null;
    return p.scope==='pdd'?(M.goodFcd(p.fcd_by_month[o.month])?number(p.fcd_by_month[o.month].green_rai):null):C.greenArea(p,o);
  }
  function greenPct(p,o){const area=green(p,o);return area===null||!p.area_rai?null:area/p.area_rai*100;}
  function ndvi(p,o){return quality(p,o).eligible?number(o?.mean_ndvi_inside):null;}
  function compare(p,before,after,requireFcd=false){
    const a=observation(p,before),b=observation(p,after),qa=quality(p,a),qb=quality(p,b);
    const base={plot:p,before,after,a,b,qa,qb,method:method(p),delta:null,deltaNdvi:null,status:'INSUFFICIENT',reason:'ข้อมูลไม่พอสำหรับการเปรียบเทียบ'};
    if(!before||!after||before>=after)return {...base,status:'NOT_COMPARABLE',reason:'เลือกช่วงก่อนให้เก่ากว่าช่วงหลัง'};
    if(before.slice(5)!==after.slice(5))return {...base,status:'NOT_COMPARABLE',reason:'ดูภาพได้ แต่ไม่สรุปการเปลี่ยนแปลงข้ามฤดูกาล'};
    if(requireFcd&&p.scope!=='pdd')return {...base,status:'MISSING_ANALYSIS',reason:'ยังไม่ได้ประมวลผล FCD สำหรับขอบเขตนี้ ไม่ใช้ค่า Proxy แทน FCD'};
    const flagged=[qa,qb].find(q=>reviewStatuses.has(q.status));
    if(flagged)return {...base,status:flagged.status,reason:flagged.reason};
    if(!qa.eligible||!qb.eligible)return base;
    const x=green(p,a),y=green(p,b),na=ndvi(p,a),nb=ndvi(p,b);
    if(x===null||y===null)return {...base,status:'MISSING_ANALYSIS',reason:'ยังไม่มีผลวิเคราะห์ที่เปรียบเทียบได้ครบทั้งสองช่วง'};
    const delta=Math.round((y-x)*100)/100;
    return {...base,delta,deltaNdvi:na===null||nb===null?null:Math.round((nb-na)*10000)/10000,
      status:delta<0?'REVIEW':'NO_DECREASE',reason:delta<0?'ค่าพื้นที่กลุ่มพืชลดลง ควรเปิดภาพตรวจ ไม่ใช่การยืนยันป่าเสียหาย':'ไม่พบการลดลงของค่าพื้นที่กลุ่มพืชในคู่นี้'};
  }
  function summarize(plots,before,after){
    const rows=plots.map(p=>compare(p,before,after));
    const totals={};
    for(const r of rows){const t=totals[r.method]||(totals[r.method]={count:0,delta:null});if(r.delta!==null){t.count++;t.delta=Math.round(((t.delta||0)+r.delta)*100)/100;}}
    return {rows,totals,matched:rows.filter(r=>r.delta!==null).length,review:rows.filter(r=>r.status==='REVIEW').length,
      qualityReview:rows.filter(r=>reviewStatuses.has(r.status)).length,insufficient:rows.filter(r=>r.delta===null).length};
  }
  function asset(p,o,layer){
    if(layer==='esri')return {state:'BASEMAP',url:null};
    if(!p||!o)return {state:'NO_DATA',url:null};
    if(layer==='fcd'){
      if(p.scope!=='pdd')return {state:'MISSING_ANALYSIS',url:null};
      return M.asset(p,o,'fcd');
    }
    if(!['gee_rgb','gee_ndvi','rgb','ndvi'].includes(layer))throw new Error('Unknown layer');
    const kind=layer.includes('ndvi')?'ndvi':'rgb';
    if(p.scope==='pdd')return M.asset(p,o,kind==='rgb'?'gee_rgb':'gee_ndvi');
    const path=C.asset({id:p.registryId},o,kind);
    if(!path||quality(p,o).base==='NO_DATA')return {state:'NO_DATA',url:null};
    return {state:'AVAILABLE',url:path};
  }
  return {number,labels,reviewStatuses,method,methodLabel,scopeLabel,observation,parseCsv,merge,quality,green,greenPct,ndvi,compare,summarize,asset,monthLabel:C.monthLabel,csvCell:M.csvCell};
});
