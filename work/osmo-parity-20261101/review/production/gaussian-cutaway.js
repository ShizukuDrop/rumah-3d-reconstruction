// Reversible, world-space shell visibility. The downloaded source is never edited.
// A height test alone cannot remove vertical walls, doors or furniture here.
// The room is the non-convex floor/ceiling footprint (occupied_footprint.py), not
// its convex hull: the hull spans corridor and bathroom recesses, so concave walls
// were never cut and the exterior halo of unobserved splats stayed visible.
const decode=text=>Uint8Array.from(atob(text||''),c=>c.charCodeAt(0));
export function footprintBytes(footprint){
 const [w,h]=footprint?.size||[],sdf=decode(footprint?.sdfCm),lower=footprint?.lowerCeiling?decode(footprint.lowerCeiling.select):new Uint8Array(sdf.length);
 if(!(w>0&&h>0)||sdf.length!==w*h||lower.length!==w*h||!(footprint.cellSize>0))throw Error('Occupied shell footprint is missing or malformed.');
 // RG8 texels: R is int8 hundredths as offset binary, (d*100+128)/255; G selects the dropped ceiling.
 const bytes=new Uint8Array(2*w*h);
 for(let i=0;i<w*h;i++){bytes[2*i]=sdf[i]^0x80;bytes[2*i+1]=lower[i]?255:0;}
 return bytes;
}
// orbitTarget() returns the orbit target, or null outside Orbit. In Orbit, wall splats on the camera's
// side of it fade too. This modifier only applies the reversible Gaussian shell cutaway.
export function installCutaway({dyno,THREE,model,shell,orbitTarget=()=>null}){
 const fp=shell?.footprint,bytes=footprintBytes(fp),[w,h]=fp.size;
 // Rows are X, columns Z (index = x*h + z); texel centres sit on cell centres.
 const texture=new THREE.DataTexture(bytes,h,w,THREE.RGFormat,THREE.UnsignedByteType);
 texture.unpackAlignment=1;texture.magFilter=texture.minFilter=THREE.LinearFilter;texture.generateMipmaps=false;texture.needsUpdate=true;
 const enabled=dyno.dynoBool(false),view=dyno.dynoVec3(new THREE.Vector3()),centre=dyno.dynoVec3(new THREE.Vector3()),sdf=dyno.dynoSampler2D(texture);
 const margin=dyno.dynoFloat(fp.exteriorMargin);
 const gl=n=>Number(n).toFixed(7),plane=([a,b,c])=>`(${gl(a)}*p.x+${gl(b)}*p.z+${gl(c)})`;
 const floor=plane(shell.fittedPlanes.floor.YequalsAXplusBZplusC),upper=plane(shell.fittedPlanes.upperCeiling.YequalsAXplusBZplusC);
 const lower=fp.lowerCeiling?plane(fp.lowerCeiling.YequalsAXplusBZplusC):upper;
 const scale=`vec2(${gl(1/(fp.cellSize*h))},${gl(1/(fp.cellSize*w))})`,origin=`vec2(${gl(fp.origin[1])},${gl(fp.origin[0])})`;
 const observers=(shell.interiorCameras||[]).map(c=>`{ vec3 observer=vec3(${c.map(gl).join(',')});float d=dot(p-observer,p-observer);if(d<nearestDistance){nearestDistance=d;nearest=observer;} }`).join('\n');
 const modifier=dyno.dynoBlock({gsplat:dyno.Gsplat},{gsplat:dyno.Gsplat},({gsplat})=>{
  const normal=dyno.gsplatNormal(gsplat);
  const operation=new dyno.Dyno({inTypes:{gsplat:dyno.Gsplat,normal:'vec3',enabled:'bool',view:'vec3',centre:'vec3',margin:'float',sdf:'sampler2D'},outTypes:{gsplat:dyno.Gsplat},inputs:{gsplat,normal,enabled,view,centre,margin,sdf},statements:({inputs:i,outputs:o})=>[
   `${o.gsplat}=${i.gsplat};`,
   `if(${i.enabled}){ vec3 p=${i.gsplat}.center; vec3 n=${i.normal}; bool hidden=false;
      // Gaussian covariance normals have no sign. Orient to the nearest actual
      // interior capture before applying the same back-face semantics as a mesh.
      float nearestDistance=1e20;vec3 nearest=p+vec3(0.0,1.0,0.0);${observers}
      if(dot(n,nearest-p)<0.0)n=-n;
      if(dot(n,${i.view}-p)<-0.015)hidden=true;
      // Footprint texel: signed distance to the edge (positive outside) and the local ceiling.
      // Explicit LOD: implicit derivatives are undefined in this per-splat branch.
      vec2 uv=(p.zx-${origin})*${scale};vec2 texel=${scale}*${gl(fp.cellSize)};
      vec2 here=textureLod(${i.sdf},uv,0.0).rg;float d=here.r*2.55-1.28;float ceiling=here.g>0.5?${lower}:${upper};
      // Ceiling cap: horizontal normal AND high ceiling band. Never a blanket height slice.
      if(p.y>ceiling-${gl(shell.ceilingBand)} && abs(n.y)>0.65) hidden=true;
      // Judge each Gaussian by its 2-sigma reach, not its centre: a shard centred
      // inside the room can still poke through a wall or above the ceiling.
      mat3 RS=scaleQuaternionToMatrix(${i.gsplat}.scales,${i.gsplat}.quaternion);
      float reachY=2.0*length(vec3(0.0,1.0,0.0)*RS);
      // Outside the room volume: above the local ceiling or below the floor (glossy reflections).
      if(p.y+reachY>ceiling+0.1 || p.y-reachY<${floor}-0.1) hidden=true;
      // Needles have no usable normal and read as shards along walls and ceilings: longest
      // axis over 4x the middle one and over 0.03 units. Interior detail keeps all but the longest.
      vec3 s=${i.gsplat}.scales;float longest=max(s.x,max(s.y,s.z)),middle=s.x+s.y+s.z-longest-min(s.x,min(s.y,s.z));
      bool shell=d>-${gl(fp.wallBand)} || p.y>ceiling-0.3;
      if(shell && longest>0.03 && longest>4.0*middle) hidden=true;
      // Seen from above, long needles anywhere read as streaks (0.4% of interior splats).
      if(longest>0.05 && longest>5.0*middle) hidden=true;
      vec2 outward=vec2(textureLod(${i.sdf},uv+vec2(0.0,texel.y),0.0).r-textureLod(${i.sdf},uv-vec2(0.0,texel.y),0.0).r,
                        textureLod(${i.sdf},uv+vec2(texel.x,0.0),0.0).r-textureLod(${i.sdf},uv-vec2(texel.x,0.0),0.0).r);
      outward=dot(outward,outward)>1e-8?normalize(outward):vec2(0.0);
      // Beyond the wall line: unobserved exterior splats, reflections and outward shards.
      // Short alpha ramps instead of on/off cuts avoid 5 cm grid steps and popping while orbiting.
      float keep=1.0-smoothstep(${i.margin},${i.margin}+0.08,d+2.0*length(vec3(outward.x,0.0,outward.y)*RS));
      // Wall layer facing the camera, judged against the local (non-convex) wall direction.
      // Only flat, horizontal splats below the wall top (shelf and counter tops) survive in that layer:
      // a round blob has no real normal, and flat ones at the wall-ceiling junction are wall-top fuzz.
      bool shelf=abs(n.y)>=0.7 && min(s.x,min(s.y,s.z))<0.3*middle && p.y<ceiling-0.5;
      // So does the wall layer on the camera's side of the orbit target, where jog and recess walls
      // facing away would stand as free-standing fins. Seen from straight above this term is ~0.
      float near=dot(p.xz-${i.centre}.xz,${i.view}.xz-${i.centre}.xz)/max(length(${i.view}-${i.centre}),1e-3);
      if(d>-${gl(fp.wallBand)} && !shelf && p.y>${floor}+0.12) keep*=1.0-max(smoothstep(0.05,0.3,dot(outward,${i.view}.xz-p.xz)),smoothstep(0.4,0.8,near));
      ${o.gsplat}.rgba.a*=hidden?0.0:keep;
    }`
  ]});
  return operation.outputs;
 });
 model.worldModifiers=[modifier];model.updateGenerator();
 // Regenerating every splat on every orbit frame is the overview's main cost on phones. While the
 // camera moves, refresh at most every 100 ms; settle() makes it exact once the camera rests.
 let pending=false,last=-Infinity;
 const api={regenerations:0,
  update(active,camera,now=performance.now()){
   if(enabled.value!==active){enabled.value=active;regenerate(camera);return;}
   if(!active||view.value.equals(camera.position))return;
   if(now-last>=100){last=now;regenerate(camera);}else pending=true;
  },
  settle(camera){if(!pending||!enabled.value)return false;regenerate(camera);return true;},
  dispose(){texture.dispose();},
  method:'wall-trimmed non-convex footprint SDF with local ceilings: exterior + camera-facing and near-side wall layer + ceiling cap + out-of-volume + shell needles; reversible opacity'};
 function regenerate(camera){
  const target=orbitTarget();view.value.copy(camera.position);centre.value.copy(target??camera.position);
  pending=false;api.regenerations++;model.updateVersion();}
 return api;
}
