"""Fair cached-ALIKED matcher experiments; importing this module never initializes a GPU.

Plan only: python -m tools.reconstruction.matcher_benchmark manifest.json out
Run explicitly: add --run --device cuda --allow-gpu --weights local-aliked.pth

Manifest: features {image_id: {path,sha256,source_sha256,split,camera?}}, pairs
[{id,image0,image1,stratum}]. Feature files are original VKFT v6 or NPZ containing
keypoints[N,2], descriptors[N,128], scores[N], image_size[2], original_indices[N].
Every arm uses the same image pairs. The 2048 arm truncates these cached features,
not a new extraction. Exact selected tensors and original row maps are hashed.
External backend command adapters receive one NPZ pair and must echo its digest;
the pinned Spirula CLI has no arbitrary-pair API, so none is claimed here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import random
import re
import struct
import subprocess
import tempfile
import time

import numpy as np


ARMS = {'fixed4096': (4096, -1., -1.), 'adaptive4096': (4096, .95, .99), 'adaptive2048': (2048, .95, .99)}


def quality_failures(geometry,min_inliers=15,min_cells=4):
    reasons=[]
    if geometry.get('inliers',0)<min_inliers:reasons.append('insufficient_verified_inliers')
    if len(geometry.get('occupied_cells',[]))!=2 or min(geometry['occupied_cells'])<min_cells:reasons.append('poor_spatial_spread')
    return reasons


def fallback_decision(pair,arm,geometry,mode='none',min_inliers=15,min_cells=4):
    if mode not in ('none','protected','all-weak'):raise ValueError('Unknown fallback policy')
    protected=pair.get('protected',False) or pair['stratum'] in ('doorway','bridge','revisit','loop_candidate')
    failures=quality_failures(geometry,min_inliers,min_cells)
    retry=arm=='adaptive4096' and bool(failures) and (mode=='all-weak' or (mode=='protected' and protected))
    return {'retry_fixed4096':retry,'protected':bool(protected),'quality_failures':failures,
            'reason':'verified_quality_gate' if retry else 'quality_passed' if not failures else 'fallback_policy_does_not_cover_edge'}


def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def digest_arrays(*arrays):
    h=hashlib.sha256()
    for a in arrays:
        a=np.ascontiguousarray(a)
        h.update(json.dumps([a.dtype.str,a.shape],separators=(',',':')).encode()); h.update(a.tobytes())
    return h.hexdigest()


@dataclass(frozen=True)
class Features:
    keypoints: np.ndarray
    descriptors: np.ndarray
    scores: np.ndarray
    image_size: np.ndarray
    original_indices: np.ndarray

    def validate(self):
        n=len(self.keypoints)
        if self.keypoints.shape!=(n,2) or self.descriptors.shape!=(n,128) or self.scores.shape!=(n,):
            raise ValueError('Expected cached ALIKED Nx2 points, Nx128 descriptors, and N scores')
        if self.image_size.shape!=(2,) or np.any(self.image_size<=0): raise ValueError('Invalid original image_size')
        if self.original_indices.shape!=(n,) or self.original_indices.dtype.kind not in 'iu' or np.any(self.original_indices<0) or len(set(self.original_indices))!=n:
            raise ValueError('Original feature row identities must be unique nonnegative integers')
        for a in (self.keypoints,self.descriptors,self.scores,self.image_size):
            if not np.isfinite(a).all(): raise ValueError('Nonfinite feature tensor')
        if np.any(self.keypoints<0) or np.any(self.keypoints>=self.image_size): raise ValueError('Keypoints are not in source image pixels')
        return self

    def subset(self,budget):
        if type(budget) is not int or budget<1: raise ValueError('Budget must be positive')
        # Highest detector scores, deterministic original-row tie break; preserve original input order.
        indices=np.lexsort((self.original_indices,-self.scores))[:budget]
        indices=np.sort(indices)
        return Features(self.keypoints[indices],self.descriptors[indices],self.scores[indices],self.image_size.copy(),self.original_indices[indices]).validate()

    def digest(self): return digest_arrays(self.keypoints,self.descriptors,self.scores,self.image_size,self.original_indices)


def read_vkft(path):
    """Strict version-6 F32 decoder from pinned Spirula Features.h; refuses partial files."""
    data=memoryview(Path(path).read_bytes()); offset=0
    def take(n):
        nonlocal offset
        if n<0 or offset+n>len(data): raise ValueError('Truncated VKFT record')
        out=data[offset:offset+n];offset+=n;return out
    def number(fmt): return struct.unpack(fmt,take(struct.calcsize(fmt)))[0]
    if bytes(take(4))!=b'VKFT': raise ValueError('Not a VKFT feature archive')
    version,width,height,count,dim,dtype=struct.unpack('<6I',take(24))
    if version!=6 or dtype!=1 or dim!=128 or not 0<count<=1_000_000 or min(width,height)<1:
        raise ValueError('Only bounded VKFT v6 F32 ALIKED features are supported')
    points=np.frombuffer(take(count*16),dtype='<f4').reshape(count,4)[:,:2].copy()
    descriptors=np.frombuffer(take(count*dim*4),dtype='<f4').reshape(count,dim).copy()
    colors=number('<B')
    if colors not in (0,1): raise ValueError('Invalid VKFT colors flag')
    if colors: take(count*3)
    number('<d'); camera_len=number('<I');take(camera_len)
    take(8)  # extraction size is not the coordinate system of these keypoints
    has_scores=number('<B')
    if has_scores!=1: raise ValueError('Detector scores required for a fair cached-budget comparison')
    scores=np.frombuffer(take(count*4),dtype='<f4').copy()
    orientation=number('<B')
    if orientation not in range(1,9) or offset!=len(data): raise ValueError('Invalid VKFT suffix or trailing bytes')
    return Features(points,descriptors,scores,np.array([width,height],dtype=np.int64),np.arange(count,dtype=np.int64)).validate()


def read_features(path):
    path=Path(path)
    if path.suffix.lower()=='.npz':
        with np.load(path,allow_pickle=False) as d:
            return Features(*(d[k].copy() for k in ('keypoints','descriptors','scores','image_size','original_indices'))).validate()
    return read_vkft(path)


def load_manifest(path):
    path=Path(path); manifest=json.loads(path.read_text(encoding='utf-8')); features={}
    for image_id,spec in manifest['features'].items():
        if spec.get('split') not in ('train','eval'): raise ValueError('Feature train/eval provenance is required')
        for key in ('sha256','source_sha256'):
            if not re.fullmatch('[0-9a-f]{64}',spec.get(key,'')): raise ValueError('Feature/source SHA-256 provenance required')
        file=(path.parent/spec['path']).resolve()
        if sha_file(file)!=spec['sha256']: raise ValueError('Cached feature file hash mismatch: '+image_id)
        features[image_id]=read_features(file)
    pairs=manifest['pairs']; seen=set();ids=set()
    if not pairs: raise ValueError('No benchmark pairs')
    for p in pairs:
        endpoints=(p['image0'],p['image1']); unordered=tuple(sorted(endpoints))
        if endpoints[0]==endpoints[1] or any(i not in features for i in endpoints) or unordered in seen or p['id'] in ids:
            raise ValueError('Unknown, self, duplicated or ambiguously identified pair')
        if not p.get('stratum'): raise ValueError('Each pair needs a coverage stratum')
        seen.add(unordered);ids.add(p['id'])
    return manifest,features


def pair_digest(pair,left,right):
    h=hashlib.sha256(json.dumps([pair['id'],pair['image0'],pair['image1']],separators=(',',':')).encode())
    h.update(left.digest().encode());h.update(right.digest().encode());return h.hexdigest()


def map_matches(matches,scores,left,right):
    matches=np.asarray(matches);scores=np.asarray(scores)
    if matches.ndim!=2 or matches.shape[1]!=2 or matches.dtype.kind not in 'iu' or scores.shape!=(len(matches),):
        raise ValueError('Malformed matcher result')
    if not np.isfinite(scores).all() or np.any(matches<0) or np.any(matches[:,0]>=len(left.keypoints)) or np.any(matches[:,1]>=len(right.keypoints)):
        raise ValueError('Matcher returned an invalid feature index or score')
    if len(set(matches[:,0]))!=len(matches) or len(set(matches[:,1]))!=len(matches): raise ValueError('Matcher result is not one-to-one')
    return np.column_stack([left.original_indices[matches[:,0]],right.original_indices[matches[:,1]]]).astype(np.int64)


def gpu_idle_guard(allow_gpu,device='cuda',max_util=10,min_free_mib=4000,allow_background_pids=()):
    if not device.startswith('cuda'): return {'device':device,'gpu_checked':False}
    if not allow_gpu: raise RuntimeError('GPU execution requires explicit --allow-gpu')
    index=int(device.split(':')[1]) if ':' in device else 0
    try:
        result=subprocess.run(['nvidia-smi',f'--id={index}','--query-gpu=utilization.gpu,memory.free','--format=csv,noheader,nounits'],check=True,capture_output=True,text=True,timeout=10)
        util,free=[int(x.strip()) for x in result.stdout.strip().split(',')]
        compute=subprocess.run(['nvidia-smi',f'--id={index}','--query-compute-apps=pid','--format=csv,noheader,nounits'],check=True,capture_output=True,text=True,timeout=10)
    except (OSError,ValueError,subprocess.SubprocessError) as error: raise RuntimeError('Cannot verify GPU availability; benchmark refused') from error
    present={int(line.strip()) for line in compute.stdout.splitlines() if line.strip().isdigit()}
    allowed=set(allow_background_pids)
    if any(type(pid) is not int or pid<1 for pid in allowed):raise ValueError('Background PID allowlist must contain positive integers')
    if util>max_util or free<min_free_mib or present-allowed:
        raise RuntimeError(f'GPU busy or insufficient free memory: utilization={util}%, free={free} MiB; stop competing work first')
    return {'device':device,'utilization_percent':util,'free_mib':free,'unknown_compute_apps':0,
            'explicitly_allowed_background_pids':sorted(present&allowed),'scope':'Preflight snapshot, not an exclusive GPU lock; Windows WDDM reports desktop graphics applications here too.'}


class LightGlueBackend:
    def __init__(self,weights,device,depth,width,flash=True):
        import torch
        from lightglue import LightGlue
        self.torch=torch;self.device=device
        torch.set_num_threads(1)
        # features=None prevents a hidden network download; require complete local ALIKED weights.
        self.model=LightGlue(features=None,input_dim=128,weights=None,depth_confidence=depth,width_confidence=width,flash=flash,mp=False).eval()
        state=torch.load(weights,map_location='cpu',weights_only=True)
        for i in range(self.model.conf.n_layers):
            state={k.replace(f'self_attn.{i}',f'transformers.{i}.self_attn').replace(f'cross_attn.{i}',f'transformers.{i}.cross_attn'):v for k,v in state.items()}
        missing,unexpected=self.model.load_state_dict(state,strict=False)
        # This buffer is generated deterministically by the upstream constructor,
        # not a learned head; official v0.1_arxiv weights omit it.
        learned_missing=set(missing)-{'confidence_thresholds'}
        if learned_missing or unexpected: raise ValueError(f'Incomplete/incompatible LightGlue weights: missing={sorted(learned_missing)}, unexpected={unexpected}')
        self.model=self.model.to(device)
        self.info={'torch':torch.__version__,'cuda_build':torch.version.cuda,'weights_sha256':sha_file(weights),
                   'depth_confidence':depth,'width_confidence':width,'flash':flash,'mp':False,'compile':False,'cpu_threads':1,
                   'constructor_generated_buffers':missing,
                   'lightglue_source_sha256':sha_file(importlib.import_module('lightglue.lightglue').__file__)}
    def sync(self):
        if self.device.startswith('cuda'): self.torch.cuda.synchronize(self.device)
    def match(self,left,right):
        t=self.torch
        def tensor(f):return {k:t.from_numpy(np.ascontiguousarray(getattr(f,k),dtype=np.float32)).unsqueeze(0).to(self.device) for k in ('keypoints','descriptors','image_size')}
        with t.inference_mode(): result=self.model({'image0':tensor(left),'image1':tensor(right)})
        self.sync()
        return result['matches'][0].cpu().numpy(),result['scores'][0].cpu().numpy(),{'layers':int(result['stop'])}
    def fixed_match(self,left,right):
        depth,width=self.model.conf.depth_confidence,self.model.conf.width_confidence
        try:
            self.model.conf.depth_confidence=-1.;self.model.conf.width_confidence=-1.
            return self.match(left,right)
        finally:self.model.conf.depth_confidence=depth;self.model.conf.width_confidence=width
    def close(self):
        del self.model
        if self.device.startswith('cuda'): self.torch.cuda.empty_cache()


class CommandBackend:
    """Adapter argv must contain {input}, {output}; result NPZ echoes pair_digest.

    Output fields: matches (indices in supplied tensors), scores, pair_digest.
    Process wall time includes startup/serialization, explicitly not kernel time.
    """
    def __init__(self,command,timeout=120):
        if not isinstance(command,list) or not all(isinstance(x,str) for x in command) or not all(any('{'+key+'}' in x for x in command) for key in ('input','output')):
            raise ValueError('Command adapter requires argv placeholders {input} and {output}')
        self.command=command;self.timeout=timeout;self.digest='';self.info={'backend':'external-command','timing_scope':'Process, file I/O and matching'}
    def sync(self): pass
    def match(self,left,right):
        with tempfile.TemporaryDirectory(prefix='rumah-match-') as tmp:
            inp=Path(tmp)/'pair.npz';out=Path(tmp)/'matches.npz'
            arrays={f'{name}{i}':getattr(f,name) for i,f in enumerate((left,right)) for name in ('keypoints','descriptors','scores','image_size','original_indices')}
            np.savez(inp,**arrays,pair_digest=np.array(self.digest))
            argv=[s.replace('{input}',str(inp)).replace('{output}',str(out)) for s in self.command]
            subprocess.run(argv,check=True,capture_output=True,timeout=self.timeout)
            with np.load(out,allow_pickle=False) as result:
                if str(result['pair_digest'].item())!=self.digest: raise ValueError('External matcher did not echo exact input identity')
                return result['matches'].copy(),result['scores'].copy(),{}
    def close(self): pass


def verify_geometry(left,right,matches,cam0,cam1,max_error=4.0):
    import pycolmap as pc
    if len(matches)<8: return {'inliers':0,'configuration':'insufficient_matches','occupied_cells':[0,0]}
    cameras=[pc.Camera(model=c['model'],width=c['width'],height=c['height'],params=c['params']) for c in (cam0,cam1)]
    # Some perspective fisheye APIs do not invert rays beyond 90 degrees.
    # Exclude those matches identically for every backend; retain all raw matches.
    usable=np.ones(len(matches),dtype=bool)
    for i,(camera,features) in enumerate(zip(cameras,(left,right))):
        xy=features.keypoints[matches[:,i]].astype(float)
        rays=np.asarray(camera.cam_ray_from_img(xy))
        back=np.asarray(camera.img_from_cam(rays,check_cheirality=False))
        residual=np.linalg.norm(back-xy,axis=1)
        usable &= np.isfinite(rays).all(axis=1)&np.isfinite(residual)&(residual<=.05)
    excluded=int((~usable).sum());matches=matches[usable]
    if len(matches)<8:return {'inliers':0,'configuration':'insufficient_invertible_matches','occupied_cells':[0,0],'excluded_noninvertible_rays':excluded}
    result=pc.estimate_calibrated_two_view_geometry(cameras[0],left.keypoints.astype(float),cameras[1],right.keypoints.astype(float),matches.astype(np.uint32),
        {'min_num_inliers':15,'compute_relative_pose':True,'ransac':{'max_error':max_error,'random_seed':0,'num_threads':1}})
    inliers=np.asarray(result.inlier_matches).reshape(-1,2)
    cells=[]
    for i,f in enumerate((left,right)):
        xy=f.keypoints[inliers[:,i].astype(int)]/f.image_size if len(inliers) else np.empty((0,2))
        cells.append(len(set(map(tuple,np.floor(xy*4).astype(int)))))
    return {'inliers':len(inliers),'configuration':str(result.config),'occupied_cells':cells,'max_error_source_pixels':max_error,
            'excluded_noninvertible_rays':excluded,'bearing_roundtrip_max_error_px':.05,
            'verifier':'PyCOLMAP calibrated two-view; not claimed identical to Spirula verifier'}


def angular_error_threshold(left,right,cam0,cam1,max_error=4.0):
    """One threshold from the original full feature pools, shared by every arm."""
    import pycolmap as pc
    from .localization import NativeCamera
    maximum=0.
    for spec,features in zip((cam0,cam1),(left,right)):
        camera=NativeCamera(spec,pc.Camera(model=spec['model'],width=spec['width'],height=spec['height'],params=spec['params']))
        xy=features.keypoints.astype(float);rays=np.asarray(camera.cam_ray_from_img(xy));jac=np.empty((len(xy),3,2));eps=.05
        for axis in range(2):
            shifted=xy.copy();shifted[:,axis]+=eps
            jac[:,:,axis]=(np.asarray(camera.cam_ray_from_img(shifted))-rays)/eps
        valid=np.isfinite(jac).all(axis=(1,2))
        if np.any(valid):maximum=max(maximum,float(np.max(np.linalg.svd(jac[valid],compute_uv=False))))
    if not maximum>0:raise ValueError('No finite calibrated feature rays for pair threshold')
    return max_error*maximum*1.1


def verify_full_sphere_geometry(left,right,matches,cam0,cam1,max_error=4.0,angular_threshold_rad=None):
    """Essential geometry on exact native bearings, including rear-facing KB4 rays.

    Spherical pixels are only an estimator interface. No images are resampled.
    The threshold derives from local native-pixel bearing Jacobians and is
    reported in angular units; this is not a final room/pose acceptance gate.
    """
    import pycolmap as pc
    from .localization import NativeCamera
    if not hasattr(pc.CameraModelId,'EQUIRECTANGULAR'):raise RuntimeError('Full-sphere verifier requires PyCOLMAP spherical camera support')
    if len(matches)<8:return {'inliers':0,'configuration':'insufficient_matches','occupied_cells':[0,0]}
    rays=[];valid=np.ones(len(matches),bool);max_amplification=0.
    for i,(spec,features) in enumerate(zip((cam0,cam1),(left,right))):
        camera=NativeCamera(spec,pc.Camera(model=spec['model'],width=spec['width'],height=spec['height'],params=spec['params']))
        xy=features.keypoints[matches[:,i]].astype(float);ray=np.asarray(camera.cam_ray_from_img(xy));back=np.asarray(camera.img_from_cam(ray,check_cheirality=False))
        good=np.isfinite(ray).all(axis=1)&np.isfinite(back).all(axis=1)&(np.linalg.norm(back-xy,axis=1)<=.05)
        jac=np.empty((len(xy),3,2));eps=.05
        for axis in range(2):
            shifted=xy.copy();shifted[:,axis]+=eps
            jac[:,:,axis]=(np.asarray(camera.cam_ray_from_img(shifted))-ray)/eps
        good &= np.isfinite(jac).all(axis=(1,2))
        if np.any(good):max_amplification=max(max_amplification,float(np.max(np.linalg.svd(jac[good],compute_uv=False))))
        valid &= good;rays.append(ray)
    excluded=int((~valid).sum());matches=matches[valid];rays=[r[valid] for r in rays]
    if len(matches)<8:return {'inliers':0,'configuration':'insufficient_calibrated_rays','occupied_cells':[0,0],'excluded_outside_calibration':excluded}
    spherical=pc.Camera(model='EQUIRECTANGULAR',width=4096,height=2048,params=[4096,2048])
    angular=angular_error_threshold(left,right,cam0,cam1,max_error) if angular_threshold_rad is None else float(angular_threshold_rad)
    if not np.isfinite(angular) or not 0<angular<np.pi/2:raise ValueError('Invalid angular verification threshold')
    threshold=angular/spherical.cam_from_img_threshold(1.)
    result=pc.estimate_essential_matrix(spherical.img_from_cam(rays[0]),spherical.img_from_cam(rays[1]),spherical,spherical,
        {'max_error':threshold,'random_seed':0,'num_threads':1,'max_num_trials':10000})
    report={'verifier':'PyCOLMAP full-sphere essential pose on exact native KB4 bearings',
        'excluded_outside_calibration':excluded,'negative_native_z_matches':int(np.sum((rays[0][:,2]<0)|(rays[1][:,2]<0))),
        'angular_threshold_degrees':float(np.degrees(angular)),'native_pixel_proposal_threshold':max_error,
        'threshold_basis':'Maximum native-pixel bearing amplification in the original full cached feature pool times pixel threshold and 1.1 safety factor; fixed for the pair across methods and budgets.'}
    if result is None:return {**report,'inliers':0,'configuration':'estimation_failed','occupied_cells':[0,0]}
    mask=np.asarray(result['inlier_mask'],bool)
    if mask.shape!=(len(matches),):raise ValueError('Invalid full-sphere inlier mask')
    E=np.asarray(result['E']);normal1=rays[1]@E;normal2=rays[0]@E.T
    numerator=np.abs(np.sum(rays[1]*normal2,axis=1))
    denominator=np.minimum(np.linalg.norm(normal1,axis=1),np.linalg.norm(normal2,axis=1))
    error=np.arcsin(np.clip(np.divide(numerator,denominator,out=np.ones(len(matches)),where=denominator>1e-12),0,1))
    mask &= np.isfinite(error)&(error<=angular)
    cells=[]
    for i,f in enumerate((left,right)):
        xy=f.keypoints[matches[mask,i]]/f.image_size
        cells.append(len(set(map(tuple,np.floor(xy*4).astype(int)))))
    return {**report,'inliers':int(mask.sum()),'configuration':'calibrated_full_sphere','occupied_cells':cells,
        'p95_angular_epipolar_degrees':float(np.degrees(np.percentile(error[mask],95))) if np.any(mask) else None}


def run_benchmark(manifest_path,output,*,execute=False,device='cpu',allow_gpu=False,weights=None,arms=None,repeats=2,warmup=2,seed=7,command=None,max_util=10,allow_background_pids=(),fallback_mode='none',min_verified_inliers=15,min_inlier_cells=4):
    start=time.perf_counter();manifest,features=load_manifest(manifest_path)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    arms=list(arms or ARMS)
    if any(arm not in ARMS for arm in arms) or len(set(arms))!=len(arms) or repeats<1 or warmup<0: raise ValueError('Invalid benchmark arms or repeat counts')
    if command is not None and arms!=['fixed4096']:
        raise ValueError('An external backend must use --arms fixed4096; this adapter cannot enable or certify its adaptivity')
    if fallback_mode not in ('none','protected','all-weak') or min_verified_inliers<1 or not 1<=min_inlier_cells<=16:raise ValueError('Invalid fallback policy or gates')
    if fallback_mode!='none' and (command is not None or arms!=['adaptive4096']):
        raise ValueError('Hybrid fallback requires only adaptive4096; critical edges must never be halved to 2048')
    pairs=manifest['pairs'];pair_identity=hashlib.sha256(json.dumps(pairs,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    plan={'schema':'rumah-matcher-benchmark-v1','manifest_sha256':sha_file(manifest_path),'pair_list_sha256':pair_identity,'pairs':len(pairs),'arms':{},
          'device':device,'repeats':repeats,'warmup_per_arm':warmup,'seed':seed,'executed':False,
          'fallback_policy':{'mode':fallback_mode,'min_verified_inliers':min_verified_inliers,'min_inlier_cells':min_inlier_cells,'gate_status':'Pilot thresholds, not validated reconstruction acceptance'},
          'scope':'Cached ALIKED descriptors only; no new extraction, poses or model quality claim. 2048 is cached truncation.',
          'input_provenance':manifest['features']}
    selected={}
    for arm in arms:
        selected[arm]={k:v.subset(ARMS[arm][0]) for k,v in features.items()}
        plan['arms'][arm]={'budget':ARMS[arm][0],'pair_tensors':{p['id']:pair_digest(p,selected[arm][p['image0']],selected[arm][p['image1']]) for p in pairs}}
    (output/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    if not execute:return plan
    resource=gpu_idle_guard(allow_gpu,device,max_util=max_util,allow_background_pids=allow_background_pids)
    if command is None and (weights is None or not Path(weights).is_file()): raise ValueError('Local complete ALIKED-LightGlue weights required; no automatic download')
    # Randomized arm order per round avoids always giving one method the warm GPU.
    rng=random.Random(seed);records=[];loads=[]
    thresholds={}
    for p in pairs:
        specs=[manifest['features'][p[k]] for k in ('image0','image1')]
        if all('camera' in s for s in specs):
            thresholds[p['id']]=angular_error_threshold(features[p['image0']],features[p['image1']],specs[0]['camera'],specs[1]['camera'],manifest.get('verification_max_error_px',4.0))
    for round_id in range(repeats):
        order=arms.copy();rng.shuffle(order)
        for arm in order:
            tick=time.perf_counter()
            backend=CommandBackend(command) if command else LightGlueBackend(weights,device,ARMS[arm][1],ARMS[arm][2])
            backend.sync();load=time.perf_counter()-tick
            try:
                p=pairs[0];left=selected[arm][p['image0']];right=selected[arm][p['image1']]
                backend.digest=plan['arms'][arm]['pair_tensors'][p['id']]
                tick=time.perf_counter()
                for _ in range(warmup):backend.match(left,right)
                backend.sync();warm=time.perf_counter()-tick
                loads.append({'round':round_id,'arm':arm,'load_seconds':load,'warmup_seconds':warm,'backend':backend.info})
                shuffled=pairs.copy();rng.shuffle(shuffled)
                for p in shuffled:
                    left=selected[arm][p['image0']];right=selected[arm][p['image1']];identity=plan['arms'][arm]['pair_tensors'][p['id']]
                    backend.digest=identity;backend.sync();pipeline_start=time.perf_counter();tick=pipeline_start
                    matches,scores,extra=backend.match(left,right);backend.sync();elapsed=time.perf_counter()-tick
                    original=map_matches(matches,scores,left,right)
                    filename=f'matches-{len(records):05d}.npz';np.savez(output/filename,matches=original,scores=scores,pair_digest=np.array(identity))
                    record={'round':round_id,'arm':arm,'pair':p['id'],'stratum':p['stratum'],'pair_digest':identity,'seconds':elapsed,
                            'matches':len(original),'feature_counts':[len(left.keypoints),len(right.keypoints)],'file':filename,**extra}
                    specs=[manifest['features'][p[k]] for k in ('image0','image1')]
                    if all('camera' in s for s in specs):
                        tick=time.perf_counter();record['geometry']=verify_full_sphere_geometry(left,right,matches,specs[0]['camera'],specs[1]['camera'],manifest.get('verification_max_error_px',4.0),thresholds[p['id']]);record['verification_seconds']=time.perf_counter()-tick
                    else:record['geometry']={'status':'not_run','reason':'No calibrated camera metadata; raw match count is not geometric success'}
                    decision=fallback_decision(p,arm,record['geometry'],fallback_mode,min_verified_inliers,min_inlier_cells)
                    record['fallback_decision']=decision
                    record['final_file']=filename;record['final_geometry']=record['geometry'];record['final_method']=arm
                    if decision['retry_fixed4096']:
                        if not all('camera' in s for s in specs):raise ValueError('Fallback requires calibrated geometric verification, never raw match scores')
                        backend.sync();tick=time.perf_counter();fm,fs,extra=backend.fixed_match(left,right);backend.sync();elapsed_fixed=time.perf_counter()-tick
                        mapped=map_matches(fm,fs,left,right);fixed_file=f'matches-{len(records):05d}-fallback-fixed4096.npz'
                        np.savez(output/fixed_file,matches=mapped,scores=fs,pair_digest=np.array(identity))
                        tick=time.perf_counter();fg=verify_full_sphere_geometry(left,right,fm,specs[0]['camera'],specs[1]['camera'],manifest.get('verification_max_error_px',4.0),thresholds[p['id']]);verify_seconds=time.perf_counter()-tick
                        record['fallback_attempt']={'method':'fixed4096','seconds':elapsed_fixed,'verification_seconds':verify_seconds,'matches':len(mapped),'file':fixed_file,'geometry':fg,**extra}
                        def rank(g):return (not quality_failures(g,min_verified_inliers,min_inlier_cells),g.get('inliers',0),min(g.get('occupied_cells',[0,0])))
                        if rank(fg)>rank(record['geometry']):record.update(final_file=fixed_file,final_geometry=fg,final_method='fixed4096')
                        record['final_choice_reason']='fixed_recovered_quality_gate' if not quality_failures(fg,min_verified_inliers,min_inlier_cells) else 'fallback_still_weak_keep_best_verified_support'
                    else:record['final_choice_reason']=decision['reason']
                    record['edge_passes_pilot_gate']=not quality_failures(record['final_geometry'],min_verified_inliers,min_inlier_cells)
                    record['pipeline_seconds']=time.perf_counter()-pipeline_start
                    records.append(record)
                    with (output/'records.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,allow_nan=False)+'\n')
            finally:backend.close()
    summaries={}
    for arm in arms:
        values=[r['seconds'] for r in records if r['arm']==arm]
        chosen=[r for r in records if r['arm']==arm]
        summaries[arm]={'timed_pairs':len(values),'total_matching_seconds':sum(values),'median_seconds':float(np.median(values)),'p95_seconds':float(np.percentile(values,95)),
                       'fallback_attempts':sum('fallback_attempt' in r for r in chosen),'fallback_matching_seconds':sum(r.get('fallback_attempt',{}).get('seconds',0) for r in chosen),
                       'total_pair_pipeline_seconds':sum(r['pipeline_seconds'] for r in chosen),'pairs_passing_pilot_gate':sum(r['edge_passes_pilot_gate'] for r in chosen)}
    result={**plan,'executed':True,'resource_preflight':resource,'loads':loads,'timings':summaries,'total_wall_seconds':time.perf_counter()-start,'pair_angular_thresholds_rad':thresholds,
            'timing_scope':'Pair includes host-to-device input transfer, matching, synchronization, and result transfer. Feature loading, model loading, warmup and verification reported separately.',
            'records':'records.jsonl','vulkan_comparison':'not performed' if command is None else 'External adapter result; identity check does not establish backend implementation equivalence.'}
    (output/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--run',action='store_true');p.add_argument('--device',default='cpu');p.add_argument('--allow-gpu',action='store_true');p.add_argument('--weights',type=Path)
    p.add_argument('--arms',nargs='+',choices=ARMS);p.add_argument('--repeats',type=int,default=2);p.add_argument('--warmup',type=int,default=2);p.add_argument('--seed',type=int,default=7)
    p.add_argument('--command-json',type=Path,help='JSON argv list for an external exact-pair adapter');p.add_argument('--max-gpu-util',type=int,default=10)
    p.add_argument('--allow-background-pid',type=int,nargs='*',default=[],help='Explicit audited desktop PID exceptions for WDDM; utilization/memory checks still apply')
    p.add_argument('--fallback-mode',choices=['none','protected','all-weak'],default='none');p.add_argument('--min-verified-inliers',type=int,default=15);p.add_argument('--min-inlier-cells',type=int,default=4)
    a=p.parse_args();result=run_benchmark(a.manifest,a.output,execute=a.run,device=a.device,allow_gpu=a.allow_gpu,weights=a.weights,arms=a.arms,repeats=a.repeats,warmup=a.warmup,seed=a.seed,
        command=json.loads(a.command_json.read_text()) if a.command_json else None,max_util=a.max_gpu_util,allow_background_pids=a.allow_background_pid,
        fallback_mode=a.fallback_mode,min_verified_inliers=a.min_verified_inliers,min_inlier_cells=a.min_inlier_cells)
    print(json.dumps({'executed':result['executed'],'pairs':result['pairs'],'output':str(a.output)}))


if __name__=='__main__':main()
