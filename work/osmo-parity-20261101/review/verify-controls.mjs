import {createRequire} from 'node:module';import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';
const require=createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../mobile-20261029/package.json')),{chromium}=require('playwright-core'),angle={win32:'d3d11',darwin:'metal'}[process.platform],chrome=process.env.CHROME_PATH||process.platform==='win32'?{executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{channel:'chrome'};
const here=path.dirname(fileURLToPath(import.meta.url)),reviewModel=process.env.REVIEW_MODEL||(process.env.MESH_PREVIEW==='1'?'vertex':''),evidence=process.env.EVIDENCE_DIR||(reviewModel?reviewModel+'-evidence':'evidence');await fs.mkdir(path.join(here,evidence),{recursive:true});
const browser=await chromium.launch({...chrome,headless:true,args:['--enable-gpu',...(angle?['--use-angle='+angle]:[]),'--disable-background-timer-throttling']});
const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});const errors=[],checks=[],requests=[];
await page.route('**/favicon.ico',route=>route.fulfill({status:204}));
page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text().slice(0,1500));});page.on('request',r=>requests.push(r.url()));
const check=(name,pass,evidence)=>{checks.push({name,pass:!!pass,evidence:structuredClone(evidence)});console.log(pass?'PASS':'FAIL',name);};
const state=()=>page.evaluate(()=>__room.state());
const shapeRequest=u=>/\/models\/osmo-shapes-[0-9a-f]{10}\.json(?:\?|$)/.test(u);
const pose=s=>({position:s.position,quaternion:s.quaternion,projection:s.projection,fov:s.fov,mode:s.mode,orbit:s.orbit});
const samePose=(a,b)=>JSON.stringify(pose(a))===JSON.stringify(pose(b));
const pureGaussian=s=>!s.simpleShapes&&s.shapeSubstitution==='none'&&s.visibleShapeMeshes===0&&s.gaussianVisible===true&&s.overviewWalls===false&&s.shapeShadows===false;
let expectedShapes=0;
async function stable(){await page.evaluate(()=>__room.stable());await page.waitForTimeout(100);return state();}
async function setSimple(on){
 if((await state()).simpleShapes!==on){
  const first=on&&!requests.some(shapeRequest),response=first?page.waitForResponse(r=>shapeRequest(r.url())):null;
  await page.click('#simple');
  if(response){const data=await (await response).json();expectedShapes=data.shapes.length;}
  await page.waitForFunction(value=>__room.state().simpleShapes===value,on,{timeout:30000});
 }
 return stable();
}
async function setInside(on){if((await state()).seeInside!==on)await page.click('#see-inside');return stable();}
function allShapes(s){return s.simpleShapes&&s.shapeSubstitution==='all'&&s.gaussianVisible===false&&s.overviewWalls===false&&s.shapeShadows===true&&s.totalShapeMeshes===expectedShapes&&s.visibleShapeMeshes>0&&(s.seeInside?s.visibleShapeMeshes<expectedShapes:s.visibleShapeMeshes===expectedShapes);}
try{
 await page.goto((process.env.BASE_URL||'http://127.0.0.1:53270/')+'?quality=osmo&ablation=1'+(reviewModel?'&mesh='+reviewModel:''));await page.waitForTimeout(1500);
 check('Zero model bytes before explicit open',!requests.some(u=>/\.(sog|glb|spz|ply)(\?|$)/.test(u)),requests);
 await page.screenshot({path:path.join(here,evidence+'/00-model-chooser.png')});
 console.log('BUTTONS',await page.locator('button').allTextContents());
 await page.locator('#open-model').click();await page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',undefined,{timeout:90000});
 await page.waitForTimeout(2000);const gpu=await page.evaluate(()=>__room.rendererInfo());check('GPU hardware',gpu.renderer!=='unavailable'&&!/swiftshader|llvmpipe|softpipe|software/i.test(gpu.renderer),gpu);
 let s=await state();check('Default fitted dollhouse',s.mode==='orbit'&&s.fov===42&&s.seeInside&&s.orbit.radius>4,s);
 if(!reviewModel)check('Default overview is photographic with no inferred primitives',pureGaussian(s)&&s.totalShapeMeshes===0&&/Photographic reconstruction/.test(await page.locator('#quality-note').textContent())&&await page.locator('#quality-note').isVisible()&&await page.locator('#photographic-view').isHidden(),{state:s,note:await page.locator('#view-details').textContent()});
 check('Overview controls enabled',await page.locator('#top').isVisible()&&await page.locator('#top').isEnabled()&&await page.locator('#see-inside').isVisible(),null);
 await page.screenshot({path:path.join(here,evidence+'/01-osmo-dollhouse.png')});
 await page.click('#top');await page.waitForTimeout(1000);s=await state();check('Top view',s.forward[1]<-.999&&s.mode==='orbit',s);await page.screenshot({path:path.join(here,evidence+'/02-osmo-top.png')});
 await page.click('#see-inside');await page.waitForTimeout(1000);s=await state();check('Shell restores',!s.seeInside,s);await page.screenshot({path:path.join(here,evidence+'/03-osmo-roof-restored.png')});
 await page.click('#reset');await page.waitForTimeout(1000);s=await state();check('Orbit reset stays overview',s.mode==='orbit'&&s.seeInside&&s.fov===42,s);
 await page.click('#walk');await page.waitForTimeout(1000);s=await state();check('Walk starts inside with shell restored',s.mode==='walk'&&!s.seeInside&&s.position.every((v,i)=>v>=-5&&v<=5),s);
 await page.click('#reset');s=await state();check('Walk reset stays walk',s.mode==='walk',s);
 await page.selectOption('#views','0');const a=await state();await page.mouse.move(900,500);await page.mouse.down();const b=await state();await page.mouse.up();
 check('Preset exit preserves pixel focal length',Math.abs(a.projection[5]-b.projection[5])<1e-6,{before:a.projection[5],after:b.projection[5],beforePose:a.position,afterPose:b.position});
 await page.keyboard.down('w');await page.waitForTimeout(250);await page.keyboard.up('w');await page.waitForTimeout(600);const released=await state();await page.waitForTimeout(300);const stopped=await state();
 check('Walking input releases without cleanup',released.keys.length===0&&Math.hypot(...stopped.position.map((x,i)=>x-released.position[i]))<.001,{released,stopped});
 await page.click('#orbit');await page.waitForTimeout(1500);await page.screenshot({path:path.join(here,evidence+'/04-osmo-orbit-return.png')});
 if(!reviewModel){
  check('Orbit Top and Walk do not automatically fetch a shape asset',!requests.some(shapeRequest)&&pureGaussian(await state()),requests.filter(shapeRequest));
  s=await setSimple(true);
  check('Simple shapes are explicitly labeled as inferred',allShapes(s)&&/Simple shapes.*inferred room and furniture/.test(await page.locator('#quality-note').textContent())&&await page.locator('#photographic-view').isVisible(),{state:s,expectedShapes});
  await page.click('#photographic-view');s=await state();
  check('Photographic alternative exits shapes and opens Walk',s.mode==='walk'&&pureGaussian(s)&&!s.seeInside&&/Photographic reconstruction/.test(await page.locator('#quality-note').textContent())&&await page.locator('#photographic-view').isHidden(),s);
  await page.setViewportSize({width:390,height:844});await page.click('#orbit');await page.waitForTimeout(500);
  const notice=await page.locator('#view-details').boundingBox(),stage=await page.locator('#stage').boundingBox();
  check('Phone layout keeps the photographic label visible without an inferred overlay',pureGaussian(await state())&&await page.locator('#quality-note').isVisible()&&await page.locator('#photographic-view').isHidden()&&notice?.x>=0&&notice.x+notice.width<=390&&notice.y+notice.height<=844&&stage?.height>150,{notice,stage});
  await page.screenshot({path:path.join(here,evidence+'/05-osmo-phone-layout-label.png')});
  for(const [device,viewport] of [['desktop',{width:1920,height:1080}],['phone',{width:390,height:844}]]){
   await page.setViewportSize(viewport);
   for(const [view,button] of [['orbit','#orbit'],['top','#top'],['walk','#walk']]){
    await setSimple(false);await page.click(button);await stable();
    for(const seeInside of [true,false]){
     await setInside(seeInside);const before=await setSimple(false),prefix=`06-${device}-${view}-inside-${seeInside}`,capture=seeInside&&(device==='desktop'&&(view==='orbit'||view==='top')||device==='phone'&&view==='orbit');
     if(capture)await page.screenshot({path:path.join(here,evidence,prefix+'-off.png')});
     const on=await setSimple(true);
     check(`${device} ${view} See inside ${seeInside}: ON substitutes all primitives without moving the camera`,pureGaussian(before)&&allShapes(on)&&samePose(before,on),{before,on,expectedShapes});
     if(capture)await page.screenshot({path:path.join(here,evidence,prefix+'-on.png')});
     const switched=await setInside(!seeInside),restored=await setInside(seeInside);
     check(`${device} ${view} shapes keep Gaussian hidden through shell roundtrip`,allShapes(switched)&&allShapes(restored)&&samePose(on,switched)&&samePose(on,restored),{on,switched,restored,expectedShapes});
     const after=await setSimple(false);
     check(`${device} ${view} OFF returns to pure Gaussian at the identical camera`,pureGaussian(after)&&samePose(before,after)&&before.seeInside===after.seeInside,{before,after});
     if(capture)await page.screenshot({path:path.join(here,evidence,prefix+'-off-restored.png')});
    }
   }
  }
  check('Shape asset is requested once and only after explicit ON',requests.filter(shapeRequest).length===1,{shapeRequests:requests.filter(shapeRequest),expectedShapes});
  await page.setViewportSize({width:1920,height:1080});
 }
 check('No browser/render errors',errors.length===0,errors);
}catch(e){errors.push(String(e));console.error(e);await page.screenshot({path:path.join(here,evidence+'/error.png')});}
finally{await fs.writeFile(path.join(here,process.env.VERIFICATION_OUTPUT||(reviewModel?reviewModel+'-controls-verification.json':'controls-verification.json')),JSON.stringify({checks,errors,gpu:checks.find(c=>c.name==='GPU hardware')?.evidence?.renderer??null,platform:process.platform,physicalPhonesTested:false,viewport:[1920,1080]},null,2));await browser.close();}
if(errors.length||checks.some(c=>!c.pass))process.exitCode=1;
