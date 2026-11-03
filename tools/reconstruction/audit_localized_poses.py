"""Audit accepted localized poses against a reference, never treat it as truth.

Uses the SAME similarity already fit to common TRAIN anchors. Query/evaluation
poses do not refit the transform. Old 3D points are never read or used for PnP.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from .geometry_compare import read_pose_headers,distribution
from .localization import file_hash,matrix_pose
from .localize_batch import write_json


def pose_difference(pose,reference,similarity,span):
    pose=matrix_pose(pose);scale=float(similarity['scale']);q=np.asarray(similarity['rotation'],float);t=np.asarray(similarity['translation'],float)
    check=np.eye(4);check[:3,:3]=q;check[:3,3]=t;matrix_pose(check)
    if not np.isfinite(scale) or scale<=0 or not np.isfinite(span) or span<=0:raise ValueError('Invalid fixed similarity scale/span')
    center=-pose[:3,:3].T@pose[:3,3];difference=float(np.linalg.norm(scale*q@center+t-reference['center']))
    delta=reference['R']@(pose[:3,:3]@q.T).T
    angle=float(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1))))
    return {'center_difference_reference_units':difference,'center_difference_fraction_trajectory_span':difference/span,
            'orientation_difference_degrees':angle}


def audit(preparation,results,geometry_comparison,output,*,allow_partial=False):
    preparation=Path(preparation).resolve();results=Path(results).resolve();geometry_comparison=Path(geometry_comparison).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    prep=json.loads(preparation.read_text());comparison=json.loads(geometry_comparison.read_text());batch=json.loads((results/'batch.json').read_text())
    progress=json.loads((results/'progress.json').read_text())
    if prep.get('status')!='complete' or batch['identity']['preparation_sha256']!=file_hash(preparation):raise ValueError('Localization preparation/batch mismatch')
    if progress.get('status')!='complete' and not allow_partial:raise ValueError('Incomplete batch requires explicit partial inspection')
    if comparison.get('heldout_images_in_fit')!=0:raise ValueError('Agreement transform must not be fit to heldout poses')
    if comparison['inputs']['candidate_images']['sha256']!=prep['anchor_model_sha256']['images.bin']:
        raise ValueError('Similarity was not fitted using this fresh anchor model')
    reference_spec=comparison['inputs']['reference_images'];reference_path=Path(reference_spec['path'])
    if file_hash(reference_path)!=reference_spec['sha256']:raise ValueError('Reference camera poses changed after similarity fitting')
    reference=read_pose_headers(reference_path);rows=[];missing=[];groups=defaultdict(list)
    for prepared in prep['queries']:
        if not prepared['request']:continue
        path=results/'results'/f'frame-{prepared["frame_id"]:06d}.json'
        if not path.exists():continue
        result=json.loads(path.read_text());request_path=preparation.parent/prepared['request']
        if result.get('request_sha256')!=file_hash(request_path):raise ValueError('Result does not match its localization request')
        if not result.get('accepted'):continue
        if result.get('execution_status')!='complete' or result.get('map_mutated'):raise ValueError('Invalid accepted localization provenance')
        request=json.loads(request_path.read_text());poses=result['camera_from_world']
        if len(poses)!=len(request['cameras']):raise ValueError('Incomplete accepted rig poses')
        by_id={str(camera['id']):pose for camera,pose in zip(request['cameras'],poses)}
        for query in request['queries']:
            name=query['source_name']
            if name not in reference:missing.append(name);continue
            difference=pose_difference(by_id[str(query['camera_id'])],reference[name],comparison['candidate_to_reference'],comparison['reference_trajectory_span'])
            row={'name':name,'frame_id':query['frame_id'],'lens':query['camera_id'],'split':query['split'],'regions':query.get('regions',[]),**difference}
            rows.append(row)
            for region in query.get('regions',[]) or ['unassigned']:groups[region,query['split']].append(row)
    def stats(items):
        return {field:distribution([row[field] for row in items]) for field in ('center_difference_reference_units','center_difference_fraction_trajectory_span','orientation_difference_degrees')}
    report={'schema':'rumah-localized-pose-agreement-v1','reference_is_ground_truth':False,'acceptance_passed':False,
        'scope':'Agreement diagnostic only; fixed transform inherited from common training anchors, no query/eval refit.',
        'old_geometry_used_for_localization':False,'old_point_cloud_opened':False,'heldout_images_in_similarity_fit':0,
        'units':'Arbitrary reference reconstruction units, not meters','compared_accepted_images':len(rows),
        'missing_reference_images':missing,'partial_batch':progress['status']!='complete',
        'candidate_to_reference':comparison['candidate_to_reference'],'reference_trajectory_span':comparison['reference_trajectory_span'],
        'overall':stats(rows),'per_region_split':[{'region':region,'split':split,**stats(items)} for (region,split),items in groups.items()],
        'per_image':rows,'inputs':{'preparation_sha256':file_hash(preparation),'batch_identity':batch['identity'],
            'geometry_comparison_sha256':file_hash(geometry_comparison),'reference_images':reference_spec}}
    output.parent.mkdir(parents=True,exist_ok=True);write_json(output,report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('preparation','results','geometry-comparison','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--allow-partial',action='store_true');a=p.parse_args();report=audit(a.preparation,a.results,a.geometry_comparison,a.output,allow_partial=a.allow_partial)
    print(json.dumps({'compared_accepted_images':report['compared_accepted_images'],'overall':report['overall']}))


if __name__=='__main__':main()
