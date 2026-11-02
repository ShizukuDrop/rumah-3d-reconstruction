import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {footprintBytes,installCutaway} from './gaussian-cutaway.js';
const read=async name=>JSON.parse(await readFile(new URL(name,import.meta.url),'utf8'));
const b64=values=>btoa(String.fromCharCode(...values.map(v=>v&255)));
const footprint=values=>({size:[1,values.length],cellSize:.05,sdfCm:b64(values)});
test('footprint distances decode to offset-binary RG texels and malformed grids are refused',()=>{
 assert.deepEqual([...footprintBytes(footprint([-127,-1,0,1,127]))],[1,0,127,0,128,0,129,0,255,0]);
 assert.deepEqual([...footprintBytes({...footprint([0,0]),lowerCeiling:{select:b64([1,0])}})],[128,255,128,0]);
 assert.throws(()=>footprintBytes({...footprint([0,0]),size:[2,2]}),/malformed/);
 assert.throws(()=>footprintBytes({...footprint([0,0]),lowerCeiling:{select:b64([1])}}),/malformed/);
 assert.throws(()=>footprintBytes({...footprint([0]),cellSize:0}),/malformed/);
 assert.throws(()=>footprintBytes(undefined),/missing/);
});
test('the shipped footprint belongs to the packed candidate and contains every capture position',async()=>{
 const candidate=await read('./candidate.json'),cameras=await read(candidate.cameras),packing=await read(candidate.packingReport);
 const fp=cameras.occupiedShell.footprint,bytes=footprintBytes(fp),[,h]=fp.size;
 assert.equal(packing.sha256,candidate.sha256);assert.equal(fp.source.sha256,packing.sourceSha256);
 const distance=([x,,z])=>(bytes[2*(Math.floor((x-fp.origin[0])/fp.cellSize)*h+Math.floor((z-fp.origin[1])/fp.cellSize))]-128)/100;
 const positions=[...cameras.occupiedShell.interiorCameras,cameras.startCamera.position,...cameras.presets.map(p=>p.position)];
 // The edge is the wall line now, and the phone passed within ~0.2 of some walls.
 for(const p of positions)assert.ok(distance(p)<-.05,`capture position ${p} lies inside the room footprint`);
 assert.ok(fp.wallBand>=.15&&fp.wallBand<=.4&&fp.exteriorMargin>0);
});

test('shell modifier preserves Gaussian furniture and has no primitive replacement mode',()=>{
 // Capture the actual generated shader and uniforms through a minimal Dyno
 // adapter. No WebGL or model download is needed to verify what the GPU receives.
 class Vector3{
  constructor(x=0,y=0,z=0){Object.assign(this,{x,y,z});}
  copy(v){Object.assign(this,{x:v.x,y:v.y,z:v.z});return this;}
  equals(v){return this.x===v.x&&this.y===v.y&&this.z===v.z;}
 }
 class DataTexture{dispose(){this.disposed=true;}}
 let operation;
 const dyno={Gsplat:'Gsplat',dynoBool:value=>({value}),dynoFloat:value=>({value}),dynoVec3:value=>({value}),dynoSampler2D:value=>({value}),gsplatNormal:()=>({}),dynoBlock:(_in,_out,fn)=>fn({gsplat:{}}),Dyno:class{
  constructor(definition){operation=definition;this.outputs={gsplat:{}};}
 }};
 const shell={footprint:{...footprint([0]),origin:[0,0],wallBand:.25,exteriorMargin:.22},fittedPlanes:{floor:{YequalsAXplusBZplusC:[0,0,0]},upperCeiling:{YequalsAXplusBZplusC:[0,0,3]}},ceilingBand:.15,interiorCameras:[[0,1,0]]};
 const model={updateGenerator(){},updateVersion(){}};
 let target=new Vector3(0,1,0);
 const api=installCutaway({dyno,THREE:{Vector3,DataTexture},model,shell,orbitTarget:()=>target});
 assert.equal('trimWalls' in api,false,'the viewer cannot activate an implicit fitted/primitive trim');
 assert.equal('fitted' in operation.inTypes,false);
 assert.equal('fitted' in operation.inputs,false);
 const inputs=Object.fromEntries(Object.keys(operation.inputs).map(key=>[key,key]));
 const shader=operation.statements({inputs,outputs:{gsplat:'result'}}).join('\n');
 assert.match(shader,/result=gsplat;/);
 assert.match(shader,/result\.rgba\.a\*=hidden\?0\.0:keep;/);
 assert.match(shader,/d>-0\.2500000 && !shelf/,'the ordinary shelf-preserving wall band remains');
 assert.match(shader,/textureLod\(sdf/,'non-convex shell and local-ceiling sampling remains');
 assert.doesNotMatch(shader,/\bfitted\b|d>-0\.45|d>-0\.08|longest>0\.1/,'no fitted-only floor replacement or blanket furniture removal');
 assert.deepEqual([...shader.matchAll(/result\.(\w+)/g)].map(match=>match[1]),['rgba'],'only opacity changes, never Gaussian geometry');
 const camera={position:new Vector3(2,2,2)};
 api.update(true,camera,0);
 assert.equal(operation.inputs.enabled.value,true);
 assert.equal(operation.inputs.margin.value,.22);
 target=null;camera.position=new Vector3(3,2,2);api.update(true,camera,200);
 assert.equal(operation.inputs.margin.value,.22,'changing view modes cannot switch to an interior-only fitted floor');
 api.update(false,camera,201);
 assert.equal(operation.inputs.enabled.value,false,'See inside off still restores the complete Gaussian');
 api.dispose();assert.equal(operation.inputs.sdf.value.disposed,true);
});
