"""Ray-depth seeding for native dual OPENCV_FISHEYE COLMAP captures.

Reusable read_model(path) returns (cameras, images, points) dicts keyed by ID.
Camera: id, model, model_id, width, height, params float64 array.
Image: id, qvec float64 [qw,qx,qy,qz] WORLD->CAM, tvec float64[3], camera_id,
       name, points2D_xy float64[N,2], point3D_ids int64[N], n_points2D.
Point: id, xyz float64[3], rgb uint8[3], error, track_len,
       image_ids int32[M], point2D_idxs int32[M].
Image coordinates follow COLMAP: top-left pixel center (0.5,0.5), not (0,0).
No coordinate normalization is applied: seed.ply stays in the input SfM frame.

Camera IDs/parameter counts verified against the installed Spirula source:
  src/data/parsers/ColmapParser.cpp (colmap_model_table)
and COLMAP upstream src/colmap/sensor/models/base.h. In particular ID 5 is
OPENCV_FISHEYE with EIGHT parameters, not SIMPLE_RADIAL_FISHEYE.
The retained iPhone helper's custom table must not be used for this capture.
"""
from __future__ import annotations
import argparse
from collections import OrderedDict
import json
import math
from pathlib import Path
import re
import struct
import sys
import time
import cv2
import numpy as np

CAMERA_MODELS = {
    0: ('SIMPLE_PINHOLE',3), 1: ('PINHOLE',4), 2: ('SIMPLE_RADIAL',4),
    3: ('RADIAL',5), 4: ('OPENCV',8), 5: ('OPENCV_FISHEYE',8),
    6: ('FULL_OPENCV',12), 7: ('FOV',5), 8: ('SIMPLE_RADIAL_FISHEYE',4),
    9: ('RADIAL_FISHEYE',5), 10: ('THIN_PRISM_FISHEYE',12),
    11: ('RAD_TAN_THIN_PRISM_FISHEYE',16), 12: ('SIMPLE_DIVISION',4),
    13: ('DIVISION',5), 14: ('SIMPLE_FISHEYE',3), 15: ('FISHEYE',4),
    16: ('EUCM',6), 17: ('EQUIRECTANGULAR',2),
}
CAMERA_NAMES = {name:(mid,n) for mid,(name,n) in CAMERA_MODELS.items()}

def _unpack(f, fmt):
    n=struct.calcsize(fmt);raw=f.read(n)
    if len(raw)!=n: raise ValueError(f'Truncated COLMAP record in {f.name}')
    return struct.unpack(fmt,raw)

def _assert_eof(f):
    if f.read(1): raise ValueError(f'Extra bytes after COLMAP records in {f.name}; unsupported model layout')

def qvec_to_rotmat(q):
    q=np.asarray(q,dtype=np.float64);norm=np.linalg.norm(q)
    if not np.isfinite(norm) or norm<1e-12: raise ValueError('Invalid COLMAP quaternion')
    w,x,y,z=q/norm
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])

def rotmat_to_qvec(r):
    from scipy.spatial.transform import Rotation
    x,y,z,w=Rotation.from_matrix(np.asarray(r,dtype=np.float64)).as_quat()
    q=np.array([w,x,y,z]);return q if q[0]>=0 else -q

def camera_centers(images):
    return {iid:-qvec_to_rotmat(im['qvec']).T@im['tvec'] for iid,im in images.items()}

