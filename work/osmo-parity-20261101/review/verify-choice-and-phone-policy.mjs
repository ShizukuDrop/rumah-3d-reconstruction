import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';
const W=path.dirname(fileURLToPath(import.meta.url)),require=createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../mobile-20261029/package.json')),{chromium}=require('playwright-core'),angle={win32:'d3d11',darwin:'metal'}[process.platform],chrome=process.env.CHROME_PATH||process.platform==='win32'?{executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{channel:'chrome'};
const browser=await chromium.launch({...chrome,headless:true,args:['--enable-gpu',...(angle?['--use-angle='+angle]:[])]});const rows=[];
try{
 for(const profile of [{name:'desktop',viewport:{width:1920,height:1080},deviceScaleFactor:2,hasTouch:false},{name:'narrow-touch',viewport:{width:412,height:915},deviceScaleFactor:3,hasTouch:true},{name:'wide-touch',viewport:{width:900,height:840},deviceScaleFactor:3,hasTouch:true}]){
  const {name,...options}=profile,context=await browser.newContext(options),page=await context.newPage(),requests=[],errors=[];await page.route('**/favicon.ico',r=>r.fulfill({status:204}));page.on('request',r=>requests.push(r.url()));page.on('pageerror',e=>errors.push(String(e)));
  const prechoice=[];
  for(const linked of ['', 'phone','native','iphone-full','osmo']){
   requests.length=0;await page.goto((process.env.BASE_URL||'http://127.0.0.1:53270/')+''+(linked?'?quality='+linked:''));await page.waitForTimeout(250);
   const choices=await page.locator('input[name="model-choice"]').evaluateAll(inputs=>inputs.map(input=>input.value));
   if(JSON.stringify(choices)!==JSON.stringify(['phone','osmo']))throw Error('Only iPhone Lite and Osmo may be offered');
   if(['native','iphone-full'].includes(linked)&&!(await page.locator('input[value="phone"]').isChecked()))throw Error('Retired full link did not preselect iPhone Lite');
   for(const value of ['phone','osmo']){await page.locator('input[name="model-choice"][value="'+value+'"]').check({force:true});await page.waitForTimeout(100);}
   const state=await page.evaluate(()=>({viewerStarted:!!window.__room,viewerScripts:[...document.scripts].some(s=>s.src.includes('room-viewer')),phase:document.body.dataset.phase||null}));
   const modelRequests=requests.filter(u=>/\.(?:glb|sog|spz|ply)(?:\.gz)?(?:\?|$)/.test(u));if(modelRequests.length||state.viewerStarted||state.viewerScripts)throw Error('Prechoice fetched/started 3D: '+name);
   prechoice.push({linked:linked||'bare',requests:[...requests],modelRequests:0,modelBytes:0,...state});
  }
  const row={profile:name,emulatedTouch:options.hasTouch,physicalPhone:false,prechoice,errors};
  if(name==='narrow-touch'){
   await page.locator('input[name="model-choice"][value="phone"]').check({force:true});
   const started=Date.now();await page.click('#open-model');await page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',undefined,{timeout:90000});row.readySeconds=(Date.now()-started)/1000;
   row.draw=await page.evaluate(()=>__room.stable());row.renderer=await page.evaluate(()=>__room.rendererInfo());
   row.selection=await page.evaluate(()=>({quality:document.body.dataset.quality,option:document.getElementById('quality').value,selected:document.body.dataset.selectedModel,state:__room.state(),label:document.getElementById('stats').textContent}));
   if(row.selection.quality!=='phone'||row.selection.option!=='phone'||row.selection.selected!=='phone'||row.selection.state.triangles<1||row.draw.dpr!==1.5||!/iPhone Lite/.test(row.selection.label))throw Error('iPhone Lite failed to reach a nonempty phone draw');
   if(process.env.EVIDENCE_DIR){await fs.mkdir(process.env.EVIDENCE_DIR,{recursive:true});row.screenshot=path.resolve(process.env.EVIDENCE_DIR,'2026-11-03-iphone-lite-narrow-touch.png');await page.screenshot({path:row.screenshot});}
  }
  if(name==='wide-touch'||name==='desktop'){
   const started=Date.now();await page.click('#open-model');await page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',undefined,{timeout:90000});row.readySeconds=(Date.now()-started)/1000;row.draw=await page.evaluate(()=>__room.stable());row.renderer=await page.evaluate(()=>__room.rendererInfo());
   const phone=name==='wide-touch';
   if(row.draw.dpr!==(phone?1.5:2)||row.draw.lod!==phone||row.draw.activeSplats>(phone?1500000:3000000)||row.draw.activeSplats<1||!row.draw.extSplats||row.draw.blur!==.05)throw Error('Device rendering policy does not match mandate: '+name);
  }
  row.modelRequests=requests.filter(u=>/\.(?:glb|sog|spz|ply)(?:\.gz)?(?:\?|$)/.test(u));
  row.fullModelRequests=row.modelRequests.filter(u=>/iphone[-_].*full|16f8963b/i.test(new URL(u).pathname));
  if(row.fullModelRequests.length)throw Error('Retired iPhone Full was requested: '+name);
  if(errors.length)throw Error(errors.join('\n'));rows.push(row);console.log('PASS',name,'zero prechoice bytes',row.draw||'');await context.close();
 }
}finally{await fs.writeFile(path.join(W,process.env.VERIFICATION_OUTPUT||'choice-and-phone-policy-verification.json'),JSON.stringify({rows,scope:'Desktop Chrome GPU with touch/DPR emulation. No physical Fold 7, iPhone 17 or Safari claim.'},null,2));await browser.close();}
