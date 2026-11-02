import {createRequire} from 'node:module';import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';
const require=createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../mobile-20261029/package.json')),{chromium}=require('playwright-core'),angle={win32:'d3d11',darwin:'metal'}[process.platform],chrome=process.env.CHROME_PATH||process.platform==='win32'?{executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{channel:'chrome'};
const W=path.dirname(fileURLToPath(import.meta.url)),OUT=path.join(W,'display-ablation');await fs.mkdir(OUT,{recursive:true});
const browser=await chromium.launch({...chrome,headless:true,args:['--enable-gpu',...(angle?['--use-angle='+angle]:[])]});
const variants=[
 ['baseline',{lod:1,ext:0,blur:.3,dpr:1.25,budget:2000000}],
 ['blur-zero',{lod:1,ext:0,blur:0,dpr:1.25,budget:2000000}],
 ['blur-005',{lod:1,ext:0,blur:.05,dpr:1.25,budget:2000000}],
 ['extended',{lod:1,ext:1,blur:.3,dpr:1.25,budget:2000000}],
 ['budget-3m',{lod:1,ext:0,blur:.3,dpr:1.25,budget:3000000}],
 ['all-source',{lod:0,ext:1,blur:.05,dpr:1.25,budget:3000000}],
 ['dpr-2',{lod:1,ext:0,blur:.3,dpr:2,budget:2000000}],
 ['combined',{lod:0,ext:1,blur:.05,dpr:2,budget:3000000}],
];const results=[];
try{for(const [name,settings] of variants){
 const context=await browser.newContext({viewport:{width:1920,height:1080},deviceScaleFactor:2}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));await page.route('**/favicon.ico',r=>r.fulfill({status:204}));
 const query=new URLSearchParams({quality:'osmo',mode:'walk',ablation:'1',...settings});const start=Date.now();
 await page.goto('http://127.0.0.1:53270/?'+query);await page.click('#open-model');await page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',{timeout:90000});
 const row={name,settings,readySeconds:(Date.now()-start)/1000,errors,views:[]};
 for(const [label,index] of [['fridge',0],['fan',6],['dining',4],['bathroom',5]]){
  await page.evaluate(i=>__room.preset(i),index);const diagnostics=await page.evaluate(()=>__room.stable());
  const base=path.join(OUT,`${name}-${label}`);await page.screenshot({path:base+'-viewport.png',scale:'css'});
  const png=await page.evaluate(()=>__room.snapshot());await fs.writeFile(base+'-canvas.png',Buffer.from(png.split(',')[1],'base64'));
  row.views.push({label,index,diagnostics,state:await page.evaluate(()=>__room.state()),viewportFile:base+'-viewport.png',canvasFile:base+'-canvas.png'});
 }
 await page.evaluate(()=>__room.benchmark(true));await page.waitForTimeout(1500);const timings=await page.evaluate(()=>__room.timings());await page.evaluate(()=>__room.benchmark(false));row.frameCount=timings.length;row.averageFps=1000/(timings.reduce((a,b)=>a+b,0)/timings.length);
 results.push(row);await fs.writeFile(path.join(OUT,'measurements.json'),JSON.stringify({viewport:[1920,1080],deviceScaleFactor:2,sourceSha256:'cbb33c91b5b481460b2c75e2125f3efa1458e6634abc3da1ce051a0989fd315c',results,physicalPhones:false},null,2));console.log('Finished',name,'FPS',row.averageFps.toFixed(1),'errors',errors.length);
 await context.close();
}}finally{await browser.close();}
