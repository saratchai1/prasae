"""Isolated Chromium integration checks. Leaflet, Chart, imagery and data are fixtures.
This is NOT a production-data, geospatial, or live CDN end-to-end test.
Run: python tests/pdd22-dom.test.py (requires playwright and Chromium).
"""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
HTML = re.sub(r'<script\b[^>]*>.*?</script>', '', (ROOT/'index.html').read_text(), flags=re.S)
HTML = re.sub(r'<link\b[^>]*>', '', HTML)
BASE = r'''
const MILESTONE_MONTHS=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08'];
const thaiMonths={1:'ม.ค.',2:'ก.พ.',3:'มี.ค.',4:'เม.ย.',5:'พ.ค.',6:'มิ.ย.',7:'ก.ค.',8:'ส.ค.',9:'ก.ย.',10:'ต.ค.',11:'พ.ย.',12:'ธ.ค.'};
const ESRI_WORLD_IMAGERY='fixture-basemap';
let plotsCatalog=[],allPlotsData=[],activePlot=null,currentMonthIndex=0,currentPlotLayerKey='esri',verifiedDatasetLoaded=false;
let plotSatelliteMap=null,currentSentinelOverlay=null,plotBoundaryLayer=null,leafletMap=null,thailandGeojsonLayer=null,plotNdviChart=null,comparePlotId=null;
window.fixtureFail='';window.fixtureDelays={};
const parseMonthKey=month=>({month,year:Number(month.slice(0,4)),month_num:Number(month.slice(5))});
const escapeHtml=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const imageBoundsForPlot=p=>[[0,0],[1,1]];
function loadData(){} function updateStaticCopy(){} function renderSidebarList(){} function initTable(){}
function initLeafletThailandMap(){} function resetMapZoom(){} function updateGeeOverlay(){} function setPlotMapLayer(){}
function setMonthIndex(){} function initCompareSelectors(){} function exportPlotsCSV(){} function ensureCompareMaps(){} function updateCompareView(){}
function renderPlotChart(p){plotNdviChart={data:{datasets:[{data:p.timeseries.map(i=>i.mean_ndvi_inside)},{data:p.timeseries.map(i=>i.vegetation_coverage_proxy_pct)}]},setActiveElements(){},update(){}};}
function selectPlot(id){
 activePlot=allPlotsData.find(p=>p.id===Number(id));if(!activePlot)return;
 document.getElementById('kpi-current-plot-name').textContent=activePlot.code;
 renderPlotChart(activePlot);initCompareSelectors(activePlot);setMonthIndex(currentMonthIndex);
 if(document.getElementById('panel-compare').classList.contains('active'))setTimeout(updateCompareView,0);
 if(thailandGeojsonLayer)thailandGeojsonLayer.eachLayer(l=>l.setStyle({color:'#10b981'}));
}
function switchWorkspaceTab(tab){
 document.querySelectorAll('.w-tab-btn,.tab-content-panel').forEach(e=>e.classList.remove('active'));
 document.getElementById('wtab-'+tab).classList.add('active');document.getElementById('panel-'+tab).classList.add('active');
 if(tab==='compare')setTimeout(()=>{ensureCompareMaps();updateCompareView();},0);
}
function filterPlots(province,query){renderSidebarList(allPlotsData.filter(p=>(province==='ALL'||p.province===province)&&(!query||p.code.toLowerCase().includes(query)||p.province.includes(query))));}
function onPlotSearchInput(query){filterPlots(document.getElementById('province-filter').value,query.toLowerCase().trim());}
function onProvinceFilterChange(province){filterPlots(province,document.getElementById('plot-search-input').value.toLowerCase().trim());}
class FixtureLayer {
 constructor(url='',options={},image=false){this.url=url;this.options=options;this.image=image;this.events={};this.node=document.createElement('div');this.node.className='fixture-frame';this.node.dataset.url=url;this.node.style.cssText='position:absolute;width:500px;height:300px;';this.node.decode=()=>Promise.resolve();}
 once(name,cb){this.events[name]=cb;return this;} off(name,cb){if(this.events[name]===cb)delete this.events[name];return this;}
 addTo(map){this.map=map;map.layers.add(this);if(this.image){map.element.append(this.node);const failed=window.fixtureFail&&this.url.includes(window.fixtureFail);const delay=Object.entries(window.fixtureDelays).find(([s])=>this.url.includes(s))?.[1]||5;setTimeout(()=>this.events[failed?'error':'load']?.(),delay);}return this;}
 getElement(){return this.node;}setOpacity(o){this.opacity=o;return this;}bringToFront(){return this;}setStyle(s){this.style={...this.style,...s};return this;}
 getBounds(){return {isValid:()=>true};}bindTooltip(){return this;}on(){return this;}
 eachLayer(fn){(this.children||[]).forEach(fn);}
}
class FixtureMap {
 constructor(id){this.element=document.getElementById(id);this.layers=new Set();this.panes={};this.dragging={disable(){},enable(){}};}
 setView(){return this;}fitBounds(){}hasLayer(l){return this.layers.has(l);}removeLayer(l){this.layers.delete(l);l.node?.remove();return this;}
 createPane(name){this.panes[name]={style:{}};}getPane(name){return this.panes[name];}on(){}invalidateSize(){}
}
const L={map:id=>new FixtureMap(id),tileLayer:()=>new FixtureLayer(),imageOverlay:(url,bounds,options)=>new FixtureLayer(url,options,true),
 geoJSON(data,options={}){const l=new FixtureLayer();if(data.features){l.children=data.features.map(f=>{const child=new FixtureLayer();child.feature=f;options.onEachFeature?.(f,child);return child;});}return l;}};
const catalog=[{id:1,code:'TEST-A',province:'ระยอง',area_rai:100,geometry:{type:'Polygon',coordinates:[]}}, {id:2,code:'TEST-B',province:'ชุมพร',area_rai:200,geometry:{type:'Polygon',coordinates:[]}}];
const good=(month,green,qa='GOOD',coverage=100)=>({month,green_rai:green,yellow_rai:10,red_rai:5,green_observed_rai:green/2,yellow_observed_rai:5,red_observed_rai:2.5,qa,coverage_pct:coverage});
const fcd=catalog.map((p,i)=>({code:p.code,observations:[good('2024-03',30),good('2025-03',25),good('2026-03',20+i*20),good('2026-08',35,i?'PARTIAL':'GOOD',i?80:100)]}));
const coverage=['plot_code,month,qa,coverage_pct,mean_ndvi,scene_count',...catalog.flatMap(p=>MILESTONE_MONTHS.map(m=>`${p.code},${m},${m==='2024-06'?'NO_DATA':'GOOD'},${m==='2024-06'?.81:100},0.5,1`))].join('\n');
window.fetch=async url=>new Response(url.includes('plots_catalog')?JSON.stringify(catalog):url.includes('coverage_report')?coverage:JSON.stringify(fcd));
async function boot(){await loadData();updateStaticCopy();renderSidebarList(allPlotsData);plotSatelliteMap=L.map('plot-satellite-map');initLeafletThailandMap();initTable(allPlotsData);selectPlot(1);}
'''

