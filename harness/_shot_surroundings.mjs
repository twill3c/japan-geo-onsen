// 温泉の詳細パネルの「まわり 5〜50km」の表を撮り、パネル幅に収まっているかを測る
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
const T={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.geojson':'application/json','.png':'image/png','.svg':'image/svg+xml','.ico':'image/x-icon','.txt':'text/plain'};
const server=createServer(async(req,res)=>{try{let p=decodeURIComponent(new URL(req.url,'http://x').pathname);if(p.endsWith('/'))p+='index.html';const b=await readFile(join('out',p));res.writeHead(200,{'content-type':T[extname(p)]??'application/octet-stream'});res.end(b);}catch{res.writeHead(404);res.end('x');}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const b=await chromium.launch();
for (const [w,h] of [[1280,900],[390,844]]) {
  const page=await b.newPage({viewport:{width:w,height:h}});
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});
  await page.waitForSelector('.maplibregl-canvas');
  await page.waitForFunction(()=>(window.__map?.queryRenderedFeatures({layers:['onsen']})??[]).length>0,null,{timeout:30000});
  await page.evaluate(()=>{const m=window.__map;const f=m.queryRenderedFeatures({layers:['onsen']})[0];const p=m.project(f.geometry.coordinates);const r=m.getCanvas().getBoundingClientRect();m.getCanvas().dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:p.x+r.left,clientY:p.y+r.top}));});
  await page.waitForSelector('.feature-panel .surroundings table',{timeout:20000});
  await page.locator('.feature-panel .surroundings').scrollIntoViewIfNeeded();
  const fit=await page.evaluate(()=>{const panel=document.querySelector('.feature-panel');const t=document.querySelector('.feature-panel .surroundings table');return {panel:Math.round(panel.clientWidth),table:Math.round(t.scrollWidth),overflowX:panel.scrollWidth>panel.clientWidth+1};});
  console.log(`${w}px: パネル ${fit.panel} / 表 ${fit.table} / 横はみ出し ${fit.overflowX}`);
  await page.locator('.feature-panel .surroundings').screenshot({path:`harness/shots/surroundings_${w}.png`});
  await page.close();
}
await b.close(); server.close();
