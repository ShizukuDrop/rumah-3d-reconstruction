import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';
const W=path.dirname(fileURLToPath(import.meta.url)),require=createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../mobile-20261029/package.json')),{chromium}=require('playwright-core'),angle={win32:'d3d11',darwin:'metal'}[process.platform],chrome=process.env.CHROME_PATH||process.platform==='win32'?{executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{channel:'chrome'};
const expectStick=process.env.EXPECT_STICK==='1';
const choicesExpected=expectStick?['phone','osmo','osmo-stick']:['phone','osmo'];
const base=process.env.BASE_URL||'http://127.0.0.1:53270/';
const modelRequest=url=>/\.(?:glb|sog|spz|ply)(?:\.gz)?$/.test(new URL(url).pathname);
const ready=page=>page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',undefined,{timeout:90000});
const cameraSummary=page=>page.evaluate(()=>{
  const data=__room.data;
  return {start:data.startCamera,first:data.presets[0],source:data.occupiedShell?.footprint?.source?.sha256};
});
const browser=await chromium.launch({...chrome,headless:true,args:['--enable-gpu',...(angle?['--use-angle='+angle]:[])]});const rows=[];
try{
 for(const profile of [{name:'desktop',viewport:{width:1920,height:1080},deviceScaleFactor:2,hasTouch:false},{name:'narrow-touch',viewport:{width:412,height:915},deviceScaleFactor:3,hasTouch:true},{name:'wide-touch',viewport:{width:900,height:840},deviceScaleFactor:3,hasTouch:true}]){
  const {name,...options}=profile,context=await browser.newContext(options),page=await context.newPage(),requests=[],errors=[];await page.route('**/favicon.ico',r=>r.fulfill({status:204}));page.on('request',r=>requests.push(r.url()));page.on('pageerror',e=>errors.push(String(e)));
  const prechoice=[];
  for(const linked of ['', 'phone','native','iphone-full','iphone-lite','iphone-fast','osmo-lite','osmo-stick','osmo']){
   requests.length=0;await page.goto(base+(linked?'?quality='+linked:''));await page.waitForTimeout(250);
   const choices=await page.locator('input[name="model-choice"]').evaluateAll(inputs=>inputs.map(input=>input.value));
   if(JSON.stringify(choices)!==JSON.stringify(choicesExpected))throw Error('Unexpected chooser model keys');
   if(['native','iphone-full'].includes(linked)&&!(await page.locator('input[value="phone"]').isChecked()))throw Error('Retired full link did not preselect iPhone Lite');
   if(linked==='osmo-stick'){
    if(expectStick&&!(await page.locator('input[value="osmo-stick"]').isChecked()))throw Error('Stick link did not preselect Stick');
    if(!expectStick&&!(await page.locator('#open-model').isDisabled()))throw Error('Unpublished Stick link enabled Open');
   }
   for(const value of choicesExpected){await page.locator('input[name="model-choice"][value="'+value+'"]').check({force:true});await page.waitForTimeout(100);}
   const state=await page.evaluate(()=>({viewerStarted:!!window.__room,viewerScripts:[...document.scripts].some(s=>s.src.includes('room-viewer')),phase:document.body.dataset.phase||null}));
   const modelRequests=requests.filter(modelRequest);if(modelRequests.length||state.viewerStarted||state.viewerScripts)throw Error('Prechoice fetched/started 3D: '+name);
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
   await page.locator('input[name="model-choice"][value="osmo"]').check({force:true});
   const started=Date.now();await page.click('#open-model');await ready(page);row.readySeconds=(Date.now()-started)/1000;row.draw=await page.evaluate(()=>__room.stable());row.renderer=await page.evaluate(()=>__room.rendererInfo());
   const phone=name==='wide-touch';
   if(row.draw.dpr!==(phone?1.5:2)||row.draw.lod!==phone||row.draw.activeSplats>(phone?1500000:3000000)||row.draw.activeSplats<1||!row.draw.extSplats||row.draw.blur!==.05)throw Error('Device rendering policy does not match mandate: '+name);
   if(expectStick){
    const held=await cameraSummary(page),heldRequests=requests.filter(modelRequest);
    if(!held.source||!heldRequests.length||!(await page.locator('#stats').textContent()).startsWith('Omso Held'))throw Error('Held verification is incomplete');
    const offset=requests.length;
    await page.goto(base+'?quality=osmo-stick');
    const [manifestResponse]=await Promise.all([
     page.waitForResponse(r=>/\/room-[a-f0-9]{10}\.json$/.test(new URL(r.url()).pathname),{timeout:90000}),
     page.click('#open-model').then(()=>ready(page))
    ]);
    const manifest=await manifestResponse.json(),asset=manifest.models['osmo-stick'];
    const stick=await cameraSummary(page),draw=await page.evaluate(()=>__room.stable());
    const modelRequests=requests.slice(offset).filter(modelRequest);
    if(!asset||asset.cameraSet!=='osmo-stick'||!Number.isSafeInteger(asset.fileBytes)||asset.fileBytes>=30_000_000||asset.url===manifest.models.osmo.url||!stick.source||stick.source===held.source)
     throw Error('Stick model or camera lineage overlaps Held, or budget exceeded');
    if(JSON.stringify(held.first)!==JSON.stringify(manifest.cameraSets.osmo.presets[0])||JSON.stringify(held.start)!==JSON.stringify(manifest.cameraSets.osmo.startCamera))throw Error('Held viewer did not apply its calibrated cameras');
    if(JSON.stringify(stick.first)!==JSON.stringify(manifest.cameraSets['osmo-stick'].presets[0])||JSON.stringify(stick.start)!==JSON.stringify(manifest.cameraSets['osmo-stick'].startCamera))throw Error('Stick viewer did not apply its calibrated cameras');
    if(modelRequests.length!==1||modelRequests[0]!==new URL(asset.url,base).href||draw.activeSplats<1||draw.activeSplats>(phone?1500000:3000000)||draw.lod!==phone||draw.dpr!==(phone?1.5:2)||!draw.extSplats||!(await page.locator('#stats').textContent()).startsWith('Osmo Stick'))
     throw Error('Stick selected another payload or failed to render with the expected device policy');
    row.stick={fileBytes:asset.fileBytes,draw,modelRequests,heldCameraSource:held.source,stickCameraSource:stick.source};
   }
  }
  row.modelRequests=requests.filter(modelRequest);
  row.fullModelRequests=row.modelRequests.filter(u=>/iphone[-_].*full|16f8963b/i.test(new URL(u).pathname));
  if(row.fullModelRequests.length)throw Error('Retired iPhone Full was requested: '+name);
  if(errors.length)throw Error(errors.join('\n'));rows.push(row);console.log('PASS',name,'zero prechoice bytes',row.draw||'');await context.close();
 }
}finally{await fs.writeFile(path.join(W,process.env.VERIFICATION_OUTPUT||'choice-and-phone-policy-verification.json'),JSON.stringify({expectStick,rows,scope:'Desktop Chrome GPU with touch/DPR emulation. No physical Fold 7, iPhone 17 or Safari claim.'},null,2));await browser.close();}
