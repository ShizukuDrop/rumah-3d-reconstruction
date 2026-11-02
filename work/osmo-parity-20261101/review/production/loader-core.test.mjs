import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseQuality,isPhoneDevice,readModel,pinchRatio,withDeadline} from './loader-core.js';
const glb=()=>{const a=new Uint8Array(20),v=new DataView(a.buffer);v.setUint32(0,0x46546c67,true);v.setUint32(4,2,true);v.setUint32(8,20,true);return a;};
test('iPhone Lite is the default asset on phones and desktops; hardware detection remains separate',()=>{
  assert.equal(chooseQuality({width:1800,touchPoints:5,coarse:false,userAgent:'Mozilla/5.0 Android'}),'phone');
  assert.equal(chooseQuality({width:402,touchPoints:5,coarse:true,userAgent:'iPhone'}),'phone');
  assert.equal(chooseQuality({width:1440,touchPoints:0,coarse:false,userAgent:'Windows'}),'phone');
  assert.equal(chooseQuality({requested:'native',width:402,touchPoints:5,coarse:true}),'phone');
  assert.equal(isPhoneDevice({width:1800,touchPoints:5,coarse:false,userAgent:'Android'}),true);
  assert.equal(isPhoneDevice({width:1440,touchPoints:0,coarse:false,userAgent:'Windows'}),false);
  assert.equal(isPhoneDevice({width:700,touchPoints:0,coarse:false}),true);
  assert.equal(isPhoneDevice({width:Infinity,touchPoints:0,coarse:false}),false);
});

test('the retired full model is rejected before allocating a download buffer',async()=>{
  await assert.rejects(readModel(new Response(glb()),435614584),/file size is invalid/);
});
test('progress uses the decoded GLB size, not the smaller HTTP gzip Content-Length',async()=>{
  const values=[];
  const response=new Response(glb(),{headers:{'content-type':'model/gltf-binary','content-length':'10'}});
  const result=await readModel(response,20,{onProgress:(n,total)=>values.push([n,total])});
  assert.equal(result.byteLength,20);assert.deepEqual(values.at(-1),[20,20]);
});
test('interrupted and oversized downloads produce a visible failure instead of parsing partial data',async()=>{
  await assert.rejects(readModel(new Response(glb().slice(0,12)),20),/stopped before/);
  await assert.rejects(readModel(new Response(new Uint8Array(24)),20),/file size changed/);
});
test('an HTML challenge or HTTP failure cannot be mistaken for a 3D file',async()=>{
  await assert.rejects(readModel(new Response('<html>Wait</html>',{headers:{'content-type':'text/html'}}),20),/web page/);
  await assert.rejects(readModel(new Response('Unavailable',{status:503}),20),/503/);
});
test('aborted and malformed files never report ready',async()=>{
  const controller=new AbortController();controller.abort();
  await assert.rejects(readModel(new Response(glb()),20,{signal:controller.signal}),{name:'AbortError'});
  await assert.rejects(readModel(new Response(new Uint8Array(20)),20),/incomplete/);
});
test('pinch spread zooms in, and invalid tiny gestures do not jump the camera',()=>{
  assert.equal(pinchRatio(100,200),.5);assert.equal(pinchRatio(200,100),2);assert.equal(pinchRatio(0,200),1);
});
test('a stuck preparation promise is bounded, while a successful one returns normally',async()=>{
  await assert.rejects(withDeadline(new Promise(()=>{}),10,'Preparation stalled'),/Preparation stalled/);
  assert.equal(await withDeadline(Promise.resolve('ready'),1000,'Failed'),'ready');
});
