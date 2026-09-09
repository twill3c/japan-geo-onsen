// 3 層 + 火山の色を、実際の地図で見る(HC-257 の後)
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
const TYPES={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.geojson':'application/json','.png':'image/png','.svg':'image/svg+xml','.ico':'image/x-icon','.txt':'text/plain'};
const server=createServer(async(req,res)=>{try{let p=decodeURIComponent(new URL(req.url,'http://x').pathname);if(p.endsWith('/'))p+='index.html';const b=await readFile(join('out',p));res.writeHead(200,{'content-type':TYPES[extname(p)]??'application/octet-stream'});res.end(b);}catch{res.writeHead(404);res.end('x');}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const b=await chromium.launch();
const page=await b.newPage({viewport:{width:1280,height:900}});
await page.goto(base+'/',{waitUntil:'domcontentloaded'});
await page.waitForSelector('.maplibregl-canvas');
await page.waitForTimeout(4000);
// 八ヶ岳周辺(温泉・火山が混在する場所)
await page.evaluate(()=>window.__map.jumpTo({center:[138.45,36.0],zoom:9}));
await page.waitForTimeout(3500);
await page.locator('.map-area').screenshot({path:'harness/shots/map_colors.png'});
// ほったらかし温泉のあたり
await page.evaluate(()=>window.__map.jumpTo({center:[138.652,35.706],zoom:12}));
await page.waitForTimeout(3000);
await page.locator('.map-area').screenshot({path:'harness/shots/map_facility.png'});
console.log('撮影完了');
await b.close(); server.close();
