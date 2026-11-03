import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseQuality,selectModel} from './loader-core.js';
import {OSMO_LIMITS,compressionTarget} from './delivery-policy.js';
const iphone={bounds:[[-1,0,-2],[1,3,2]],presets:[{name:'iphone-camera'}]};
const osmo={bounds:[[-5,0,-6],[5,3,6]],presets:[]};
const manifest={cameraSets:{iphone,osmo},models:{
  phone:{cameraSet:'iphone',fileBytes:21144604,maxTextureSize:2048},
  osmo:{cameraSet:'osmo',fileBytes:20000000,maxTextureSize:2048}
}};
test('all public model choices and query aliases override device defaults',()=>{
  for(const [requested,key] of [['phone','phone'],['native','phone'],['osmo','osmo'],['iphone-lite','phone'],['iphone-fast','phone'],['iphone-full','phone'],['osmo-lite','osmo']]){
    assert.equal(chooseQuality({requested,width:402,coarse:true,touchPoints:5}),key);
    assert.equal(chooseQuality({requested,width:1800,coarse:false,touchPoints:0}),key);
  }
  assert.equal(chooseQuality({width:1800,touchPoints:5}),'phone');
});
test('Osmo selection receives its own bounds and cameras, never retained iPhone metadata',()=>{
  const selected=selectModel(manifest,'osmo');
  assert.equal(selected.cameraData,osmo);assert.notEqual(selected.cameraData,iphone);
  assert.equal(selectModel(manifest,'phone').cameraData,iphone);
  assert.equal(selectModel(manifest,'native').asset,manifest.models.phone);
  assert.equal(selected.downloadTimeout,180000);assert.equal(selected.prepareTimeout,60000);
  assert.equal(selectModel(manifest,'phone').prepareTimeout,30000);
  assert.equal(selectModel(manifest,'iphone-full').downloadTimeout,180000);
});
test('Osmo Stick requires its own camera set and a Gaussian payload strictly below 30 MB',()=>{
  const key='osmo-stick',cameraData={bounds:[[-1,0,-1],[1,2,1]],presets:[]};
  const stick={cameraSet:key,representation:'gaussian',format:'sog',fileBytes:29_999_999,splats:1000,shDegree:0};
  const available={cameraSets:{...manifest.cameraSets,[key]:cameraData},models:{...manifest.models,[key]:stick}};
  assert.throws(()=>selectModel(manifest,key),/unavailable/);
  assert.equal(selectModel(available,key).cameraData,cameraData);
  assert.throws(()=>selectModel({...available,models:{[key]:{...stick,fileBytes:30_000_000}}},key),/larger/);
  assert.throws(()=>selectModel({...available,models:{[key]:{...stick,cameraSet:'osmo'}}},key),/own Gaussian model and camera set/);
});
test('each model keeps its own budget; Osmo permits 50 decimal MB and a 4K atlas',()=>{
  for(const [key,bytes,texture] of [['phone',24*1024*1024,2048],['osmo',50000000,4096]]){
    const withAsset=changes=>({...manifest,models:{...manifest.models,[key]:{...manifest.models[key],...changes}}});
    assert.throws(()=>selectModel(withAsset({fileBytes:bytes+1}),key),/larger/);
    assert.throws(()=>selectModel(withAsset({maxTextureSize:texture*2}),key),/texture budget/);
    assert.equal(selectModel(withAsset({fileBytes:bytes,maxTextureSize:texture}),key).asset.fileBytes,bytes);
  }
  assert.equal(selectModel(manifest,'osmo').geometryLimit,192);
  assert.equal(selectModel(manifest,'phone').geometryLimit,64);
  assert.equal(selectModel(manifest,'native').asset.fileBytes,21144604);
  assert.throws(()=>selectModel(manifest,'missing'),/unavailable/);
  assert.throws(()=>selectModel({...manifest,cameraSets:{iphone}},'osmo'),/unavailable/);
});
test('compression costs decide simplification, with no fixed triangle cap',()=>{
  assert.equal(compressionTarget({triangles:6000000,bytes:49000000,decodedGeometryBytes:180*1024*1024}),null);
  assert.equal(compressionTarget({triangles:6000000,bytes:40000000,decodedGeometryBytes:128*1024*1024}),null);
  const target=compressionTarget({triangles:6000000,bytes:60000000,decodedGeometryBytes:210*1024*1024});
  assert.ok(target>4000000&&target<6000000);
  assert.equal(OSMO_LIMITS.textureSize,4096);assert.equal(OSMO_LIMITS.fileBytes,50000000);
  assert.throws(()=>compressionTarget({triangles:NaN,bytes:1,decodedGeometryBytes:1}),/invalid/);
});
