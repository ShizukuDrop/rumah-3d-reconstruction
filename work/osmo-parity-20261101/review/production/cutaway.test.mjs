import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {footprintBytes} from './gaussian-cutaway.js';
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
 for(const p of positions)assert.ok(distance(p)<-.2,`capture position ${p} lies inside the room footprint`);
 assert.ok(fp.wallBand>=.15&&fp.wallBand<=.4&&fp.exteriorMargin>0);
});
