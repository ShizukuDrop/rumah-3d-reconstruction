"""Validate scale-only pinhole depths across distinct training timestamps.

Only pixels agreeing within 5% with at least TWO other camera timestamps become
depth targets or dense seeds. Eval images/depths never participate. The sparse
train-only seed is retained at higher priority during seed voxel reduction.
"""
import os,faulthandler
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1';os.environ['MKL_NUM_THREADS']='1'
faulthandler.enable();faulthandler.dump_traceback_later(45,repeat=True)
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,sys,time
import cv2,numpy as np
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W.parent/'osmo-reconstruct-20261031'))
from seed_fisheye import read_model,qvec_to_rotmat,voxel_reduce,write_seed_ply,load_depth
P=argparse.ArgumentParser();P.add_argument('--dataset',type=Path,required=True);P.add_argument('--max-seed',type=int,default=450000);a=P.parse_args();started=time.monotonic();cv2.setNumThreads(1)
out=a.dataset/'depths-trusted'
if out.exists() and any(out.iterdir()):raise FileExistsError(out)
out.mkdir(exist_ok=True);cameras,images,points=read_model(a.dataset/'sparse/0');by_name={im['name']:im for im in images.values()};scale_audit=json.loads((a.dataset/'depth-scale-audit.json').read_text());views=[]
for row in scale_audit['frames']:
    if not row['acceptedScale']:continue
    if '_eval' in row['name']:raise ValueError('Eval depth leaked into training validation')
    im=by_name[row['name']];cam=cameras[im['camera_id']];R=qvec_to_rotmat(im['qvec']).astype(np.float32);t=im['tvec'].astype(np.float32);centre=-t@R;fx,fy,cx,cy=cam['params']
    depth,known=load_depth((a.dataset/'depths'/row['name']).with_suffix('.png'),row['scale']);H,DW=depth.shape  # saturated 65535 is not a depth
    mask=cv2.imread(str((a.dataset/'masks'/row['name']).with_suffix('.png')),0);mask=cv2.resize(mask,(DW,H),interpolation=cv2.INTER_NEAREST);mask=cv2.erode(mask,np.ones((7,7),np.uint8))>127
    mask&=known&np.isfinite(depth)&(depth>.02)&(depth<60)
    k=np.array([fx*DW/cam['width'],fy*H/cam['height'],cx*DW/cam['width'],cy*H/cam['height']],np.float32)
    forward=R[2];median=float(np.median(depth[mask]));target=centre+forward*median*.85
    views.append({**row,'R':R,'t':t,'centre':centre,'depth':depth,'mask':mask,'k':k,'forward':forward,'target':target})
