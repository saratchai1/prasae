#!/usr/bin/env python3
import csv,json,os,threading
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];PORT=8765
HTML='''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/all-plots-portfolio.css"><div class="portal-layout"><button id="plot-picker-toggle"></button><aside class="plot-sidebar"></aside><main class="workspace-area"><div class="workspace-card"><div class="workspace-tabs"><button class="w-tab-btn" id="wtab-detail">PDD22</button></div><div class="tab-content-panel" id="panel-detail"></div></div></main></div><script>function switchWorkspaceTab(tab){document.querySelectorAll(".w-tab-btn,.tab-content-panel").forEach(x=>x.classList.remove("active"));document.getElementById("wtab-"+tab)?.classList.add("active");document.getElementById("panel-"+tab)?.classList.add("active")}</script><script src="/all-plots-core.js"></script><script src="/all-plots-portfolio.js"></script>'''
class H(SimpleHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path.split('?')[0]=='/__allplots_test__.html':
   b=HTML.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
  super().do_GET()
def close(a,b,tol=1):return abs(float(a)-float(b))<=tol
def run():
 os.chdir(ROOT);s=ThreadingHTTPServer(('127.0.0.1',PORT),H);threading.Thread(target=s.serve_forever,daemon=True).start();checks=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox'])
   for width,height in [(1440,950),(390,900)]:
    page=browser.new_page(viewport={'width':width,'height':height},accept_downloads=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{PORT}/__allplots_test__.html');page.wait_for_function('window.__allPlotsReady===true',timeout=20000)
    assert page.locator('#wtab-allplots').inner_text()=='แปลงทั่วไป · 210';page.locator('#wtab-allplots').click();assert page.locator('#allplots-rows tr').count()==210
    assert page.evaluate("AllPlotsPortfolio.secondaryQa({id:164},'2025-09').status")=='TIDE_WATER_REVIEW'
    assert page.evaluate("AllPlotsPortfolio.secondaryQa({id:121},'2025-06').status")=='ATMOSPHERE_REVIEW'
    checks.append(f'{width}: 210 plots + committed secondary QA load')

    page.select_option('#allplots-before','2024-03');page.select_option('#allplots-after','2026-03');page.evaluate('AllPlotsPortfolio.selectById(142)')
    assert page.evaluate("AllPlotsPortfolio.screenedCompare(AllPlotsPortfolio.state.plots.find(p=>p.id===142),'2024-03','2026-03').status")=='VISUAL_REVIEW'
    assert page.evaluate("AllPlotsPortfolio.screenedCompare(AllPlotsPortfolio.state.plots.find(p=>p.id===142),'2024-03','2026-03').deltaGreenArea") is None
    assert page.locator('#allplots-qa-warning').is_visible()
    checks.append(f'{width}: flagged endpoint blocks delta')

    page.wait_for_function("document.getElementById('allplots-before-img').dataset.cropWidth && document.getElementById('allplots-after-img').dataset.cropWidth",timeout=10000)
    crop=page.evaluate('''()=>{const a=document.getElementById('allplots-before-img'),b=document.getElementById('allplots-after-img'),ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();return {a:{sw:+a.dataset.sourceWidth,sh:+a.dataset.sourceHeight,cw:+a.dataset.cropWidth,ch:+a.dataset.cropHeight,w:ra.width,h:ra.height},b:{sw:+b.dataset.sourceWidth,sh:+b.dataset.sourceHeight,cw:+b.dataset.cropWidth,ch:+b.dataset.cropHeight,w:rb.width,h:rb.height}}}''')
    assert crop['a']['cw']<crop['a']['sw'] or crop['a']['ch']<crop['a']['sh']
    assert crop['a']['cw']==crop['b']['cw'] and crop['a']['ch']==crop['b']['ch']
    assert close(crop['a']['w'],crop['b']['w']) and close(crop['a']['h'],crop['b']['h'])
    checks.append(f'{width}: before/after use identical geographic crop and rendered scale')

    page.select_option('#allplots-province','กระบี่')
    with page.expect_download() as dl:page.locator('#allplots-export').click()
    with open(dl.value.path(),encoding='utf-8-sig',newline='') as fh:rows=list(csv.reader(fh))
    assert rows[0][0]=='รหัสแปลง' and 'QA เพิ่มเติมก่อน' in rows[0] and 'QA เพิ่มเติมหลัง' in rows[0]
    assert all(r[3]=='กระบี่' for r in rows[1:])
    checks.append(f'{width}: Thai CSV includes secondary QA and follows province filter')
    if width<600:assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+1');checks.append(f'{width}: no page overflow')
    assert not errors,errors;page.close()

   full=browser.new_page(viewport={'width':1440,'height':950});full_errors=[];full.on('pageerror',lambda e:full_errors.append(str(e)))
   transparent=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082')
   full.route('https://server.arcgisonline.com/**',lambda route:route.fulfill(status=200,content_type='image/png',body=transparent))
   full.route('https://fonts.googleapis.com/**',lambda route:route.abort());full.route('https://fonts.gstatic.com/**',lambda route:route.abort())
   full.goto(f'http://127.0.0.1:{PORT}/index.html',wait_until='domcontentloaded',timeout=30000)
   full.wait_for_function('window.__allPlotsReady===true && document.getElementById("wtab-overview")',timeout=30000)
   full.locator('#wtab-allplots').click();assert full.locator('#allplots-rows tr').count()==210;assert 'ประมวลผลไว้ล่วงหน้า' in full.locator('.brand-subtitle').inner_text()
   full.locator('#wtab-overview').click();assert full.locator('#overview-rows tr').count()==22;assert 'PDD22' in full.locator('.brand-title').inner_text();assert not full_errors,full_errors
   checks.append('full index: PDD22 and corrected 210-plot workspace coexist')
   full.close();browser.close()
 finally:s.shutdown()
 print(json.dumps({'mode':'ACTUAL_210_PLOT_DATA_SECONDARY_QA_AND_CROPPED_IMAGES','passed':len(checks),'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':run()
