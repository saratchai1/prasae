(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AllPlotsCore=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){'use strict';
const MONTHS=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08'];
const THAI={1:'ม.ค.',2:'ก.พ.',3:'มี.ค.',4:'เม.ย.',5:'พ.ค.',6:'มิ.ย.',7:'ก.ค.',8:'ส.ค.',9:'ก.ย.',10:'ต.ค.',11:'พ.ย.',12:'ธ.ค.'};
const number=v=>v===null||v===undefined||String(v).trim()===''?null:Number.isFinite(Number(v))?Number(v):null;
const monthLabel=m=>/^\d{4}-\d{2}$/.test(m||'')?`${THAI[Number(m.slice(5))]} ${Number(m.slice(0,4))+543}`:'—';
const displayCode=p=>{const m=String(p?.name||'').match(/(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])/i);return m?`${Number(m[1])}-${m[2].toUpperCase()}`:String(p?.code||'—');};
const qa=o=>{if(!o||['no_data','insufficient_clear_pixels','not_processed'].includes(o.status))return'NO_DATA';const c=number(o.clear_pixel_pct);if(c===null||c<5)return'NO_DATA';if(c>=95&&c<=100)return'GOOD';if(c>=50)return'PARTIAL';return'LOW_QA';};
const qaThai=q=>({GOOD:'ดี',PARTIAL:'บางส่วน',LOW_QA:'คุณภาพต่ำ',NO_DATA:'ไม่มีข้อมูล'}[q]||String(q||'—'));
const observed=o=>!!o&&['observed_single_scene','observed_monthly_composite'].includes(o.status);
const obs=(p,m)=>(p?.timeseries||[]).find(o=>o.month===m)||null;
const greenPct=o=>number(o?.vegetation_coverage_proxy_pct);
const greenArea=(p,o)=>{const d=number(o?.proxy_area_rai);if(d!==null)return d;const pct=greenPct(o),area=number(p?.area_rai);return pct===null||area===null?null:Math.round(area*pct)/100;};
const waterPct=o=>number(o?.open_water_pct),otherPct=o=>number(o?.open_nonvegetated_pct),ndvi=o=>number(o?.mean_ndvi_inside);
function compare(p,before,after){const a=obs(p,before),b=obs(p,after),aq=qa(a),bq=qa(b),base={plot:p,before,after,beforeObs:a,afterObs:b,beforeQa:aq,afterQa:bq,deltaGreenArea:null,deltaGreenPct:null,deltaNdvi:null};
if(!before||!after||before>=after)return{...base,status:'NOT_COMPARABLE',reason:'เลือกช่วงก่อนให้เก่ากว่าช่วงหลัง'};
if(before.slice(5)!==after.slice(5))return{...base,status:'NOT_COMPARABLE',reason:'ต่างเดือน: ไม่สรุปแนวโน้มข้ามฤดูกาล'};
if(aq!=='GOOD'||bq!=='GOOD')return{...base,status:'INSUFFICIENT',reason:'ข้อมูลไม่พอ: ต้องผ่านเกณฑ์คุณภาพระดับดีทั้งสองช่วง'};
const ga=greenArea(p,a),gb=greenArea(p,b),pa=greenPct(a),pb=greenPct(b),na=ndvi(a),nb=ndvi(b);if([ga,gb,pa,pb].some(v=>v===null))return{...base,status:'INSUFFICIENT',reason:'ข้อมูล Green Cover Proxy ไม่ครบทั้งสองช่วง'};
const da=Math.round((gb-ga)*100)/100,dp=Math.round((pb-pa)*100)/100,dn=na!==null&&nb!==null?Math.round((nb-na)*10000)/10000:null;
return{...base,deltaGreenArea:da,deltaGreenPct:dp,deltaNdvi:dn,status:da<0?'REVIEW':'NO_DECREASE',reason:da<0?'พื้นที่ Green Cover Proxy ลดลง: ควรเปิดภาพตรวจประกอบ':'ไม่พบการลดลงของ Green Cover Proxy ในคู่นี้'};}
function summarize(plots,before,after){const rows=plots.map(p=>compare(p,before,after)),matched=rows.filter(r=>r.deltaGreenArea!==null),totalArea=plots.reduce((s,p)=>s+(number(p.area_rai)||0),0),matchedArea=matched.reduce((s,r)=>s+(number(r.plot.area_rai)||0),0);return{rows,totalArea,matchedArea,matchedCount:matched.length,matchedAreaPct:totalArea?matchedArea/totalArea*100:null,deltaGreenArea:matched.length?Math.round(matched.reduce((s,r)=>s+r.deltaGreenArea,0)*100)/100:null,reviewCount:rows.filter(r=>r.status==='REVIEW').length,insufficientCount:rows.filter(r=>r.status==='INSUFFICIENT').length};}
function defaultPair(plots){const pairs=[];for(const after of MONTHS)for(const before of MONTHS)if(before<after&&before.slice(5)===after.slice(5))pairs.push({before,after,count:summarize(plots,before,after).matchedCount});pairs.sort((a,b)=>b.count-a.count||b.after.localeCompare(a.after)||a.before.localeCompare(b.before));return pairs[0]||{before:MONTHS[0],after:MONTHS.at(-1),count:0};}
const asset=(p,o,layer='rgb')=>!p||!o||!observed(o)||!['rgb','ndvi'].includes(layer)?null:`data/plots/${encodeURIComponent(p.id)}/${layer}_${encodeURIComponent(o.month)}.png`;
const csvCell=value=>{let s=value===null||value===undefined?'':String(value);if(typeof value==='string'&&/^[\s]*[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
const statusThai=s=>({REVIEW:'ควรตรวจการเปลี่ยนแปลง',INSUFFICIENT:'ข้อมูลไม่พอ',NOT_COMPARABLE:'ยังเปรียบเทียบไม่ได้',NO_DECREASE:'ไม่พบการลดลงในคู่นี้'}[s]||String(s||'—'));
return{MONTHS,number,monthLabel,displayCode,qa,qaThai,observed,obs,greenPct,greenArea,waterPct,otherPct,ndvi,compare,summarize,defaultPair,asset,csvCell,statusThai};});