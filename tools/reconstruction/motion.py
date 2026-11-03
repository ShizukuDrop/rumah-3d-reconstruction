"""Masked, calibrated dual-fisheye tracking for prospective keyframe selection.

Rotation-compensated angular motion is a parallax proxy, not metric translation.
It does not require the expensive completed reconstruction. Both lenses are
evaluated; low support produces unknown evidence, never a redundant verdict.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import json
import math
import time
import cv2
import numpy as np
from .capture import load_capture


@dataclass(frozen=True)
class MotionConfig:
    image_edge: int = 640
    max_tracks: int = 400
    min_tracks: int = 40
    min_grid_cells: int = 5
    grid: int = 5
    forward_backward_px: float = 1.0
    theta_max_rad: float = 2.05


def fisheye_bearings(points, camera, theta_max=2.05):
    """Invert the calibrated KB4 radius, retaining rays beyond 90 degrees."""
    p = np.asarray(camera['params'], dtype=float)
    if camera['model'] not in ('opencv-fisheye', 'OPENCV_FISHEYE') or len(p) != 8:
        raise ValueError('Expected calibrated OPENCV_FISHEYE / KB4')
    xy = (np.asarray(points, dtype=float)-p[2:4])/p[:2]
    radius = np.linalg.norm(xy, axis=1)
    def project(theta):
        t2=theta*theta
        return theta*(1+t2*(p[4]+t2*(p[5]+t2*(p[6]+t2*p[7]))))
    # A fitted polynomial need not remain invertible outside its calibrated
    # lens. End the inverse at its first positive derivative root; never choose
    # a second solution from the folded polynomial tail.
    roots=np.polynomial.polynomial.polyroots([1,3*p[4],5*p[5],7*p[6],9*p[7]])
    positive=[float(np.sqrt(r.real)) for r in roots if abs(r.imag)<1e-9 and r.real>0]
    if positive:theta_max=min(theta_max,min(positive)-1e-6)
    grid=np.linspace(0,theta_max,256)
    if not np.all(np.diff(project(grid)) > 0):
        raise ValueError('Calibration is not monotonic over the requested angular range')
    valid=np.isfinite(radius)&(radius<=project(theta_max))
    lo=np.zeros_like(radius); hi=np.full_like(radius,theta_max)
    for _ in range(35):
        mid=(lo+hi)/2
        below=project(mid)<radius
        lo=np.where(below,mid,lo); hi=np.where(below,hi,mid)
    theta=(lo+hi)/2
    scale=np.divide(np.sin(theta),radius,out=np.ones_like(radius),where=radius>1e-12)
    rays=np.column_stack([xy*scale[:,None],np.cos(theta)])
    rays[~valid]=np.nan
    return rays,valid


def robust_rotation(first, second):
    """Robust fit of b = R a. Residuals retain translation/depth variation."""
    a,b=np.asarray(first,float),np.asarray(second,float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3 or len(a)<6:
        raise ValueError('At least six paired bearings are required')
    use=np.ones(len(a),bool)
    for _ in range(6):
        u,_,vt=np.linalg.svd(a[use].T@b[use])
        r=vt.T@np.diag([1.,1.,np.linalg.det(vt.T@u.T)])@u.T
        residual=np.arccos(np.clip(np.sum((a@r.T)*b,axis=1),-1,1))
        median=np.median(residual)
        mad=np.median(np.abs(residual-median))
        next_use=residual<=max(math.radians(.05),median+3*1.4826*mad)
        if next_use.sum()<6 or np.array_equal(next_use,use):
            break
        use=next_use
    return r,np.degrees(residual),use


def load_gray(image_path, mask_path, config):
    # JPEG reduced decode avoids decoding a 3840 image into full RGB.
    image=cv2.imread(str(image_path),cv2.IMREAD_REDUCED_GRAYSCALE_4)
    mask=cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        raise ValueError(f'Unreadable image/mask: {image_path}')
    native_h,native_w=mask.shape
    scale=config.image_edge/max(image.shape)
    size=(max(1,round(image.shape[1]*scale)),max(1,round(image.shape[0]*scale)))
    image=cv2.resize(image,size,interpolation=cv2.INTER_AREA)
    mask=cv2.resize(mask,size,interpolation=cv2.INTER_NEAREST)
    mask=cv2.erode((mask>127).astype(np.uint8)*255,np.ones((7,7),np.uint8))
    return image,mask,np.array([native_w/size[0],native_h/size[1]])


def track_view(first, second, camera, config=MotionConfig()):
    a,ma,native_scale=first; b,mb,other_scale=second
    if a.shape!=b.shape or not np.array_equal(native_scale,other_scale):
        raise ValueError('Tracking frames must have equal native and analysis dimensions')
    points=cv2.goodFeaturesToTrack(a,maxCorners=config.max_tracks,qualityLevel=.015,
                                    minDistance=9,mask=ma,blockSize=5)
    if points is None or len(points)<config.min_tracks:
        return {'status':'unknown','reason':'insufficient_texture','tracks':0}
    next_points,status,_=cv2.calcOpticalFlowPyrLK(a,b,points,None,winSize=(21,21),maxLevel=3)
    if next_points is None:
        return {'status':'unknown','reason':'tracking_failed','tracks':0}
    back,back_status,_=cv2.calcOpticalFlowPyrLK(b,a,next_points,None,winSize=(21,21),maxLevel=3)
    if back is None:
        return {'status':'unknown','reason':'back_tracking_failed','tracks':0}
    p=points.reshape(-1,2); q=next_points.reshape(-1,2)
    valid=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back.reshape(-1,2)-p,axis=1)<config.forward_backward_px)
    valid&=np.isfinite(q).all(axis=1)&(q[:,0]>=0)&(q[:,1]>=0)&(q[:,0]<b.shape[1])&(q[:,1]<b.shape[0])
    indices=np.flatnonzero(valid)
    rounded=np.rint(q[indices]).astype(int)
    rounded[:,0]=np.clip(rounded[:,0],0,b.shape[1]-1); rounded[:,1]=np.clip(rounded[:,1],0,b.shape[0]-1)
    valid[indices]&=mb[rounded[:,1],rounded[:,0]]>0
    p,q=p[valid],q[valid]
    # LK uses integer-centered OpenCV pixels. The native SfM calibration uses
    # COLMAP centers: undo the resize-center offset, then add the native +0.5.
    rays_a,va=fisheye_bearings((p+.5)*native_scale,camera,config.theta_max_rad)
    rays_b,vb=fisheye_bearings((q+.5)*native_scale,camera,config.theta_max_rad)
    use=va&vb; p,q,rays_a,rays_b=p[use],q[use],rays_a[use],rays_b[use]
    cells=np.unique(np.floor(q/np.array([b.shape[1],b.shape[0]])*config.grid).astype(int),axis=0)
    if len(p)<config.min_tracks or len(cells)<config.min_grid_cells:
        return {'status':'unknown','reason':'insufficient_distributed_tracks','tracks':len(p),'grid_cells':len(cells)}
    rotation,residual,inliers=robust_rotation(rays_a,rays_b)
    return {'status':'measured','tracks':len(p),'grid_cells':len(cells),
            'track_survival':float(len(p)/len(points)),
            'rotation_deg':float(np.degrees(np.arccos(np.clip((np.trace(rotation)-1)/2,-1,1)))),
            'parallax_deg_p50':float(np.percentile(residual,50)),
            'parallax_deg_p75':float(np.percentile(residual,75)),
            'rotation_inlier_residual_deg_p75':float(np.percentile(residual[inliers],75)),
            'parallax_population':'all forward/back-consistent, mask-valid tracked bearings; not only rotation-fit inliers',
            'rotation_fit_inlier_fraction':float(inliers.mean()),
            'interpretation':'rotation-compensated angular tracking residual; not metric baseline'}


def compare_pair(capture, first, second, config=MotionConfig(), cache=None):
    root=Path(capture['dataset']); cache={} if cache is None else cache
    result={}
    for lens in ('cam0','cam1'):
        views=[]
        for frame in (first,second):
            key=(frame['id'],lens)
            if key not in cache:
                cache[key]=load_gray(root/'images'/frame['images'][lens],root/'masks'/frame['masks'][lens],config)
            views.append(cache[key])
        result[lens]=track_view(*views,capture['cameras'][lens],config)
    return {'reference_frame':first['id'],'frame':second['id'],
            'seconds':second['time_seconds']-first['time_seconds'],'lenses':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--pairs',required=True,help='Comma-separated source frame pairs, e.g. 2247:2248,2247:2262')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cv2.setNumThreads(1)
    capture=load_capture(args.dataset); frames={r['id']:r for r in capture['frames']}
    config=MotionConfig(); cache={}; start=time.perf_counter(); results=[]
    for pair in args.pairs.split(','):
        first,second=map(int,pair.split(':'))
        results.append(compare_pair(capture,frames[first],frames[second],config,cache))
    output={'source_selection_sha256':capture['source_selection_sha256'],'configuration':asdict(config),
            'elapsed_seconds':time.perf_counter()-start,'comparisons':results,'gpu_used':False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(output,stream,indent=2)
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
