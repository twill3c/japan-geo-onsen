// 起動時に取りに行くデータを実測する。既定で消えている層のデータを読んでいないこと。
// (実測 2026-09-10: Wikipedia の層 1.8MB を既定 OFF のまま起動時に取っていた)
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join } from 'node:path';
const T={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.geojson':'application/json','.png':'image/png','.svg':'image/svg+xml','.ico':'image/x-icon','.txt':'text/plain'};
const server=createServer(async(req,res)=>{try{let p=decodeURIComponent(new URL(req.url,'http://x').pathname);if(p.endsWith('/'))p+='index.html';const b=await readFile(join('out',p));res.writeHead(200,{'content-type':T[extname(p)]??'application/octet-stream'});res.end(b);}catch{res.writeHead(404);res.end('x');}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const b=await chromium.launch();
const page=await b.newPage({viewport:{width:1280,height:900}});
const got=new Set();
page.on('request',(r)=>{const m=r.url().match(/\/data\/([a-z_]+\.(?:geojson|json))/);if(m)got.add(m[1]);});
await page.goto(base+'/',{waitUntil:'domcontentloaded'});
await page.waitForSelector('.maplibregl-canvas');
await page.waitForTimeout(6000);
let total=0;
for(const f of got){ total += (await stat(join('out','data',f))).size; }
console.log('起動時に取得:', [...got].sort().join(', '));
console.log('合計', (total/1024/1024).toFixed(2), 'MB');
const lazy=['onsen_wikipedia.geojson','rivers.geojson','lakes.geojson'];
const leaked=lazy.filter((f)=>got.has(f));
console.log(leaked.length? `**既定で消えている層を読んでいる: ${leaked.join(', ')}**` : '既定で消えている層は読んでいない');
await b.close(); server.close();
process.exitCode = leaked.length ? 1 : 0;