def _read_binary(path):
    cameras={};images={};points={}
    with (path/'cameras.bin').open('rb') as f:
        count,=_unpack(f,'<Q')
        if count>1000000: raise ValueError('Implausible camera count')
        for _ in range(count):
            cid,mid,w,h=_unpack(f,'<iiQQ')
            if mid not in CAMERA_MODELS: raise ValueError(f'Unsupported COLMAP model ID {mid}; refusing guessed parameter count')
            model,n=CAMERA_MODELS[mid]
            cameras[cid]={'id':cid,'model':model,'model_id':mid,'width':w,'height':h,'params':np.array(_unpack(f,'<'+'d'*n))}
        _assert_eof(f)
    with (path/'images.bin').open('rb') as f:
        count,=_unpack(f,'<Q')
        for _ in range(count):
            iid,=_unpack(f,'<i');q=np.array(_unpack(f,'<4d'));t=np.array(_unpack(f,'<3d'));cid,=_unpack(f,'<i')
            name=bytearray()
            while True:
                c=f.read(1)
                if not c: raise ValueError('Unterminated COLMAP image name')
                if c==b'\0': break
                name.extend(c)
                if len(name)>32768: raise ValueError('Implausible COLMAP image name')
            n,=_unpack(f,'<Q')
            dtype=np.dtype([('x','<f8'),('y','<f8'),('pid','<i8')]);raw=f.read(n*dtype.itemsize)
            if len(raw)!=n*dtype.itemsize: raise ValueError('Truncated COLMAP observations')
            obs=np.frombuffer(raw,dtype=dtype)
            images[iid]={'id':iid,'qvec':q,'tvec':t,'camera_id':cid,'name':name.decode('utf-8'),
                         'points2D_xy':np.column_stack([obs['x'],obs['y']]),'point3D_ids':obs['pid'].copy(),'n_points2D':n}
        _assert_eof(f)
    with (path/'points3D.bin').open('rb') as f:
        count,=_unpack(f,'<Q')
        for _ in range(count):
            pid,=_unpack(f,'<Q');xyz=np.array(_unpack(f,'<3d'));rgb=np.array(_unpack(f,'<3B'),dtype=np.uint8)
            error,=_unpack(f,'<d');n,=_unpack(f,'<Q');raw=f.read(n*8)
            if len(raw)!=n*8: raise ValueError('Truncated COLMAP point track')
            track=np.frombuffer(raw,dtype='<i4').reshape(-1,2)
            points[pid]={'id':pid,'xyz':xyz,'rgb':rgb,'error':error,'track_len':n,
                         'image_ids':track[:,0].copy(),'point2D_idxs':track[:,1].copy()}
        _assert_eof(f)
    return cameras,images,points

