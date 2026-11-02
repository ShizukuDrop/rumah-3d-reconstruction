import {createRequire} from 'node:module';import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';
const require=createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../mobile-20261029/package.json')),{chromium}=require('playwright-core'),angle={win32:'d3d11',darwin:'metal'}[process.platform],chrome=process.env.CHROME_PATH||process.platform==='win32'?{executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}:{channel:'chrome'};
const here=path.dirname(fileURLToPath(import.meta.url)),reviewModel=process.env.REVIEW_MODEL||(process.env.MESH_PREVIEW==='1'?'vertex':''),evidence=process.env.EVIDENCE_DIR||(reviewModel?reviewModel+'-evidence':'evidence');await fs.mkdir(path.join(here,evidence),{recursive:true});
const browser=await chromium.launch({...chrome,headless:true,args:['--enable-gpu',...(angle?['--use-angle='+angle]:[]),'--disable-background-timer-throttling']});
const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});const errors=[],checks=[],requests=[];
await page.route('**/favicon.ico',route=>route.fulfill({status:204}));
page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text().slice(0,1500));});page.on('request',r=>requests.push(r.url()));
const check=(name,pass,evidence)=>{checks.push({name,pass:!!pass,evidence:structuredClone(evidence)});console.log(pass?'PASS':'FAIL',name);};
const state=()=>page.evaluate(()=>__room.state());
try{
 await page.goto((process.env.BASE_URL||'http://127.0.0.1:53270/')+'?quality=osmo&ablation=1'+(reviewModel?'&mesh='+reviewModel:''));await page.waitForTimeout(1500);
 check('Zero model bytes before explicit open',!requests.some(u=>/\.(sog|glb|spz|ply)(\?|$)/.test(u)),requests);
 console.log('BUTTONS',await page.locator('button').allTextContents());
 await page.locator('#open-model').click();await page.waitForFunction(()=>window.__room?.ready&&document.body.dataset.phase==='ready',undefined,{timeout:90000});
 await page.waitForTimeout(2000);const gpu=await page.evaluate(()=>__room.rendererInfo());check('GPU hardware',gpu.renderer!=='unavailable'&&!/swiftshader|llvmpipe|softpipe|software/i.test(gpu.renderer),gpu);
 let s=await state();check('Default fitted dollhouse',s.mode==='orbit'&&s.fov===42&&s.seeInside&&s.orbit.radius>4,s);
 if(!reviewModel)check('Inferred overview is labeled with a photographic alternative',s.overviewWalls&&/Layout approximation/.test(await page.locator('#quality-note').textContent())&&await page.locator('#quality-note').isVisible()&&await page.locator('#photographic-view').isVisible(),await page.locator('#view-details').textContent());
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
  await page.click('#simple');await page.waitForFunction(()=>__room.state().simpleShapes);s=await state();
  check('Simple shapes are explicitly labeled as inferred',/Simple shapes.*inferred room and furniture/.test(await page.locator('#quality-note').textContent())&&await page.locator('#photographic-view').isVisible(),s);
  await page.click('#photographic-view');s=await state();
  check('Photographic alternative exits shapes and opens Walk',s.mode==='walk'&&!s.simpleShapes&&!s.seeInside&&/Photographic reconstruction/.test(await page.locator('#quality-note').textContent())&&await page.locator('#photographic-view').isHidden(),s);
  await page.setViewportSize({width:390,height:844});await page.click('#orbit');await page.waitForTimeout(500);
  const notice=await page.locator('#view-details').boundingBox(),stage=await page.locator('#stage').boundingBox();
  check('Phone layout keeps the approximation label and action visible',await page.locator('#quality-note').isVisible()&&await page.locator('#photographic-view').isVisible()&&notice?.x>=0&&notice.x+notice.width<=390&&notice.y+notice.height<=844&&stage?.height>150,{notice,stage});
  await page.screenshot({path:path.join(here,evidence+'/05-osmo-phone-layout-label.png')});await page.setViewportSize({width:1920,height:1080});
 }
 check('No browser/render errors',errors.length===0,errors);
}catch(e){errors.push(String(e));console.error(e);await page.screenshot({path:path.join(here,evidence+'/error.png')});}
finally{await fs.writeFile(path.join(here,process.env.VERIFICATION_OUTPUT||(reviewModel?reviewModel+'-controls-verification.json':'controls-verification.json')),JSON.stringify({checks,errors,gpu:checks.find(c=>c.name==='GPU hardware')?.evidence?.renderer??null,platform:process.platform,physicalPhonesTested:false,viewport:[1920,1080]},null,2));await browser.close();}
if(errors.length||checks.some(c=>!c.pass))process.exitCode=1;
