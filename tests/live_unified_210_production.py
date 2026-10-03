#!/usr/bin/env python3
import json, os
from playwright.sync_api import sync_playwright

URL='https://saratchai1.github.io/prasae/'
checks=[]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox'])
    page=b.new_page(viewport={'width':1440,'height':950})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('https://fonts.googleapis.com/**',lambda r:r.abort())
    page.route('https://fonts.gstatic.com/**',lambda r:r.abort())
    page.goto(URL,wait_until='domcontentloaded',timeout=60000)
    page.wait_for_function('window.UnifiedWorkspace && document.querySelectorAll("#plot-list-container .plot-card-item").length===210',timeout=60000)
    assert page.locator('#sidebar-count-display').inner_text().startswith('แสดง 210 จาก 210')
    assert page.locator('#wtab-allplots').count()==0
    assert '210 แปลง' in page.locator('.brand-title').inner_text()
    checks.append('live main workspace has exactly 210 registry identities')

    pdd=page.evaluate('()=>UnifiedWorkspace.masters.find(m=>m.pdd).id')
    page.evaluate('(id)=>selectPlot(id)',pdd)
    assert page.locator('#analysis-scope-select option[value="pdd"]').is_enabled()
    page.select_option('#analysis-scope-select','pdd')
    assert 'พื้นที่เข้าร่วม PDD' in page.locator('#kpi-current-plot-sub').inner_text()
    assert page.locator('[data-layer="fcd"]').is_enabled()
    checks.append('live PDD plot exposes optional PDD scope/FCD without duplicate identity')

    non=page.evaluate('()=>UnifiedWorkspace.masters.find(m=>!m.pdd).id')
    page.evaluate('(id)=>selectPlot(id)',non)
    assert page.locator('[data-layer="fcd"]').is_disabled()
    checks.append('live non-PDD registry plot cannot use FCD')

    page.locator('#wtab-map').click()
    page.wait_for_function('window.thailandGeojsonLayer && thailandGeojsonLayer.getLayers().length===210',timeout=15000)
    checks.append('live GIS contains 210 registry features')

    page.locator('#wtab-table').click()
    assert page.locator('#table-body tr').count()==210
    checks.append('live analysis table contains 210 plots')

    # Verify newly ingested exact-month source is present in production data model.
    accepted=[(25,'2026-03'),(115,'2026-08'),(131,'2026-03'),(132,'2026-08'),(155,'2026-08'),(156,'2026-08')]
    found=[]
    for pid,month in accepted:
        item=page.evaluate('''([pid,month])=>{const m=UnifiedWorkspace.getMaster(pid);const o=m?.registry?.timeseries?.find(x=>x.month===month);return o?{status:o.status,coverage:o.clear_pixel_pct,provenance:o.ingest_provenance||null}:null}''',[pid,month])
        assert item and item['status'] in ('observed_single_scene','observed_monthly_composite') and float(item['coverage'])>=5
        found.append([pid,month,item['coverage']])
    checks.append('live production includes all 6 newly accepted Drive observations')

    assert not errors, errors
    print(json.dumps({'result':'PASS','url':URL,'checks':checks,'accepted_live':found},ensure_ascii=False,indent=2))
    b.close()