def _read_text(path):
    cameras={};images={};points={}
    for line in (path/'cameras.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        f=line.split();cid=int(f[0]);name=f[1]
        if name not in CAMERA_NAMES:raise ValueError(f'Unknown camera model {name}')
        mid,n=CAMERA_NAMES[name];params=np.array(list(map(float,f[4:])))
        if len(params)!=n:raise ValueError(f'Wrong {name} parameter count')
        cameras[cid]={'id':cid,'model':name,'model_id':mid,'width':int(f[2]),'height':int(f[3]),'params':params}
    lines=iter((path/'images.txt').read_text(encoding='utf-8').splitlines())
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):continue
        f=line.split(maxsplit=9)
        if len(f)!=10:raise ValueError('Invalid COLMAP image pose line')
        iid=int(f[0]);obs=next(lines,None)
        if obs is None:raise ValueError('Missing COLMAP image observation line')
        fields=obs.split()
        if len(fields)%3:raise ValueError('Invalid COLMAP image observations')
        xy=np.array([[float(fields[j]),float(fields[j+1])] for j in range(0,len(fields),3)]).reshape(-1,2)
        ids=np.array([int(fields[j+2]) for j in range(0,len(fields),3)],dtype=np.int64)
        images[iid]={'id':iid,'qvec':np.array(list(map(float,f[1:5]))),'tvec':np.array(list(map(float,f[5:8]))),
                     'camera_id':int(f[8]),'name':f[9],'points2D_xy':xy,'point3D_ids':ids,'n_points2D':len(ids)}
    for line in (path/'points3D.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        f=line.split();pid=int(f[0]);track=np.array(list(map(int,f[8:])),dtype=np.int32).reshape(-1,2)
        points[pid]={'id':pid,'xyz':np.array(list(map(float,f[1:4]))),'rgb':np.array(list(map(int,f[4:7])),dtype=np.uint8),
                     'error':float(f[7]),'track_len':len(track),'image_ids':track[:,0].copy(),'point2D_idxs':track[:,1].copy()}
    return cameras,images,points

def read_model(path):
    path=Path(path)
    cameras,images,points=_read_binary(path) if (path/'cameras.bin').exists() else _read_text(path)
    for im in images.values():
        if im['camera_id'] not in cameras:raise ValueError('Image references an absent camera')
        if not np.isfinite(im['qvec']).all() or not np.isfinite(im['tvec']).all():raise ValueError('Non-finite camera pose')
    return cameras,images,points

def write_model_text(path,cameras,images,points,overwrite=False):
    path=Path(path);names=['cameras.txt','images.txt','points3D.txt']
    if any((path/n).exists() for n in ['cameras.bin','images.bin','points3D.bin']):
        raise FileExistsError(f'Binary model present at {path}; write text into a fresh directory to avoid stale binary precedence')
    if not overwrite and any((path/n).exists() for n in names):raise FileExistsError(f'Model already exists: {path}')
    path.mkdir(parents=True,exist_ok=True)
    fmt=lambda a:' '.join(f'{float(v):.17g}' for v in a)
    rows=[]
    for cid,c in sorted(cameras.items()):rows.append(f"{cid} {c['model']} {c['width']} {c['height']} {fmt(c['params'])}")
    (path/'cameras.txt').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    rows=[]
    for iid,im in sorted(images.items()):
        rows.append(f"{iid} {fmt(im['qvec'])} {fmt(im['tvec'])} {im['camera_id']} {im['name']}")
        rows.append(' '.join(f'{xy[0]:.17g} {xy[1]:.17g} {int(pid)}' for xy,pid in zip(im['points2D_xy'],im['point3D_ids'])))
    (path/'images.txt').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    rows=[]
    for pid,p in sorted(points.items()):
        track=' '.join(f'{int(iid)} {int(idx)}' for iid,idx in zip(p.get('image_ids',[]),p.get('point2D_idxs',[])))
        rows.append(f"{pid} {fmt(p['xyz'])} {' '.join(str(int(v)) for v in p['rgb'])} {p['error']:.17g} {track}".rstrip())
    (path/'points3D.txt').write_text('\n'.join(rows)+'\n',encoding='utf-8')

class Fisheye:
    """OPENCV_FISHEYE projection onto unit rays, including z<=0 rays.

    rho = theta*(1+k1*theta^2+k2*theta^4+k3*theta^6+k4*theta^8).
    The inverse is restricted to the first monotonic branch, never to z>0.
    """
    def __init__(self,camera,width=None,height=None,max_theta_degrees=105):
        if camera['model']!='OPENCV_FISHEYE' or len(camera['params'])!=8:
            raise ValueError('This dense seeder requires calibrated OPENCV_FISHEYE (8 parameters)')
        self.width=int(width or camera['width']);self.height=int(height or camera['height'])
        p=np.asarray(camera['params'],dtype=float).copy()
        p[[0,2]]*=self.width/camera['width'];p[[1,3]]*=self.height/camera['height']
        self.fx,self.fy,self.cx,self.cy=p[:4];self.k=p[4:]
        if not np.isfinite(p).all() or min(self.fx,self.fy)<=0:raise ValueError('Invalid fisheye calibration')
        theta=np.linspace(0,math.radians(max_theta_degrees),16385)
        t2=theta*theta
        derivative=1+3*self.k[0]*t2+5*self.k[1]*t2**2+7*self.k[2]*t2**3+9*self.k[3]*t2**4
        bad=np.flatnonzero(derivative<=0)
        if len(bad):theta=theta[:int(bad[0])]
        if len(theta)<100:raise ValueError('Fisheye polynomial has no usable monotonic domain')
        self.theta=theta;self.rho=self.distort(theta);self.max_theta=float(theta[-1])

    def distort(self,theta):
        t2=theta*theta
        return theta*(1+self.k[0]*t2+self.k[1]*t2**2+self.k[2]*t2**3+self.k[3]*t2**4)

    def unproject(self,xy):
        xy=np.asarray(xy,dtype=float);uv=(xy-np.array([self.cx,self.cy]))/np.array([self.fx,self.fy])
        rho=np.linalg.norm(uv,axis=-1);valid=np.isfinite(uv).all(axis=-1)&(rho<=self.rho[-1])
        theta=np.interp(rho,self.rho,self.theta)
        direction=uv/np.maximum(rho[...,None],1e-15)
        ray=np.concatenate([direction*np.sin(theta)[...,None],np.cos(theta)[...,None]],axis=-1)
        return ray,valid

    def project(self,xyz):
        xyz=np.asarray(xyz,dtype=float);radius=np.linalg.norm(xyz[...,:2],axis=-1)
        theta=np.arctan2(radius,xyz[...,2]);rho=self.distort(theta)
        uv=xyz[...,:2]/np.maximum(radius[...,None],1e-15)*rho[...,None]
        xy=uv*np.array([self.fx,self.fy])+np.array([self.cx,self.cy])
        valid=np.isfinite(xy).all(axis=-1)&(theta<=self.max_theta)&(np.linalg.norm(xyz,axis=-1)>1e-10)
        return xy,valid

def _find_map(root,name,extensions=('.png','.npy','.npz'),required=True):
    rel=Path(name)
    candidates=[root/rel.with_suffix(ext) for ext in extensions]+[root/Path(str(rel)+'.png')]
    for path in candidates:
        if path.is_file():return path
    if required:raise FileNotFoundError(f'No map for {name} under {root}')
    return None

def load_depth(path,integer_scale=.001):
    path=Path(path)
    if path.suffix.lower()=='.npy':raw=np.load(path,allow_pickle=False)
    elif path.suffix.lower()=='.npz':
        with np.load(path,allow_pickle=False) as data:
            key='depth' if 'depth' in data.files else 'arr_0' if 'arr_0' in data.files else data.files[0]
            raw=data[key].copy()
    else:raw=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
    if raw is None or raw.ndim!=2:raise ValueError(f'Expected scalar depth map: {path}')
    valid=np.isfinite(raw)&(raw>0)
    if np.issubdtype(raw.dtype,np.integer):
        valid&=raw<np.iinfo(raw.dtype).max
        depth=raw.astype(np.float32)*integer_scale
    else:depth=raw.astype(np.float32)
    return depth,valid

def pinhole_face_maps(model,face,size):
    """cv2.remap maps for a PINHOLE view (f=cx=cy=size/2) looking along face.

    Both sides follow COLMAP: output pixel i holds the ray through i+0.5, and a
    fisheye sample at continuous u is cv2 index u-0.5. Treating either side as
    integer-centred shifts the RGB 0.1-0.9 px off its written camera model.
    """
    f=size/2;xx,yy=np.meshgrid(np.arange(size)+.5,np.arange(size)+.5)
    uv,valid=model.project(np.stack([(xx-f)/f,(yy-f)/f,np.ones_like(xx)],axis=-1).reshape(-1,3)@face)
    valid&=(uv[:,0]>=0)&(uv[:,0]<model.width)&(uv[:,1]>=0)&(uv[:,1]<model.height)
    return (uv[:,0]-.5).reshape(size,size).astype(np.float32),(uv[:,1]-.5).reshape(size,size).astype(np.float32),valid.reshape(size,size)

def sample_map(values,xy,nearest=False):
    """COLMAP continuous pixel coordinates -> cv2 integer-centered sample grid."""
    xy=np.asarray(xy,dtype=np.float32).reshape(-1,2)
    return cv2.remap(values,(xy[:,0]-.5).reshape(-1,1),(xy[:,1]-.5).reshape(-1,1),
                     cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT,borderValue=0).reshape((-1,)+values.shape[2:])

def robust_affine_ray_fit(raw_depth,target_range,min_points=30,threshold=.10,min_inlier_fraction=.5,seed=0):
    x=np.asarray(raw_depth,dtype=float);y=np.asarray(target_range,dtype=float)
    valid=np.isfinite(x)&np.isfinite(y)&(x>0)&(y>0);x=x[valid];y=y[valid]
    if len(x)<min_points:raise ValueError(f'Only {len(x)} usable sparse ray-distance observations')
    spread=float(np.subtract(*np.percentile(x,[75,25])))
    if spread<max(1e-5,.005*np.median(x)):raise ValueError('Depth values have insufficient spread for an affine fit')
    rng=np.random.default_rng(seed);best=None;best_score=(-1,-np.inf)
    for _ in range(256):
        i,j=rng.choice(len(x),2,replace=False)
        if abs(x[i]-x[j])<.05*spread:continue
        scale=(y[i]-y[j])/(x[i]-x[j]);offset=y[i]-scale*x[i]
        if scale<=0 or not np.isfinite(scale+offset):continue
        residual=np.abs(scale*x+offset-y)/np.maximum(y,1e-10);inside=residual<threshold
        score=(int(inside.sum()),-float(np.median(residual)))
        if score>best_score:best_score=score;best=(scale,offset)
    if best is None:raise ValueError('No positive affine ray-depth fit')
    scale,offset=best
    for _ in range(5):
        residual=np.abs(scale*x+offset-y)/y;inside=residual<threshold
        if inside.sum()<min_points:break
        a=np.column_stack([x[inside],np.ones(inside.sum())])/y[inside,None]
        scale,offset=np.linalg.lstsq(a,np.ones(inside.sum()),rcond=None)[0]
    prediction=scale*x+offset;residual=np.abs(prediction-y)/y;inside=residual<threshold
    fraction=float(inside.mean());median=float(np.median(residual));p90=float(np.percentile(residual,90))
    if scale<=0 or fraction<min_inlier_fraction or median>.12 or p90>.35 or np.mean(prediction>0)<.95:
        raise ValueError(f'Invalid ray fit: scale={scale:.4g}, fraction={fraction:.3f}, median={median:.3f}, p90={p90:.3f}')
    return {'scale':float(scale),'offset':float(offset),'observations':len(x),'inliers':int(inside.sum()),
            'inlier_fraction':fraction,'median_relative_residual':median,'p90_relative_residual':p90,
            'sparse_range_median':float(np.median(y)),'sparse_range_p95':float(np.percentile(y,95)),
            'raw_range_iqr':spread}

def load_frame(dataset,image,camera,args,fit=None):
    name=image['name'];depth_path=_find_map(dataset/'depths',name)
    depth,valid=load_depth(depth_path,args.depth_scale);height,width=depth.shape
    model=Fisheye(camera,width,height,args.max_theta_degrees)
    mask_path=_find_map(dataset/'masks',name,('.png',),required=not args.allow_missing_masks)
    if mask_path is not None:
        mask=cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE)
        if mask is None:raise ValueError(f'Cannot read mask {mask_path}')
        mask=cv2.resize(mask,(width,height),interpolation=cv2.INTER_NEAREST)>127
        if args.mask_erode:mask=cv2.erode(mask.astype(np.uint8),np.ones((3,3),np.uint8),iterations=args.mask_erode)>0
        valid&=mask
    valid[:args.border]=False;valid[-args.border:]=False;valid[:,:args.border]=False;valid[:,-args.border:]=False
    # Bilinear depth samples must not straddle invalid holes or masked people.
    valid=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8),iterations=1)>0
    if fit is not None:
        depth=fit['scale']*depth+fit['offset']
        valid&=np.isfinite(depth)&(depth>0)
    return {'depth':depth,'valid':valid,'model':model,'R':qvec_to_rotmat(image['qvec']),'t':image['tvec'],
            'image':image,'normal_map':_find_map(dataset/'normals',name,('.png','.npy','.npz'),required=False),
            'depth_path':depth_path,'mask_path':mask_path}

