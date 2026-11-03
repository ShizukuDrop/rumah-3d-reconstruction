import {OSMO_LIMITS} from './delivery-policy.js';
import {nativePolicy,validateModelHeader} from './native-delivery.js';
import {canonicalChoice,isOsmoChoice} from './choice-core.js';
// Asset choice and device capacity are independent: desktops also default to iPhone Lite.
export function chooseQuality({requested}={}) {
  return canonicalChoice(requested)||'phone';
}
export function isPhoneDevice({coarse=false,touchPoints=0,width=1920,userAgent=''}={}) {
  return Boolean(coarse||touchPoints>1||width<1000||/Android|iPhone|iPad|iPod/i.test(userAgent));
}

export function selectModel(manifest,key){
  key=canonicalChoice(key);
  const asset=manifest.models?.[key],cameraData=manifest.cameraSets?.[asset?.cameraSet];
  if(!asset||!cameraData)throw new Error('That room view is unavailable.');
  if(key==='osmo-stick'&&(asset.cameraSet!==key||asset.representation!=='gaussian'))throw new Error('Osmo Stick needs its own Gaussian model and camera set.');
  const lite=true;
  const osmo=isOsmoChoice(key);
  const fileLimit=key==='osmo-stick'&&asset.previewCheckpoint!==true?29_999_999:osmo?OSMO_LIMITS.fileBytes:24*1024*1024;
  const textureLimit=osmo?OSMO_LIMITS.textureSize:2048;
  const geometryLimit=osmo?OSMO_LIMITS.maximumGeometryBytes/1024/1024:64;
  if(!Number.isSafeInteger(asset.fileBytes)||asset.fileBytes<12||asset.fileBytes>fileLimit)
    throw new Error('The selected 3D view is larger than expected. Please refresh and retry.');
  if(asset.representation==='gaussian')nativePolicy(asset);
  if(asset.representation!=='gaussian'&&(!Number.isSafeInteger(asset.maxTextureSize)||asset.maxTextureSize<1||asset.maxTextureSize>textureLimit))
    throw new Error('The selected view exceeds its texture budget.');
  return {asset,cameraData,lite,textureLimit,geometryLimit,downloadTimeout:180000,prepareTimeout:key==='phone'?30000:60000};
}

export async function readModel(response,expectedBytes,{signal,onProgress=()=>{},format='glb'}={}) {
  const checkAbort=()=>{if(signal?.aborted)throw new DOMException('Download cancelled','AbortError');};
  checkAbort();
  if(!response.ok)throw new Error(`The 3D download failed (${response.status}). Please try again.`);
  const type=response.headers.get('content-type')||'';
  if(type.includes('text/html'))throw new Error('The server returned a web page instead of the 3D room. Please retry.');
  if(!Number.isSafeInteger(expectedBytes)||expectedBytes<12||expectedBytes>OSMO_LIMITS.fileBytes)throw new Error('The 3D file size is invalid.');
  const result=new Uint8Array(expectedBytes);
  let received=0;
  const copy=chunk=>{
    checkAbort();
    if(received+chunk.length>expectedBytes)throw new Error('The 3D file size changed. Refresh this page and retry.');
    result.set(chunk,received);received+=chunk.length;onProgress(received,expectedBytes);
  };
  if(response.body?.getReader){
    const reader=response.body.getReader();
    const cancel=()=>{reader.cancel().catch(()=>{});};
    signal?.addEventListener('abort',cancel,{once:true});
    try{for(;;){checkAbort();const item=await reader.read();checkAbort();if(item.done)break;copy(item.value);}}
    catch(error){await reader.cancel().catch(()=>{});throw error;}
    finally{signal?.removeEventListener('abort',cancel);reader.releaseLock();}
  }else copy(new Uint8Array(await response.arrayBuffer()));
  if(received!==expectedBytes)throw new Error('The download stopped before the whole room arrived. Please retry.');
  if(!validateModelHeader(result,format))
    throw new Error('The downloaded 3D file is incomplete. Please retry.');
  return result.buffer;
}

export function pinchRatio(previousDistance,nextDistance){
  if(!Number.isFinite(previousDistance)||!Number.isFinite(nextDistance)||previousDistance<2||nextDistance<2)return 1;
  return Math.max(.5,Math.min(2,previousDistance/nextDistance));
}

export async function withDeadline(task,milliseconds,message){
  let timer;
  try{return await Promise.race([task,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),milliseconds);})]);}
  finally{clearTimeout(timer);}
}
