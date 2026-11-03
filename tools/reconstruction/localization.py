"""Fixed-map generalized rig localization, with no triangulation or bundle adjustment.

Run: python -m tools.reconstruction.localization request.json result.json

The JSON request supplies cameras (id/model/width/height/params/cam_from_rig),
queries (camera_id/frame_id/time_seconds/split/source_sha256/features), an anchor
archive, and correspondences. Each archive reference is {path, sha256}; paths
are relative to the request. Anchor NPZ: point_ids, points3D. Query feature NPZ:
keypoints, original_indices. Correspondence NPZ: camera_idxs, query_feature_ids,
point3D_ids. camera_idxs index the ordered cameras, never external camera IDs.
All correspondences resolve to verified archive rows, not caller-supplied XYZ.

PyCOLMAP is an optional runtime dependency, never installed or downloaded here.
API: https://colmap.github.io/pycolmap/pycolmap.html
Threshold defaults are starting hypotheses, not validated Osmo acceptance values.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
import time

import numpy as np


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Expected a lowercase SHA-256 identity')
    return value


def integers(value, name):
    a = np.asarray(value)
    if a.ndim != 1 or a.dtype.kind not in 'iu' or np.any(a < 0):
        raise ValueError(f'{name} must be a nonnegative integer vector')
    if a.size and np.max(a) > np.iinfo(np.int64).max:
        raise ValueError(f'{name} exceeds supported integer range')
    return a.astype(np.int64)


def matrix_pose(value):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != (4, 4) or not np.isfinite(a).all() or not np.allclose(a[3], [0, 0, 0, 1], atol=1e-9):
        raise ValueError('A finite rigid 4x4 transform is required')
    r = a[:3, :3]
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-7) or not np.isclose(np.linalg.det(r), 1, atol=1e-7):
        raise ValueError('Pose rotation must be proper and orthonormal')
    return a


def archive(base, spec):
    path = (base / spec['path']).resolve()
    if file_hash(path) != sha(spec['sha256']):
        raise ValueError(f'Archive identity changed: {path.name}')
    with np.load(path, allow_pickle=False) as data:
        return {name: data[name].copy() for name in data.files}


def anchor_lookup(data):
    ids=integers(data['point_ids'],'anchor point_ids');xyz=np.asarray(data['points3D'],dtype=np.float64)
    if xyz.shape!=(len(ids),3) or not np.isfinite(xyz).all() or len(set(ids))!=len(ids):
        raise ValueError('Malformed or duplicate fixed anchor points')
    ids.setflags(write=False);xyz.setflags(write=False)
    return {int(i):point for i,point in zip(ids,xyz)}


class AnchorLookupCache:
    """One SHA-validated, read-only point lookup, fingerprint checked per query."""
    def __init__(self):self.entries={};self.hits=0;self.misses=0;self.validation_seconds=0.
    def get(self,base,spec):
        path=(base/spec['path']).resolve();digest=sha(spec['sha256']);stat=path.stat()
        state=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
        if path in self.entries:
            previous_digest,previous_state,lookup=self.entries[path]
            if state!=previous_state or digest!=previous_digest:raise ValueError('Shared anchor archive changed after validation')
            self.hits+=1;return lookup
        start=time.perf_counter();lookup=anchor_lookup(archive(base,spec));after=path.stat()
        if state!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('Shared anchor archive changed during validation')
        self.entries[path]=(digest,state,lookup);self.misses+=1;self.validation_seconds+=time.perf_counter()-start;return lookup
    def stats(self):
        return {'hits':self.hits,'misses':self.misses,'validation_seconds':self.validation_seconds,
                'policy':'SHA256 checked once on load; device/inode/size/mtime and expected hash checked every query; point arrays read-only'}


@dataclass(frozen=True)
class Gates:
    min_inliers: int = 24
    min_inlier_ratio: float = .25
    min_inliers_per_camera: int = 6
    grid_size: int = 4
    min_occupied_cells_per_camera: int = 4
    min_span_fraction: float = .15
    max_median_px: float = 2.0
    max_p95_px: float = 4.0
    max_p95_angle_degrees: float = 1.0
    max_prior_translation: float | None = None
    max_prior_rotation_degrees: float | None = None

    def __post_init__(self):
        for name in ('min_inliers', 'min_inliers_per_camera', 'grid_size', 'min_occupied_cells_per_camera'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'Invalid gate {name}')
        if self.min_occupied_cells_per_camera > self.grid_size ** 2:
            raise ValueError('More occupied cells required than the grid contains')
        for name in ('min_inlier_ratio', 'min_span_fraction'):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f'Invalid gate {name}')
        for name in ('max_median_px', 'max_p95_px', 'max_p95_angle_degrees', 'max_prior_translation', 'max_prior_rotation_degrees'):
            value = getattr(self, name)
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError(f'Invalid gate {name}')


class NativeCamera:
    """Exact KB4 sphere projection, avoiding perspective-only library inverses."""
    def __init__(self, spec, camera):
        self.spec=spec;self.camera=camera
        self.width=spec['width'];self.height=spec['height'];self.params=np.asarray(spec['params'],float)
        self.fisheye=spec['model'] in ('OPENCV_FISHEYE','opencv-fisheye')
        self.theta_max=float(spec.get('theta_max_rad',2.05))
        if not 0<self.theta_max<np.pi:raise ValueError('Invalid calibrated fisheye angular domain')

    def cam_ray_from_img(self, xy):
        if not self.fisheye:return self.camera.cam_ray_from_img(xy)
        from .motion import fisheye_bearings
        return fisheye_bearings(xy,self.spec,self.theta_max)[0]

    def img_from_cam(self, xyz, check_cheirality=True):
        if not self.fisheye:return self.camera.img_from_cam(xyz,check_cheirality=check_cheirality)
        xyz=np.asarray(xyz,float);p=self.params
        radius=np.linalg.norm(xyz[:,:2],axis=1);theta=np.arctan2(radius,xyz[:,2]);t2=theta*theta
        distorted=theta*(1+t2*(p[4]+t2*(p[5]+t2*(p[6]+t2*p[7]))))
        scale=np.divide(distorted,radius,out=np.ones_like(radius),where=radius>1e-12)
        xy=xyz[:,:2]*scale[:,None]*p[:2]+p[2:4]
        valid=(theta<=self.theta_max)&(np.linalg.norm(xyz,axis=1)>1e-12)&np.isfinite(xyz).all(axis=1)
        xy[~valid]=np.nan
        return xy


def virtualize_rig(points2d,camera_idxs,native_cameras,extrinsics,pc,max_native_error):
    """Rotate bearings to six cube faces; no pixels/images are warped or created.

    Each virtual camera has the native lens centre and a fixed face rotation.
    Correspondence order and original native feature IDs remain unchanged.
    """
    axes=np.concatenate([np.eye(3),-np.eye(3)],axis=0);faces=[]
    for forward in axes:
        reference=np.array([0.,1.,0.]) if abs(forward[1])<.5 else np.array([0.,0.,1.])
        right=np.cross(reference,forward);down=np.cross(forward,right)
        faces.append(np.stack([right,down,forward]))
    faces=np.asarray(faces);focal=1024.;virtual=np.empty_like(points2d);indices=np.empty(len(points2d),np.int64)
    cameras=[];members=[];native_rays=np.empty((len(points2d),3));max_jacobian=0.
    for i,(native,extrinsic) in enumerate(zip(native_cameras,extrinsics)):
        rows=np.flatnonzero(camera_idxs==i);xy=points2d[rows];rays=np.asarray(native.cam_ray_from_img(xy),float)
        roundtrip=np.asarray(native.img_from_cam(rays,check_cheirality=False),float)
        error=np.linalg.norm(roundtrip-xy,axis=1)
        if not np.isfinite(rays).all() or not np.isfinite(error).all() or np.any(error>.05):
            raise ValueError('Camera projection cannot invert all correspondence rays within 0.05 pixels')
        native_rays[rows]=rays
        face_ids=np.argmax(rays@axes.T,axis=1)
        rotations=faces[face_ids]
        def project(r):
            local=np.einsum('nij,nj->ni',rotations,r)
            if np.any(local[:,2]<=0):raise ValueError('Virtual face does not contain its assigned bearing')
            return local[:,:2]/local[:,2,None]*focal+focal
        projected=project(rays);virtual[rows]=projected;indices[rows]=i*6+face_ids
        # Local native-pixel -> virtual-pixel amplification; native residual gates
        # still decide acceptance after estimation, so this is a proposal threshold.
        jacobian=np.empty((len(rows),2,2));epsilon=.05
        for axis in range(2):
            shifted=xy.copy();shifted[:,axis]+=epsilon
            jacobian[:,:,axis]=(project(np.asarray(native.cam_ray_from_img(shifted)))-projected)/epsilon
        if not np.isfinite(jacobian).all():raise ValueError('Correspondence lies on an unsupported calibration boundary')
        if len(rows):max_jacobian=max(max_jacobian,float(np.max(np.linalg.svd(jacobian,compute_uv=False))))
        for rotation in faces:
            transform=np.eye(4);transform[:3,:3]=rotation@extrinsic[:3,:3];transform[:3,3]=rotation@extrinsic[:3,3]
            members.append(pc.Rigid3d(transform[:3]));cameras.append(pc.Camera(model='PINHOLE',width=2048,height=2048,params=[focal,focal,focal,focal]))
    return virtual,indices,cameras,members,{'method':'Exact native bearings assigned to six fixed virtual PINHOLE rig faces per lens; no image warp',
        'max_error_virtual_pixels':float(max_native_error*max_jacobian*1.1),'max_local_pixel_amplification':max_jacobian,
        'virtual_camera_idxs':indices.tolist(),'negative_native_z_correspondences':int((native_rays[:,2]<0).sum()),'virtual_focal':focal}


def load_request(request_path,anchor_cache=None):
    request_path = Path(request_path)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    base = request_path.parent
    if 'preparation_report' in request:
        report_path=(base/request['preparation_report']).resolve()
        report=json.loads(report_path.read_text(encoding='utf-8'))
        listed={(report_path.parent/row['request']).resolve() for row in report.get('queries',[]) if row.get('request')}
        if report.get('status')!='complete' or request_path.resolve() not in listed:
            raise ValueError('Localization preparation is incomplete or does not list this request')
    cameras = request['cameras']
    if len(cameras) < 2 or len({str(c['id']) for c in cameras}) != len(cameras):
        raise ValueError('A rig requires at least two uniquely identified cameras')
    for c in cameras:
        matrix_pose(c['cam_from_rig'])
        if type(c['width']) is not int or type(c['height']) is not int or min(c['width'], c['height']) <= 0:
            raise ValueError('Invalid camera image dimensions')
        params = np.asarray(c['params'], dtype=float)
        if params.ndim != 1 or not len(params) or not np.isfinite(params).all():
            raise ValueError('Invalid fixed camera parameters')
    queries = request['queries']
    if len(queries) != len(cameras) or {str(q['camera_id']) for q in queries} != {str(c['id']) for c in cameras}:
        raise ValueError('Exactly one query per rig camera is required')
    if len({q['frame_id'] for q in queries}) != 1 or len({q['split'] for q in queries}) != 1:
        raise ValueError('Rig members must preserve the same frame identity and train/eval split')
    if queries[0]['split'] not in ('train', 'eval'):
        raise ValueError('Unknown train/eval split')
    times = np.asarray([q['time_seconds'] for q in queries], dtype=float)
    if not np.isfinite(times).all() or times.min() < 0 or np.ptp(times) > 1e-6:
        raise ValueError('Rig members must be synchronized')
    features = {}
    for q in queries:
        sha(q['source_sha256'])
        data = archive(base, q['features'])
        ids = integers(data['original_indices'], 'original_indices')
        xy = np.asarray(data['keypoints'], dtype=np.float64)
        if xy.shape != (len(ids), 2) or not np.isfinite(xy).all() or len(set(ids)) != len(ids):
            raise ValueError('Malformed query feature identities')
        c = next(c for c in cameras if str(c['id']) == str(q['camera_id']))
        if np.any(xy < 0) or np.any(xy >= [c['width'], c['height']]):
            raise ValueError('Query coordinates must use original camera pixels')
        features[str(q['camera_id'])] = {int(i): p for i, p in zip(ids, xy)}
    lookup=anchor_lookup(archive(base,request['anchors'])) if anchor_cache is None else anchor_cache.get(base,request['anchors'])
    corr = archive(base, request['correspondences'])
    ci = integers(corr['camera_idxs'], 'camera_idxs')
    fi = integers(corr['query_feature_ids'], 'query_feature_ids')
    pi = integers(corr['point3D_ids'], 'point3D_ids')
    if not (len(ci) == len(fi) == len(pi)) or len(ci) < 6 or np.any(ci >= len(cameras)):
        raise ValueError('Incomplete or invalid correspondence rows')
    if len(set(zip(ci, fi))) != len(ci) or len(set(zip(ci, pi))) != len(ci):
        raise ValueError('Ambiguous or duplicate query-to-anchor assignment')
    try:
        points2d = np.asarray([features[str(cameras[c]['id'])][int(f)] for c, f in zip(ci, fi)])
        points3d = np.asarray([lookup[int(p)] for p in pi])
    except KeyError as error:
        raise ValueError('Correspondence references an unknown original feature or anchor point') from error
    return request, points2d, points3d, ci, fi, pi


def assess_pose(points2d, points3d, camera_idxs, cameras, extrinsics, pose, inliers, gates, prior=None):
    """Independent residual/spread gate; cameras expose img_from_cam/cam_ray_from_img."""
    pose = matrix_pose(pose)
    mask = np.asarray(inliers)
    if mask.dtype.kind != 'b' or mask.shape != (len(points2d),):
        raise ValueError('Estimator returned an invalid inlier mask')
    residuals = np.full(len(mask), np.inf)
    angular = np.full(len(mask), np.inf)
    forward = np.zeros(len(mask), dtype=bool)
    coverage = []
    for i, (camera, extrinsic) in enumerate(zip(cameras, extrinsics)):
        rows = np.flatnonzero(camera_idxs == i)
        transform = matrix_pose(extrinsic) @ pose
        camxyz = points3d[rows] @ transform[:3, :3].T + transform[:3, 3]
        # Bearing agreement supports valid fisheye rays without imposing pinhole z > 0.
        if not hasattr(camera, 'cam_ray_from_img'):
            raise RuntimeError('PyCOLMAP camera requires cam_ray_from_img; upgrade explicitly for generalized fisheye support')
        rays = np.asarray(camera.cam_ray_from_img(points2d[rows]), dtype=float)
        projected = np.asarray(camera.img_from_cam(camxyz), dtype=float)
        if rays.shape != (len(rows), 3) or projected.shape != (len(rows), 2):
            raise ValueError('Camera projection returned invalid shapes')
        length = np.linalg.norm(camxyz, axis=1) * np.linalg.norm(rays, axis=1)
        cosine = np.divide(np.sum(camxyz * rays, axis=1), length, out=np.full(len(rows), np.nan), where=length > 0)
        residuals[rows] = np.linalg.norm(projected - points2d[rows], axis=1)
        angular[rows] = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
        forward[rows] = cosine > 0
        selected = rows[mask[rows]]
        xy = points2d[selected] / [camera.width, camera.height]
        cells = np.floor(xy * gates.grid_size).astype(int)
        span = np.ptp(xy, axis=0) if len(xy) else np.zeros(2)
        coverage.append({'camera_idx': i, 'inliers': len(selected), 'occupied_cells': len(set(map(tuple, cells))), 'span_fraction': span.tolist()})
    reasons = []
    count = int(mask.sum())
    if count < gates.min_inliers: reasons.append('insufficient_inliers')
    if count / len(mask) < gates.min_inlier_ratio: reasons.append('low_inlier_ratio')
    for c in coverage:
        if c['inliers'] < gates.min_inliers_per_camera: reasons.append(f"camera_{c['camera_idx']}_insufficient_inliers")
        if c['occupied_cells'] < gates.min_occupied_cells_per_camera or min(c['span_fraction']) < gates.min_span_fraction:
            reasons.append(f"camera_{c['camera_idx']}_poor_spatial_spread")
    finite = count > 0 and np.isfinite(residuals[mask]).all() and np.isfinite(angular[mask]).all()
    median = float(np.median(residuals[mask])) if finite else None
    p95 = float(np.percentile(residuals[mask], 95)) if finite else None
    angle95 = float(np.percentile(angular[mask], 95)) if finite else None
    if not finite: reasons.append('nonfinite_or_empty_projection')
    else:
        if median > gates.max_median_px or p95 > gates.max_p95_px: reasons.append('reprojection_residual')
        if angle95 > gates.max_p95_angle_degrees: reasons.append('angular_residual')
    if not np.all(forward[mask]): reasons.append('bearing_cheirality')
    prior_metrics = None
    if prior is not None:
        previous = matrix_pose(prior)
        c0 = -pose[:3, :3].T @ pose[:3, 3]
        c1 = -previous[:3, :3].T @ previous[:3, 3]
        distance = float(np.linalg.norm(c0-c1))
        rotation = float(np.degrees(np.arccos(np.clip((np.trace(pose[:3, :3] @ previous[:3, :3].T)-1)/2, -1, 1))))
        prior_metrics = {'translation_scene_units': distance, 'rotation_degrees': rotation}
        if gates.max_prior_translation is not None and distance > gates.max_prior_translation: reasons.append('prior_translation')
        if gates.max_prior_rotation_degrees is not None and rotation > gates.max_prior_rotation_degrees: reasons.append('prior_rotation')
    elif gates.max_prior_translation is not None or gates.max_prior_rotation_degrees is not None:
        raise ValueError('Pose prior gates require an explicit prior_rig_from_world')
    return {'accepted': not reasons, 'rejection_reasons': reasons, 'inliers': count,
            'inlier_ratio': count/len(mask), 'median_px': median, 'p95_px': p95,
            'p95_angle_degrees': angle95, 'coverage': coverage, 'prior': prior_metrics}


def native_residuals(points2d,points3d,camera_idxs,cameras,extrinsics,pose):
    """Residuals in the original calibrated pixels, never virtual-face pixels."""
    pose=matrix_pose(pose);difference=np.full((len(points2d),2),np.nan);angular=np.full(len(points2d),np.inf)
    forward=np.zeros(len(points2d),bool)
    for ci,(camera,extrinsic) in enumerate(zip(cameras,extrinsics)):
        rows=np.flatnonzero(camera_idxs==ci);transform=extrinsic@pose
        local=points3d[rows]@transform[:3,:3].T+transform[:3,3]
        rays=np.asarray(camera.cam_ray_from_img(points2d[rows]));projected=np.asarray(camera.img_from_cam(local))
        length=np.linalg.norm(local,axis=1)*np.linalg.norm(rays,axis=1)
        cosine=np.divide(np.sum(local*rays,axis=1),length,out=np.full(len(rows),np.nan),where=length>0)
        difference[rows]=projected-points2d[rows];angular[rows]=np.degrees(np.arccos(np.clip(cosine,-1,1)));forward[rows]=cosine>0
    return difference,angular,forward


def native_consensus(points2d,points3d,camera_idxs,cameras,extrinsics,pose,gates):
    difference,angular,forward=native_residuals(points2d,points3d,camera_idxs,cameras,extrinsics,pose)
    error=np.linalg.norm(difference,axis=1)
    mask=np.isfinite(error)&np.isfinite(angular)&forward&(error<=gates.max_p95_px)&(angular<=gates.max_p95_angle_degrees)
    finite=error[np.isfinite(error)]
    return mask,{'native_pixel_threshold':gates.max_p95_px,'native_angle_threshold_degrees':gates.max_p95_angle_degrees,
        'inliers':int(mask.sum()),'outliers':int((~mask).sum()),'nonfinite_residuals':int((~np.isfinite(error)).sum()),
        'all_correspondence_median_px':float(np.median(finite)) if len(finite) else None,
        'all_correspondence_p95_px':float(np.percentile(finite,95)) if len(finite) else None}


def refine_native_pose(points2d,points3d,camera_idxs,cameras,extrinsics,pose,gates):
    """Refine only one rig pose with robust native-pixel residuals and fixed map.

    The virtual solver is a proposal generator with a conservative threshold.
    Its inlier mask is not portable to native pixels. Reclassify all original
    correspondences at the unchanged native 4px criterion, then refine only a
    well-supported consensus. A pose can still fail the independent median,
    count, ratio, per-camera spread, angular, and optional prior gates.
    """
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation
    pose=matrix_pose(pose).copy();initial=pose.copy();rounds=[]
    mask,before=native_consensus(points2d,points3d,camera_idxs,cameras,extrinsics,pose,gates)
    for _ in range(2):
        counts=np.bincount(camera_idxs[mask],minlength=len(cameras))
        if mask.sum()<gates.min_inliers or min(counts)<gates.min_inliers_per_camera:break
        selected=np.flatnonzero(mask);xy=points2d[selected];xyz=points3d[selected];ci=camera_idxs[selected]
        parameter=np.concatenate([Rotation.from_matrix(pose[:3,:3]).as_rotvec(),pose[:3,3]])
        def unpack(value):
            transform=np.eye(4);transform[:3,:3]=Rotation.from_rotvec(value[:3]).as_matrix();transform[:3,3]=value[3:];return transform
        def residual(value):
            transform=unpack(value);difference=np.full((len(selected),2),1e6)
            for camera_idx,(camera,extrinsic) in enumerate(zip(cameras,extrinsics)):
                rows=np.flatnonzero(ci==camera_idx);combined=extrinsic@transform
                local=xyz[rows]@combined[:3,:3].T+combined[:3,3]
                difference[rows]=np.asarray(camera.img_from_cam(local))-xy[rows]
            return np.nan_to_num(difference,nan=1e6,posinf=1e6,neginf=-1e6).ravel()
        original=residual(parameter);scale=gates.max_median_px
        initial_cost=float(np.sum(scale*scale*(np.sqrt(1+(original/scale)**2)-1)))
        fitted=least_squares(residual,parameter,loss='soft_l1',f_scale=scale,x_scale='jac',max_nfev=30,ftol=1e-8,xtol=1e-8,gtol=1e-8)
        improved=bool(np.isfinite(fitted.x).all() and np.isfinite(fitted.cost) and fitted.cost<=initial_cost+1e-8)
        rounds.append({'consensus_points':len(selected),'nfev':fitted.nfev,'success':bool(fitted.success),'status':int(fitted.status),
                       'initial_robust_cost':initial_cost,'final_robust_cost':float(fitted.cost),'update_used':improved})
        if not improved:break
        pose=unpack(fitted.x);new_mask,_=native_consensus(points2d,points3d,camera_idxs,cameras,extrinsics,pose,gates)
        unchanged=np.array_equal(mask,new_mask);mask=new_mask
        if unchanged:break
    mask,after=native_consensus(points2d,points3d,camera_idxs,cameras,extrinsics,pose,gates)
    delta_rotation=float(np.degrees(np.arccos(np.clip((np.trace(pose[:3,:3]@initial[:3,:3].T)-1)/2,-1,1))))
    centers=[-value[:3,:3].T@value[:3,3] for value in (initial,pose)]
    return pose,mask,{'method':'Two bounded robust native-pixel pose-only refinements with native consensus reclassification',
        'fixed_points':True,'fixed_intrinsics':True,'fixed_rig_extrinsics':True,'before':before,'after':after,'rounds':rounds,
        'rotation_update_degrees':delta_rotation,'center_update_scene_units':float(np.linalg.norm(centers[1]-centers[0]))}


def localize_fixed_rig(request_path,anchor_cache=None):
    start = time.perf_counter()
    request, xy, xyz, ci, fi, pi = load_request(request_path,anchor_cache=anchor_cache)
    loaded = time.perf_counter()
    gates = Gates(**request.get('gates', {}))
    try: pc = importlib.import_module('pycolmap')
    except ImportError as error: raise RuntimeError('PyCOLMAP is not installed. No pose was estimated; install explicitly in the selected CPU environment.') from error
    if not hasattr(pc, 'estimate_and_refine_generalized_absolute_pose'):
        raise RuntimeError('Installed PyCOLMAP lacks generalized rig localization')
    native_params = [pc.Camera(model=c['model'], width=c['width'], height=c['height'], params=c['params']) for c in request['cameras']]
    cameras=[NativeCamera(spec,camera) for spec,camera in zip(request['cameras'],native_params)]
    extrinsics = [matrix_pose(c['cam_from_rig']) for c in request['cameras']]
    virtual_xy,virtual_ci,virtual_cameras,members,virtual_report=virtualize_rig(xy,ci,cameras,extrinsics,pc,gates.max_p95_px)
    before = [np.asarray(c.params).copy() for c in virtual_cameras]
    member_before=[m.matrix().copy() for m in members]
    options = {'max_error': virtual_report['max_error_virtual_pixels'], 'min_inlier_ratio': gates.min_inlier_ratio, 'random_seed': 0}
    prepared = time.perf_counter()
    # Dict conversion is documented by PyCOLMAP; do not allow callers to enable calibration refinement.
    result = pc.estimate_and_refine_generalized_absolute_pose(virtual_xy.copy(), xyz.copy(), virtual_ci.tolist(), members, virtual_cameras,
        estimation_options=options, refinement_options={'refine_focal_length': False, 'refine_extra_params': False}, return_covariance=True)
    estimated = time.perf_counter()
    output = {'schema': 'rumah-fixed-rig-localization-v1', 'request_sha256': file_hash(request_path),
              'anchors_sha256': request['anchors']['sha256'], 'correspondences_sha256': request['correspondences']['sha256'],
              'queries': request['queries'], 'gates': asdict(gates), 'pycolmap_version': getattr(pc, '__version__', 'unknown'),
              'map_mutated': False, 'intrinsics_refined': False, 'rig_extrinsics_refined': False,
              'bearing_adapter':virtual_report,
              'pose_convention': 'rig_from_world; camera_from_world = camera_from_rig @ rig_from_world',
              'threshold_status': 'User-adjustable hypotheses; validate on scene before promotion.'}
    if result is None:
        output.update(accepted=False, rejection_reasons=['pose_estimation_failed'])
    else:
        for original, camera, member, e in zip(before, virtual_cameras, members, member_before):
            if not np.array_equal(original, camera.params) or not np.allclose(member.matrix(), e, atol=1e-12):
                raise RuntimeError('Fixed calibration or rig extrinsics changed')
        returned = result.get('cameras', virtual_cameras)
        if any(not np.array_equal(p, c.params) for p, c in zip(before, returned)):
            raise RuntimeError('Estimator returned modified intrinsics')
        pose = np.eye(4); pose[:3] = result['rig_from_world'].matrix()
        virtual_mask = np.asarray(result['inlier_mask'])
        output['virtual_proposal_assessment']=assess_pose(xy,xyz,ci,cameras,extrinsics,pose,virtual_mask,gates,request.get('prior_rig_from_world'))
        pose,mask,native_refinement=refine_native_pose(xy,xyz,ci,cameras,extrinsics,pose,gates)
        output['native_refinement']=native_refinement
        output['virtual_proposal_inliers']=int(virtual_mask.sum())
        output['virtual_proposal_outliers_under_native_gate']=int(np.count_nonzero(virtual_mask&~mask))
        assessment = assess_pose(xy, xyz, ci, cameras, extrinsics, pose, mask, gates, request.get('prior_rig_from_world'))
        output.update(assessment)
        output['inlier_correspondence_rows'] = np.flatnonzero(mask).tolist()
        if assessment['accepted']:
            output['rig_from_world'] = pose.tolist()
            output['camera_from_world'] = [(e @ pose).tolist() for e in extrinsics]
        covariance = result.get('covariance')
        if covariance is not None and np.isfinite(covariance).all(): output['virtual_proposal_covariance'] = np.asarray(covariance).tolist()
    output['elapsed_seconds'] = time.perf_counter()-start
    output['anchor_loading']={'mode':'fresh_validation_per_request'} if anchor_cache is None else {'mode':'fingerprint_bound_shared_lookup',**anchor_cache.stats()}
    output['timing_seconds'] = {'input_validation_loading':loaded-start,'camera_bearing_preparation':prepared-loaded,
                                'pose_estimation_refinement':estimated-prepared,'independent_gate_and_output':time.perf_counter()-estimated}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = localize_fixed_rig(args.request)
    with args.output.open('x', encoding='utf-8') as f: json.dump(result, f, indent=2, allow_nan=False)
    return 0 if result['accepted'] else 2


if __name__ == '__main__': raise SystemExit(main())
