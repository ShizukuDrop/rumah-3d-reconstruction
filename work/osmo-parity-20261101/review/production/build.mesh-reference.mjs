import {readFile,writeFile,copyFile,mkdir,link,stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import path from 'node:path';
import {OSMO_LIMITS} from './delivery-policy.js';
const here=new URL('./',import.meta.url),pub=new URL('public/',here);
const parentRequire=createRequire(new URL('../../../mobile-20261029/package.json',here));
const {build}=parentRequire('esbuild');
const sharp=parentRequire('sharp'),hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const release='20261031-osmo-v3';
const localPath=value=>path.resolve(fileURLToPath(here),value);
const json=async url=>JSON.parse(await readFile(url,'utf8'));
const finiteArray=(a,n)=>Array.isArray(a)&&a.length>=n&&a.slice(0,n).every(Number.isFinite);
const newAssets=new Set();
await mkdir(new URL('models/',pub),{recursive:true});await mkdir(new URL('sources/',pub),{recursive:true});
// Missing real inputs is a build failure; there is no placeholder Osmo model.
const osmo=await json(new URL('osmo-asset-report.json',here));
const osmoCamera=await json(new URL('osmo-cameras.json',here));
if(!osmo.file||!osmo.sha256||!Number.isSafeInteger(osmo.bytes)||osmo.bytes<12||osmo.bytes>OSMO_LIMITS.fileBytes||
   !Number.isSafeInteger(osmo.triangles)||osmo.triangles<1||!Number.isSafeInteger(osmo.maxTextureSize)||osmo.maxTextureSize>OSMO_LIMITS.textureSize||
   !Number.isSafeInteger(osmo.decodedGeometryBytes)||osmo.decodedGeometryBytes<1||osmo.decodedGeometryBytes>OSMO_LIMITS.maximumGeometryBytes||osmo.unlit!==true)
  throw Error('Osmo report must identify a real unlit model within 50,000,000 bytes, 4096px textures and 192 MiB decoded geometry.');
if(!Array.isArray(osmoCamera.bounds)||osmoCamera.bounds.length!==2||!osmoCamera.bounds.every(a=>finiteArray(a,3))||
   !osmoCamera.bounds[0].every((v,i)=>v<osmoCamera.bounds[1][i])||
   !finiteArray(osmoCamera.startCamera?.position,3)||!finiteArray(osmoCamera.startCamera?.quaternion,4))
  throw Error('Osmo camera metadata must provide finite nonempty bounds and its own start camera.');
if(osmoCamera.homeTarget&&!finiteArray(osmoCamera.homeTarget,3))throw Error('Invalid Osmo home target.');
const osmoBytes=await readFile(localPath(osmo.file)),osmoSha=hash(osmoBytes);
if(osmoSha!==osmo.sha256||osmoBytes.length!==osmo.bytes)throw Error('Osmo asset hash or length does not match its report.');
if(osmoBytes.readUInt32LE(0)!==0x46546c67||osmoBytes.readUInt32LE(4)!==2||osmoBytes.readUInt32LE(8)!==osmoBytes.length)
  throw Error('Osmo asset is not a complete glTF 2 binary.');
const osmoName=`models/osmo-lite-${osmoSha.slice(0,10)}.glb`;
await writeFile(new URL(osmoName,pub),osmoBytes);newAssets.add(osmoName);
const osmoGzip=gzipSync(osmoBytes,{level:6,mtime:0});
await writeFile(new URL(osmoName+'.gz',pub),osmoGzip);newAssets.add(osmoName+'.gz');
const addImage=async file=>{
  const bytes=await sharp(localPath(file)).rotate().resize({width:1920,withoutEnlargement:true}).jpeg({quality:86,chromaSubsampling:'4:4:4'}).toBuffer();
  const name=`sources/osmo-${hash(bytes).slice(0,10)}.jpg`;
  await writeFile(new URL(name,pub),bytes);newAssets.add(name);return name;
};
const presets=[];
for(const p of osmoCamera.presets||[]){
  if(!finiteArray(p.position,3)||!finiteArray(p.quaternion,4)||!finiteArray(p.intrinsics,4)||
     !(p.imageWidth>0&&p.imageHeight>0&&p.intrinsics[0]>0&&p.intrinsics[1]>0)||!p.sourceFile)
    throw Error('Only calibrated perspective views can be Osmo recorded camera presets. Use photos for unposed views.');
  presets.push(Object.fromEntries(['name','label','position','quaternion','imageWidth','imageHeight','intrinsics'].map(k=>[k,p[k]])));
  presets.at(-1).source=await addImage(p.sourceFile);
}
const photos=presets.map(p=>({name:p.name,label:p.label,source:p.source}));
for(const p of osmo.photos||[]){if(!p.sourceFile||!p.label)throw Error('Osmo photos need sourceFile and label.');photos.push({name:p.name||'',label:p.label,source:await addImage(p.sourceFile)});}
const osmoCameraData={bounds:osmoCamera.bounds,startCamera:osmoCamera.startCamera,presets,photos};
if(osmoCamera.homeTarget)osmoCameraData.homeTarget=osmoCamera.homeTarget;
let osmoPreview;
if(osmo.overviewFile)osmoPreview=await addImage(osmo.overviewFile);else if(photos.length)osmoPreview=photos[0].source;

const oldPub=new URL('../hosting/public/',here),mobilePub=new URL('../mobile-20261029/public/',here);
const phone=await json(new URL('../mobile-20261029/phone-asset-report.json',here));
const camera=await json(new URL('cameras.json',oldPub));
const iphoneCamera={bounds:camera.bounds,startCamera:camera.startCamera,homeTarget:camera.homeTarget,
  presets:camera.presets.map(c=>Object.fromEntries(['name','label','source','position','quaternion','imageWidth','imageHeight','intrinsics'].map(k=>[k,c[k]])))};
iphoneCamera.photos=iphoneCamera.presets.map(c=>({name:c.name,label:c.label,source:c.source}));
const preview=await sharp(fileURLToPath(new URL('../../outputs/iPhone_Wide_Rebuilt_Overview.png',here))).resize({width:1200,withoutEnlargement:true}).jpeg({quality:74}).toBuffer();
const overviewName=`overview-${hash(preview).slice(0,10)}.jpg`;await writeFile(new URL(overviewName,pub),preview);
for(const c of iphoneCamera.presets)await copyFile(new URL(c.source,oldPub),new URL(c.source,pub));
async function hardlinkExisting(from,to){
  try{await link(from,to);}catch(error){if(error.code!=='EEXIST')throw error;}
}
for(const name of [phone.phoneFile,phone.phoneFile+'.gz'])await hardlinkExisting(new URL(name,mobilePub),new URL(name,pub));
await hardlinkExisting(new URL('../../outputs/iPhone_Wide_Full_Native.glb',here),new URL('models/iphone-full-room-16f8963b.glb',pub));
const manifest={build:release,cameraSets:{iphone:iphoneCamera,osmo:osmoCameraData},models:{
  phone:{label:'iPhone Fast',cameraSet:'iphone',url:phone.phoneFile,fileBytes:phone.bytes,downloadBytes:(await stat(new URL(phone.phoneFile+'.gz',mobilePub))).size,triangles:phone.triangles,maxTextureSize:2048,preview:overviewName,note:'iPhone Fast · full-height view'},
  native:{label:'iPhone Full',cameraSet:'iphone',url:'models/iphone-full-room-16f8963b.glb',fileBytes:435614584,downloadBytes:302564257,triangles:11891853,maxTextureSize:8192,preview:overviewName,note:'iPhone Full · approximate scale'},
  osmo:{label:'Osmo',cameraSet:'osmo',url:osmoName,fileBytes:osmo.bytes,downloadBytes:osmoGzip.length,decodedGeometryBytes:osmo.decodedGeometryBytes,triangles:osmo.triangles,maxTextureSize:osmo.maxTextureSize,...(osmoPreview?{preview:osmoPreview}:{}),note:osmo.note||'Osmo · approximate scale'}
}};
const manifestBytes=Buffer.from(JSON.stringify(manifest)),manifestName=`room-${hash(manifestBytes).slice(0,10)}.json`;
await writeFile(new URL(manifestName,pub),manifestBytes);
const source=(await readFile(new URL('room-viewer.js',here),'utf8')).replace('__MANIFEST__',manifestName);
const result=await build({stdin:{contents:source,sourcefile:'room-viewer.js',resolveDir:fileURLToPath(here),loader:'js'},nodePaths:[fileURLToPath(new URL('../mobile-20261029/node_modules/',here))],bundle:true,write:false,minify:true,format:'iife',target:'es2020',logLevel:'warning'});
const bundle=result.outputFiles[0].contents,bundleName=`room-viewer-${hash(bundle).slice(0,10)}.js`;
await writeFile(new URL(bundleName,pub),bundle);
const chooserSource=(await readFile(new URL('chooser.js',here),'utf8')).replace('__BUNDLE__',bundleName);
const chooserBuild=await build({stdin:{contents:chooserSource,sourcefile:'chooser.js',resolveDir:fileURLToPath(here),loader:'js'},bundle:true,write:false,minify:true,format:'iife',target:'es2020',logLevel:'warning'});
const chooserInline=chooserBuild.outputFiles[0].text.replaceAll('</script','<\\/script');
let shell=(await readFile(new URL('room-shell.html',here),'utf8')).replace('__CHOOSER_INLINE__',chooserInline);
for(const [key,marker] of [['phone','PHONE'],['native','NATIVE'],['osmo','OSMO']]){
  const model=manifest.models[key],mb=value=>(value/1000000).toFixed(1)+' MB';
  shell=shell.replace(`__${marker}_COST__`,'≈ '+mb(model.downloadBytes)).replace(`__${marker}_FILE__`,mb(model.fileBytes));
}
if(/__[A-Z_]+__/.test(shell)||/<(?:img|script)\b[^>]*\bsrc\s*=/i.test(shell)||/\brel=["'](?:preload|prefetch|modulepreload)/i.test(shell))throw Error('Landing page contains an unresolved token or an automatic external request.');
await writeFile(new URL('index.html',pub),shell);
await writeFile(new URL('qa-script-failure.html',pub),shell.replace(bundleName,'room-viewer-qa-missing.js'));
// Private, visible read-only measurement aid. Never part of deploymentFiles.
const quotaPanel=`<aside id="quota-qa" style="position:fixed;right:8px;bottom:8px;z-index:9999;background:#071018f2;color:#e9f5ff;border:1px solid #7bbcca;border-radius:8px;padding:10px;max-width:min(94vw,560px);max-height:40vh;overflow:auto;font:11px/1.4 monospace"><button id="quota-read" style="font:12px system-ui">Read downloads</button><pre id="quota-output" style="white-space:pre-wrap;margin:6px 0 0">Read downloads before selecting, then after Open model finishes.</pre></aside><script>(()=>{document.getElementById('quota-read').onclick=()=>{const all=performance.getEntriesByType('resource'),rows=all.map(r=>({path:new URL(r.name,location.href).pathname,transferBytes:r.transferSize,decodedBytes:r.decodedBodySize})),models=rows.filter(r=>/\\.glb(?:\\.gz)?$/.test(r.path)),images=rows.filter(r=>/\\.(?:jpe?g|png|webp|avif)$/.test(r.path)),main=rows.filter(r=>/\\/room-viewer-[^/]+\\.js$/.test(r.path));document.getElementById('quota-output').textContent=JSON.stringify({phase:document.body.dataset.phase||'choosing',selected:document.body.dataset.selectedModel||null,completedGlbRequests:models.length,completedImageRequests:images.length,mainBundleRequests:main.length,models,images,mainBundle:main,allCompletedResources:rows.length,note:'Completed resource entries only. In-flight requests appear when complete. This button never requests a model.'},null,2);};})();</script>`;
await writeFile(new URL('qa-quota.html',pub),shell.replace('</body>',quotaPanel+'</body>'));
await writeFile(new URL('robots.txt',pub),'User-agent: *\nDisallow: /\n');
const deploymentFiles=['index.html',manifestName,bundleName,...newAssets];
const deploymentManifest=[];
for(const name of deploymentFiles){const bytes=await readFile(new URL(name,pub));deploymentManifest.push({path:name,bytes:bytes.length,sha256:hash(bytes)});}
const buildReport={build:release,manifestName,bundleName,overviewName,osmoFile:osmoName,osmoBytes:osmo.bytes,osmoGzipBytes:(await stat(new URL(osmoName+'.gz',pub))).size,
  osmoModelSha256:osmoSha,phoneModelSha256:phone.sha256,nativeModelSha256:'16f8963b043a766317497ee4281f4cf39c6b2190fafaaed51334734723c8b207',
  indexSha256:hash(Buffer.from(shell)),bundleSha256:hash(bundle),choiceRequired:true,viewerRequestsBeforeChoice:0,automaticModelRetry:false,
  modelCosts:Object.fromEntries(Object.entries(manifest.models).map(([key,m])=>[key,{fileBytes:m.fileBytes,downloadBytes:m.downloadBytes}])),
  osmoBudget:OSMO_LIMITS,privateQaFiles:['qa-script-failure.html','qa-quota.html'],deploymentFiles,deploymentManifest};
await writeFile(new URL('build-report.json',here),JSON.stringify(buildReport,null,2));
console.log(JSON.stringify(buildReport,null,2));
