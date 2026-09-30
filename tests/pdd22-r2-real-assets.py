"""R2 release gate: committed production PNGs and real Leaflet/Chart in Chromium.
Esri basemap tiles are replaced with a transparent tile, and fonts are suppressed.
This tests browser behavior/geographic bounds contracts, not scientific accuracy.
"""
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from threading import Thread
from urllib.request import urlopen, Request
import base64, hashlib, json, os, subprocess
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/r2-release'
OUT.mkdir(parents=True,exist_ok=True)

def audit():
    catalog=json.loads((ROOT/'data/pdd22/plots_catalog.json').read_text())
    assert len(catalog)==22
    assert round(sum(p['area_rai'] for p in catalog),2)==6775.53
    checks=0; dates=0
    for plot in catalog:
        folder=ROOT/'data/pdd22_spectral/plots'/plot['code']
        manifest=json.loads((folder/'spectral_manifest.json').read_text())
        assert manifest['plot_code']==plot['code']
        assert manifest['asset_role']=='browser_visualization_only'
        assert manifest['encoding']['reflectance_min']==0
        assert manifest['encoding']['reflectance_max']==.4
        assert manifest['bounds']==plot['bounds']
        seen=set()
        for d in manifest['dates']:
            assert d['month'] not in seen;seen.add(d['month']);dates+=1
            if d['status']!='available':
                assert not d.get('files');continue
            for band in manifest['bands']:
                expected=f"band_{band}_{d['month']}.png"
                assert d['files'][band]==expected
                with Image.open(folder/expected) as im:
                    assert im.size==(manifest['width'],manifest['height'])
                    assert im.mode in ('LA','RGBA')
                    im.verify()
                checks+=1
    return {'plots':len(catalog),'dates':dates,'png_crc_dimensions_checked':checks}

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def dependencies():
    urls={
      'leaflet.js':'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
      'leaflet.css':'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
      'chart.js':'https://cdn.jsdelivr.net/npm/chart.js'
    }
    result={}
    for name,url in urls.items():
        with urlopen(Request(url,headers={'User-Agent':'PDD22-R2-verification'}),timeout=40) as r:
            result[name]=r.read()
    return result