if not views:raise ValueError('No scale-qualified depth frames')
shapes={v['depth'].shape for v in views}
if len(shapes)!=1:raise ValueError('Expected uniform explicit pinhole depth maps')
H,DW=next(iter(shapes));fx,fy,cx,cy=views[0]['k'];x,y=np.meshgrid(np.arange(DW,dtype=np.float32)+.5,np.arange(H,dtype=np.float32)+.5);rays=np.stack([(x-cx)/fx,(y-cy)/fy,np.ones_like(x)],axis=-1);rays/=np.linalg.norm(rays,axis=-1,keepdims=True)
print(f'Loaded {len(views)} accepted depth views for consistency validation',flush=True)
def sample_image(image,mx,my,interpolation):
    # OpenCV remap dimensions are bounded by SHRT_MAX. Pack long point lists
    # into a small 2D grid instead of a hundreds-of-thousands-row N-by-1 map.
    n=len(mx);cols=1024;rows=(n+cols-1)//cols
    xmap=np.full(rows*cols,-1,np.float32);ymap=np.full_like(xmap,-1);xmap[:n]=mx;ymap[:n]=my
    result=cv2.remap(image,xmap.reshape(rows,cols),ymap.reshape(rows,cols),interpolation,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    return result.reshape(-1,image.shape[2])[:n] if image.ndim==3 else result.ravel()[:n]
def process(index):
    view=views[index];target=view['target'];candidates=[]
    for j,other in enumerate(views):
        if other['sourceFrame']==view['sourceFrame'] or abs(other['sourceFrame']-view['sourceFrame'])<6:continue
        baseline=float(np.linalg.norm(other['centre']-view['centre']))
        if not .03<=baseline<=3:continue
        local=target@other['R'].T+other['t']
        if local[2]<=.02:continue
        off=np.max(np.abs(local[:2]/local[2]))
        if off>1.6:continue
        score=baseline+.5*float(off);candidates.append((score,j))
    # One neighbour per timestamp; include available opposite-visit evidence.
    opposite=sorted((item for item in candidates if (views[item[1]]['sourceFrame']<1000)!=(view['sourceFrame']<1000)))
    ordered=opposite[:3]+sorted(candidates);chosen=[];stamps=set()
    for _,j in ordered:
        stamp=views[j]['sourceFrame']
        if stamp in stamps:continue
        stamps.add(stamp);chosen.append(j)
        if len(chosen)==14:break
    valid_indices=np.flatnonzero(view['mask']);depth=view['depth'].ravel()[valid_indices];local_points=rays.reshape(-1,3)[valid_indices]*depth[:,None];world=(local_points-view['t'])@view['R'];votes=np.zeros(len(world),np.uint8);cross=np.zeros(len(world),bool)
    for j in chosen:
        other=views[j];xc=world@other['R'].T+other['t'];distance=np.linalg.norm(xc,axis=1);z=xc[:,2];fx,fy,cx,cy=other['k'];uv=xc[:,:2]/np.maximum(z[:,None],1e-12)*[fx,fy]+[cx,cy];mx=(uv[:,0]-.5).astype(np.float32).reshape(-1,1);my=(uv[:,1]-.5).astype(np.float32).reshape(-1,1)
        observed=sample_image(other['depth'],mx.ravel(),my.ravel(),cv2.INTER_NEAREST);valid=sample_image(other['mask'].astype(np.uint8),mx.ravel(),my.ravel(),cv2.INTER_NEAREST)>0
        agree=valid&(z>.02)&(np.abs(observed-distance)<=.05*np.maximum(distance,1e-5));votes+=agree
        if (other['sourceFrame']<1000)!=(view['sourceFrame']<1000):cross|=agree
    trusted=votes>=2;trusted_map=np.zeros((H,DW),bool);trusted_map.ravel()[valid_indices]=trusted
    # Remove depth-boundary pixels; zero remains the explicit 'no depth' sentinel.
    trusted_map=cv2.erode(trusted_map.astype(np.uint8),np.ones((3,3),np.uint8))>0
    count=int(trusted_map.sum());row={'name':view['name'],'sourceFrame':view['sourceFrame'],'neighbourTimestamps':[views[j]['sourceFrame'] for j in chosen],'candidatePixels':len(valid_indices),'trustedPixels':count,'crossVisitSupportedPixelsBeforeErosion':int(np.sum(trusted&cross)),'written':count>=500}
    if count<500:return row,None
    mm=np.rint(view['depth']*1000);encoded=np.where(trusted_map&(mm>0)&(mm<65535),mm,0).astype(np.uint16);path=(out/view['name']).with_suffix('.png');cv2.imwrite(str(path),encoded);row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    # Depth-derived normals provide seed orientation, independent of normal-map conventions.
    pc=rays*view['depth'][...,None];dx=np.zeros_like(pc);dy=np.zeros_like(pc);dx[:,1:-1]=pc[:,2:]-pc[:,:-2];dy[1:-1]=pc[2:]-pc[:-2];normal=np.cross(dx,dy);length=np.linalg.norm(normal,axis=2);normal/=np.maximum(length[...,None],1e-12);normal[np.sum(normal*pc,axis=2)>0]*=-1
    sparse_grid=np.zeros((H,DW),bool);sparse_grid[::4,::4]=True;sample=trusted_map&sparse_grid&(length>1e-10)
    points_camera=pc[sample];world_seed=(points_camera-view['t'])@view['R'];normals=normal[sample]@view['R']
    image=cv2.imread(str(a.dataset/'images'/view['name']));ys,xs=np.nonzero(sample);rgb=sample_image(image,(xs.astype(np.float32)+.5)*image.shape[1]/DW-.5,(ys.astype(np.float32)+.5)*image.shape[0]/H-.5,cv2.INTER_LINEAR)[:,::-1]
    scores=np.ones(len(rgb),np.float32)
    # Record stronger cross-visit evidence in priorities without inventing geometry.
    cross_map=np.zeros((H,DW),bool);cross_map.ravel()[valid_indices]=cross;scores+=cross_map[sample]
    return row,(world_seed,rgb,normals,scores)
rows=[];seed_parts=[]
for i,index in enumerate(range(len(views)),1):
    row,seed=process(index);rows.append(row)
    if seed is not None:seed_parts.append(seed)
    if i%10==0:print(f'Multi-view depths {i}/{len(views)}; targets {sum(r["written"] for r in rows)}',flush=True)
if not seed_parts:raise ValueError('No multi-view-consistent depth pixels')
with (a.dataset/'seed-sparse-train.ply').open('rb') as f:
    header=b''
    while not header.endswith(b'end_header\n'):header+=f.readline()
    n=int(next(line.split()[-1] for line in header.decode().splitlines() if line.startswith('element vertex ')))
    dtype=np.dtype([(k,'<f4') for k in ['x','y','z','nx','ny','nz']]+[(k,'u1') for k in ['red','green','blue']]);sparse=np.fromfile(f,dtype=dtype,count=n)
seed_parts.insert(0,(np.column_stack([sparse[k] for k in ['x','y','z']]),np.column_stack([sparse[k] for k in ['red','green','blue']]),np.column_stack([sparse[k] for k in ['nx','ny','nz']]),np.full(n,10,np.float32)))
xyz,colour,normal,score=[np.concatenate([part[i] for part in seed_parts]) for i in range(4)];before=len(xyz);xyz,colour,normal,voxel=voxel_reduce(xyz,colour,normal,score,.004,a.max_seed);seed_path=a.dataset/'seed-dense-train.ply';write_seed_ply(seed_path,xyz,colour,normal)
report={'method':__doc__,'dataset':str(a.dataset.resolve()),'positiveScaleOnly':True,'offset':0.0,'relativeConsistencyTolerance':.05,'minimumOtherDistinctTrainingTimestamps':2,'scaleAcceptedFrames':len(views),'trustedDepthFrames':sum(r['written'] for r in rows),'trustedPixels':sum(r['trustedPixels'] for r in rows),'crossVisitSupportedPixels':sum(r['crossVisitSupportedPixelsBeforeErosion'] for r in rows),'sourceSparseSeedPoints':n,'seedCandidatesBeforeVoxel':before,'finalSeedPoints':len(xyz),'seedVoxelSizeSceneUnits':voxel,'seedSha256':hashlib.sha256(seed_path.read_bytes()).hexdigest(),'depthNumericUnits':'uint16 /1000 = original audited normalized SfM scene units, NOT measured metres','coordinateFrame':'+Y up, same fresh global SfM frame','oldGaussianOrDepthOpened':False,'evalInputsUsed':False,'scaleAuditSha256':hashlib.sha256((a.dataset/'depth-scale-audit.json').read_bytes()).hexdigest(),'explicitCameraAuditSha256':hashlib.sha256((a.dataset/'explicit-pinhole-audit.json').read_bytes()).hexdigest(),'frames':rows,'seconds':time.monotonic()-started}
(a.dataset/'trusted-depth-and-seed-audit.json').write_text(json.dumps(report,indent=2));faulthandler.cancel_dump_traceback_later();print(json.dumps({k:v for k,v in report.items() if k not in ['method','frames']},indent=2))
