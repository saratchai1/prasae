'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const M=require('../pdd22-observations.js');
const good=(green=20,coverage=100)=>({qa:'GOOD',coverage_pct:coverage,green_rai:green,yellow_rai:10,red_rai:5});
const plot=(code='TEST-A',a=30,b=20)=>({code,area_rai:100,fcd_by_month:{'2024-03':good(a),'2026-03':good(b)}});
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {resolve,reject,promise};};
function harness(){
 const events=[],pending=new Map();
 const controller=M.createFrameController({
  load(s){const d=defer();pending.set(s.id,d);return d.promise;},
  commit(s){events.push(['commit',s.id]);},clear(s){events.push(['clear',s.id]);},
  loading(s,old){events.push(['loading',s.id,old?.id]);},failed(s){events.push(['failed',s.id]);}
 });return {controller,events,pending};
}
function frame(events,id){return {dispose(){events.push(['dispose',id]);}};}

test('null, undefined, empty and nonfinite values do not become zero',()=>{
 for(const v of [null,undefined,'','  ','oops',Infinity,NaN])assert.equal(M.number(v),null);
 assert.equal(M.number(0),0);assert.equal(M.number('0'),0);
});
test('QA requires finite coverage and respects declared NO_DATA',()=>{
 assert.equal(M.qa({qa:'GOOD'}),'NO_DATA');assert.equal(M.qa({qa:'NO_DATA',coverage_pct:99}),'NO_DATA');
 assert.equal(M.qa({qa:'GOOD',coverage_pct:94.99}),'LOW_QA');assert.equal(M.qa({qa:'GOOD',coverage_pct:95}),'GOOD');
 assert.notEqual(M.qa({qa:'GOOD',coverage_pct:101}),'GOOD');
});
test('real 18-VSD Sep 2025 counterexample: NDVI 0.5345, coverage 0.81, NO_DATA is not a metric',()=>{
 assert.equal(M.ndvi({qa:'NO_DATA',clear_pixel_pct:.81,mean_ndvi_inside:.5345}),null);
});
test('LOW_QA/PARTIAL values are never whole-plot chart metrics',()=>{
 for(const [qa,coverage] of [['LOW_QA',6.64],['PARTIAL',84.96]])assert.equal(M.ndvi({qa,coverage_pct:coverage,mean_ndvi:.4681}),null);
 assert.equal(M.ndvi({qa:'GOOD',clear_pixel_pct:99.98,mean_ndvi_inside:0}),0);
});
test('FCD requires complete nonnegative class metrics, including legitimate zero',()=>{
 assert.equal(M.goodFcd({...good(),green_rai:null}),false);assert.equal(M.goodFcd({...good(),red_rai:-1}),false);
 assert.equal(M.goodFcd(good(0)),true);
});
test('latest good returns its real month, not requested-month substitution',()=>{
 const p=plot();p.fcd_by_month['2026-08']={...good(50,84),qa:'PARTIAL'};
 assert.equal(M.latestGood(p).month,'2026-03');p.fcd_by_month['2027-03']=good(40);
 assert.equal(M.latestGood(p).month,'2027-03');assert.equal(M.latestGood({}),null);
});
test('FCD comparison classifies a decline without an invented health severity threshold',()=>{
 assert.equal(M.compare(plot(),'2024-03','2026-03').status,'REVIEW');
 assert.equal(M.compare(plot(),'2024-03','2026-03').delta,-10);
 assert.equal(M.compare(plot('B',10,20),'2024-03','2026-03').status,'NO_DECREASE');
});
test('insufficient QA is distinct from change status',()=>{
 const p=plot();p.fcd_by_month['2026-03'].qa='LOW_QA';
 assert.equal(M.compare(p,'2024-03','2026-03').status,'INSUFFICIENT');assert.equal(M.compare(p,'2024-03','2026-03').delta,null);
});
test('same date, reversed chronology and cross-season pairs do not produce deltas',()=>{
 const p=plot();p.fcd_by_month['2026-08']=good(50);
 for(const pair of [['2026-03','2026-03'],['2026-03','2024-03'],['2024-03','2026-08']]){
  const r=M.compare(p,...pair);assert.equal(r.status,'NOT_COMPARABLE');assert.equal(r.delta,null);
 }
});
test('matched-set aggregation uses precisely the same plot IDs on each side',()=>{
 const a=plot('A',30,20),b=plot('B',50,90);b.fcd_by_month['2024-03'].qa='PARTIAL';
 const s=M.summarize([a,b],'2024-03','2026-03');
 assert.equal(s.matchedCount,1);assert.equal(s.beforeGreen,30);assert.equal(s.afterGreen,20);assert.equal(s.delta,-10);
 assert.equal(s.matchedAreaPct,50);assert.equal(s.insufficientCount,1);
});
test('empty or unmatched portfolios show null, not a misleading zero delta',()=>{
 const s=M.summarize([],'2024-03','2026-03');assert.equal(s.delta,null);assert.equal(s.matchedAreaPct,null);
 const p=plot();delete p.fcd_by_month['2026-03'];assert.equal(M.summarize([p],'2024-03','2026-03').beforeGreen,null);
});
test('default pair comes from available FCD dates and maximizes matched plots',()=>{
 const p=plot();p.fcd_by_month['2025-03']=good();p.fcd_by_month['2026-08']=good();
 assert.deepEqual(M.defaultPair([p]),{before:'2024-03',after:'2026-03',count:1});
});
test('image selection uses exact month and never a nearby FCD observation',()=>{
 const p=plot('A / B');const item={month:'2025-06',qa:'GOOD',clear_pixel_pct:100};
 assert.equal(M.asset(p,item,'fcd').state,'NO_FCD');assert.equal(M.asset(p,item,'fcd').url,null);
 assert.match(M.asset(p,item,'gee_rgb').url,/A%20%2F%20B\/2025-06\/rgb\.png$/);
});
test('NO_DATA image paths are not requested even when a numeric metric exists',()=>{
 assert.equal(M.asset(plot(),{month:'2025-09',qa:'NO_DATA',clear_pixel_pct:.81,mean_ndvi_inside:.5345},'gee_ndvi').url,null);
 assert.equal(M.asset(plot(),null,'esri').state,'BASEMAP');
});
test('CSV quotes delimiters/newlines and guards string formulas without corrupting numeric negatives',()=>{
 assert.equal(M.csvCell('a,"b"\nc'),'"a,""b""\nc"');assert.equal(M.csvCell('=SUM(A1)'),'"\'=SUM(A1)"');
 assert.equal(M.csvCell(-10),'"-10"');assert.equal(M.csvCell(null),'""');
});
test('successful frame commits only after load and keeps old displayed metadata while pending',async()=>{
 const h=harness();let a=h.controller.request({id:'A',url:'A'});assert.equal(h.controller.displayed,null);
 h.pending.get('A').resolve(frame(h.events,'A'));await a;
 const b=h.controller.request({id:'B',url:'B'});assert.equal(h.controller.displayed.id,'A');
 assert.deepEqual(h.events.at(-1),['loading','B','A']);
 h.pending.get('B').resolve(frame(h.events,'B'));await b;assert.equal(h.controller.displayed.id,'B');
});
test('failed replacement clears old imagery and old metadata',async()=>{
 const h=harness();const a=h.controller.request({id:'A',url:'A'});h.pending.get('A').resolve(frame(h.events,'A'));await a;
 const b=h.controller.request({id:'B',url:'B'});h.pending.get('B').reject(new Error('HTTP 404'));await b;
 assert.equal(h.controller.displayed,null);assert.deepEqual(h.events.slice(-2),[['clear','B'],['failed','B']]);
});
test('rapid A→B requests dispose stale frames without overwriting B',async()=>{
 const h=harness();const a=h.controller.request({id:'A',url:'A'}),b=h.controller.request({id:'B',url:'B'});
 h.pending.get('B').resolve(frame(h.events,'B'));await b;h.pending.get('A').resolve(frame(h.events,'A'));await a;
 assert.equal(h.controller.displayed.id,'B');assert.ok(h.events.some(e=>e[0]==='dispose'&&e[1]==='A'));
 assert.equal(h.events.filter(e=>e[0]==='commit').length,1);
});
test('a stale failure never clears a newer frame',async()=>{
 const h=harness();const a=h.controller.request({id:'A',url:'A'}),b=h.controller.request({id:'B',url:'B'});
 h.pending.get('B').resolve(frame(h.events,'B'));await b;h.pending.get('A').reject(new Error('late'));await a;
 assert.equal(h.controller.displayed.id,'B');assert.equal(h.events.some(e=>e[0]==='failed'),false);
});
test('NO_DATA or basemap selection cancels pending satellite delivery',async()=>{
 const h=harness();const a=h.controller.request({id:'A',url:'A'});await h.controller.request({id:'none',url:null});
 h.pending.get('A').resolve(frame(h.events,'A'));await a;
 assert.equal(h.controller.displayed,null);assert.deepEqual(h.events.filter(e=>e[0]==='commit'),[['commit','none']]);
});
test('explicit invalidation prevents old plot data arriving after a selection',async()=>{
 const h=harness();const a=h.controller.request({id:'A',url:'A'});h.controller.invalidate();
 h.pending.get('A').resolve(frame(h.events,'A'));await a;assert.equal(h.events.some(e=>e[0]==='commit'),false);
});
test('runtime scripts load once and in dependency order; no dynamic swipe injection',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
 const scripts=[...html.matchAll(/<script src="([^"]+)"/g)].map(m=>m[1].split('?')[0]);
 assert.equal(new Set(scripts).size,scripts.length);
 assert.ok(scripts.indexOf('pdd22-observations.js')<scripts.indexOf('pdd22-production.js'));
 assert.ok(scripts.indexOf('pdd22-production.js')<scripts.indexOf('pdd22-compare-swipe.js'));
 assert.equal(fs.readFileSync(path.join(__dirname,'../pdd22-chart-hotfix.js'),'utf8').includes("createElement('script')"),false);
});