def fit_frame(dataset,image,camera,points,args):
    frame=load_frame(dataset,image,camera,args);depth=frame['depth'];h,w=depth.shape
    xy=image['points2D_xy']*np.array([w/camera['width'],h/camera['height']])
    raw=sample_map(depth,xy);mask=sample_map(frame['valid'].astype(np.uint8),xy,nearest=True)>0
    entries=[]
    for idx,pid in enumerate(image['point3D_ids']):
        point=points.get(int(pid))
        if point is not None and mask[idx] and point['track_len']>=args.min_track:
            entries.append((idx,point['xyz']))
    if not entries:raise ValueError('No usable masked sparse tracks')
    idx=np.array([item[0] for item in entries]);world=np.array([item[1] for item in entries])
    xc=world@frame['R'].T+frame['t'];ranges=np.linalg.norm(xc,axis=1)
    rays,valid=frame['model'].unproject(xy[idx]);alignment=np.sum(rays*xc/np.maximum(ranges[:,None],1e-15),axis=1)
    projected,projectable=frame['model'].project(xc)
    image_scale=np.array([w/camera['width'],h/camera['height']])
    reprojection_error=np.linalg.norm((projected-xy[idx])/image_scale,axis=1)
    valid&=projectable&(alignment>math.cos(math.radians(2)))&(reprojection_error<=args.max_sparse_error)
    fit=robust_affine_ray_fit(raw[idx][valid],ranges[valid],args.min_fit_points,args.fit_threshold,args.min_fit_fraction,image['id'])
    fitted=fit['scale']*depth+fit['offset'];fraction=float(np.mean(fitted[frame['valid']]>0)) if frame['valid'].any() else 0
    if fraction<.85:raise ValueError(f'Affine model makes too much of the masked depth non-positive: {fraction:.3f}')
    fit.update(positive_fraction=fraction,depth_shape=[h,w],normal_map_present=frame['normal_map'] is not None,
               sparse_error_source='Actual native-fisheye per-observation reprojection, in original camera pixels; stored point.error is not trusted',
               sparse_observations_before_reprojection_gate=len(idx),sparse_observations_after_reprojection_gate=int(valid.sum()),
               median_reprojection_pixels=float(np.median(reprojection_error[valid])) if valid.any() else None,
               raw_depth_path=str(frame['depth_path']),mask_path=str(frame['mask_path']) if frame['mask_path'] else None)
    return fit

