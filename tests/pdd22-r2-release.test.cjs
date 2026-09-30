'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const S=require('../pdd22-spectral-core.js');
const snapshot={code:'TEST',month:'2026-03',preset:'truecolor',channels:{r:'B04',g:'B03',b:'B02'}};
const manifest=()=>({plot_code:'TEST',asset_role:'browser_visualization_only',width:2,height:1,bands:S.BANDS.slice(),encoding:{reflectance_min:0,reflectance_max:.4},dates:[{month:'2026-03',status:'available',qa:'GOOD',coverage_pct:100,files:Object.fromEntries(S.BANDS.map(b=>[b,`band_${b}_2026-03.png`]))}]});
const tuning={brightness:1,contrast:1,gamma:1};
const pixels=spec=>Object.fromEntries(spec.required.map(b=>[b,{width:2,height:1,luma:new Uint8Array([120,0]),alpha:new Uint8Array([255,0])}]));

test('15 supported presets and ten distinct bands',()=>{assert.equal(Object.keys(S.PRESETS).length,15);assert.equal(new Set(S.BANDS).size,10);});
test('exact identity, month, file and encoding are mandatory',()=>{
 for(const mutate of [m=>m.plot_code='OTHER',m=>m.dates[0].files.B04='../bad.png',m=>m.encoding.reflectance_max=1,m=>m.width=0]){const m=manifest();mutate(m);assert.throws(()=>S.selection(m,snapshot));}
 assert.throws(()=>S.selection(manifest(),{...snapshot,month:'2025-03'}),/NO_DATA/);
});
test('NO_DATA cannot masquerade as available; partial stays viewable',()=>{const m=manifest();m.dates[0].qa='NO_DATA';assert.throws(()=>S.selection(m,snapshot),/NO_DATA/);m.dates[0].qa='PARTIAL';m.dates[0].coverage_pct=80;assert.equal(S.selection(m,snapshot).date.qa,'PARTIAL');});
test('unrelated missing band does not disable RGB',()=>{const m=manifest();delete m.dates[0].files.B12;assert.ok(S.selection(m,snapshot));assert.throws(()=>S.selection(m,{...snapshot,preset:'nbr'}),/MISSING_BAND/);});
test('all presets compose typed RGBA and preserve invalid alpha',async()=>{
 for(const preset of Object.keys(S.PRESETS)){const spec=S.selection(manifest(),{...snapshot,preset});const rgba=await S.compose(spec,pixels(spec),tuning);assert.equal(rgba.length,8);assert.equal(rgba[3],255);assert.equal(rgba[7],0);}
});
test('undefined index division stays transparent rather than a fake zero',async()=>{const spec=S.selection(manifest(),{...snapshot,preset:'ndvi'}),loaded=pixels(spec);for(const p of Object.values(loaded))p.luma.fill(0);const out=await S.compose(spec,loaded,tuning);assert.equal(out[3],0);});
test('mixed pixel grids and invalid tuning are rejected',async()=>{const spec=S.selection(manifest(),snapshot),loaded=pixels(spec);loaded.B03.width=3;await assert.rejects(S.compose(spec,loaded,tuning),/BAND_GRID_MISMATCH/);await assert.rejects(S.compose(spec,pixels(spec),{...tuning,gamma:0}),/INVALID_TUNING/);});
test('cache is bounded and least-recently-used entries expire',()=>{const c=S.createCache(8);c.set('a',1,4);c.set('b',2,4);assert.equal(c.get('a'),1);c.set('c',3,4);assert.equal(c.get('b'),undefined);assert.equal(c.bytes,8);c.set('huge',4,9);assert.equal(c.get('huge'),undefined);c.clear();assert.equal(c.bytes,0);});
test('abort rejects compositing and watches late promise rejection',async()=>{const a=new AbortController();a.abort();const spec=S.selection(manifest(),snapshot);await assert.rejects(S.compose(spec,pixels(spec),tuning,{signal:a.signal}));await assert.rejects(S.abortable(Promise.reject(new Error('late')),a.signal));});
test('runner commits only the newest request and disposes a stale frame',async()=>{let completeA;const log=[];const runner=S.createRunner({loading(){},load(s){if(s.id==='a')return new Promise(r=>completeA=r);return Promise.resolve({dispose(){log.push('dispose-b');}});},commit(s){log.push(s.id);},failed(){log.push('fail');}});const a=runner.run({id:'a'});await runner.run({id:'b'});completeA({dispose(){log.push('dispose-a');}});await a;assert.deepEqual(log,['b','dispose-a']);});
test('HTML loads shared core before viewer once and keeps the production baseline',()=>{const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');const scripts=[...html.matchAll(/<script src="([^"]+)"/g)].map(m=>m[1].split('?')[0]);assert.equal(new Set(scripts).size,scripts.length);assert.ok(scripts.indexOf('pdd22-observations.js')<scripts.indexOf('pdd22-spectral-core.js'));assert.ok(scripts.indexOf('pdd22-spectral-core.js')<scripts.indexOf('pdd22-spectral-studio.js'));});
