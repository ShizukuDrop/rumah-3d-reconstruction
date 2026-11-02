// Simple-shape stand-in for the room (simple_shapes.py): boxes, cylinders and spheres, each a flat
// colour. Furniture gets a dark outline and walls a dark top, so the layout reads at a glance.
const TYPES=new Set(['box','cylinder','sphere']),KINDS=new Set(['floor','ceiling','wall','object']);
export const SHAPE_LIMIT=2000;
const finite=(v,n)=>Array.isArray(v)&&v.length===n&&v.every(Number.isFinite);
export function validateShapes(data){
 if(data?.version!==1||!Array.isArray(data.shapes)||!data.shapes.length||data.shapes.length>SHAPE_LIMIT)throw Error('Simple shapes are missing or malformed.');
 for(const s of data.shapes)if(!TYPES.has(s.type)||!KINDS.has(s.kind)||!finite(s.center,3)||!finite(s.size,3)||!s.size.every(v=>v>0&&v<50)||!Number.isFinite(s.yaw)||!/^#[0-9a-f]{6}$/.test(s.color)||(s.outward!==undefined&&!finite(s.outward,2))||(s.anchor!==undefined&&!finite(s.anchor,2))||(s.behind!==undefined&&s.behind!==true))throw Error('Simple shapes are missing or malformed.');
 return data;
}
// Overview cutaway for shapes: ceilings go, and walls drop to STUB-high stubs, so every room keeps
// its outline, when their outside faces the camera, when they stand on the camera's side of the orbit
// target (more than NEAR_SLACK in, where jog and recess walls would read as free-standing fins) or
// when another room lies right behind them (behind). A wall run is judged as a whole at its anchor,
// so a door never stands above its stubbed wall. Seen from straight above, every wall stays.
// Returns true, 'stub' or false.
const NEAR_SLACK=.6;export const STUB=.35;
export function shapeVisible(s,seeInside,camera,target){
 if(!seeInside)return true;if(s.kind==='ceiling')return false;if(!s.outward)return true;
 const tx=camera.x-target.x,ty=camera.y-target.y,tz=camera.z-target.z,reach=Math.hypot(tx,ty,tz);if(ty>.95*reach)return true;
 const [x,z]=s.anchor??[s.center[0],s.center[2]];
 return s.behind||s.outward[0]*(camera.x-x)+s.outward[1]*(camera.z-z)>0||(x-target.x)*tx+(z-target.z)*tz>NEAR_SLACK*reach?'stub':true;
}
// Shows a built shape full size, as a stub standing on the floor (lintels above a door have none), or not at all.
export function placeShape(mesh,state,floor){
 const s=mesh.userData.shape,bottom=s.center[1]-s.size[1]/2,stub=state==='stub';
 mesh.visible=!!state&&!(stub&&bottom>floor+.01);
 mesh.scale.y=stub?Math.min(STUB,s.size[1]):s.size[1];mesh.position.y=stub?bottom+mesh.scale.y/2:s.center[1];
}
export function buildShapes(THREE,data){
 validateShapes(data);
 const unit={box:new THREE.BoxGeometry(1,1,1),cylinder:new THREE.CylinderGeometry(.5,.5,1,32),sphere:new THREE.SphereGeometry(.5,32,16)};
 const outline={box:new THREE.EdgesGeometry(unit.box),cylinder:new THREE.EdgesGeometry(unit.cylinder,30),sphere:null};
 const line=new THREE.LineBasicMaterial({color:0x1d2630,transparent:true,opacity:.5}),cap=new THREE.MeshStandardMaterial({color:0x58616c,roughness:.9});
 const group=new THREE.Group();group.name='simple-shapes';
 for(const s of data.shapes){
  const material=new THREE.MeshStandardMaterial({color:s.color,roughness:.85,metalness:0,flatShading:s.type==='box'});
  // Box faces are +x, -x, +y, -y, +z, -z: a wall's top is its cut edge in the dollhouse.
  const mesh=new THREE.Mesh(unit[s.type],s.kind==='wall'?[material,material,cap,material,material,material]:material);
  mesh.position.fromArray(s.center);mesh.scale.fromArray(s.size);mesh.rotation.y=s.yaw;mesh.userData.shape=s;
  // Shadows ground the blocks; slabs do not cast them. Only furniture is outlined: on walls and slabs
  // the box edges would draw seams.
  mesh.castShadow=s.kind!=='floor'&&s.kind!=='ceiling';mesh.receiveShadow=true;
  if(outline[s.type]&&s.kind==='object')mesh.add(new THREE.LineSegments(outline[s.type],line));
  group.add(mesh);
 }
 // The floor the stubs stand on: the lowest wall bottom.
 group.userData.floor=Math.min(...data.shapes.filter(s=>s.kind==='wall').map(s=>s.center[1]-s.size[1]/2));
 group.userData.dispose=()=>{for(const g of [...Object.values(unit),...Object.values(outline)])g?.dispose();line.dispose();cap.dispose();group.traverse(o=>{if(o.isMesh)[].concat(o.material).forEach(m=>m.dispose());});};
 return group;
}
