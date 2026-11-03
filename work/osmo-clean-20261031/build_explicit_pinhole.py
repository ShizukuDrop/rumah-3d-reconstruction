"""Materialize calibrated pinhole RGB/mask views with independently checked poses.

The supplied SfM frame is preserved without assuming its up axis. Source timestamps retain their train/eval
split across both lenses and every virtual view. No SfM rerun, old depth map,
learned image synthesis, or previous Gaussian checkpoint is used.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,re,sys,time
import cv2,numpy as np
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W.parent/'osmo-reconstruct-20261031'))
from seed_fisheye import read_model,write_model_text,write_seed_ply,Fisheye,qvec_to_rotmat,rotmat_to_qvec,pinhole_face_maps
P=argparse.ArgumentParser();P.add_argument('--source',type=Path,required=True);P.add_argument('--output',type=Path,required=True);P.add_argument('--size',type=int,default=1024);P.add_argument('--subset',choices=['bathroom','all'],default='bathroom')
P.add_argument('--images-dir',type=Path,help='Native RGB root; defaults to SOURCE/images')
P.add_argument('--masks-dir',type=Path,help='Native mask root; defaults to SOURCE/masks')
P.add_argument('--selection',type=Path,default=W/'frame-selection.json',help='Timestamp metadata JSON with selected rows')
P.add_argument('--train-whitelist',type=Path,help='Exact native training names, JSON views[].image or a JSON/text name list; requires eval whitelist and --subset all')
P.add_argument('--eval-whitelist',type=Path,help='Exact native held-out names; both whitelists exclude nonlisted anchors')
P.add_argument('--workers',type=int,default=4,help='CPU image workers (default:4)')
a=P.parse_args();started=time.monotonic();cv2.setNumThreads(1)
if a.output.exists():raise FileExistsError(a.output)
if not 512<=a.size<=2048:raise ValueError('Invalid face size')
if not 1<=a.workers<=16:raise ValueError('Workers must be between1 and16')
if bool(a.train_whitelist)!=bool(a.eval_whitelist):raise ValueError('Provide both train and eval whitelists; implicit inclusion of nonlisted anchors is forbidden')
if a.train_whitelist and a.subset!='all':raise ValueError('Explicit whitelists require --subset all')
images_dir=a.images_dir or a.source/'images';masks_dir=a.masks_dir or a.source/'masks'
selection=json.loads(a.selection.read_text());by_name={r['filename']:r for r in selection['selected']}
if len(by_name)!=len(selection['selected']):raise ValueError('Duplicate selection filename')
cameras,images,points=read_model(a.source/'sparse/0')
by_image_name={im['name']:im for im in images.values()}
if len(by_image_name)!=len(images):raise ValueError('Duplicate source COLMAP image name')

def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def metadata(im):
    name=im['name'];row=by_name.get(Path(name).name)
    if row is None:raise ValueError('Source image absent from selection metadata: '+name)
    match=re.fullmatch(r'frame_(\d+)_(train|eval)\.jpg',Path(name).name)
    if not match or int(match[1])!=row['source_frame'] or match[2]!=row['split']:
        raise ValueError('Source image/selection timestamp or split mismatch: '+name)
    return row

def read_whitelist(path,split):
    if path is None:return None,None
    raw=path.read_text(encoding='utf-8-sig')
    if path.suffix.lower()=='.json':
        data=json.loads(raw);rows=data.get('views',data.get('images')) if isinstance(data,dict) else data
    else:data=None;rows=[line.strip() for line in raw.splitlines() if line.strip()]
    if not isinstance(rows,list):raise ValueError('Whitelist must contain a names list or views list: '+str(path))
    names=[]
    for row in rows:
        name=row.get('image') if isinstance(row,dict) else row
        if not isinstance(name,str) or not re.fullmatch(r'cam\d+/frame_\d+_(train|eval)\.jpg',name):
            raise ValueError('Whitelist requires an exact relative native COLMAP image name: '+str(name))
        if name not in by_image_name:raise ValueError('Whitelisted pose missing from supplied model: '+name)
        info=metadata(by_image_name[name])
        if info['split']!=split:raise ValueError('Whitelist split mismatch: '+name)
        if isinstance(row,dict):
            if row.get('split',split)!=split or row.get('frame_id',info['source_frame'])!=info['source_frame'] or row.get('lens',name.split('/')[0])!=name.split('/')[0]:
                raise ValueError('Whitelist metadata differs from exact source name: '+name)
            if split=='train' and row.get('quality_status','passed')!='passed':raise ValueError('Training whitelist includes unpassed quality: '+name)
        names.append(name)
    if len(set(names))!=len(names):raise ValueError('Duplicate whitelist name: '+str(path))
    record={'path':str(path.resolve()),'sha256':file_hash(path),'count':len(names),'split':split}
    if isinstance(data,dict):
        if data.get('split',split)!=split:raise ValueError('Whitelist document split mismatch')
        for key in ('schema','training_ready','remaining_gate','point_geometry_uses_eval_images','pose_localization_uses_eval_pixels'):
            if key in data:record[key]=data[key]
    return set(names),record

train_names,train_provenance=read_whitelist(a.train_whitelist,'train')
eval_names,eval_provenance=read_whitelist(a.eval_whitelist,'eval')
if train_names is not None and train_names&eval_names:raise ValueError('Train/eval whitelist overlap')
def selected(im):
    if train_names is not None:return im['name'] in train_names or im['name'] in eval_names
    row=metadata(im);n=row['source_frame'];return a.subset=='all' or 540<=n<=720 or 1470<=n<=1650
inputs=sorted((im for im in images.values() if selected(im)),key=lambda im:(by_name[Path(im['name']).name]['source_frame'],im['name']))
if not inputs:raise ValueError('No input views selected')
for im in inputs:
    metadata(im)
    for path in [images_dir/im['name'],(masks_dir/im['name']).with_suffix('.png')]:
        if not path.is_file():raise FileNotFoundError(path)
source_model_hashes={name:file_hash(a.source/'sparse/0'/name) for name in (['cameras.bin','images.bin','points3D.bin'] if (a.source/'sparse/0/cameras.bin').exists() else ['cameras.txt','images.txt','points3D.txt'])}
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
    row=metadata(im);source=cv2.imread(str(images_dir/im['name']));mask_path=(masks_dir/im['name']).with_suffix('.png');mask=cv2.imread(str(mask_path),0)
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
with ThreadPoolExecutor(max_workers=a.workers) as pool:
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
sources_without_faces=sorted({im['name'] for im in inputs}-{v['sourceName'] for v in provenance})
if train_names is not None and sources_without_faces:raise ValueError('Whitelisted source produced no sufficiently valid virtual face: '+str(sources_without_faces))
for pid,track in tracks.items():
    if len(track)<2:continue
    point=dict(points[pid]);point['image_ids']=np.array([v[0] for v in track]);point['point2D_idxs']=np.array([v[1] for v in track]);point['track_len']=len(track);output_points[pid]=point
for im in output_images.values():im['point3D_ids']=np.array([pid if int(pid) in output_points else -1 for pid in im['point3D_ids']])
output_cameras={1:{'id':1,'model':'PINHOLE','width':S,'height':S,'params':np.array([f,f,f,f])}}
write_model_text(a.output/'sparse/0',output_cameras,output_images,output_points)
seed_ids=[pid for pid in output_points if len(train_times.get(pid,set()))>=2 and pid in colours]
seed_xyz=np.array([points[pid]['xyz'] for pid in seed_ids],dtype=np.float64).reshape(-1,3);seed_rgb=np.array([np.clip(np.rint(colours[pid][0]/colours[pid][1]),0,255) for pid in seed_ids],np.uint8).reshape(-1,3)
write_seed_ply(a.output/'seed-sparse-train.ply',seed_xyz,seed_rgb,np.zeros_like(seed_xyz))
if any(file_hash(a.source/'sparse/0'/name)!=digest for name,digest in source_model_hashes.items()):raise ValueError('Source model changed while materializing views')
report={'purpose':__doc__,'sourceDataset':str(a.source.resolve()),'outputDataset':str(a.output.resolve()),
        'imagesDirectory':str(images_dir.resolve()),'masksDirectory':str(masks_dir.resolve()),
        'selection':{'path':str(a.selection.resolve()),'sha256':file_hash(a.selection)},
        'whitelists':{'train':train_provenance,'eval':eval_provenance},
        'explicitWhitelistApplied':train_names is not None,'unlistedSourceImagesExcluded':len(images)-len(inputs),
        'sourceInputsWithoutValidVirtualFaces':sources_without_faces,
        'sourceModelSha256':source_model_hashes,'sourcePoseManifestSha256':file_hash(a.source/'pose-manifest.json') if (a.source/'pose-manifest.json').exists() else None,
        'subset':a.subset,'size':S,'workers':a.workers,'sourceInputs':len(inputs),'virtualViews':len(output_images),
        'trainViews':sum(v['sourceSplit']=='train' for v in output_images.values()),'evalViews':sum(v['sourceSplit']=='eval' for v in output_images.values()),
        'seedPoints':len(seed_ids),'seedColours':'Only unmasked selected source training images; at least two distinct training timestamps per seed point.',
        'seedLimit':'Localized views with point IDs=-1 add no sparse seed observations. No tracks, points or colours are fabricated; inspect seed count before training.',
        'worldCoordinateFrame':'Unchanged input COLMAP frame; up axis undeclared, no normalization or old-pose substitution.',
        'worldTransformApplied':False,'perFaceWorldRayIdentityTolerance':1e-12,
        'reprojection':{'observations':len(errors),'meanPixels':float(np.mean(errors)) if errors else None,'medianPixels':float(np.median(errors)) if errors else None,'p95Pixels':float(np.percentile(errors,95)) if errors else None,'maxPixels':float(np.max(errors)) if errors else None},
        'trainingReady':False if train_provenance is None else train_provenance.get('training_ready',False),
        'materializationIsNotQualityAcceptance':True,'newTrainingOrDepthUsed':False,
        'maskConvention':'255 keep / 0 exclude; source operator and mirror masks reprojected by nearest neighbour',
        'imagesSynthesized':False,'sourceFilesModified':False,'seconds':time.monotonic()-started,'views':provenance,
        'sha256':{name:file_hash(a.output/name) for name in ['sparse/0/cameras.txt','sparse/0/images.txt','sparse/0/points3D.txt','seed-sparse-train.ply']}}
(a.output/'explicit-pinhole-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['purpose','views','sha256']},indent=2))