def frame_candidates(dataset,frame,args):
    depth,valid,model=frame['depth'],frame['valid'],frame['model'];h,w=depth.shape
    step=max(args.stride,int(math.ceil(math.sqrt(h*w/args.max_candidates))))
    yy,xx=np.meshgrid(np.arange(2,h-2,step),np.arange(2,w-2,step),indexing='ij')
    yy=yy.ravel();xx=xx.ravel();keep=valid[yy,xx]&valid[yy,xx+1]&valid[yy+1,xx]
    xx=xx[keep];yy=yy[keep];xy=np.column_stack([xx+.5,yy+.5])
    rays,ok=model.unproject(xy);rx,okx=model.unproject(xy+[1,0]);ry,oky=model.unproject(xy+[0,1])
    p=rays*depth[yy,xx,None];px=rx*depth[yy,xx+1,None];py=ry*depth[yy+1,xx,None]
    normals=np.cross(px-p,py-p);length=np.linalg.norm(normals,axis=1)
    ok&=okx&oky&(length>1e-12)
    # Reject depth discontinuities instead of joining an object's silhouette to a wall.
    ok&=(np.abs(depth[yy,xx+1]-depth[yy,xx])/depth[yy,xx]<.05)&(np.abs(depth[yy+1,xx]-depth[yy,xx])/depth[yy,xx]<.05)
    p=p[ok];rays=rays[ok];normals=normals[ok]/length[ok,None]
    normals[np.sum(normals*rays,axis=1)>0]*=-1
    rgb=cv2.imread(str(dataset/'images'/frame['image']['name']),cv2.IMREAD_COLOR)
    if rgb is None:raise ValueError('Cannot read source image colors')
    rgb=cv2.cvtColor(cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB)
    colors=rgb[yy[ok],xx[ok]]
    world=(p-frame['t'])@frame['R'];normal_world=normals@frame['R']
    return world.astype(np.float32),colors,normal_world.astype(np.float32)