def run():
    report={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'mode':'COMMITTED_PRODUCTION_PNG_REAL_LEAFLET_CHART_CHROMIUM','basemap_tiles':'transparent test tile','scientific_validation':False,'checks':[]}
    server=None; browser=None; current_page=None
    try:
        report['source_audit']=audit()
        deps=dependencies()
        report['dependency_sha256']={k:hashlib.sha256(v).hexdigest() for k,v in deps.items()}
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
        Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}/'
        transparent=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            for width in (1440,390):
                page=browser.new_page(viewport={'width':width,'height':950},has_touch=width<600,is_mobile=width<600)
                current_page=page;errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                def network(route):
                    u=route.request.url
                    if 'unpkg.com/leaflet@1.9.4/dist/leaflet.js' in u:route.fulfill(body=deps['leaflet.js'],content_type='application/javascript')
                    elif 'unpkg.com/leaflet@1.9.4/dist/leaflet.css' in u:route.fulfill(body=deps['leaflet.css'],content_type='text/css')
                    elif 'cdn.jsdelivr.net/npm/chart.js' in u:route.fulfill(body=deps['chart.js'],content_type='application/javascript')
                    elif 'server.arcgisonline.com/' in u:route.fulfill(body=transparent,content_type='image/png')
                    elif 'fonts.googleapis.com/' in u:route.fulfill(body='',content_type='text/css')
                    elif 'fonts.gstatic.com/' in u:route.abort()
                    else:route.continue_()
                page.route('**/*',network)
                page.goto(url,wait_until='domcontentloaded')
                page.wait_for_function("typeof allPlotsData!=='undefined'&&allPlotsData.length===22&&activePlot!==null",timeout=30000)
                assert page.evaluate("L.version")=='1.9.4'
                report['chart_version']=page.evaluate('Chart.version')
                assert page.locator('#panel-overview').get_attribute('class').endswith('active')
                page.evaluate("switchWorkspaceTab('spectral')")
                def ready(code=None,month=None,preset=None):
                    page.wait_for_function("""(s)=>{const p=document.getElementById('panel-spectral');return document.getElementById('spectral-feedback').dataset.state==='READY'&&(!s.code||p.dataset.displayedPlot===s.code)&&(!s.month||p.dataset.displayedMonth===s.month)&&(!s.preset||p.dataset.displayedPreset===s.preset);} """,arg={'code':code,'month':month,'preset':preset},timeout=30000)
                    assert page.locator('img.spectral-observation-overlay').count()==1
                    assert page.locator('img.spectral-observation-overlay').evaluate('(e)=>e.complete&&e.naturalWidth>0')
                def state(value):
                    page.wait_for_function('(value)=>document.getElementById("spectral-feedback").dataset.state===value',arg=value,timeout=30000)
                def select(code,index=10):
                    page.evaluate('(s)=>{selectPlot(allPlotsData.find(p=>p.code===s.code).id);setMonthIndex(s.index);}',{'code':code,'index':index})
                def ok(label):report['checks'].append(f'{width}: {label}')
                ready(month='2026-03')
                # Real native Leaflet overlays from real source pixels for every plot.
                codes=page.evaluate('allPlotsData.map(p=>p.code)')
                for code in codes:
                    select(code);ready(code=code,month='2026-03')
                    assert page.locator('#spectral-qa').inner_text().startswith('GOOD')
                ok('all 22 plots render real March 2026 bands with matching identity and QA')
                select('90-VSD');ready(code='90-VSD')
                assert page.locator('#panel-spectral [data-preset]').count()==15
                assert page.locator('#spectral-r option').count()==10
                for preset in page.evaluate('Object.keys(Pdd22Spectral.PRESETS)'):
                    page.locator(f'#panel-spectral [data-preset="{preset}"]').click()
                    ready(code='90-VSD',preset=preset)
                ok('all 15 presets compose actual PNG bands with real Canvas and Leaflet')
                page.evaluate("document.querySelector('.spectral-advanced').open=true")
                page.select_option('#spectral-r','B8A');ready(preset='custom')
                page.evaluate("document.getElementById('spectral-opacity').value='35';document.getElementById('spectral-opacity').dispatchEvent(new Event('input'))")
                assert page.locator('img.spectral-observation-overlay').evaluate('(e)=>Number(e.style.opacity)')==.35
                page.locator('#spectral-reset').click();ready(preset='truecolor')
                page.locator('#spectral-boundary').uncheck()
                page.locator('#spectral-boundary').check()
                ok('custom RGB, opacity, reset, boundary control work on actual Leaflet')
                select('90-VSD',0);state('NO_DATA')
                assert page.locator('img.spectral-observation-overlay').count()==0
                assert page.locator('#panel-spectral').get_attribute('data-displayed-month') is None
                select('18-VSD',11);ready(code='18-VSD',month='2026-08')
                assert page.locator('#spectral-qa').inner_text().startswith('PARTIAL')
                ok('actual NO_DATA and PARTIAL observations are not promoted to GOOD')
                # Delay only responses, never fabricate satellite pixel data.
                page.evaluate("""() => {const native=window.fetch;window.__originalFetch=native;window.fetch=async function(input,options={}){const r=await native(input,options);if(String(input).includes('band_')&&String(input).includes('2025-03'))await Pdd22Spectral.abortable(new Promise(resolve=>setTimeout(resolve,800)),options.signal);return r;};setMonthIndex(6);} """)
                state('LOADING')
                assert page.locator('#panel-spectral').get_attribute('data-displayed-month')=='2026-08'
                assert '2026-08' in page.locator('#spectral-status').inner_text()
                page.evaluate('setMonthIndex(10)');ready(code='18-VSD',month='2026-03')
                page.wait_for_timeout(1000);ready(code='18-VSD',month='2026-03')
                page.evaluate('window.fetch=window.__originalFetch')
                ok('delayed prior request cannot overwrite a newer real observation')
                fail_pattern='**/data/pdd22_spectral/plots/19-VSD/band_B04_2024-03.png*'
                page.route(fail_pattern,lambda route:route.fulfill(status=404,body='controlled failure'))
                select('19-VSD',2);state('ERROR')
                assert page.locator('img.spectral-observation-overlay').count()==0
                assert page.locator('#panel-spectral').get_attribute('data-displayed-plot') is None
                page.unroute(fail_pattern)
                page.locator('#spectral-retry').click();ready(code='19-VSD',month='2024-03')
                ok('HTTP error clears old image; retry recovers exact real observation')
                page.evaluate("switchWorkspaceTab('detail');selectPlot(allPlotsData.find(p=>p.code==='90-VSD').id)")
                page.wait_for_timeout(100)
                assert page.locator('img.spectral-observation-overlay').count()==0
                page.evaluate("switchWorkspaceTab('spectral')");ready(code='90-VSD')
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
                assert page.locator('img.spectral-observation-overlay').count()==0
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))");ready(code='90-VSD')
                ok('tab exit, hidden plot change and bfcache restore do not show stale frames')
                page.evaluate("document.querySelector('.spectral-advanced').open=false")
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
                page.locator('#panel-spectral').screenshot(path=str(OUT/f'spectral-real-{width}.png'))
                assert not errors,errors
                ok('responsive layout has no horizontal overflow and no page errors')
                page.close();current_page=None
            browser.close();browser=None
        report['result']='PASS'
    except Exception as error:
        report['result']='FAIL';report['error']=str(error)
        if current_page:
            try:current_page.screenshot(path=str(OUT/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if server:server.shutdown()
        (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
