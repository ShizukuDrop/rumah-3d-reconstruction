import * as THREE from 'three';import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';import {MeshoptDecoder} from 'meshoptimizer';import {SparkRenderer,SplatMesh} from '@sparkjsdev/spark';
const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true,powerPreference:'high-performance'});renderer.setPixelRatio(1);renderer.setSize(1920,1080);renderer.setClearColor(0x141b23,1);renderer.outputColorSpace=THREE.SRGBColorSpace;document.body.appendChild(renderer.domElement);
const camera=new THREE.PerspectiveCamera(75,1920/1080,.025,100),scene=new THREE.Scene();let model,spark;const metadata=await(await fetch(new URLSearchParams(location.search).get('metadata')||'/review/qa/metadata.json')).json(),occupied=await(await fetch('/review/occupied-cameras.json')).json();
const api=window.__qa={ready:true,async open(kind){
 api.ready=false;if(model){scene.remove(model);if(model.isSplatMesh)model.dispose();else model.traverse(o=>{if(o.isMesh){o.geometry.dispose();o.material.map?.dispose();o.material.dispose();}});model=null;}if(spark){scene.remove(spark);spark.dispose();spark=null;}
 const asset=metadata.models[kind];if(!asset)throw Error('Unknown QA asset '+kind);
 if(['ply','sog','spz'].includes(asset.format)){spark=new SparkRenderer({renderer,autoUpdate:false,enableLod:false,sortRadial:true,blurAmount:.05,preBlurAmount:0,minSortIntervalMs:0});scene.add(spark);model=new SplatMesh({url:asset.url,lod:false,extSplats:true,editable:false,raycastable:false});scene.add(model);await model.initialized;}
 else{const gltf=await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(asset.url);model=gltf.scene;model.traverse(o=>{if(o.isMesh){o.material.side=THREE.DoubleSide;}});scene.add(model);}
 api.kind=kind;await api.view(metadata.poses[0].label);api.ready=true;return {kind,splats:model.numSplats};
 },async view(label){const p=metadata.poses.find(p=>p.label===label);camera.fov=75;if(!spark)model.traverse(o=>{if(o.isMesh)o.material.side=THREE.DoubleSide;});camera.position.fromArray(p.position);camera.quaternion.fromArray(p.quaternion);camera.updateProjectionMatrix();scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
 if(spark){for(let i=0;i<3;i++){await spark.update({scene,camera});renderer.render(scene,camera);await new Promise(r=>setTimeout(r,60));}}
 renderer.render(scene,camera);renderer.getContext().finish();return {pose:p,activeSplats:spark?.activeSplats};},
 overview(which='orbit',inside=true){
 if(spark)throw Error('This QA overview is only for the mesh pilot.');
 model.traverse(o=>{if(o.isMesh)o.material.side=inside?THREE.FrontSide:THREE.DoubleSide;});
 const center=new THREE.Vector3().fromArray(occupied.bounds[0]).add(new THREE.Vector3().fromArray(occupied.bounds[1])).multiplyScalar(.5),phi=which==='top'?.001:.85,theta=.7;
 const direction=new THREE.Vector3(Math.sin(phi)*Math.sin(theta),Math.cos(phi),Math.sin(phi)*Math.cos(theta)),right=new THREE.Vector3(Math.cos(theta),0,-Math.sin(theta)),up=new THREE.Vector3().crossVectors(direction,right),p=new THREE.Vector3();camera.fov=42;const tangent=Math.tan(THREE.MathUtils.degToRad(21));let radius=.3;
 for(let i=0;i<occupied.framingPoints.length;i+=3){p.fromArray(occupied.framingPoints,i).sub(center);const depth=p.dot(direction);radius=Math.max(radius,depth+1.12*Math.abs(p.dot(right))/(tangent*camera.aspect),depth+1.12*Math.abs(p.dot(up))/tangent);}
 camera.position.copy(center).addScaledVector(direction,radius);camera.up.set(0,1,0);camera.lookAt(center);camera.updateProjectionMatrix();camera.updateMatrixWorld(true);scene.updateMatrixWorld(true);renderer.render(scene,camera);renderer.getContext().finish();return {which,inside,fov:42,radius};
 },snapshot(){renderer.render(scene,camera);renderer.getContext().finish();return renderer.domElement.toDataURL('image/png');}
};
