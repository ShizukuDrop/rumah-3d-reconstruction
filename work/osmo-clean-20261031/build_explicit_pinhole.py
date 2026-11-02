"""Materialize calibrated pinhole RGB/mask views with independently checked poses.

The global fresh SfM frame is preserved. Source timestamps retain their train/eval
split across both lenses and every virtual view. No SfM rerun, old depth map,
learned image synthesis, or previous Gaussian checkpoint is used.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,sys,time
import cv2,numpy as np
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W.parent/'osmo-reconstruct-20261031'))
from seed_fisheye import read_model,write_model_text,write_seed_ply,Fisheye,qvec_to_rotmat,rotmat_to_qvec,pinhole_face_maps
P=argparse.ArgumentParser();P.add_argument('--source',type=Path,required=True);P.add_argument('--output',type=Path,required=True);P.add_argument('--size',type=int,default=1024);P.add_argument('--subset',choices=['bathroom','all'],default='bathroom');a=P.parse_args();started=time.monotonic();cv2.setNumThreads(1)
if a.output.exists():raise FileExistsError(a.output)
if not 512<=a.size<=2048:raise ValueError('Invalid face size')
selection=json.loads((W/'frame-selection.json').read_text());by_name={r['filename']:r for r in selection['selected']}
cameras,images,points=read_model(a.source/'sparse/0')
def selected(im):
    row=by_name[Path(im['name']).name];n=row['source_frame'];return a.subset=='all' or 540<=n<=720 or 1470<=n<=1650
inputs=sorted((im for im in images.values() if selected(im)),key=lambda im:(by_name[Path(im['name']).name]['source_frame'],im['name']))
faces=[np.eye(3),np.array([[0,0,-1],[0,1,0],[1,0,0]]),np.array([[0,0,1],[0,1,0],[-1,0,0]]),np.array([[1,0,0],[0,0,-1],[0,1,0]]),np.array([[1,0,0],[0,0,1],[0,-1,0]])]
for face in faces:
    if not np.allclose(face@face.T,np.eye(3)) or not np.isclose(np.linalg.det(face),1):raise ValueError('Invalid proper face rotation')
S=a.size;f=S/2;xx,yy=np.meshgrid(np.arange(S),np.arange(S));virtual=np.stack([(xx-f)/f,(yy-f)/f,np.ones_like(xx)],axis=-1).reshape(-1,3)
maps={};models={}
for cid,camera in cameras.items():
    models[cid]=Fisheye(camera,max_theta_degrees=99)
    # COLMAP pixel centres on both sides; the old corner rays put the RGB 0.1-0.9 px off the model.
    for j,face in enumerate(faces):maps[cid,j]=pinhole_face_maps(models[cid],face,S)
(a.output/'images').mkdir(parents=True);(a.output/'masks').mkdir()
def process(im):
    row=by_name[Path(im['name']).name];source=cv2.imread(str(a.source/'images'/im['name']));mask_path=(a.source/'masks'/im['name']).with_suffix('.png');mask=cv2.imread(str(mask_path),0)
    if source is None or mask is None:raise ValueError('Missing source RGB/mask '+im['name'])
    camera=cameras[im['camera_id']]
    if source.shape[:2]!=(camera['height'],camera['width']) or mask.shape!=source.shape[:2]:raise ValueError('Native RGB/mask/calibration mismatch')
    R=qvec_to_rotmat(im['qvec']);rays,ok=models[im['camera_id']].unproject(im['points2D_xy']);ids=im['point3D_ids'];ok&=ids>=0
    indices=np.flatnonzero(ok);xy=im['points2D_xy'][indices];inside=(xy[:,0]>=0)&(xy[:,0]<camera['width'])&(xy[:,1]>=0)&(xy[:,1]<camera['height']);indices=indices[inside];xy=xy[inside]
    keep=mask[np.clip(xy[:,1].astype(int),0,camera['height']-1),np.clip(xy[:,0].astype(int),0,camera['width']-1)]>127;indices=indices[keep];xy=xy[keep]
    rgb=source[xy[:,1].astype(int),xy[:,0].astype(int),::-1];colour=[(int(ids[i]),c) for i,c in zip(indices,rgb)] if row['split']=='train' else []
    results=[];error_values=[]
    for j,face in enumerate(faces):
        mx,my,valid=maps[im['camera_id'],j];face_mask=cv2.remap(mask,mx,my,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0);face_mask=np.where(valid&(face_mask>127),255,0).astype(np.uint8)
        if np.mean(face_mask>0)<.12:continue
        # Keep real RGB under the separate operator/mirror mask for monocular
        # inference context. Only rays outside the physical lens are black.
        photo=cv2.remap(source,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0);photo[~valid]=0
        stem=f'{im["name"].split("/")[0]}-n{row["source_frame"]:06d}-f{j}_{row["split"]}';name=stem+'.jpg'
        cv2.imwrite(str(a.output/'images'/name),photo,[cv2.IMWRITE_JPEG_QUALITY,96]);cv2.imwrite(str(a.output/'masks'/(stem+'.png')),face_mask)
        Rv=face@R;tv=face@im['tvec'];direction=rays[indices]@face.T;z=direction[:,2];uv=direction[:,:2]/np.maximum(z[:,None],1e-15)*f+f
        usable=(z>0)&(uv[:,0]>=3)&(uv[:,0]<S-3)&(uv[:,1]>=3)&(uv[:,1]<S-3);use=indices[usable];uv=uv[usable];pids=ids[use]
        foreground=face_mask[uv[:,1].astype(int),uv[:,0].astype(int)]>0;uv=uv[foreground];pids=pids[foreground]
        have=np.array([int(pid) in points for pid in pids],dtype=bool);uv=uv[have];pids=pids[have]
        if len(pids):
            world=np.array([points[int(pid)]['xyz'] for pid in pids]);xc=world@Rv.T+tv;projected=xc[:,:2]/xc[:,2,None]*f+f;errors=np.linalg.norm(projected-uv,axis=1);error_values.extend(errors.tolist())
            if not np.isfinite(errors).all():raise ValueError('Invalid independent reprojection')
        # Verify a world ray from each camera/face stays the same after conversion.
        test=virtual[::10007];original_world=(test@face)@R;virtual_world=test@Rv
        if np.max(np.abs(original_world-virtual_world))>1e-12:raise ValueError('World-ray identity failed')
        results.append({'name':name,'qvec':rotmat_to_qvec(Rv),'tvec':tv,'camera_id':1,'points2D_xy':uv,'point3D_ids':pids,'sourceName':im['name'],'sourceFrame':row['source_frame'],'sourceSplit':row['split'],'face':j,'keepFraction':float(np.mean(face_mask>0))})
    return results,colour,error_values
output_images={};tracks={};train_times={};colours={};errors=[];provenance=[]
with ThreadPoolExecutor(max_workers=4) as pool:
    for k,(views,samples,errs) in enumerate(pool.map(process,inputs),1):
        for view in views:
            iid=len(output_images)+1;view['id']=iid;output_images[iid]=view
            provenance.append({key:view[key] for key in ['name','sourceName','sourceFrame','sourceSplit','face','keepFraction']})
            for j,pid in enumerate(view['point3D_ids']):
                pid=int(pid);tracks.setdefault(pid,[]).append((iid,j))
                if view['sourceSplit']=='train':train_times.setdefault(pid,set()).add(view['sourceFrame'])
        for pid,c in samples:
            if pid not in colours:colours[pid]=[np.zeros(3,np.float64),0]
            colours[pid][0]+=c;colours[pid][1]+=1
        errors.extend(errs)
        if k%20==0:print(f'Explicit pinhole {k}/{len(inputs)} inputs, {len(output_images)} output views',flush=True)
output_points={}
for pid,track in tracks.items():
    if len(track)<2:continue
    point=dict(points[pid]);point['image_ids']=np.array([v[0] for v in track]);point['point2D_idxs']=np.array([v[1] for v in track]);point['track_len']=len(track);output_points[pid]=point
for im in output_images.values():im['point3D_ids']=np.array([pid if int(pid) in output_points else -1 for pid in im['point3D_ids']])
output_cameras={1:{'id':1,'model':'PINHOLE','width':S,'height':S,'params':np.array([f,f,f,f])}}
write_model_text(a.output/'sparse/0',output_cameras,output_images,output_points)
seed_ids=[pid for pid in output_points if len(train_times.get(pid,set()))>=2 and pid in colours]
seed_xyz=np.array([points[pid]['xyz'] for pid in seed_ids]);seed_rgb=np.array([np.clip(np.rint(colours[pid][0]/colours[pid][1]),0,255) for pid in seed_ids],np.uint8)
write_seed_ply(a.output/'seed-sparse-train.ply',seed_xyz,seed_rgb,np.zeros_like(seed_xyz))
report={'purpose':__doc__,'sourceDataset':str(a.source.resolve()),'outputDataset':str(a.output.resolve()),'subset':a.subset,'size':S,'sourceInputs':len(inputs),'virtualViews':len(output_images),'trainViews':sum(v['sourceSplit']=='train' for v in output_images.values()),'evalViews':sum(v['sourceSplit']=='eval' for v in output_images.values()),'seedPoints':len(seed_ids),'seedColours':'Only unmasked source training images; at least two distinct training timestamps per seed point.','worldCoordinateFrame':'+Y up; identical to audited fresh SfM, no new similarity','perFaceWorldRayIdentityTolerance':1e-12,'reprojection':{'observations':len(errors),'meanPixels':float(np.mean(errors)),'medianPixels':float(np.median(errors)),'p95Pixels':float(np.percentile(errors,95)),'maxPixels':float(np.max(errors))},'newTrainingOrDepthUsed':False,'maskConvention':'255 keep / 0 exclude; source operator and mirror masks reprojected by nearest neighbour','imagesSynthesized':False,'sourceFilesModified':False,'seconds':time.monotonic()-started,'views':provenance,'sha256':{name:hashlib.sha256((a.output/name).read_bytes()).hexdigest() for name in ['sparse/0/cameras.txt','sparse/0/images.txt','sparse/0/points3D.txt','seed-sparse-train.ply']}}
(a.output/'explicit-pinhole-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['purpose','views','sha256']},indent=2))
