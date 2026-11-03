// Isolated production staging. Never deploys and never writes old public/.
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import zlib from 'node:zlib';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import crypto from 'node:crypto';
import {nativePolicy,validateModelHeader} from './native-delivery.js';
import {validateShapes} from './simple-shapes.js';
import {footprintBytes} from './gaussian-cutaway.js';
const here=path.dirname(fileURLToPath(import.meta.url)),work=path.resolve(here,'../../..'),pub=path.join(here,'public');
const old=path.join(work,'mobile-20261029/iphone-baseline');
const require=createRequire(path.join(work,'mobile-20261029/package.json')), {build}=require('esbuild');
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const args=process.argv.slice(2);
if(args.length&&(args.length!==2||args[0]!=='--stick-candidate'||!args[1]))throw Error('Usage: node build.mjs [--stick-candidate <path>]');
const sourceStickCandidate=args.length?path.resolve(args[1]):null;
const stickConfigBytes=sourceStickCandidate?await fs.readFile(sourceStickCandidate):null;
const stickConfig=stickConfigBytes?JSON.parse(stickConfigBytes):null;
if(sourceStickCandidate&&(!stickConfig||typeof stickConfig!=='object'||Array.isArray(stickConfig)))throw Error('Osmo Stick candidate must be a JSON object.');
const manifest=await read(path.join(old,'manifest.json'));
// Full was retired by the owner. Preserve only Lite and its calibrated cameras.
manifest.models={phone:manifest.models.phone};
manifest.cameraSets={iphone:manifest.cameraSets.iphone};
const candidate=await read(path.join(here,'candidate.json'));
const provisional=candidate.provisional!==false;
const releaseId=stickConfig?stickConfig.releaseId:provisional?'20261031-native-provisional':candidate.releaseId;
if(!/^[0-9]{8}-[a-z0-9-]+$/.test(releaseId||''))throw Error('A safe dated release ID is required.');
if(!provisional&&(!candidate.newTraining||!candidate.cameras))throw Error('Final release requires the fresh training candidate and its fresh camera export.');
if(stickConfig&&(provisional||stickConfig.provisional!==false||stickConfig.newTraining!==true||releaseId===candidate.releaseId||!stickConfig.file||!stickConfig.cameras||!stickConfig.packingReport))
 throw Error('Osmo Stick requires a separate dated release and an explicit trained candidate, camera export and packing report.');
