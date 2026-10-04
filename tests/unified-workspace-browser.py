#!/usr/bin/env python3
import os,threading,json,io
from PIL import Image,ImageChops
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];PORT=8791
class H(SimpleHTTPRequestHandler):
 def log_message(self,*a):pass
os.chdir(R);s=ThreadingHTTPServer(('127.0.0.1',PORT),H);threading.Thread(target=s.serve_forever,daemon=True).start()
checks=[]
try:
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox'])
  page=b.new_page(viewport={'width':1440,'height':950})
  page_errors=[]
  page.on('pageerror',lambda error:page_errors.append(str(error)))
  transparent=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082')
  page.route('https://server.arcgisonline.com/**',lambda r:r.fulfill(status=200,content_type='image/png',body=transparent))
  page.route('https://fonts.googleapis.com/**',lambda r:r.abort());page.route('https://fonts.gstatic.com/**',lambda r:r.abort())
  page.goto(f'http://127.0.0.1:{PORT}/index.html',wait_until='domcontentloaded',timeout=30000)
  page.wait_for_function('window.UnifiedWorkspace && document.querySelectorAll("#plot-list-container .plot-card-item").length===210',timeout=30000)
  assert page.locator('#sidebar-count-display').inner_text().startswith('แสดง 210 จาก 210')
  assert page.locator('#wtab-allplots').count()==0
  assert '210 แปลง' in page.locator('.brand-title').inner_text()
  checks.append('single workspace lists exactly 210 registry identities')

  page.locator('#plot-search-input').fill('13-VSD')
  page.wait_for_function('document.querySelectorAll("#plot-list-container .plot-card-item").length===1')
  assert '13-VSD' in page.locator('#plot-list-container').inner_text()
  page.locator('#plot-search-input').fill('')
  page.select_option('#province-filter','ระยอง')
  page.wait_for_function('document.querySelectorAll("#plot-list-container .plot-card-item").length===11')
  page.select_option('#province-filter','ALL')
  page.wait_for_function('document.querySelectorAll("#plot-list-container .plot-card-item").length===210')
  checks.append('sidebar search and province filter preserve registry identities')

  # PDD identity exists once and exposes optional PDD scope.
  pdd=page.evaluate('()=>UnifiedWorkspace.masters.find(m=>m.pdd).id')
  page.evaluate('(id)=>selectPlot(id)',pdd)
  assert page.locator('#analysis-scope-select option[value="pdd"]').is_enabled()
  registry_area=page.locator('#kpi-current-plot-sub').inner_text()
  page.select_option('#analysis-scope-select','pdd')
  pdd_area=page.locator('#kpi-current-plot-sub').inner_text()
  assert registry_area!=pdd_area and 'พื้นที่เข้าร่วม PDD' in pdd_area
  assert page.locator('[data-layer="fcd"]').is_enabled()
  checks.append('PDD plot remains one identity with explicit registry/PDD scope switch')

  # non-PDD cannot accidentally use FCD.
  non=page.evaluate('()=>UnifiedWorkspace.masters.find(m=>!m.pdd).id')
  page.evaluate('(id)=>selectPlot(id)',non)
  assert page.locator('[data-layer="fcd"]').is_disabled()
  assert 'ขอบเขตทะเบียนแปลง' in page.locator('#kpi-current-plot-sub').inner_text()
  checks.append('non-PDD plot uses registry scope and FCD is disabled')

  # actual RGB path loads for selected registry plot on a known observed month
  pid=page.evaluate('''()=>{for(const m of UnifiedWorkspace.masters){const o=m.registry.timeseries.find(x=>x.month==="2024-03");if(o&&AllPlotsCore.observed(o))return m.id}return null}''')
  page.evaluate('(id)=>selectPlot(id)',pid);page.evaluate('setMonthIndex(2);setPlotMapLayer("gee_rgb")')
  page.wait_for_timeout(500)
  assert 'Sentinel-2' in page.locator('.stage-hud.top-right .hud-tag').inner_text()
  checks.append('registry plot uses same per-plot map viewer with Sentinel-2 RGB')

  # Newly ingested low-coverage observations have real imagery, while chart
  # metrics remain null until they satisfy the portfolio comparison QA gate.
  report_path=R/'audit-artifacts/local-satellite-ingest/ingest_result.json'
  if report_path.exists():
   accepted=[r for r in json.loads(report_path.read_text())['records'] if r['result']=='ACCEPTED']
   for rec in accepted:
    month_index=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08'].index(rec['month'])
    page.evaluate('(id)=>selectPlot(id)',rec['plot_id'])
    assert page.evaluate('()=>plotNdviChart.data.labels.length')==12
    if rec['coverage_pct']<95:
     assert page.evaluate('(i)=>plotNdviChart.data.datasets[0].data[i]',month_index) is None
     assert page.evaluate('(i)=>plotNdviChart.data.datasets[1].data[i]',month_index) is None
     assert page.evaluate('()=>plotNdviChart.data.datasets[0].spanGaps') is False
    for layer,prefix in [('gee_rgb','rgb'),('gee_ndvi','ndvi')]:
     path=f"data/plots/{rec['plot_id']}/{prefix}_{rec['month']}.png"
     with page.expect_response(lambda response: path in response.url and response.status==200):
      page.evaluate('([i,layer])=>{setMonthIndex(i);setPlotMapLayer(layer)}',[month_index,layer])
     page.wait_for_function('(path)=>Array.from(document.querySelectorAll("img.sentinel-overlay")).some(im=>im.src.includes(path)&&im.complete&&im.naturalWidth>0)',arg=path)
   checks.append('new local RGB/NDVI loads for its exact month; low coverage stays excluded from charts')

  # A PDD-only crop must leave the registry slot missing and must not substitute
  # either the participating footprint or an adjacent month.
  missing=page.evaluate('''()=>{for(const m of UnifiedWorkspace.masters){const o=m.registry.timeseries.find(x=>!AllPlotsCore.observed(x));if(o)return {id:m.id,index:m.registry.timeseries.indexOf(o)}}return null}''')
  page.evaluate('(id)=>selectPlot(id)',missing['id'])
  page.evaluate('(i)=>{setMonthIndex(i);setPlotMapLayer("gee_rgb")}',missing['index'])
  page.wait_for_function('document.querySelector(".stage-hud.top-right .hud-sub").innerText.includes("ไม่มีภาพที่ใช้ได้ในเดือนนี้")')
  assert page.evaluate('()=>UnifiedData.asset(activePlot,activePlot.timeseries[currentMonthIndex],"gee_rgb").state')=='NO_DATA'
  assert page.evaluate('()=>plotNdviChart.data.datasets[0].data[currentMonthIndex]') is None
  checks.append('missing registry months remain missing in viewer and chart')

  # GIS has 210 layers and table 210 rows.
  page.locator('#wtab-map').click();page.wait_for_timeout(200)
  assert page.evaluate('()=>thailandGeojsonLayer.getLayers().length')==210
  page.locator('#wtab-table').click();assert page.locator('#table-body tr').count()==210
  checks.append('GIS and analysis table both cover 210 plots')

  # A single geographic transform, independently clipped before/after imagery,
  # and real pointer/keyboard interaction. Use production PNG bytes.
  compare_plot=page.evaluate('''()=>UnifiedWorkspace.masters.find(m=>m.registry.code==='35-STC').id''')
  page.evaluate('(id)=>selectPlot(id)',compare_plot)
  page.locator('#wtab-compare').click()
  page.select_option('#comp-left-select','6');page.select_option('#comp-right-select','11')
  page.select_option('#comp-mode-select','rgb_vs_ndvi')
  page.wait_for_function('''()=>document.querySelector("#compare-container").getAttribute("aria-busy")==="false"&&
   document.querySelector(".compare-before-raster")?.src.includes("rgb_2025-03")&&
   document.querySelector(".compare-after-raster")?.src.includes("ndvi_2026-08")''')
  assert page.locator('#unified-compare-map').count()==1
  assert page.locator('#compare-map-left,#compare-map-right').count()==0
  assert 'ก่อน' in page.locator('#comp-label-before').inner_text() and 'RGB' in page.locator('#comp-label-before').inner_text()
  assert 'หลัง' in page.locator('#comp-label-after').inner_text() and 'NDVI' in page.locator('#comp-label-after').inner_text()
  bounds=page.evaluate('()=>[compareLeftOverlay.getBounds().toBBoxString(),compareRightOverlay.getBounds().toBBoxString()]')
  assert bounds[0]==bounds[1]
  stage=page.locator('#unified-compare-map').bounding_box()
  handle=page.locator('#unified-compare-handle')
  for target in [.25,.75]:
   box=handle.bounding_box();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
   page.mouse.down();page.mouse.move(stage['x']+stage['width']*target,box['y']+box['height']/2,steps=8);page.mouse.up()
   assert abs(float(page.locator('#compare-position').input_value())-target*100)<1
   assert page.evaluate('()=>compareLeftMap.dragging.enabled()')
  handle.focus();page.keyboard.press('ArrowLeft');assert float(page.locator('#compare-position').input_value())<75
  checks.append('before/after uses aligned exact-month rasters; handle drags both ways and supports keyboard')

  def position(value):
   page.locator('#compare-position').evaluate('(range,value)=>{range.value=value;range.dispatchEvent(new Event("input",{bubbles:true}))}',value)
   page.wait_for_timeout(50)
  def capture():
   return Image.open(io.BytesIO(page.locator('#unified-compare-map').screenshot())).convert('RGB')
  # Pixel proof: at the midpoint the left region equals the all-before view,
  # and the right region equals the all-after view. Both regions must differ
  # from the opposite date/layer. This catches stacked, unclipped maps.
  position('0');after_image=capture()
  position('100');before_image=capture()
  position('50');split_image=capture()
  w,h=split_image.size
  regions={'left':(int(w*.1),int(h*.24),int(w*.40),int(h*.68)),
           'right':(int(w*.60),int(h*.24),int(w*.9),int(h*.68))}
  for side,expected,other in [('left',before_image,after_image),('right',after_image,before_image)]:
   box=regions[side]
   assert ImageChops.difference(split_image.crop(box),expected.crop(box)).getbbox() is None,side
   assert ImageChops.difference(split_image.crop(box),other.crop(box)).getbbox() is not None,side
  checks.append('rendered left pixels are before RGB and right pixels are after NDVI')
  artifact_dir=os.getenv('PRASAE_BROWSER_ARTIFACT_DIR')
  if artifact_dir:
   artifacts=Path(artifact_dir);artifacts.mkdir(parents=True,exist_ok=True)
   page.locator('#panel-compare').screenshot(path=str(artifacts/'before-after-split.png'))

  def check_clipping():
   assert page.evaluate('''()=>{
    const area=document.querySelector('#unified-compare-map').getBoundingClientRect(),split=area.left+area.width*.5;
    return ['.compare-before-raster','.compare-after-raster'].every(selector=>{
     const image=document.querySelector(selector),rect=image.getBoundingClientRect();
     const values=image.style.clipPath.match(/[0-9.]+%/g);if(!values)return false;
     const actual=parseFloat(values[0]),expected=Math.max(0,Math.min(100,(split-rect.left)/rect.width*100));
     return Math.abs(actual-expected)<.01;
    });
   }''')
  page.locator('#unified-compare-map .leaflet-control-zoom-in').click();page.wait_for_timeout(100)
  check_clipping()
  map_view=page.evaluate('()=>compareLeftMap.getCenter()')
  page.mouse.move(stage['x']+stage['width']*.20,stage['y']+stage['height']*.35);page.mouse.down()
  page.mouse.move(stage['x']+stage['width']*.30,stage['y']+stage['height']*.45,steps=8);page.mouse.up();page.wait_for_timeout(300)
  assert page.evaluate('()=>compareLeftMap.getCenter()')!=map_view
  check_clipping()
  boundary_count=page.locator('#unified-compare-map .leaflet-unifiedCompareBoundary-pane path').count()
  assert boundary_count>0
  page.locator('#comp-boundary-toggle').uncheck();assert page.locator('#unified-compare-map .leaflet-unifiedCompareBoundary-pane path').count()==0
  page.locator('#comp-boundary-toggle').check();assert page.locator('#unified-compare-map .leaflet-unifiedCompareBoundary-pane path').count()==boundary_count
  checks.append('divider stays aligned during zoom/pan; boundary toggle works')

  # Index zero is a valid right-hand date, not a falsy fallback to month 11.
  page.select_option('#comp-right-select','0')
  page.wait_for_function('''()=>document.querySelector('#compare-container').getAttribute('aria-busy')==='false'&&
   document.querySelector('#comp-label-after').textContent.includes('2566')''')
  if page.locator('.compare-after-raster').count():
   assert '2023-09' in page.locator('.compare-after-raster').get_attribute('src')
  checks.append('right selector accepts first month without substituting the last month')

  # A missing exact month clears both dated rasters and never retains an old pair.
  page.evaluate('(id)=>selectPlot(id)',missing['id'])
  page.select_option('#comp-left-select',str(missing['index']))
  page.wait_for_function('''()=>document.querySelector('#compare-container').getAttribute('aria-busy')==='false'&&
   document.querySelector('#unified-compare-status').textContent.includes('ไม่มีภาพที่ใช้ได้ครบทั้งสองฝั่ง')&&
   document.querySelectorAll('.compare-before-raster,.compare-after-raster').length===0''')
  assert page.locator('.compare-before-raster,.compare-after-raster').count()==0
  checks.append('missing comparison dates clear old imagery and state the gap honestly')

  # A failed date request clears the old pair and offers an actual retry.
  page.evaluate('(id)=>selectPlot(id)',compare_plot)
  page.select_option('#comp-left-select','6');page.select_option('#comp-right-select','11')
  page.wait_for_function('''()=>document.querySelector('#compare-container').getAttribute('aria-busy')==='false'&&
   document.querySelector('.compare-before-raster')?.src.includes('rgb_2025-03')''')
  failing_month=page.evaluate('()=>activePlot.timeseries.findIndex(o=>o.month!=="2025-03"&&AllPlotsCore.observed(o))')
  failing_path=page.evaluate('(i)=>UnifiedData.asset(activePlot,activePlot.timeseries[i],"gee_rgb").url',failing_month)
  page.route(f'**/{failing_path}?*',lambda route:route.abort())
  page.select_option('#comp-left-select',str(failing_month))
  page.wait_for_function("document.querySelector('#unified-compare-status').textContent.includes('โหลดภาพไม่สำเร็จ')")
  assert page.locator('.compare-before-raster,.compare-after-raster').count()==0
  page.unroute(f'**/{failing_path}?*')
  page.locator('#unified-compare-status button').click()
  page.wait_for_function("document.querySelector('#compare-container').getAttribute('aria-busy')==='false'&&document.querySelector('.compare-before-raster')?.complete")
  assert failing_path in page.locator('.compare-before-raster').get_attribute('src')
  checks.append('image request failure clears both old frames; retry restores the exact selected pair')

  # Optional PDD uses its own footprint and cannot retain registry frames.
  scope_plot=page.evaluate('''()=>UnifiedWorkspace.masters.find(m=>m.pdd&&m.pdd.timeseries.some((o,i)=>
   UnifiedData.asset(m.pdd,o,'gee_rgb').state==='AVAILABLE'&&
   UnifiedData.asset(m.registry,m.registry.timeseries[i],'gee_rgb').state==='AVAILABLE')).id''')
  page.evaluate('(id)=>selectPlot(id)',scope_plot)
  scope_index=page.evaluate('''()=>{const m=UnifiedWorkspace.getMaster(activePlot.registryId);return m.pdd.timeseries.findIndex((o,i)=>
   UnifiedData.asset(m.pdd,o,'gee_rgb').state==='AVAILABLE'&&
   UnifiedData.asset(m.registry,m.registry.timeseries[i],'gee_rgb').state==='AVAILABLE')}''')
  page.evaluate('setAnalysisScope("pdd")')
  page.select_option('#comp-left-select',str(scope_index));page.select_option('#comp-right-select',str(scope_index))
  page.select_option('#comp-mode-select','rgb')
  page.wait_for_function('''()=>document.querySelector('#compare-container').getAttribute('aria-busy')==='false'&&
   document.querySelector('.compare-before-raster')?.src.includes('data/pdd22_satellite')''')
  assert 'data/pdd22_satellite' in page.locator('.compare-after-raster').get_attribute('src')
  assert page.locator('#comp-ndvi-legend').is_hidden()
  page.evaluate('setAnalysisScope("registry")')
  page.wait_for_function('''()=>document.querySelector('#compare-container').getAttribute('aria-busy')==='false'&&
   document.querySelector('.compare-before-raster')?.src.includes('data/plots/')''')
  assert 'data/plots/' in page.locator('.compare-after-raster').get_attribute('src')
  checks.append('registry/PDD scope changes replace both rasters with the selected footprint')

  # Mobile resizing keeps one aligned map and a visible touch-sized handle.
  page.set_viewport_size({'width':390,'height':844})
  page.wait_for_timeout(150)
  assert handle.is_visible() and handle.bounding_box()['width']>=44
  assert page.locator('#compare-position').is_visible()
  assert page.locator('#unified-compare-map').bounding_box()['width']>200
  checks.append('mobile comparison retains the handle and range control')

  assert not page.locator('#panel-allplots').count()
  assert not page_errors,page_errors
  print(json.dumps({'result':'PASS','checks':checks},ensure_ascii=False,indent=2))
  b.close()
finally:s.shutdown()
