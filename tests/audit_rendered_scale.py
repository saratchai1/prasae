#!/usr/bin/env python3
import os,threading,json
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];PORT=8777
class H(SimpleHTTPRequestHandler):
 def log_message(self,*a): pass
def close(a,b,tol=.75): return abs(float(a)-float(b))<=tol
os.chdir(R);s=ThreadingHTTPServer(('127.0.0.1',PORT),H);threading.Thread(target=s.serve_forever,daemon=True).start();out={}
try:
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox']);page=b.new_page(viewport={'width':1440,'height':950})
  transparent=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082')
  page.route('https://server.arcgisonline.com/**',lambda r:r.fulfill(status=200,content_type='image/png',body=transparent))
  page.route('https://fonts.googleapis.com/**',lambda r:r.abort());page.route('https://fonts.gstatic.com/**',lambda r:r.abort())
  page.goto(f'http://127.0.0.1:{PORT}/index.html',wait_until='domcontentloaded',timeout=30000);page.wait_for_function('window.__allPlotsReady===true && document.getElementById("wtab-overview")',timeout=30000)

  # General plot exact-month pair
  page.locator('#wtab-allplots').click();page.select_option('#allplots-before','2024-03');page.select_option('#allplots-after','2026-03')
  pid=page.evaluate('()=>{const C=AllPlotsCore,s=AllPlotsPortfolio.state,p=s.plots.find(p=>C.asset(p,C.obs(p,"2024-03"),"rgb")&&C.asset(p,C.obs(p,"2026-03"),"rgb"));return p.id}')
  page.evaluate('(id)=>AllPlotsPortfolio.selectById(id)',pid)
  page.wait_for_function("document.getElementById('allplots-before-img').naturalWidth>0&&document.getElementById('allplots-after-img').naturalWidth>0")
  g=page.evaluate('''()=>{const a=document.getElementById('allplots-before-img'),b=document.getElementById('allplots-after-img'),ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();return {before:{nw:a.naturalWidth,nh:a.naturalHeight,x:ra.x,y:ra.y,w:ra.width,h:ra.height},after:{nw:b.naturalWidth,nh:b.naturalHeight,x:rb.x,y:rb.y,w:rb.width,h:rb.height}}}''')
  assert g['before']['nw']==g['after']['nw'] and g['before']['nh']==g['after']['nh'],g
  assert close(g['before']['w'],g['after']['w']) and close(g['before']['h'],g['after']['h']),g
  out['general']=g

  # PDD22 swipe uses one map; choose first plot and March pair.
  page.locator('#wtab-overview').click();page.locator('#overview-rows tr').first.locator('button').click()
  page.select_option('#comp-left-select',str(2));page.select_option('#comp-right-select',str(10));page.select_option('#comp-mode-select','rgb')
  page.evaluate('updateCompareView()')
  page.wait_for_function("document.querySelectorAll('#pdd22-swipe-map img.leaflet-image-layer').length>=2",timeout=15000)
  pdd=page.evaluate('''()=>{const imgs=[...document.querySelectorAll('#pdd22-swipe-map img.leaflet-image-layer')].slice(-2);return imgs.map(i=>{const r=i.getBoundingClientRect();return {src:i.getAttribute('src'),nw:i.naturalWidth,nh:i.naturalHeight,x:r.x,y:r.y,w:r.width,h:r.height}})}''')
  assert len(pdd)==2,pdd
  a,c=pdd
  assert a['nw']==c['nw'] and a['nh']==c['nh'],pdd
  for k in ['x','y','w','h']: assert close(a[k],c[k]),(k,pdd)
  out['pdd22']=pdd
  print(json.dumps({'result':'PASS','tolerance_css_px':.75,'measurements':out},ensure_ascii=False,indent=2))
  b.close()
finally:s.shutdown()
