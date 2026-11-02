import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {validateShapes,shapeVisible,buildShapes,placeShape,STUB} from './simple-shapes.js';
const read=async name=>JSON.parse(await readFile(new URL(name,import.meta.url),'utf8'));
const box={kind:'object',type:'box',center:[0,.5,0],size:[1,1,1],yaw:0,color:'#aabbcc'};
test('shape files are validated before anything is drawn',()=>{
 assert.equal(validateShapes({version:1,shapes:[box]}).shapes.length,1);
 for(const bad of [{...box,type:'cone'},{...box,size:[1,0,1]},{...box,color:'red'},{...box,center:[0,NaN,0]},{...box,outward:[1]}])
  assert.throws(()=>validateShapes({version:1,shapes:[bad]}),/malformed/);
 assert.throws(()=>validateShapes({version:2,shapes:[box]}),/malformed/);
});
test('the overview hides ceilings and cuts camera-facing and near-side walls to stubs',()=>{
 const wall={...box,kind:'wall',center:[2,1,0],outward:[1,0]},camera={x:10,y:5,z:0},target={x:0,y:0,z:0};
 assert.equal(shapeVisible(wall,true,camera,target),'stub');assert.equal(shapeVisible(wall,true,{x:-10,y:5,z:0},target),true);
 assert.equal(shapeVisible({...box,kind:'ceiling'},true,camera,target),false);assert.equal(shapeVisible({...box,kind:'wall'},true,camera,target),true);
 assert.equal(shapeVisible(wall,false,camera,target),true);
 const fin={...wall,outward:[0,1]};  // side-on to the camera, 2 in front of the target
 assert.equal(shapeVisible(fin,true,camera,target),'stub');assert.equal(shapeVisible(fin,true,{x:.01,y:10,z:0},target),true);
 // A partition is a stub from any side; a run is judged at its anchor, not at each piece.
 assert.equal(shapeVisible({...wall,outward:[-1,0],behind:true},true,{x:-10,y:5,z:0},target),'stub');
 assert.equal(shapeVisible({...fin,center:[-2,1,0],anchor:[2,0]},true,camera,target),'stub');
 // A stub stands on the floor at STUB height; a lintel above a door has no stub.
 const mesh={userData:{shape:{...wall,center:[2,1.2,0],size:[1,2.4,.1]}},scale:{y:2.4},position:{y:1.2}};
 placeShape(mesh,'stub',0);assert.ok(mesh.visible);assert.equal(mesh.scale.y,STUB);assert.equal(mesh.position.y,STUB/2);
 placeShape(mesh,true,0);assert.equal(mesh.scale.y,2.4);assert.equal(mesh.position.y,1.2);
 mesh.userData.shape={...wall,center:[2,2.2,0],size:[1,.4,.1]};placeShape(mesh,'stub',0);assert.equal(mesh.visible,false);
});
test('the shipped shape file matches the packed model and builds into three.js meshes',async()=>{
 const candidate=await read('./candidate.json'),shapes=await read(candidate.simpleShapes),packing=await read(candidate.packingReport);
 assert.equal(shapes.source.sha256,packing.sourceSha256);validateShapes(shapes);
 const require=createRequire(new URL('../../../mobile-20261029/package.json',import.meta.url));
 const THREE=await import(pathToFileURL(require.resolve('three')).href);
 const group=buildShapes(THREE,shapes);assert.equal(group.children.length,shapes.shapes.length);
 const mesh=group.children.find(m=>m.userData.shape.type==='box');assert.deepEqual(mesh.scale.toArray(),mesh.userData.shape.size);
 group.userData.dispose();
});
test('no two walls or furniture pieces intersect (coplanar tops would flicker)',async()=>{
 const shapes=await read((await read('./candidate.json')).simpleShapes),t=shapes.manhattanYaw,c=Math.cos(t),s=Math.sin(t);
 // In the room's own frame every shape is axis-aligned: size[0] runs along u, size[2] along v.
 const box=w=>{const u=w.center[0]*c+w.center[2]*s,v=-w.center[0]*s+w.center[2]*c;
  return [[u-w.size[0]/2,u+w.size[0]/2],[w.center[1]-w.size[1]/2,w.center[1]+w.size[1]/2],[v-w.size[2]/2,v+w.size[2]/2]];};
 const walls=shapes.shapes.filter(w=>w.kind==='wall'||w.kind==='object').map(box);
 for(let i=0;i<walls.length;i++)for(let j=i+1;j<walls.length;j++)
  assert.ok(walls[i].some((r,k)=>Math.min(r[1],walls[j][k][1])-Math.max(r[0],walls[j][k][0])<=.002),`shapes ${i} and ${j} intersect`);
});