def temporal_agreement(world,neighbor,tolerance=.05):
    xc=world@neighbor['R'].T+neighbor['t'];distance=np.linalg.norm(xc,axis=1)
    xy,valid=neighbor['model'].project(xc);h,w=neighbor['depth'].shape
    valid&=(xy[:,0]>=1.5)&(xy[:,0]<w-1.5)&(xy[:,1]>=1.5)&(xy[:,1]<h-1.5)
    valid&=sample_map(neighbor['valid'].astype(np.uint8),xy,nearest=True)>0
    measured=sample_map(neighbor['depth'],xy)
    return valid&(np.abs(measured-distance)<=tolerance*np.maximum(distance,1e-10))

def voxel_reduce(points,colors,normals,scores,voxel_size,max_points):
    order=np.argsort(-scores,kind='stable');points=points[order];colors=colors[order];normals=normals[order]
    size=voxel_size;indices=np.arange(len(points))
    for _ in range(15):
        cells=np.floor(points/size).astype(np.int64)
        _,indices=np.unique(cells,axis=0,return_index=True);used=size
        if len(indices)<=max_points:break
        size*=max(1.05,(len(indices)/max_points)**(1/3)*1.02)
    if len(indices)>max_points:indices=np.sort(np.random.default_rng(73031).choice(indices,max_points,replace=False))
    return points[indices],colors[indices],normals[indices],float(used)

