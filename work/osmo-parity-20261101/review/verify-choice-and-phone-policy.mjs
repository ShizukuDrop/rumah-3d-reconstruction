import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';
const W=path.dirname(fileURLToPath(import.meta.url)),require=createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../mobile-20261029/package.json')),{chromium}=require('playwright-core'),angle={win32:'d3d11',darwin:'metal'}[process.platform],chrome=process.env.CHROME_PATH||process.platform==='win32'?{executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{channel:'chrome'};
const browser=await chromium.launch({...chrome,headless:true,args:['--enable-gpu',...(angle?['--use-angle='+angle]:[])]});const rows=[];
try{
 for(const profile of [{name:'desktop',viewport:{width:1920,height:1080},deviceScaleFactor:2,hasTouch:false},{name:'narrow-touch',viewport:{width:412,height:915},deviceScaleFactor:3,hasTouch:true},{name:'wide-touch',viewport:{width:900,height:840},deviceScaleFactor:3,hasTouch:true}]){
  const {name,...options}=profile,context=await browser.newContext(options),page=await context.newPage(),requests=[],errors=[];await page.route('**/favicon.ico',r=>r.fulfill({status:204}));page.on('request',r=>requests.push(r.url()));page.on('pageerror',e=>errors.push(String(e)));
  const prechoice=[];
  for(const linked of ['', 'phone','native','osmo']){
   requests.length=0;await page.goto('http://127.0.0.1:53270/'+(linked?'?quality='+linked:''));await page.waitForTimeout(250);
   for(const value of ['phone','native','osmo']){await page.locator('input[name="model-choice"][value="'+value+'"]').check({force:true});await page.waitForTimeout(100);}
   const state=await page.evaluate(()=>({viewerStarted:!!window.__room,viewerScripts:[...document.scripts].some(s=>s.src.includes('room-viewer')),phase:document.body.dataset.phase||null}));
   const modelRequests=requests.filter(u=>/\.(?:glb|sog|spz|ply)(?:\?|$)/.test(u));if(modelRequests.length||state.viewerStarted||state.viewerScripts)throw Error('Prechoice fetched/started 3D: '+name);
   prechoice.push({linked:linked||'bare',requests:[...requests],modelRequests:0,modelBytes:0,...state});
  }
  const row={profile:name,emulatedTouch:options.hasTouch,physicalPhone:false,prechoice,errors};
  if(name==='wide-touch'){
   const started=Date.now();await page.click('#open-model');await page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',undefined,{timeout:90000});row.readySeconds=(Date.now()-started)/1000;row.draw=await page.evaluate(()=>__room.stable());row.renderer=await page.evaluate(()=>__room.rendererInfo());
   if(row.draw.dpr!==1.5||row.draw.lod!==true||row.draw.activeSplats>1500000||row.draw.activeSplats<1||!row.draw.extSplats||row.draw.blur!==.05)throw Error('Phone rendering policy does not match mandate');
  }
  if(errors.length)throw Error(errors.join('\n'));rows.push(row);console.log('PASS',name,'zero prechoice bytes',row.draw||'');await context.close();
 }
}finally{await fs.writeFile(path.join(W,'choice-and-phone-policy-verification.json'),JSON.stringify({rows,scope:'Desktop Chrome GPU with touch/DPR emulation. No physical Fold 7, iPhone 17 or Safari claim.'},null,2));await browser.close();}