const assetPath=path.resolve(here,candidate.file), bytes=await fs.readFile(assetPath),sha=hash(bytes);
const format=candidate.format;
if(sha!==candidate.sha256||bytes.length!==candidate.bytes||!validateModelHeader(bytes,format))throw Error('Candidate hash, bytes or format do not match.');
// Splat count and SH degree drive the phone budget; take them only from the matching pack report.
const packing=candidate.packingReport&&await read(path.resolve(here,candidate.packingReport));
if(packing&&(packing.sha256!==sha||packing.splats!==candidate.splats||packing.shDegree!==candidate.shDegree))throw Error('Candidate splats or SH degree differ from its packing report.');
const sourceName=`models/osmo-native-${sha.slice(0,10)}.${format}`;
const asset={label:'Omso Held',representation:'gaussian',format,cameraSet:'osmo',url:sourceName,fileBytes:bytes.length,downloadBytes:bytes.length,splats:candidate.splats,shDegree:candidate.shDegree,note:'Omso Held · native Gaussian view · approximate scale',provisional};
nativePolicy(asset,true);
manifest.build=releaseId;manifest.models.osmo=asset;
const originals={phone:JSON.parse(JSON.stringify(manifest.models.phone)),iphone:JSON.parse(JSON.stringify(manifest.cameraSets.iphone))};
await fs.mkdir(path.join(pub,'models'),{recursive:true});await fs.mkdir(path.join(pub,'sources'),{recursive:true});
// A reused staging folder may still contain the retired Full hardlinks. Unlink
// only named leaves in this build's own models directory; never touch the source.
const modelDir=path.join(pub,'models');
if((await fs.lstat(modelDir)).isSymbolicLink())throw Error('Staging models directory must not be a symlink');
for(const name of await fs.readdir(modelDir))if(/^iphone-full-.*\.glb(?:\.gz)?$/i.test(name))await fs.unlink(path.join(modelDir,name));
async function hardlink(from,to){await fs.mkdir(path.dirname(to),{recursive:true});try{await fs.link(from,to);}catch(e){if(e.code!=='EEXIST')throw e;const a=await fs.stat(from),b=await fs.stat(to);if(a.size!==b.size)throw Error('Existing staging file differs: '+to);}}
await hardlink(assetPath,path.join(pub,sourceName));
const carried=new Set();
for(const value of Object.values(manifest.models)){if(value.url!==sourceName)carried.add(value.url);if(value.preview)carried.add(value.preview);}
for(const cameras of Object.values(manifest.cameraSets))for(const photo of [...cameras.presets,...cameras.photos])if(photo.source)carried.add(photo.source);
// Carried iPhone payloads must match asset-files.json. A regenerated .gz must decode to the protected
// bytes; its own size may differ across zlib versions, which is reported rather than refused.
const catalog=Object.fromEntries((await read(path.join(old,'asset-files.json'))).files.map(f=>[f.path,f]));
const digest=stream=>new Promise((resolve,reject)=>{const h=crypto.createHash('sha256');let bytes=0;stream.on('data',c=>{h.update(c);bytes+=c.length;}).on('end',()=>resolve({sha256:h.digest('hex'),bytes})).on('error',reject);});
for(const file of carried){
 const row=catalog[file],gz=path.join(old,file+'.gz');
 if(!row)throw Error('Carried iPhone file is not in asset-files.json: '+file);
 const got=await digest(createReadStream(path.join(old,file)));if(got.sha256!==row.sha256||got.bytes!==row.bytes)throw Error('Carried iPhone file differs from asset-files.json: '+file);
 await hardlink(path.join(old,file),path.join(pub,file));
 try{await fs.access(gz);}catch{continue;}
 const decoded=await digest(createReadStream(gz).pipe(zlib.createGunzip()));if(decoded.sha256!==row.sha256)throw Error('Transfer copy does not decode to the protected file: '+file+'.gz');
 const recorded=catalog[file+'.gz'],size=(await fs.stat(gz)).size;if(recorded&&size!==recorded.bytes)console.warn(`${file}.gz is ${size} bytes, not the recorded ${recorded.bytes} (another zlib build); the chooser still shows the recorded size.`);
 await hardlink(gz,path.join(pub,file+'.gz'));
}
async function stageCameraSet(cameraFile,cameras,viewLabel){
 if(!cameras.startCamera||!cameras.bounds||!Array.isArray(cameras.presets))throw Error('Fresh camera set needs bounds, startCamera and calibrated presets.');
 const sharp=require('sharp');
 const presets=[];
 for(const p of cameras.presets){
  if(!p.sourceFile||!p.intrinsics||!p.position||!p.quaternion)throw Error('Each fresh camera needs calibrated pose, K and source image.');
  const image=path.resolve(path.dirname(cameraFile),p.sourceFile);
  const jpeg=await sharp(image).resize({width:1920,withoutEnlargement:true}).jpeg({quality:86}).toBuffer();
  const source=`sources/osmo-${hash(jpeg).slice(0,10)}.jpg`;
  await fs.writeFile(path.join(pub,source),jpeg);
  const label=Number.isFinite(p.sourceTimeSeconds)?`Capture ${p.sourceTimeSeconds.toFixed(2)}s`:p.label;
  presets.push({name:`${viewLabel} ${presets.length+1}`,label,sourceTimeSeconds:p.sourceTimeSeconds,position:p.position,quaternion:p.quaternion,imageWidth:p.imageWidth,imageHeight:p.imageHeight,intrinsics:p.intrinsics,source});
 }
 return {bounds:cameras.bounds,framingPoints:cameras.framingPoints,occupiedShell:cameras.occupiedShell,startCamera:cameras.startCamera,homeTarget:cameras.homeTarget,presets,photos:presets.map(p=>({name:p.name,label:p.label,source:p.source}))};
}
if(candidate.cameras){
 const cameraFile=path.resolve(here,candidate.cameras);
 manifest.cameraSets.osmo=await stageCameraSet(cameraFile,await read(cameraFile),'Osmo view');
 if(candidate.worldFromTraining)asset.worldFromTraining=candidate.worldFromTraining;
}
let stick;
if(stickConfig){
 const stickDir=path.dirname(sourceStickCandidate),stickPath=path.resolve(stickDir,stickConfig.file);
 const stickSize=(await fs.stat(stickPath)).size;
 if(stickSize<12||stickSize>=30_000_000||stickSize!==stickConfig.bytes)throw Error('Osmo Stick must be an exact payload smaller than 30 MB.');
 const stickBytes=await fs.readFile(stickPath),stickSha=hash(stickBytes),stickFormat=stickConfig.format;
 if(stickSha===sha||stickSha!==stickConfig.sha256||stickBytes.length!==stickSize||!validateModelHeader(stickBytes,stickFormat))throw Error('Osmo Stick hash, size or format is invalid or reuses the Held model.');
 const stickPack=await read(path.resolve(stickDir,stickConfig.packingReport));
 if(!Number.isInteger(stickConfig.shDegree)||stickConfig.shDegree<0||stickConfig.shDegree>3)throw Error('Osmo Stick SH degree is invalid.');
 for(const key of ['sha256','bytes','format','splats','shDegree'])if(stickPack[key]!==stickConfig[key])throw Error('Osmo Stick packing report differs: '+key);
 if(!/^[a-f0-9]{64}$/.test(stickPack.sourceSha256)||stickPack.sourceSha256===packing?.sourceSha256||stickPack.sourceCountPreserved!==true||stickPack.sourceShDegreePreserved!==true)
  throw Error('Osmo Stick must preserve its own packed source lineage.');
 const cameraFile=path.resolve(stickDir,stickConfig.cameras),cameras=await read(cameraFile);
 const shell=cameras.occupiedShell,footprint=shell?.footprint;
 const vector=(value,length)=>Array.isArray(value)&&value.length===length&&value.every(Number.isFinite);
 const pose=value=>vector(value?.position,3)&&vector(value?.quaternion,4)&&Math.abs(Math.hypot(...value.quaternion)-1)<0.01;
 if(cameras.coordinateFrame!=='+Y up'||!Array.isArray(cameras.presets)||!cameras.presets.length||!Array.isArray(cameras.framingPoints)||cameras.framingPoints.length<30||cameras.framingPoints.length%3||!cameras.framingPoints.every(Number.isFinite)||footprint?.source?.sha256!==stickPack.sourceSha256)
  throw Error('Osmo Stick needs a calibrated camera export and footprint fitted to its own source.');
 if(!Array.isArray(cameras.bounds)||cameras.bounds.length!==2||!cameras.bounds.every(v=>vector(v,3))||!cameras.bounds[1].every((n,i)=>n>cameras.bounds[0][i])||!pose(cameras.startCamera)||!cameras.presets.every(p=>pose(p)&&vector(p.intrinsics,4)&&p.intrinsics[0]>0&&p.intrinsics[1]>0&&Number.isSafeInteger(p.imageWidth)&&p.imageWidth>0&&Number.isSafeInteger(p.imageHeight)&&p.imageHeight>0))
  throw Error('Osmo Stick camera bounds, poses or calibration are invalid.');
 if(!vector(footprint.origin,2)||!Number.isFinite(footprint.exteriorMargin)||!Number.isFinite(shell.ceilingBand)||!vector(shell.fittedPlanes?.floor?.YequalsAXplusBZplusC,3)||!vector(shell.fittedPlanes?.upperCeiling?.YequalsAXplusBZplusC,3)||footprint.lowerCeiling&&!vector(footprint.lowerCeiling.YequalsAXplusBZplusC,3))
  throw Error('Osmo Stick fitted shell is invalid.');
 footprintBytes(footprint);
 const url=`models/osmo-native-${stickSha.slice(0,10)}.${stickFormat}`;
 stick={label:'Osmo Stick',representation:'gaussian',format:stickFormat,cameraSet:'osmo-stick',url,fileBytes:stickSize,downloadBytes:stickSize,splats:stickConfig.splats,shDegree:stickConfig.shDegree,note:'Osmo Stick · native Gaussian view · approximate scale',provisional:false};
 if(stickConfig.worldFromTraining)stick.worldFromTraining=stickConfig.worldFromTraining;
 nativePolicy(stick,true);
 await hardlink(stickPath,path.join(pub,url));
 const staged=await digest(createReadStream(path.join(pub,url)));
 if(staged.sha256!==stickSha||staged.bytes!==stickSize)throw Error('Staged Osmo Stick payload differs.');
 manifest.models['osmo-stick']=stick;
 manifest.cameraSets['osmo-stick']=await stageCameraSet(cameraFile,cameras,'Osmo Stick view');
}
if(candidate.simpleShapes){
 // Optional simple-shape stand-in, fetched only when the viewer asks for it.
 const shapes=await fs.readFile(path.resolve(here,candidate.simpleShapes)),data=JSON.parse(shapes);validateShapes(data);
 if(data.source?.sha256!==packing?.sourceSha256)throw Error('Simple shapes were not fitted to this candidate.');
 const name=`models/osmo-shapes-${hash(shapes).slice(0,10)}.json`;await fs.writeFile(path.join(pub,name),shapes);
 asset.simple={url:name,fileBytes:shapes.length,shapes:data.shapes.length};
 if(manifest.cameraSets.osmo)manifest.cameraSets.osmo.manhattanYaw=data.manhattanYaw;  // orbit views square up to the walls
}
if(JSON.stringify(originals.phone)!==JSON.stringify(manifest.models.phone)||JSON.stringify(originals.iphone)!==JSON.stringify(manifest.cameraSets.iphone))throw Error('iPhone Lite metadata changed.');
const manifestBytes=Buffer.from(JSON.stringify(manifest)),manifestName=`room-${hash(manifestBytes).slice(0,10)}.json`;await fs.writeFile(path.join(pub,manifestName),manifestBytes);
const source=(await fs.readFile(path.join(here,'room-viewer.js'),'utf8')).replace('__MANIFEST__',manifestName).replaceAll('20261031-native-provisional',releaseId);
await fs.writeFile(path.join(here,'build-entry.js'),source);
const result=await build({absWorkingDir:here,entryPoints:{'room-viewer':path.join(here,'build-entry.js')},outdir:pub,nodePaths:[path.join(work,'mobile-20261029/node_modules')],bundle:true,write:false,minify:true,format:'esm',splitting:true,entryNames:'[name]-[hash]',chunkNames:'chunks/[name]-[hash]',target:'es2020',logLevel:'warning',metafile:true});
for(const output of result.outputFiles){await fs.mkdir(path.dirname(output.path),{recursive:true});await fs.writeFile(output.path,output.contents);}
const bundle=result.outputFiles.find(o=>path.basename(o.path).startsWith('room-viewer-')),bundleName=path.basename(bundle.path);
const chooser=(await fs.readFile(path.join(here,'chooser.js'),'utf8')).replace('__BUNDLE__',bundleName);
const gate=await build({stdin:{contents:chooser,sourcefile:'chooser.js',resolveDir:here},bundle:true,write:false,minify:true,format:'iife',target:'es2020',logLevel:'warning'});
let shell=(await fs.readFile(path.join(here,'room-shell.html'),'utf8')).replace('__CHOOSER_INLINE__',()=>gate.outputFiles[0].text.replaceAll('20261031-native-provisional',releaseId).replaceAll('</script','<\\/script'));
for(const [key,marker] of [['phone','PHONE'],['osmo','OSMO']]){const m=manifest.models[key];shell=shell.replace(`__${marker}_COST__`,'≈ '+(m.downloadBytes/1e6).toFixed(1)+' MB').replace(`__${marker}_FILE__`,(m.fileBytes/1e6).toFixed(1)+' MB');}
if(stick){
 const size=(stick.fileBytes/1e6).toFixed(1)+' MB';
 shell=shell.replace('class="choice-cards"','class="choice-cards has-stick"')
  .replace('<!-- stick-choice -->',`<label class="choice-card"><input type="radio" name="model-choice" value="osmo-stick" aria-label="Osmo Stick"><span class="choice-name">Osmo Stick</span><span class="choice-size">≈ ${size} download</span><span class="choice-description">Photographic walkthrough from the stick-mounted 360° capture.</span><span class="choice-file">${size} model file</span></label>`)
  .replace('<!-- stick-option -->','<option value="osmo-stick">Osmo Stick</option>');
}
if(/__[A-Z_]+__/.test(shell)||/<(?:img|script)\b[^>]*\bsrc\s*=/i.test(shell)||/\brel=["'](?:preload|prefetch|modulepreload)/i.test(shell))throw Error('Quota gate contains an automatic resource request.');
await fs.writeFile(path.join(pub,'index.html'),shell);
await fs.writeFile(path.join(pub,'robots.txt'),'User-agent: *\nDisallow: /\n');
const report={build:manifest.build,provisional,deploymentAuthorized:false,sourceCandidate:assetPath,candidateSha256:sha,manifestName,bundleName,osmo:asset,iphoneMetadataUnchanged:true,choiceRequired:true,automaticModelRetry:false,prechoiceExternalRequests:0,lodPolicy:nativePolicy(asset,true),runtimeMemoryWarning:'LOD display budget limits active draws, not transient decoder/build memory. Physical Fold 7/iPhone 17 memory and touch tests remain required. Prebuilt paged RAD or SOG path should be benchmarked before release.',sourceFormat:`Actual Gaussian PLY -> ${format.toUpperCase()}; no mesh or photo texture proxy`,newTrainingNotUsed:!candidate.newTraining,metafile:result.metafile};
if(stick)Object.assign(report,{stick,stickCandidateSha256:hash(stickConfigBytes),sourceStickCandidate});
await fs.writeFile(path.join(here,'build-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({...report,metafile:undefined},null,2));