def write_seed_ply(path,points,colors,normals):
    dtype=np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),('nx','<f4'),('ny','<f4'),('nz','<f4'),('red','u1'),('green','u1'),('blue','u1')])
    values=np.empty(len(points),dtype=dtype)
    for i,k in enumerate(['x','y','z']):values[k]=points[:,i]
    for i,k in enumerate(['nx','ny','nz']):values[k]=normals[:,i]
    for i,k in enumerate(['red','green','blue']):values[k]=colors[:,i]
    header='ply\nformat binary_little_endian 1.0\ncomment ray-depth seed; same coordinate frame as input COLMAP model\n'+f'element vertex {len(points)}\n'
    header+=''.join(f'property float {k}\n' for k in ['x','y','z','nx','ny','nz'])
    header+=''.join(f'property uchar {k}\n' for k in ['red','green','blue'])+'end_header\n'
    temporary=path.with_suffix(path.suffix+'.partial')
    with temporary.open('wb') as f:f.write(header.encode('ascii'));values.tofile(f)
    temporary.replace(path)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True);parser.add_argument('--model',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--report',type=Path)
    parser.add_argument('--depth-scale',type=float,default=.001,help='Integer depth units -> metres (native MoGe PNGs store millimetres); float NPY/NPZ use their values directly')
    parser.add_argument('--max-points',type=int,default=200000);parser.add_argument('--max-candidates',type=int,default=18000)
    parser.add_argument('--stride',type=int,default=4);parser.add_argument('--border',type=int,default=3)
    parser.add_argument('--mask-erode',type=int,default=1);parser.add_argument('--max-theta-degrees',type=float,default=105)
    parser.add_argument('--min-track',type=int,default=3);parser.add_argument('--max-sparse-error',type=float,default=4)
    parser.add_argument('--min-fit-points',type=int,default=30);parser.add_argument('--fit-threshold',type=float,default=.10)
    parser.add_argument('--min-fit-fraction',type=float,default=.5);parser.add_argument('--min-good-frame-fraction',type=float,default=.5)
    parser.add_argument('--neighbor-tolerance',type=float,default=.05);parser.add_argument('--min-agreements',type=int,default=2)
    parser.add_argument('--voxel-size',type=float,default=0,help='SfM units; default robust scene diagonal / 500')
    parser.add_argument('--allow-missing-masks',action='store_true');parser.add_argument('--fits-only',action='store_true')
    parser.add_argument('--overwrite',action='store_true');args=parser.parse_args(argv)
    dataset=args.dataset.resolve();output=(args.output or dataset/'seed.ply').resolve()
    report_path=(args.report or dataset.parent/'analysis/seed-fisheye.json').resolve()
    if args.max_points<1 or args.max_points>200000:raise ValueError('Seed point cap must be between 1 and 200000')
    if args.border<1 or args.stride<1 or not (0<args.neighbor_tolerance<=.05) or args.min_agreements<2:
        raise ValueError('Require nonzero border/stride and at least two agreements within 5%')
    for destination in [output,report_path]:
        if any(destination.is_relative_to(dataset/leaf) for leaf in ['images','masks','depths','normals','sparse']):
            raise ValueError('An output must not overwrite input maps, imagery or the sparse model')
        if destination.exists() and not args.overwrite:raise FileExistsError(f'Output already exists: {destination}')
    cameras,images,points=read_model(args.model or dataset/'sparse/0')
    if not images or not points:raise ValueError('Sparse model has no cameras or points')
    started=time.monotonic();fits={};records={}
    report={'method':'Per-frame positive affine fit of raw unit-ray distance to observed sparse Euclidean range; no Z-depth shortcut',
            'coordinate_frame':'Unchanged input COLMAP world; camera qvec is world-to-camera',
            'depth_units':'uint16 PNG millimetres * depth_scale; float maps unchanged before affine alignment',
            'normal_source':'Ray-depth surface tangents, oriented toward source camera; predicted normal maps are not modified or assumed to use any coordinate convention',
            'camera_model_table_source':'Installed native src/data/parsers/ColmapParser.cpp; ID 5 OPENCV_FISHEYE with 8 parameters',
            'status':'fitting','registered_frames':len(images),'sparse_points':len(points),'arguments':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},'frames':records}
    def save_report():
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    for number,(iid,image) in enumerate(sorted(images.items()),1):
        try:
            fit=fit_frame(dataset,image,cameras[image['camera_id']],points,args);fits[iid]=fit;records[image['name']]={'accepted_fit':True,**fit}
        except (ValueError,FileNotFoundError) as exc:records[image['name']]={'accepted_fit':False,'reason':str(exc)}
        if number%10==0:print(f'Ray fits {number}/{len(images)}; accepted {len(fits)}',flush=True)
    report['accepted_fit_frames']=len(fits);report['accepted_fit_fraction']=len(fits)/len(images)
    save_report()
    if len(fits)<max(4,args.min_good_frame_fraction*len(images)):
        report.update(status='rejected',reason='Too few valid affine ray-depth fits');save_report()
        raise ValueError(f'Too few valid affine ray-depth fits ({len(fits)}/{len(images)}); no seed written')
    if args.fits_only:
        report.update(status='fits_validated',elapsed_seconds=time.monotonic()-started);save_report()
        print(json.dumps({k:report[k] for k in ['accepted_fit_frames','accepted_fit_fraction']}));return 0
    groups={}
    for iid,image in images.items():
        if iid in fits:groups.setdefault(Path(image['name']).parent.as_posix(),[]).append(iid)
    neighbors={}
    for group in groups.values():
        group.sort(key=lambda iid:images[iid]['name'])
        for j,iid in enumerate(group):neighbors[iid]=[group[k] for k in [j-2,j-1,j+1,j+2] if 0<=k<len(group)]
    cache=OrderedDict()
    def frame_for(iid):
        if iid not in cache:
            im=images[iid];cache[iid]=load_frame(dataset,im,cameras[im['camera_id']],args,fits[iid])
            if len(cache)>12:cache.popitem(last=False)
        cache.move_to_end(iid);return cache[iid]
    point_chunks=[];color_chunks=[];normal_chunks=[];score_chunks=[];candidate_total=accepted_total=0
    for number,iid in enumerate(sorted(fits),1):
        frame=frame_for(iid);world,colors,normals=frame_candidates(dataset,frame,args)
        agreements=np.zeros(len(world),dtype=np.uint8)
        for nid in neighbors[iid]:agreements+=temporal_agreement(world,frame_for(nid),args.neighbor_tolerance)
        keep=agreements>=args.min_agreements
        candidate_total+=len(world);accepted_total+=int(keep.sum())
        records[images[iid]['name']].update(candidates=len(world),temporal_neighbors=[images[n]['name'] for n in neighbors[iid]],
                                          consistent_points=int(keep.sum()),consistency_fraction=float(keep.mean()) if len(keep) else 0)
        if keep.any():
            point_chunks.append(world[keep]);color_chunks.append(colors[keep]);normal_chunks.append(normals[keep])
            score_chunks.append(agreements[keep].astype(np.float32)/(1+fits[iid]['median_relative_residual']))
        if number%10==0:print(f'Temporal validation {number}/{len(fits)}; accepted {accepted_total:,}/{candidate_total:,}',flush=True)
    report.update(candidate_points=candidate_total,temporally_consistent_points=accepted_total,
                  temporal_consistency_fraction=accepted_total/max(1,candidate_total))
    save_report()
    if accepted_total<1000:
        report.update(status='rejected',reason='Too few temporally consistent points');save_report()
        raise ValueError('Too few points survive temporal depth validation; no seed written')
    xyz=np.concatenate(point_chunks);rgb=np.concatenate(color_chunks);normals=np.concatenate(normal_chunks);scores=np.concatenate(score_chunks)
    sparse=np.array([p['xyz'] for p in points.values()]);diagonal=float(np.linalg.norm(np.percentile(sparse,99,axis=0)-np.percentile(sparse,1,axis=0)))
    voxel=args.voxel_size or diagonal/500
    if not np.isfinite(voxel) or voxel<=0:raise ValueError('Invalid scene extent for voxel sampling')
    xyz,rgb,normals,voxel=voxel_reduce(xyz,rgb,normals,scores,voxel,args.max_points)
    output.parent.mkdir(parents=True,exist_ok=True);write_seed_ply(output,xyz,rgb,normals)
    report.update(output=str(output),output_points=len(xyz),voxel_size=voxel,elapsed_seconds=time.monotonic()-started,status='complete')
    save_report();print(json.dumps({k:report[k] for k in ['output','output_points','voxel_size','accepted_fit_fraction','temporal_consistency_fraction','elapsed_seconds']}),flush=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'Fisheye seed failed closed: {exc}',file=sys.stderr,flush=True);raise