def run():
    checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox'])
        for width,height in [(1440,1000),(390,844)]:
            page=browser.new_page(viewport={'width':width,'height':height})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_content(HTML)
            page.add_style_tag(content='.tab-content-panel{display:none}.tab-content-panel.active{display:block}.hidden{display:none}.portal-layout{display:flex}.workspace-area{min-width:0;flex:1}.table-container{overflow:auto}.plot-sidebar{width:300px;flex-shrink:0}.workspace-tabs{display:flex;overflow:auto}.site-header{padding:10px}*{box-sizing:border-box}body{margin:0;background:#0f172a;color:white;font-family:Arial,sans-serif}')
            page.add_style_tag(path=str(ROOT/'pdd22-review.css'))
            page.add_script_tag(content=BASE)
            for name in ['pdd22-observations.js','pdd22-production.js','pdd22-chart-hotfix.js','pdd22-compare-swipe.js']:
                page.add_script_tag(path=str(ROOT/name))
            page.evaluate('boot()')
            assert page.locator('#panel-overview').get_attribute('class').endswith('active')
            assert page.locator('#overview-rows tr').count()==2
            assert page.evaluate('plotNdviChart.data.datasets[0].data[3]') is None
            assert page.locator('#hud-month-label').inner_text().startswith('ภาพพื้นหลัง')
            checks.append(f'{width}: overview boots, chart rejects NO_DATA, basemap does not imply observation date')
            page.select_option('#overview-filter','REVIEW')
            assert page.locator('#overview-rows tr').count()==1
            page.select_option('#overview-filter','ALL')
            with page.expect_download() as export_all:
                page.locator('#overview-export-csv').click()
            exported = Path(export_all.value.path()).read_text(encoding='utf-8-sig')
            lines = [line for line in exported.splitlines() if line.strip()]
            assert len(lines) == 3
            assert 'Green Before Rai' in lines[0] and 'Green After Rai' in lines[0]
            assert 'Yellow Before Rai' in lines[0] and 'Red After Rai' in lines[0]
            assert 'Before FCD Image URL' in lines[0] and 'After FCD Image URL' in lines[0]
            assert 'TEST-A' in exported and 'TEST-B' in exported
            assert 'data/pdd22_v3/maps/TEST-A/fcd_2024-03.png' in exported
            assert 'data/pdd22_v3/maps/TEST-A/fcd_2026-03.png' in exported
            page.select_option('#overview-filter','REVIEW')
            with page.expect_download() as export_review:
                page.locator('#overview-export-csv').click()
            review_exported = Path(export_review.value.path()).read_text(encoding='utf-8-sig')
            review_lines = [line for line in review_exported.splitlines() if line.strip()]
            assert len(review_lines) == 2
            assert 'TEST-A' in review_exported and 'TEST-B' not in review_exported
            assert '-10' in review_exported
            page.select_option('#overview-filter','ALL')
            page.evaluate("onPlotSearchInput('test-a')")
            assert page.locator('#overview-rows tr').count()==1
            assert page.locator('#table-body tr').count()==1
            page.evaluate("onPlotSearchInput('')")
            checks.append(f'{width}: triage, CSV export and global filters agree with the visible comparison scope')
            page.evaluate("switchWorkspaceTab('detail');setPlotMapLayer('gee_rgb')")
            page.wait_for_function("document.getElementById('observation-status').dataset.state==='AVAILABLE'")
            page.evaluate('setMonthIndex(3)')
            page.wait_for_function("document.getElementById('observation-status').dataset.state==='NO_DATA'")
            assert page.evaluate('currentSentinelOverlay===null')
            assert page.locator('#hud-in-ndvi').inner_text()=='—'
            page.evaluate('setMonthIndex(10)')
            page.wait_for_function("document.getElementById('observation-status').dataset.state==='AVAILABLE'")
            page.evaluate("fixtureFail='2026-08';setMonthIndex(11)")
            page.wait_for_function("document.getElementById('observation-status').dataset.state==='ERROR'")
            assert page.evaluate('currentSentinelOverlay===null')
            checks.append(f'{width}: detail missing data / load failure clears previous image')
            page.evaluate("fixtureFail='';fixtureDelays={'2024-03':80};setMonthIndex(2);setMonthIndex(10)")
            page.wait_for_timeout(120)
            assert page.evaluate("currentSentinelOverlay.url.includes('2026-03')")
            page.evaluate('selectPlot(2)')
            page.wait_for_timeout(30)
            assert page.evaluate("currentSentinelOverlay.url.includes('TEST-B')")
            assert page.evaluate("thailandGeojsonLayer.children[0].style.color")=='#fbbf24'
            checks.append(f'{width}: rapid selection wins, plot switch does not overwrite QA map colors')
            page.evaluate("selectPlot(1);document.getElementById('comp-mode-select').value='fcd';switchWorkspaceTab('compare')")
            page.wait_for_function("document.getElementById('compare-container').getAttribute('aria-busy')==='false'")
            assert '-10' in page.locator('#comp-gain-pill').inner_text()
            page.evaluate("fixtureFail='2026-03';updateCompareView()")
            page.wait_for_function("document.getElementById('compare-loading').textContent.includes('ล้างภาพเก่าทั้งสองฝั่ง')")
            assert page.locator('#pdd22-swipe-map .fixture-frame').count()==0
            assert page.locator('#comp-in-stat-text').inner_text()=='—'
            checks.append(f'{width}: compare commits matched metrics; a failed side clears both images')
            if width<600:
                page.locator('#plot-picker-toggle').click()
                assert page.locator('#plot-picker-toggle').get_attribute('aria-expanded')=='true'
                page.locator('#sidebar-card-1').click()
                assert page.locator('#plot-picker-toggle').get_attribute('aria-expanded')=='false'
                checks.append(f'{width}: mobile plot picker opens and closes after selection')
            assert not errors,errors
            page.close()
        browser.close()
    print(json.dumps({'mode':'ISOLATED_CHROMIUM_FIXTURES_NOT_LIVE_UAT','passed':len(checks),'checks':checks},ensure_ascii=False,indent=2))

if __name__=='__main__':run()
