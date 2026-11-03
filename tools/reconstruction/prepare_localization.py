"""Bridge a fresh, un-compacted anchor model to fixed-map localization requests.

Only the nominated fresh model supplies 3D points/calibration. The old capture
cache supplies 2D matches, never poses or geometry. Exported COLMAP image IDs are
resolved by exact name, not assumed equal to either native VKMT image table.
NPZ anchor points are shared across requests; unneeded point tracks are skipped.
The pinned Spirula rigs.txt export is required. No factory-rig fallback exists.

python -m tools.reconstruction.prepare_localization --anchor-model .../sparse/0
  --staging-provenance .../staging-provenance.json --feature-root .../features
  --matches .../matches.bin --queries training-views.json --dataset .../dense
  --output .../localization-inputs [--eval-frames all|none|29,59]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path, PurePosixPath
import struct
import time

import numpy as np

from .capture import load_capture
from .localization import file_hash, matrix_pose
from .match_cache import read_index, resolve_image_names


CAMERA_MODELS={0:('SIMPLE_PINHOLE',3),1:('PINHOLE',4),2:('SIMPLE_RADIAL',4),
               3:('RADIAL',5),4:('OPENCV',8),5:('OPENCV_FISHEYE',8),
               6:('FULL_OPENCV',12),7:('FOV',5),8:('SIMPLE_RADIAL_FISHEYE',4),
               9:('RADIAL_FISHEYE',5),10:('THIN_PRISM_FISHEYE',12)}


def _read(f,n):
    data=f.read(n)
    if len(data)!=n:raise ValueError(f'Truncated binary record in {Path(f.name).name}')
    return data


def _skip(f,n,size):
    if n<0 or f.tell()+n>size:raise ValueError('Binary record extends past the file')
    f.seek(n,1)


def _fingerprint(path):
    s=Path(path).stat();return s.st_size,s.st_mtime_ns,s.st_ino


def _hash_stable(path):
    before=_fingerprint(path);digest=file_hash(path)
    if _fingerprint(path)!=before:raise ValueError('Input changed while hashing')
    return digest


def _name(value):
    p=PurePosixPath(value.replace('\\','/'))
    if not value or p.is_absolute() or '..' in p.parts or ':' in value or '\x00' in value:
        raise ValueError('Unsafe relative image identity')
    return p.as_posix()


def _under(root,name):
    root=Path(root).resolve();path=(root/_name(name)).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('Input escapes nominated root')
    return path


def _rotation(q):
    q=np.asarray(q,float)
    if q.shape!=(4,) or not np.isfinite(q).all() or not np.isclose(np.linalg.norm(q),1,atol=1e-6):raise ValueError('Invalid camera quaternion')
    w,x,y,z=q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def read_cameras(path):
    path=Path(path);before=_fingerprint(path);result={}
    with path.open('rb') as f:
        count=struct.unpack('<Q',_read(f,8))[0]
        if not 0<count<=10000:raise ValueError('Invalid camera count')
        for _ in range(count):
            ident,model,width,height=struct.unpack('<iiQQ',_read(f,24))
            if ident in result or ident<0 or model not in CAMERA_MODELS or min(width,height)<1:raise ValueError('Unsupported or malformed camera record')
            name,n=CAMERA_MODELS[model];params=struct.unpack('<'+'d'*n,_read(f,n*8))
            if not np.isfinite(params).all():raise ValueError('Nonfinite fixed calibration')
            result[ident]={'model':name,'width':width,'height':height,'params':list(params)}
        if f.read(1):raise ValueError('Trailing camera bytes')
    if _fingerprint(path)!=before:raise ValueError('Camera model changed while reading')
    return result


def read_images(path):
    path=Path(path);before=_fingerprint(path);size=before[0];result={};names=set()
    dtype=np.dtype([('xy','<f8',(2,)),('point_id','<i8')])
    with path.open('rb') as f:
        count=struct.unpack('<Q',_read(f,8))[0]
        if not 0<count<=100000:raise ValueError('Invalid image count')
        for _ in range(count):
            row=struct.unpack('<i7di',_read(f,64));name=bytearray()
            while True:
                byte=_read(f,1)
                if byte==b'\0':break
                name.extend(byte)
                if len(name)>16384:raise ValueError('Oversized image identity')
            name=_name(name.decode('utf-8'));n=struct.unpack('<Q',_read(f,8))[0]
            if row[0]<0 or row[0] in result or name in names or n>1000000 or n*24>size-f.tell():raise ValueError('Malformed image or feature-row table')
            observations=np.frombuffer(_read(f,n*24),dtype=dtype)
            pose=np.eye(4);pose[:3,:3]=_rotation(row[1:5]);pose[:3,3]=row[5:8];matrix_pose(pose)
            if not np.isfinite(observations['xy']).all() or np.any(observations['point_id']<-1):raise ValueError('Invalid feature observation')
            result[row[0]]={'name':name,'camera_id':row[8],'camera_from_world':pose,
                            'keypoints':observations['xy'].copy(),'point_ids':observations['point_id'].copy()};names.add(name)
        if f.read(1):raise ValueError('Trailing image bytes')
    if _fingerprint(path)!=before:raise ValueError('Image model changed while reading')
    return result


def read_feature_rows(path):
    """Read original pixel coordinates only; validate the rest by bounded seeks."""
    path=Path(path);before=_fingerprint(path);size=before[0]
    with path.open('rb') as f:
        magic,version,width,height,count,dim,dtype=struct.unpack('<4s6I',_read(f,28))
        if magic!=b'VKFT' or version!=6 or dtype!=1 or dim!=128 or not 0<count<=1000000 or min(width,height)<1:raise ValueError('Expected bounded VKFT v6 ALIKED features')
        xy=np.frombuffer(_read(f,count*16),dtype='<f4').reshape(count,4)[:,:2].copy()
        _skip(f,count*dim*4,size)
        flag=_read(f,1)[0]
        if flag not in (0,1):raise ValueError('Invalid feature color flag')
        if flag:_skip(f,count*3,size)
        _read(f,8);length=struct.unpack('<I',_read(f,4))[0];_skip(f,length,size);_read(f,8)
        scores=_read(f,1)[0]
        if scores not in (0,1):raise ValueError('Invalid feature score flag')
        if scores:_skip(f,count*4,size)
        if _read(f,1)[0] not in range(1,9) or f.read(1):raise ValueError('Malformed feature suffix')
    if _fingerprint(path)!=before or not np.isfinite(xy).all() or np.any(xy<0) or np.any(xy>=[width,height]):raise ValueError('Changed or invalid original feature rows')
    return xy,(width,height)


def read_rig(path,lenses):
    text=Path(path).read_text(encoding='utf-8')
    if 'cam_from_rig' not in text or 'in this model\'s units' not in text:raise ValueError('Unknown rig export convention; fresh calibrated model units required')
    members={};rigs=set();references=set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        p=line.split()
        if len(p)!=12 or p[1] in members:raise ValueError('Malformed or duplicate rig member')
        rigs.add(p[0]);references.add(p[2]);pose=np.eye(4);pose[:3,:3]=_rotation(list(map(float,p[3:7])));pose[:3,3]=list(map(float,p[7:10]));matrix_pose(pose)
        members[p[1]]=pose
    if len(rigs)!=1 or len(references)!=1 or set(members)!=set(lenses) or next(iter(references)) not in members:
        raise ValueError('Fresh model must contain one complete, explicit calibrated rig')
    reference=next(iter(references))
    if not np.allclose(members[reference],np.eye(4),atol=1e-8):raise ValueError('Reference rig member is not identity')
    return members,{'rig':next(iter(rigs)),'reference':reference,'source':'Fresh model rigs.txt; no factory or old-model fallback','units':'fresh anchor model units'}


def read_needed_points(path,needed,images,expected_tracks):
    """Read XYZ only for referenced points, validating their reciprocal tracks."""
    path=Path(path);before=_fingerprint(path);size=before[0];points={};track_rows=0
    with path.open('rb') as f:
        count=struct.unpack('<Q',_read(f,8))[0]
        if count>(size-8)//51:raise ValueError('Impossible point count')
        for _ in range(count):
            row=struct.unpack('<Q3d3BdQ',_read(f,51));ident=row[0];length=row[-1]
            if ident not in needed:_skip(f,length*8,size);continue
            if ident in points or not np.isfinite(row[1:4]).all() or not math.isfinite(row[7]):raise ValueError('Malformed needed anchor point')
            if length*8>size-f.tell():raise ValueError('Truncated point track')
            tracks=np.frombuffer(_read(f,length*8),dtype='<i4').reshape(-1,2);pairs=set(map(tuple,tracks.tolist()))
            if len(pairs)!=len(tracks) or not expected_tracks[ident].issubset(pairs):raise ValueError('Anchor point track does not confirm correspondence identity')
            for image_id,feature_id in pairs:
                image=images.get(image_id)
                if image is None or not 0<=feature_id<len(image['point_ids']) or int(image['point_ids'][feature_id])!=ident:
                    raise ValueError('Anchor point/image tracks are not reciprocal')
            points[ident]=np.array(row[1:4]);track_rows+=len(tracks)
        if f.read(1):raise ValueError('Trailing point bytes')
    if _fingerprint(path)!=before or set(points)!=set(needed):raise ValueError('Missing or changing fresh anchor points')
    return points,{'point_headers_scanned':count,'point_payloads_retained':len(points),'retained_track_rows':track_rows,'unneeded_tracks_skipped':True}


def _resolve_query_frames(capture,queries,eval_frames,frames):
    if queries.get('source_selection_sha256')!=capture['source_selection_sha256']:raise ValueError('Training-view selection belongs to a different capture')
    lookup={f['id']:f for f in capture['frames']};views={};wanted=set()
    for row in queries['views']:
        ident=row['frame_id'];lens=row['lens'];frame=lookup.get(ident)
        if frame is None or lens not in frame['images'] or row['image']!=frame['images'][lens] or row['split']!=frame['split'] or not math.isclose(row['time_seconds'],frame['time_seconds'],abs_tol=1e-7):raise ValueError('Training-view identity, split or timestamp mismatch')
        if (ident,lens) in views:raise ValueError('Duplicate training view')
        views[ident,lens]=row
        if row['split']=='train' and row.get('selected') and row['status'] in ('eligible_pending_pose','review_required'):wanted.add(ident)
    heldout={f['id'] for f in capture['frames'] if f['split']=='eval'}
    eval_ids=heldout if eval_frames=='all' else set() if eval_frames=='none' else {int(x) for x in eval_frames.split(',')}
    if not eval_ids.issubset(heldout):raise ValueError('Requested evaluation frames are not capture-held-out timestamps')
    wanted|=eval_ids
    if frames is not None:
        selected=set(frames)
        if not selected.issubset(wanted):raise ValueError('Explicit frame is not a selected appearance candidate or requested heldout')
        wanted=selected
    return [lookup[i] for i in sorted(wanted)],views


def prepare_requests(anchor_model,staging_provenance,feature_root,matches,queries,dataset,output,*,eval_frames='all',frames=None,min_correspondences=24,min_per_camera=6,include_raw=False,match_provenance=None,allow_reanchor=False):
    started=time.perf_counter();anchor_model=Path(anchor_model).resolve();feature_root=Path(feature_root).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    if min_correspondences<6 or min_per_camera<1:raise ValueError('Insufficient minimum correspondence gates')
    staging=json.loads(Path(staging_provenance).read_text(encoding='utf-8'));query_spec=json.loads(Path(queries).read_text(encoding='utf-8'))
    if staging.get('status')!='complete' or staging.get('featureCompactionPerformed') is not False or staging.get('resumeOldMapAllowed') is not False:raise ValueError('Explicit fresh, complete, uncompacted staging provenance is required')
    if '--no-compact-unused-features' not in staging.get('requiredAutoFlags',[]):raise ValueError('No-compaction provenance is missing')
    workspace=Path(staging['workspace']).resolve()
    if not anchor_model.is_relative_to(workspace):raise ValueError('Anchor model is outside the nominated fresh staging workspace')
    if Path(staging['sourceFeatureRoot']).resolve()!=feature_root:raise ValueError('Feature root differs from the preserved staging source')
    fresh_match_plan=None;fresh_match_report=None
    if allow_reanchor and match_provenance is None:raise ValueError('Explicit reanchoring requires complete fresh-match provenance')
    if match_provenance is not None:
        provenance_path=Path(match_provenance).resolve();fresh_match_report=json.loads(provenance_path.read_text())
        if fresh_match_report.get('schema')!='rumah-fresh-query-matching-result-v1' or fresh_match_report.get('status')!='complete' or fresh_match_report.get('old_match_cache_opened') is not False:
            raise ValueError('Fresh match provenance is incomplete or uses an old cache')
        if not include_raw or fresh_match_report.get('matches_sha256')!=_hash_stable(matches):raise ValueError('Fresh raw match identity/explicit opt-in is missing')
        run=json.loads((provenance_path.parent/'run.json').read_text());plan_path=Path(run['plan'])
        if run['identity']!=fresh_match_report['identity'] or _hash_stable(plan_path)!=run['identity']['plan_sha256']:
            raise ValueError('Fresh matching plan/result provenance mismatch')
        fresh_match_plan=json.loads(plan_path.read_text())
        same_model=(Path(fresh_match_plan['fresh_anchor_model']).resolve()==anchor_model and
                    all(_hash_stable(anchor_model/name)==digest for name,digest in fresh_match_plan['anchor_model_sha256'].items()))
        if not same_model and not allow_reanchor:raise ValueError('Fresh matches were proposed for a different anchor model; explicit --allow-reanchor required')
    capture=load_capture(dataset);lenses=sorted(capture['cameras']);frames,view_rows=_resolve_query_frames(capture,query_spec,eval_frames,frames)
    if fresh_match_plan is not None and fresh_match_plan['capture_selection_sha256']!=capture['source_selection_sha256']:
        raise ValueError('Fresh matches and current queries belong to different source captures')
    model_files=('cameras.bin','images.bin','points3D.bin','rigs.txt')
    model_before={name:_fingerprint(anchor_model/name) for name in model_files}
    calibration=read_cameras(anchor_model/'cameras.bin');images=read_images(anchor_model/'images.bin');members,rig_report=read_rig(anchor_model/'rigs.txt',lenses)
    cache=read_index(matches);model_names=[i['name'] for i in images.values()];missing_cache_anchors=[]
    if allow_reanchor:
        known={row.name for row in cache.images}
        missing_cache_anchors=[name for name in model_names if name not in known and str(PurePosixPath(name).with_suffix('')) not in known]
    cache_names=resolve_image_names(cache,[name for name in model_names if name not in set(missing_cache_anchors)])
    staged={r['name']:r for r in staging['images']}
    if len(staged)!=len(staging['images']):raise ValueError('Ambiguous staging image identities')
    name_to_capture={name:f for f in capture['frames'] for name in f['images'].values()}
    image_id_map=[];anchors={};lens_camera_ids=defaultdict(set);anchor_frames=defaultdict(dict)
    for image_id,image in images.items():
        name=image['name'];row=staged.get(name);frame=name_to_capture.get(name);lens=name.split('/')[0]
        if row is None or frame is None or lens not in lenses or frame['split']!='train':raise ValueError('Registered anchor is absent from fresh staging or is held out')
        feature=_under(feature_root,str(PurePosixPath(name).with_suffix('.bin')));xy,size=read_feature_rows(feature);original_id=cache_names.get(name)
        if (original_id is not None and len(xy)!=cache.images[original_id].num_features) or len(xy)!=len(image['keypoints']):raise ValueError('Feature compaction/count mismatch; original rows cannot be inferred')
        if not np.allclose(xy,image['keypoints'],rtol=0,atol=1e-5):raise ValueError('Original feature row coordinates do not match the fresh model')
        if _hash_stable(feature)!=row['feature']['sha256']:raise ValueError('Staged/source feature identity differs')
        if fresh_match_plan is not None and original_id is not None and fresh_match_plan['features'].get(name,{}).get('sha256')!=row['feature']['sha256']:
            raise ValueError('Fresh matcher did not use the exact anchor feature file')
        # Native image IDs belong to a particular match-cache table. A fresh
        # query-only table may assign different IDs; exact names and unchanged
        # original feature rows are the portable identity, never integer IDs.
        if original_id is not None and staging.get('sourceCache') and Path(staging['sourceCache']).resolve()==Path(matches).resolve():
            if row.get('originalImageId') is not None and row['originalImageId']!=original_id:raise ValueError('Native source image identity changed')
        camera=calibration.get(image['camera_id'])
        if camera is None or tuple(size)!=(camera['width'],camera['height']):raise ValueError('Fresh camera calibration does not describe source pixels')
        lens_camera_ids[lens].add(image['camera_id']);anchor_frames[frame['id']][lens]=image
        if original_id is not None:anchors[original_id]=(image_id,image)
        image_id_map.append({'name':name,'source_cache_image_id':original_id,'staged_original_cache_image_id':row.get('originalImageId'),
                             'staged_native_image_id':row['newImageId'],'anchor_colmap_image_id':image_id})
    if any(len(lens_camera_ids[lens])!=1 for lens in lenses):raise ValueError('Each physical lens needs one explicit fresh calibration')
    camera_specs=[{'id':lens,**calibration[next(iter(lens_camera_ids[lens]))],'cam_from_rig':members[lens].tolist()} for lens in lenses]
    anchor_poses=[];pending=[]
    for frame in frames:
        registered=anchor_frames.get(frame['id'],{})
        if set(registered)==set(lenses):
            anchor_poses.append({'frame_id':frame['id'],'time_seconds':frame['time_seconds'],'split':frame['split'],'status':'registered_anchor_not_relocalized',
                                 'images':dict(frame['images']),
                                 'appearance':{lens:{key:view_rows.get((frame['id'],lens),{}).get(key) for key in ('selected','status','regions')} for lens in lenses},
                                 'camera_from_world':{lens:image['camera_from_world'].tolist() for lens,image in registered.items()},'ready_for_training':False})
        else:pending.append(frame)
    query_names=[f['images'][lens] for f in pending for lens in lenses];query_ids=resolve_image_names(cache,query_names)
    links=defaultdict(list)
    query_set=set(query_ids.values())
    for pair in cache.pairs:
        if pair.config==0 and not include_raw:continue
        if pair.image1 in query_set and pair.image2 in anchors:links[pair.image1].append((pair,pair.image2,False))
        if pair.image2 in query_set and pair.image1 in anchors:links[pair.image2].append((pair,pair.image1,True))
    output.mkdir(parents=True);(output/'features').mkdir();(output/'requests').mkdir();(output/'correspondences').mkdir()
    report={'schema':'rumah-prepare-fixed-localization-v1','status':'preparing','fresh_anchor_model':str(anchor_model),
        'staging_provenance_sha256':_hash_stable(staging_provenance),'query_manifest_sha256':_hash_stable(queries),
        'source_selection_sha256':capture['source_selection_sha256'],'source_matches_sha256':_hash_stable(matches),
        'timing_kind':'reused-2D-matches-and-features-to-fresh-anchor-3D-correspondences; not fresh matching or localization',
        'old_dense_3d_opened':False,'fresh_points_only':True,'map_mutated':False,'rig':rig_report,'image_id_mapping':image_id_map,
        'match_cache_limitation':'VKMT binds names/counts, not per-feature hashes. Current original feature hashes are recorded; anchor rows are checked against fresh model coordinates.',
        'include_unverified_raw_matches':include_raw,'registered_anchors':anchor_poses,'queries':[]}
    if fresh_match_plan is not None:
        report.update(timing_kind='Fresh-query-match-cache to fixed fresh anchor correspondences; matching runtime reported separately',
            match_provenance_sha256=_hash_stable(match_provenance),matching_plan_sha256=fresh_match_report['identity']['plan_sha256'],
            match_cache_limitation='Every used feature hash is bound to the completed fresh matcher plan; raw correspondences still require pose validation.')
        report['reanchoring']={'explicitly_enabled':allow_reanchor,'matching_proposal_model':fresh_match_plan['fresh_anchor_model'],
            'matching_proposal_model_sha256':fresh_match_plan['anchor_model_sha256'],'current_fixed_model':str(anchor_model),
            'registered_anchor_images':len(images),'anchors_bound_to_match_cache':len(anchors),
            'anchors_absent_from_cache_and_skipped_for_edges':sorted(missing_cache_anchors),
            'original_matching_anchors_absent_from_current_map':sorted({row['name'] for row in fresh_match_plan['anchors']}-set(model_names)),
            'policy':'Existing raw original-index edges only; 3D points and calibration come exclusively from the current nominated model. Unmatched new anchors supply no invented edges.'}
    report_path=output/'preparation.json';report_path.write_text(json.dumps(report,indent=2))
    expected_tracks=defaultdict(set);needed=set();requests=[]
    try:
        with cache.path.open('rb') as stream:
            for frame in pending:
                votes=defaultdict(lambda:defaultdict(set));features={};pair_records=0
                for ci,lens in enumerate(lenses):
                    name=frame['images'][lens];qid=query_ids[name];feature=_under(feature_root,str(PurePosixPath(name).with_suffix('.bin')));xy,size=read_feature_rows(feature)
                    if len(xy)!=cache.images[qid].num_features or tuple(size)!=(camera_specs[ci]['width'],camera_specs[ci]['height']):raise ValueError('Query feature rows do not match source cache/calibration')
                    if fresh_match_plan is not None and fresh_match_plan['features'].get(name,{}).get('sha256')!=_hash_stable(feature):
                        raise ValueError('Fresh matcher did not use the exact query feature file')
                    features[lens]=(name,feature,xy)
                    for pair,anchor_id,reverse in links[qid]:
                        pair_records+=1;anchor_image_id,anchor_image=anchors[anchor_id];stream.seek(pair.offset)
                        rows=np.frombuffer(_read(stream,pair.count*8),dtype='<u4').reshape(-1,2)
                        if reverse:rows=rows[:,::-1]
                        if np.any(rows[:,0]>=len(xy)) or np.any(rows[:,1]>=len(anchor_image['point_ids'])):raise ValueError('Match cache feature row is out of range')
                        for query_feature,anchor_feature in rows:
                            pid=int(anchor_image['point_ids'][anchor_feature])
                            if pid>=0:votes[ci,int(query_feature)][pid].add((anchor_image_id,int(anchor_feature)))
                ambiguous=sum(len(points)!=1 for points in votes.values())
                unique={key:next(iter(points)) for key,points in votes.items() if len(points)==1};inverse=defaultdict(list)
                for key,pid in unique.items():inverse[key[0],pid].append(key)
                collisions={key for keys in inverse.values() if len(keys)>1 for key in keys}
                accepted=sorted((ci,fi,pid) for (ci,fi),pid in unique.items() if (ci,fi) not in collisions)
                counts=[sum(ci==i for ci,_,_ in accepted) for i in range(len(lenses))]
                entry={'frame_id':frame['id'],'time_seconds':frame['time_seconds'],'split':frame['split'],'correspondences':len(accepted),
                    'regions':sorted({region for lens in lenses for region in view_rows.get((frame['id'],lens),{}).get('regions',[])}),
                    'per_camera_correspondences':dict(zip(lenses,counts)),'anchor_match_records_reused':pair_records,
                    'ambiguous_query_features_removed':ambiguous,'same_camera_point_collisions_removed':len(collisions),'ready_for_training':False}
                if len(accepted)<min_correspondences or min(counts)<min_per_camera:
                    entry.update(status='insufficient_unambiguous_correspondences',request=None);report['queries'].append(entry);continue
                query_metadata=[]
                for lens in lenses:
                    name,feature,xy=features[lens];view=view_rows.get((frame['id'],lens),{})
                    safe=f'{lens}-{frame["id"]:06d}-{frame["split"]}.npz';target=output/'features'/safe
                    np.savez(target,keypoints=xy,original_indices=np.arange(len(xy),dtype=np.int64))
                    query_metadata.append({'camera_id':lens,'frame_id':frame['id'],'time_seconds':frame['time_seconds'],'split':frame['split'],
                        'source_name':name,'source_sha256':_hash_stable(_under(Path(dataset)/'images',name)),
                        'source_feature_sha256':_hash_stable(feature),'features':{'path':'../features/'+safe,'sha256':_hash_stable(target)},
                        'requested_for_training':frame['split']=='train' and view.get('selected',False),
                        'appearance_status':view.get('status','held_out_timestamp' if frame['split']=='eval' else 'rig_partner_only'),
                        'regions':view.get('regions',[]),
                        'ready_for_training':False})
                arr=np.asarray(accepted,dtype=np.int64);corr=output/'correspondences'/f'frame-{frame["id"]:06d}.npz'
                np.savez(corr,camera_idxs=arr[:,0],query_feature_ids=arr[:,1],point3D_ids=arr[:,2])
                for ci,fi,pid in accepted:needed.add(pid);expected_tracks[pid].update(votes[ci,fi][pid])
                request={'cameras':camera_specs,'queries':query_metadata,'correspondences':{'path':'../correspondences/'+corr.name,'sha256':_hash_stable(corr)},
                    'coordinate_frame':'Fresh anchor model frame; no normalization or factory baseline substitution',
                    'rig_extrinsics_units':'Same units as fresh anchor points','input_correspondence_mode':'existing_fresh_raw_edges_reanchored_to_current_map' if allow_reanchor else 'cached_2d_matches_to_fresh_anchor_tracks',
                    'preparation_report':'../preparation.json'}
                request_path=output/'requests'/f'frame-{frame["id"]:06d}.json';requests.append((request_path,request))
                entry.update(status='pending_fixed_map_pose_validation',request=str(request_path.relative_to(output)));report['queries'].append(entry)
        if _fingerprint(cache.path)[:2]!=(cache.fingerprint[2],cache.fingerprint[3]):raise ValueError('Match cache changed during preparation')
        if any(_fingerprint(anchor_model/name)!=state for name,state in model_before.items()):raise ValueError('Fresh anchor model changed during preparation')
        points,point_report=read_needed_points(anchor_model/'points3D.bin',needed,images,expected_tracks)
        point_ids=np.array(sorted(points),dtype=np.int64);xyz=np.array([points[int(i)] for i in point_ids],float).reshape(-1,3)
        anchor_archive=output/'anchors.npz';np.savez(anchor_archive,point_ids=point_ids,points3D=xyz);anchor_sha=_hash_stable(anchor_archive)
        model_hashes={name:_hash_stable(anchor_model/name) for name in model_files}
        if any(_fingerprint(anchor_model/name)!=state for name,state in model_before.items()):raise ValueError('Fresh anchor model changed during preparation')
        for path,request in requests:
            request['anchors']={'path':'../anchors.npz','sha256':anchor_sha}
            with path.open('x',encoding='utf-8') as f:json.dump(request,f,indent=2,allow_nan=False)
        report.update(status='complete',shared_anchor_points=len(points),point_scan=point_report,
            anchor_model_sha256=model_hashes,
            request_count=len(requests),skipped_registered_anchor_frames=len(anchor_poses),elapsed_seconds=time.perf_counter()-started)
        if 'reanchoring' in report:report['reanchoring']['current_fixed_model_sha256']=model_hashes
    except Exception as error:
        report.update(status='failed',error=str(error),elapsed_seconds=time.perf_counter()-started)
        report_path.write_text(json.dumps(report,indent=2,allow_nan=False));raise
    report_path.write_text(json.dumps(report,indent=2,allow_nan=False));return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('anchor-model','staging-provenance','feature-root','matches','queries','dataset','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--eval-frames',default='all');p.add_argument('--frames',type=int,nargs='*');p.add_argument('--include-raw-matches',action='store_true');p.add_argument('--match-provenance',type=Path);p.add_argument('--allow-reanchor',action='store_true')
    p.add_argument('--min-correspondences',type=int,default=24);p.add_argument('--min-per-camera',type=int,default=6)
    a=p.parse_args();result=prepare_requests(a.anchor_model,a.staging_provenance,a.feature_root,a.matches,a.queries,a.dataset,a.output,
        eval_frames=a.eval_frames,frames=a.frames,min_correspondences=a.min_correspondences,min_per_camera=a.min_per_camera,include_raw=a.include_raw_matches,match_provenance=a.match_provenance,allow_reanchor=a.allow_reanchor)
    print(json.dumps({key:result[key] for key in ('status','request_count','shared_anchor_points','elapsed_seconds')}))


if __name__=='__main__':main()
