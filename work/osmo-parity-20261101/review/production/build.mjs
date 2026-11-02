// Isolated production staging. Never deploys and never writes old public/.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import crypto from 'node:crypto';
import {nativePolicy,validateModelHeader} from './native-delivery.js';
const here=path.dirname(fileURLToPath(import.meta.url)),work=path.resolve(here,'../../..'),pub=path.join(here,'public');
const old=path.join(work,'mobile-20261029/iphone-baseline');
const require=createRequire(path.join(work,'mobile-20261029/package.json')), {build}=require('esbuild');
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const manifest=await read(path.join(old,'manifest.json'));
const candidate=await read(path.join(here,'candidate.json'));
const provisional=candidate.provisional!==false;
const releaseId=provisional?'20261031-native-provisional':candidate.releaseId;
if(!/^[0-9]{8}-[a-z0-9-]+$/.test(releaseId||''))throw Error('A safe dated release ID is required.');
if(!provisional&&(!candidate.newTraining||!candidate.cameras))throw Error('Final release requires the fresh training candidate and its fresh camera export.');
const assetPath=path.resolve(here,candidate.file), bytes=await fs.readFile(assetPath),sha=hash(bytes);
const format=candidate.format;
if(sha!==candidate.sha256||bytes.length!==candidate.bytes||!validateModelHeader(bytes,format))throw Error('Candidate hash, bytes or format do not match.');
// Splat count and SH degree drive the phone budget; take them only from the matching pack report.
const packing=candidate.packingReport&&await read(path.resolve(here,candidate.packingReport));
if(packing&&(packing.sha256!==sha||packing.splats!==candidate.splats||packing.shDegree!==candidate.shDegree))throw Error('Candidate splats or SH degree differ from its packing report.');
const sourceName=`models/osmo-native-${sha.slice(0,10)}.${format}`;
const asset={label:'Osmo',representation:'gaussian',format,cameraSet:'osmo',url:sourceName,fileBytes:bytes.length,downloadBytes:bytes.length,splats:candidate.splats,shDegree:candidate.shDegree,note:'Osmo · native Gaussian view · approximate scale',provisional};
nativePolicy(asset,true);
manifest.build=releaseId;manifest.models.osmo=asset;
const originals={phone:JSON.parse(JSON.stringify(manifest.models.phone)),native:JSON.parse(JSON.stringify(manifest.models.native)),iphone:JSON.parse(JSON.stringify(manifest.cameraSets.iphone))};
await fs.mkdir(path.join(pub,'models'),{recursive:true});await fs.mkdir(path.join(pub,'sources'),{recursive:true});
async function hardlink(from,to){await fs.mkdir(path.dirname(to),{recursive:true});try{await fs.link(from,to);}catch(e){if(e.code!=='EEXIST')throw e;const a=await fs.stat(from),b=await fs.stat(to);if(a.size!==b.size)throw Error('Existing staging file differs: '+to);}}
await hardlink(assetPath,path.join(pub,sourceName));
const carried=new Set();
for(const value of Object.values(manifest.models)){if(value.url!==sourceName)carried.add(value.url);if(value.preview)carried.add(value.preview);}
for(const cameras of Object.values(manifest.cameraSets))for(const photo of [...cameras.presets,...cameras.photos])if(photo.source)carried.add(photo.source);
for(const file of carried){await hardlink(path.join(old,file),path.join(pub,file));try{await hardlink(path.join(old,file+'.gz'),path.join(pub,file+'.gz'));}catch(e){if(e.code!=='ENOENT')throw e;}}
if(candidate.cameras){
 const cameraFile=path.resolve(here,candidate.cameras);
 const cameras=await read(cameraFile);
 if(!cameras.startCamera||!cameras.bounds||!Array.isArray(cameras.presets))throw Error('Fresh camera set needs bounds, startCamera and calibrated presets.');
 const sharp=require('sharp');
 const presets=[];
 for(const p of cameras.presets){if(!p.sourceFile||!p.intrinsics||!p.position||!p.quaternion)throw Error('Each fresh camera needs calibrated pose, K and source image.');const jpeg=await sharp(path.resolve(path.dirname(cameraFile),p.sourceFile)).resize({width:1920,withoutEnlargement:true}).jpeg({quality:86}).toBuffer();const source=`sources/osmo-${hash(jpeg).slice(0,10)}.jpg`;await fs.writeFile(path.join(pub,source),jpeg);const label=Number.isFinite(p.sourceTimeSeconds)?`Capture ${p.sourceTimeSeconds.toFixed(2)}s`:p.label;presets.push({name:`Osmo view ${presets.length+1}`,label,sourceTimeSeconds:p.sourceTimeSeconds,position:p.position,quaternion:p.quaternion,imageWidth:p.imageWidth,imageHeight:p.imageHeight,intrinsics:p.intrinsics,source});}
 manifest.cameraSets.osmo={bounds:cameras.bounds,framingPoints:cameras.framingPoints,occupiedShell:cameras.occupiedShell,startCamera:cameras.startCamera,homeTarget:cameras.homeTarget,presets,photos:presets.map(p=>({name:p.name,label:p.label,source:p.source}))};
 if(candidate.worldFromTraining)asset.worldFromTraining=candidate.worldFromTraining;
}
if(JSON.stringify(originals.phone)!==JSON.stringify(manifest.models.phone)||JSON.stringify(originals.native)!==JSON.stringify(manifest.models.native)||JSON.stringify(originals.iphone)!==JSON.stringify(manifest.cameraSets.iphone))throw Error('iPhone metadata changed.');
const manifestBytes=Buffer.from(JSON.stringify(manifest)),manifestName=`room-${hash(manifestBytes).slice(0,10)}.json`;await fs.writeFile(path.join(pub,manifestName),manifestBytes);
const source=(await fs.readFile(path.join(here,'room-viewer.js'),'utf8')).replace('__MANIFEST__',manifestName).replaceAll('20261031-native-provisional',releaseId);
await fs.writeFile(path.join(here,'build-entry.js'),source);
const result=await build({absWorkingDir:here,entryPoints:{'room-viewer':path.join(here,'build-entry.js')},outdir:pub,nodePaths:[path.join(work,'mobile-20261029/node_modules')],bundle:true,write:false,minify:true,format:'esm',splitting:true,entryNames:'[name]-[hash]',chunkNames:'chunks/[name]-[hash]',target:'es2020',logLevel:'warning',metafile:true});
for(const output of result.outputFiles){await fs.mkdir(path.dirname(output.path),{recursive:true});await fs.writeFile(output.path,output.contents);}
const bundle=result.outputFiles.find(o=>path.basename(o.path).startsWith('room-viewer-')),bundleName=path.basename(bundle.path);
const chooser=(await fs.readFile(path.join(here,'chooser.js'),'utf8')).replace('__BUNDLE__',bundleName);
const gate=await build({stdin:{contents:chooser,sourcefile:'chooser.js',resolveDir:here},bundle:true,write:false,minify:true,format:'iife',target:'es2020',logLevel:'warning'});
let shell=(await fs.readFile(path.join(here,'room-shell.html'),'utf8')).replace('__CHOOSER_INLINE__',()=>gate.outputFiles[0].text.replaceAll('20261031-native-provisional',releaseId).replaceAll('</script','<\\/script'));
for(const [key,marker] of [['phone','PHONE'],['native','NATIVE'],['osmo','OSMO']]){const m=manifest.models[key];shell=shell.replace(`__${marker}_COST__`,'≈ '+(m.downloadBytes/1e6).toFixed(1)+' MB').replace(`__${marker}_FILE__`,(m.fileBytes/1e6).toFixed(1)+' MB');}
if(/__[A-Z_]+__/.test(shell)||/<(?:img|script)\b[^>]*\bsrc\s*=/i.test(shell)||/\brel=["'](?:preload|prefetch|modulepreload)/i.test(shell))throw Error('Quota gate contains an automatic resource request.');
await fs.writeFile(path.join(pub,'index.html'),shell);
await fs.writeFile(path.join(pub,'robots.txt'),'User-agent: *\nDisallow: /\n');
const report={build:manifest.build,provisional,deploymentAuthorized:false,sourceCandidate:assetPath,candidateSha256:sha,manifestName,bundleName,osmo:asset,iphoneMetadataUnchanged:true,choiceRequired:true,automaticModelRetry:false,prechoiceExternalRequests:0,lodPolicy:nativePolicy(asset,true),runtimeMemoryWarning:'LOD display budget limits active draws, not transient decoder/build memory. Physical Fold 7/iPhone 17 memory and touch tests remain required. Prebuilt paged RAD or SOG path should be benchmarked before release.',sourceFormat:`Actual Gaussian PLY -> ${format.toUpperCase()}; no mesh or photo texture proxy`,newTrainingNotUsed:!candidate.newTraining,metafile:result.metafile};
await fs.writeFile(path.join(here,'build-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({...report,metafile:undefined},null,2));
