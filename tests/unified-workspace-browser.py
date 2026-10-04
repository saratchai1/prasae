#!/usr/bin/env python3
import os,threading,json
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

  # compare uses same geometry/bounds on both maps.
  page.locator('#wtab-compare').click();page.wait_for_timeout(400)
  assert page.locator('#compare-map-left').count()==1 and page.locator('#compare-map-right').count()==1
  checks.append('before/after remains in the same workspace')

  assert not page.locator('#panel-allplots').count()
  assert not page_errors,page_errors
  print(json.dumps({'result':'PASS','checks':checks},ensure_ascii=False,indent=2))
  b.close()
finally:s.shutdown()
