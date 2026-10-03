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
def run():
 os.chdir(ROOT);s=ThreadingHTTPServer(('127.0.0.1',PORT),H);threading.Thread(target=s.serve_forever,daemon=True).start();checks=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox'])
   for width,height in [(1440,950),(390,900)]:
    page=browser.new_page(viewport={'width':width,'height':height},accept_downloads=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(f'http://127.0.0.1:{PORT}/__allplots_test__.html');page.wait_for_function('window.__allPlotsReady===true',timeout=20000);assert page.locator('#wtab-allplots').inner_text()=='แปลงทั่วไป · 210';page.locator('#wtab-allplots').click();assert page.locator('#allplots-rows tr').count()==210;checks.append(f'{width}: loads 210 actual plots')
    page.select_option('#allplots-province','กระบี่');assert page.locator('#allplots-rows tr').count()==39
    with page.expect_download() as dl:page.locator('#allplots-export').click()
    with open(dl.value.path(),encoding='utf-8-sig',newline='') as fh:rows=list(csv.reader(fh))
    assert len(rows)==40 and rows[0][0]=='รหัสแปลง' and 'ลิงก์ภาพ RGB ก่อน' in rows[0] and all(r[3]=='กระบี่' for r in rows[1:]);checks.append(f'{width}: Thai CSV exports 39 Krabi plots')
    page.select_option('#allplots-province','ALL');page.select_option('#allplots-before','2024-03');page.select_option('#allplots-after','2026-03');target=page.evaluate('()=>{const C=AllPlotsCore,s=AllPlotsPortfolio.state,p=s.plots.find(p=>C.asset(p,C.obs(p,"2024-03"),"rgb")&&C.asset(p,C.obs(p,"2026-03"),"rgb"));return p&&p.id}');assert target;page.evaluate('(id)=>AllPlotsPortfolio.selectById(id)',target);page.wait_for_function("document.getElementById('allplots-before-img').naturalWidth>0&&document.getElementById('allplots-after-img').naturalWidth>0",timeout=10000);assert 'rgb_2024-03.png' in page.locator('#allplots-before-img').get_attribute('src');assert 'rgb_2026-03.png' in page.locator('#allplots-after-img').get_attribute('src');page.locator('[data-allplots-layer="ndvi"]').click();page.wait_for_function("document.getElementById('allplots-before-img').naturalWidth>0&&document.getElementById('allplots-before-img').src.includes('ndvi_2024-03.png')",timeout=10000);checks.append(f'{width}: exact-month real RGB/NDVI images load')
    if width<600:assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+1');checks.append(f'{width}: no page overflow')
    assert not errors,errors;page.close()
   browser.close()
 finally:s.shutdown()
 print(json.dumps({'mode':'ACTUAL_COMMITTED_210_PLOT_DATA_AND_IMAGES','passed':len(checks),'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':run()