import {NodeIO} from '@gltf-transform/core';
import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
import {meshopt,textureCompress} from '@gltf-transform/functions';
import {MeshoptEncoder,MeshoptDecoder} from 'meshoptimizer';
import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const runtimeRequire=createRequire(import.meta.url);
const sharp=runtimeRequire('sharp');
await Promise.all([MeshoptEncoder.ready,MeshoptDecoder.ready]);
const io=new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.encoder':MeshoptEncoder,'meshopt.decoder':MeshoptDecoder});
const input=new URL('phone-simplified.glb',import.meta.url);
const doc=await io.read(fileURLToPath(input));
const before=doc.getRoot().listMeshes().map(m=>({name:m.getName(),triangles:m.listPrimitives().reduce((s,p)=>s+p.getIndices().getCount()/3,0)}));
await doc.transform(
  textureCompress({encoder:sharp,targetFormat:'jpeg',resize:[2048,2048],quality:86,chromaSubsampling:'4:4:4'}),
  meshopt({encoder:MeshoptEncoder,level:'medium',quantizePosition:16,quantizeNormal:8,quantizeTexcoord:12})
);
const output=await io.writeBinary(doc);
const sha=createHash('sha256').update(output).digest('hex');
const pub=new URL('public/',import.meta.url);
await mkdir(new URL('models/',pub),{recursive:true});
const file=`iphone-phone-${sha.slice(0,10)}.glb`;
await writeFile(new URL(`models/${file}`,pub),output);
const verified=await io.readBinary(output);
const root=verified.getRoot();
const after=root.listMeshes().map(m=>({name:m.getName(),triangles:m.listPrimitives().reduce((s,p)=>s+p.getIndices().getCount()/3,0)}));
if(JSON.stringify(before)!==JSON.stringify(after))throw Error('Compression changed topology or mesh components');
let geometryBytes=0;
for(const a of root.listAccessors())geometryBytes+=a.getArray().byteLength;
const textures=[];
for(const t of root.listTextures()){
  const meta=await sharp(t.getImage()).metadata();
  if(meta.width>2048||meta.height>2048)throw Error('Phone texture exceeds the budget');
  textures.push({width:meta.width,height:meta.height,bytes:t.getImage().byteLength});
}
if(output.byteLength>24*1024*1024||geometryBytes>64*1024*1024)throw Error('Phone asset exceeds the delivery budget');
const native=await readFile(new URL('../../outputs/iPhone_Wide_Full_Native.glb',import.meta.url));
if(createHash('sha256').update(native).digest('hex')!=='16f8963b043a766317497ee4281f4cf39c6b2190fafaaed51334734723c8b207')throw Error('Native model changed');
const report={nativeModelUnchanged:true,sourceNativeSha256:'16f8963b043a766317497ee4281f4cf39c6b2190fafaaed51334734723c8b207',phoneFile:`models/${file}`,bytes:output.byteLength,sha256:sha,triangles:after.reduce((s,m)=>s+m.triangles,0),meshes:after,textures,decodedGeometryBytes:geometryBytes,estimatedTextureGpuBytesWithMipmaps:textures.reduce((s,t)=>s+t.width*t.height*4*4/3,0),quantization:{positions:16,normals:8,uvs:12},componentsPreserved:true,ownershipCrop:false,simplificationReport:'phone-simplified.glb.json',independent2mmAccuracyClaim:false};
await writeFile(new URL('phone-asset-report.json',import.meta.url),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
