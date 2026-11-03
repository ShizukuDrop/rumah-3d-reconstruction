"""Export legacy COLMAP poses plus an explicit quality-approved training whitelist.

Only cameras.bin/images.bin/points3D.bin enter sparse/0. No stale COLMAP frames or
rig files are copied. Fresh anchor observations and point tracks stay unchanged;
localized queries have original 2D rows but every point ID is -1. This export
does not triangulate, adjust poses, normalize coordinates, warp images, or train.

The downstream warper MUST consume training-whitelist.json and eval-whitelist.json.
The mere presence of an anchor image in images.bin does not authorize training.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import struct

import numpy as np

from .localization import file_hash, load_request, matrix_pose, AnchorLookupCache
from .localize_batch import write_json
from .prepare_localization import read_images, _rotation


def quaternion(rotation):
    r=np.asarray(rotation,dtype=float);q=np.empty(4);trace=np.trace(r)
    if trace>0:
        s=np.sqrt(trace+1)*2;q[:]=[s/4,(r[2,1]-r[1,2])/s,(r[0,2]-r[2,0])/s,(r[1,0]-r[0,1])/s]
    else:
        i=int(np.argmax(np.diag(r)));j=(i+1)%3;k=(i+2)%3;s=np.sqrt(1+r[i,i]-r[j,j]-r[k,k])*2
        q[0]=(r[k,j]-r[j,k])/s;q[i+1]=s/4;q[j+1]=(r[j,i]+r[i,j])/s;q[k+1]=(r[k,i]+r[i,k])/s
    if q[0]<0:q=-q
    q/=np.linalg.norm(q)
    if not np.allclose(_rotation(q),r,atol=1e-8):raise ValueError('Quaternion conversion changed pose')
    return q


def export_poses(preparation,results,queries,output,*,allow_partial=False):
    preparation=Path(preparation).resolve();results=Path(results).resolve();queries=Path(queries).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    prep=json.loads(preparation.read_text());batch=json.loads((results/'batch.json').read_text());progress=json.loads((results/'progress.json').read_text())
    if prep.get('status')!='complete' or batch['identity']['preparation_sha256']!=file_hash(preparation):raise ValueError('Prepared map/result identity mismatch')
    if progress.get('status')!='complete' and not allow_partial:raise ValueError('Batch is incomplete; use explicit partial export for inspection only')
    if file_hash(queries)!=prep['query_manifest_sha256']:raise ValueError('Appearance whitelist source differs from preparation')
    manifest=json.loads(queries.read_text());model=Path(prep['fresh_anchor_model'])
    for name,digest in prep['anchor_model_sha256'].items():
        if file_hash(model/name)!=digest:raise ValueError('Fresh anchor model changed after localization preparation')
    images=read_images(model/'images.bin');names={i['name'] for i in images.values()};lens_camera_ids={}
    poses={}
    for image_id,image in images.items():
        lens=image['name'].split('/')[0];lens_camera_ids.setdefault(lens,set()).add(image['camera_id'])
        if '_train.' not in image['name']:raise ValueError('Heldout source image is present in fresh anchor map')
        poses[image['name']]={'image_id':image_id,'source':'registered_fresh_anchor','camera_from_world':image['camera_from_world'].tolist()}
    if any(len(ids)!=1 for ids in lens_camera_ids.values()):raise ValueError('Ambiguous fixed lens calibration')
    next_id=max(images)+1;appended=[];outcomes=[];anchor_cache=AnchorLookupCache()
    for row in prep['queries']:
        result_path=results/'results'/f'frame-{row["frame_id"]:06d}.json'
        if not row['request'] or not result_path.exists():
            outcomes.append({'frame_id':row['frame_id'],'status':'not_localized'});continue
        result=json.loads(result_path.read_text());request_path=preparation.parent/row['request']
        if result.get('request_sha256')!=file_hash(request_path):raise ValueError('Localization result/request identity mismatch')
        if not result.get('accepted'):
            outcomes.append({'frame_id':row['frame_id'],'status':'rejected','reasons':result.get('rejection_reasons',[result.get('error','unknown')])});continue
        if result.get('execution_status')!='complete' or result.get('map_mutated') or result.get('intrinsics_refined') or result.get('rig_extrinsics_refined'):
            raise ValueError('Accepted localization lacks immutable-map execution provenance')
        request,*_=load_request(request_path,anchor_cache=anchor_cache);rig=matrix_pose(result['rig_from_world'])
        if len(result['camera_from_world'])!=len(request['cameras']):raise ValueError('Partial accepted camera poses')
        by_lens={str(q['camera_id']):q for q in request['queries']}
        for camera,pose in zip(request['cameras'],result['camera_from_world']):
            pose=matrix_pose(pose)
            if not np.allclose(matrix_pose(camera['cam_from_rig'])@rig,pose,atol=1e-8):raise ValueError('Accepted camera pose violates fixed rig')
            query=by_lens[str(camera['id'])];name=query['source_name']
            if name in names:
                if not np.allclose(poses[name]['camera_from_world'],pose,atol=1e-6):
                    raise ValueError('Partially registered pair conflicts with its existing anchor pose; explicit review required')
                continue
            if f'_{query["split"]}.' not in name:raise ValueError('Image name no longer preserves train/eval ownership')
            feature_path=(request_path.parent/query['features']['path']).resolve()
            with np.load(feature_path,allow_pickle=False) as f:xy=f['keypoints'].copy();original=f['original_indices'].copy()
            if not np.array_equal(original,np.arange(len(xy))):raise ValueError('Export requires uncompacted original feature rows')
            camera_id=next(iter(lens_camera_ids[str(camera['id'])]))
            record={'id':next_id,'name':name,'camera_id':camera_id,'pose':pose,'keypoints':xy};appended.append(record)
            poses[name]={'image_id':next_id,'source':'accepted_fixed_map_localization','camera_from_world':pose.tolist(),
                         'result_sha256':file_hash(result_path),'frame_id':query['frame_id'],'split':query['split']}
            names.add(name);next_id+=1
        outcomes.append({'frame_id':row['frame_id'],'status':'accepted'})
    whitelist=[];excluded=[];heldout=[]
    for view in manifest['views']:
        name=view['image'];pose=poses.get(name)
        if view['split']=='eval':
            if pose is not None:heldout.append({'image':name,'frame_id':view['frame_id'],'lens':view['lens'],'split':'eval','pose_source':pose['source']})
            continue
        if view.get('selected') and view['status']=='eligible_pending_pose' and pose is not None:
            whitelist.append({'image':name,'frame_id':view['frame_id'],'lens':view['lens'],'split':'train','regions':view.get('regions',[]),
                              'quality_status':'passed','pose_source':pose['source']})
        elif view.get('selected'):
            excluded.append({'image':name,'frame_id':view['frame_id'],'reason':'no_accepted_pose' if pose is None else view['status']})
    if set(r['image'] for r in whitelist)&set(r['image'] for r in heldout):raise ValueError('Train/eval whitelist overlap')
    sparse=output/'sparse/0';sparse.mkdir(parents=True)
    for name in ('cameras.bin','points3D.bin'):shutil.copyfile(model/name,sparse/name)
    with (model/'images.bin').open('rb') as source,(sparse/'images.bin').open('wb') as dest:
        source_count=struct.unpack('<Q',source.read(8))[0]
        if source_count!=len(images):raise ValueError('Anchor images changed during export')
        dest.write(struct.pack('<Q',len(images)+len(appended)));shutil.copyfileobj(source,dest,1024*1024)
        for record in appended:
            pose=record['pose'];xy=record['keypoints'];q=quaternion(pose[:3,:3])
            dest.write(struct.pack('<i7di',record['id'],*q,*pose[:3,3],record['camera_id']))
            dest.write(record['name'].encode('utf-8')+b'\0'+struct.pack('<Q',len(xy)))
            observations=np.empty(len(xy),dtype=[('xy','<f8',(2,)),('point_id','<i8')]);observations['xy']=xy;observations['point_id']=-1;dest.write(observations.tobytes())
    for name,digest in prep['anchor_model_sha256'].items():
        if file_hash(model/name)!=digest:raise ValueError('Fresh anchor model changed during export')
    for name in ('cameras.bin','points3D.bin'):
        if file_hash(sparse/name)!=prep['anchor_model_sha256'][name]:raise ValueError('Copied fixed model bytes changed')
    shutil.copyfile(model/'rigs.txt',output/'fresh-rig-calibration.txt')
    write_json(output/'training-whitelist.json',{'schema':'rumah-quality-pose-whitelist-v1','source_manifest_sha256':file_hash(queries),
        'requires_explicit_consumer_filter':True,'training_ready':False,'remaining_gate':'Fresh geometry and visual quality acceptance',
        'views':whitelist,'excluded_selected_views':excluded})
    write_json(output/'eval-whitelist.json',{'schema':'rumah-heldout-pose-whitelist-v1','split':'eval','views':heldout,
        'point_geometry_uses_eval_images':False,'pose_localization_uses_eval_pixels':True})
    report={'schema':'rumah-localized-pose-export-v1','preparation_sha256':file_hash(preparation),'batch_identity':batch['identity'],
        'partial_export':progress['status']!='complete','fresh_anchor_images':len(images),'accepted_query_images_appended':len(appended),
        'training_whitelisted_views':len(whitelist),'eval_whitelisted_views':len(heldout),'training_ready':False,
        'new_point_tracks':0,'bundle_adjustment':False,'triangulation':False,'normalization':False,
        'legacy_colmap_only':True,'frames_or_colmap_rigs_copied':False,
        'seed_geometry':'Unmodified fresh train-anchor points; query observations are unlinked (-1), including every eval query.',
        'consumer_requirement':'Apply the explicit train/eval whitelist before warping; presence in images.bin alone never permits training.',
        'outcomes':outcomes,'poses':poses,
        'shared_anchor_cache':anchor_cache.stats(),'export_code_sha256':file_hash(__file__),
        'export_sha256':{name:file_hash(sparse/name) for name in ('cameras.bin','images.bin','points3D.bin')}}
    write_json(output/'pose-manifest.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('preparation','results','queries','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--allow-partial',action='store_true');a=p.parse_args();report=export_poses(a.preparation,a.results,a.queries,a.output,allow_partial=a.allow_partial)
    print(json.dumps({key:report[key] for key in ('fresh_anchor_images','accepted_query_images_appended','training_whitelisted_views','eval_whitelisted_views')}))


if __name__=='__main__':main()
