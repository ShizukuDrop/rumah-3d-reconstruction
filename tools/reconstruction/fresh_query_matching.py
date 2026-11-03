"""Fresh query-to-anchor ALIKED/LightGlue matching, independent of old match caches.

Plan on CPU: python -m tools.reconstruction.fresh_query_matching plan
  --dataset .../dense --anchor-model .../sfm/sparse/0 --staging-provenance ...json
  --queries .../training-views.json --output .../fresh-query-plan
Match only with explicit execution: ... match --plan .../plan.json --output ...
  --run --device cuda:0 --allow-gpu --weights .../aliked_lightglue-complete.pth

The output VKMT is explicitly RAW (config=0). It must enter fixed-map rig PnP
through prepare_localization --include-raw-matches. No raw match count signifies
an accepted pose. Anchors are registered TRAIN images in the fresh model only.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import json
from pathlib import Path, PurePosixPath
import struct
import time

import numpy as np

from .capture import load_capture
from .localization import file_hash
from .localize_batch import write_json
from .matcher_benchmark import LightGlueBackend,gpu_idle_guard,read_vkft,map_matches,pair_digest
from .match_cache import read_index
from .prepare_localization import read_images,_resolve_query_frames,_under,_fingerprint


def propose_edges(queries,anchors,descriptors,*,before=2,after=2,retrieval=2,retrieval_exclusion_seconds=1.5):
    """No poses or old pair records are inputs. Retrieval can cross lens IDs."""
    if not all(type(n) is int and 0<=n<=2 for n in (before,after,retrieval)) or before+after+retrieval<1:
        raise ValueError('Use at most two before, two after and two retrieval anchors')
    if not np.isfinite(retrieval_exclusion_seconds) or retrieval_exclusion_seconds<0:raise ValueError('Invalid retrieval exclusion')
    query_names={q['name'] for q in queries};anchor_names={a['name'] for a in anchors}
    if len(query_names)!=len(queries) or len(anchor_names)!=len(anchors) or query_names&anchor_names:
        raise ValueError('Unique disjoint query and registered-anchor names are required')
    if any(a['split']!='train' for a in anchors):raise ValueError('Evaluation images cannot become anchors')
    if any(q['split'] not in ('train','eval') for q in queries):raise ValueError('Unknown query split')
    if any(not np.isfinite(row['time_seconds']) or row['time_seconds']<0 for row in queries+anchors):raise ValueError('Invalid source timestamp')
    if set(descriptors)!=(query_names|anchor_names):raise ValueError('Descriptor identities do not match candidate images')
    for vector in descriptors.values():
        if np.asarray(vector).shape!=(128,) or not np.isfinite(vector).all():raise ValueError('Invalid retrieval descriptor')
    rows=[]
    for query in sorted(queries,key=lambda r:(r['time_seconds'],r['name'])):
        same=[a for a in anchors if a['lens']==query['lens']]
        older=sorted((a for a in same if a['time_seconds']<query['time_seconds']),key=lambda a:(-a['time_seconds'],a['name']))[:before]
        newer=sorted((a for a in same if a['time_seconds']>query['time_seconds']),key=lambda a:(a['time_seconds'],a['name']))[:after]
        chosen={a['name']:(a,'time_before' if a['time_seconds']<query['time_seconds'] else 'time_after',None) for a in older+newer}
        candidates=[a for a in anchors if a['name'] not in chosen and abs(a['time_seconds']-query['time_seconds'])>=retrieval_exclusion_seconds]
        scores=[(float(np.dot(descriptors[query['name']],descriptors[a['name']])),a) for a in candidates]
        for score,anchor in sorted(scores,key=lambda r:(-r[0],r[1]['name']))[:retrieval]:
            chosen[anchor['name']]=(anchor,'descriptor_retrieval',score)
        for anchor,reason,score in chosen.values():
            rows.append({'id':f'pair-{len(rows):06d}','image0':query['name'],'image1':anchor['name'],
                'query_frame':query['frame_id'],'query_split':query['split'],'anchor_frame':anchor['frame_id'],
                'stratum':reason,'same_lens':query['lens']==anchor['lens'],'retrieval_score':score,
                'time_gap_seconds':abs(query['time_seconds']-anchor['time_seconds']),'regions':query.get('regions',[])})
    return rows


def _feature_header(path):
    with Path(path).open('rb') as stream:header=stream.read(28)
    if len(header)!=28:raise ValueError('Truncated native feature header')
    magic,version,width,height,count,dimension,dtype=struct.unpack('<4s6I',header)
    if magic!=b'VKFT' or version!=6 or dtype!=1 or dimension!=128 or not 0<count<=1000000 or min(width,height)<1:
        raise ValueError('Expected native VKFT v6 ALIKED feature identity')
    return count


def build_plan(dataset,anchor_model,staging_provenance,queries,output,*,eval_frames='all',frames=None,retrieval_exclusion_seconds=1.5):
    start=time.perf_counter();dataset=Path(dataset).resolve();anchor_model=Path(anchor_model).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    staging=json.loads(Path(staging_provenance).read_text());spec=json.loads(Path(queries).read_text())
    if staging.get('status')!='complete' or staging.get('featureCompactionPerformed') is not False or staging.get('resumeOldMapAllowed') is not False:
        raise ValueError('Fresh uncompacted staging is required')
    if '--no-compact-unused-features' not in staging.get('requiredAutoFlags',[]) or not anchor_model.is_relative_to(Path(staging['workspace']).resolve()):
        raise ValueError('Fresh model must belong to the nominated no-compaction workspace')
    feature_root=Path(staging['sourceFeatureRoot']).resolve();capture=load_capture(dataset)
    model_files=('cameras.bin','images.bin','points3D.bin','rigs.txt')
    model_before={name:_fingerprint(anchor_model/name) for name in model_files}
    selected,views=_resolve_query_frames(capture,spec,eval_frames,frames);registered=read_images(anchor_model/'images.bin')
    capture_by_name={name:{'name':name,'frame_id':frame['id'],'time_seconds':frame['time_seconds'],'split':frame['split'],'lens':lens}
        for frame in capture['frames'] for lens,name in frame['images'].items()}
    staged={row['name']:row for row in staging['images']};registered_by_name={r['name']:r for r in registered.values()}
    if any(name not in staged or name not in capture_by_name or capture_by_name[name]['split']!='train' for name in registered_by_name):
        raise ValueError('Every anchor must be a registered fresh training image')
    pending=[frame for frame in selected if not all(name in registered_by_name for name in frame['images'].values())]
    query_rows=[]
    for frame in pending:
        for lens,name in frame['images'].items():
            query_rows.append({**capture_by_name[name],'regions':views.get((frame['id'],lens),{}).get('regions',[])})
    query_names={row['name'] for row in query_rows}
    # A partially registered query pair may contain a known camera. Its image
    # remains a query role in this batch; it cannot create query-query edges.
    anchor_rows=[capture_by_name[name] for name in sorted(registered_by_name) if name not in query_names]
    if not query_rows or not anchor_rows:raise ValueError('No unregistered queries or independent registered anchors')
    image_table=[]
    # A cold selected-frame pipeline need only extract features for actual
    # anchors and appearance/eval queries, not every redundant capture frame.
    used_names={row['name'] for row in anchor_rows+query_rows}
    for ident,name in enumerate(sorted(used_names)):
        path=_under(feature_root,str(PurePosixPath(name).with_suffix('.bin')))
        image_table.append({'image_id':ident,'name':name,'cache_name':str(PurePosixPath(name).with_suffix('')),
                            'num_features':_feature_header(path)})
    table={row['name']:row for row in image_table};descriptors={};features={};feature_load=0.
    for record in anchor_rows+query_rows:
        name=record['name'];path=_under(feature_root,str(PurePosixPath(name).with_suffix('.bin')));tick=time.perf_counter();before=_fingerprint(path)
        data=read_vkft(path);digest=file_hash(path)
        if _fingerprint(path)!=before:raise ValueError('Feature file changed while preparing retrieval')
        if len(data.keypoints)!=table[name]['num_features']:raise ValueError('Feature count changed after indexing')
        if name in registered_by_name:
            anchor=registered_by_name[name]
            if len(data.keypoints)!=len(anchor['keypoints']) or not np.allclose(data.keypoints,anchor['keypoints'],rtol=0,atol=1e-5):
                raise ValueError('Fresh anchor feature row compaction/identity mismatch')
            if digest!=staged[name]['feature']['sha256']:raise ValueError('Anchor source feature hash differs from staging')
        vector=data.descriptors.mean(axis=0,dtype=np.float64);norm=np.linalg.norm(vector)
        if norm<=1e-12:raise ValueError('Zero retrieval descriptor')
        descriptors[name]=vector/norm
        features[name]={'path':str(path),'sha256':digest,'num_features':len(data.keypoints),'image_size':data.image_size.tolist(),
                        'split':record['split'],'frame_id':record['frame_id'],'lens':record['lens'],
                        'role':'query' if name in query_names else 'registered_train_anchor'}
        feature_load+=time.perf_counter()-tick
    pairs=propose_edges(query_rows,anchor_rows,descriptors,retrieval_exclusion_seconds=retrieval_exclusion_seconds)
    if not pairs:raise ValueError('No candidate query-anchor edges')
    model_hashes={name:file_hash(anchor_model/name) for name in model_files}
    if any(_fingerprint(anchor_model/name)!=state for name,state in model_before.items()):raise ValueError('Fresh anchor model changed while planning')
    plan={'schema':'rumah-fresh-query-matching-plan-v1','status':'ready','dataset':str(dataset),'fresh_anchor_model':str(anchor_model),
        'query_manifest_sha256':file_hash(queries),'capture_selection_sha256':capture['source_selection_sha256'],
        'staging_sha256':file_hash(staging_provenance),'anchor_model_sha256':model_hashes,
        'old_match_cache_opened':False,'old_dense_geometry_used':False,'fresh_feature_extraction':False,
        'matcher':'upstream ALIKED-LightGlue fixed4096','descriptor_budget':4096,'depth_confidence':-1.,'width_confidence':-1.,
        'retrieval':{'method':'L2-normalized mean of cached masked ALIKED descriptors; cosine similarity','same_lens_only':False,
                     'temporal_exclusion_seconds':retrieval_exclusion_seconds,'overlap_certified':False},
        'edge_budget':{'same_lens_before':2,'same_lens_after':2,'retrieval_across_both_lenses':2},
        'image_table_basis':'Deterministic sorted names of required registered anchors and requested queries, with native feature-header counts; unselected capture features and old match caches are not required',
        'image_table':image_table,'features':features,'queries':query_rows,'anchors':anchor_rows,'pairs':pairs,
        'query_frame_count':len(pending),'registered_anchor_images':len(anchor_rows),'pair_count':len(pairs),
        'planning_seconds':time.perf_counter()-start,'feature_load_hash_retrieval_descriptor_seconds':feature_load,
        'raw_matches_require_fixed_map_pose_validation':True}
    output.mkdir(parents=True);write_json(output/'plan.json',plan);return plan


class FeatureLRU:
    def __init__(self,specs,capacity=64):self.specs=specs;self.capacity=capacity;self.cache=OrderedDict();self.load_seconds=0.;self.loads=0
    def get(self,name):
        spec=self.specs[name];path=Path(spec['path'])
        if name in self.cache:
            data,state=self.cache.pop(name)
            if _fingerprint(path)!=state:raise ValueError('Cached feature file changed during matching')
            self.cache[name]=(data,state);return data
        start=time.perf_counter();state=_fingerprint(path)
        if file_hash(path)!=spec['sha256']:raise ValueError('Native feature hash changed after planning')
        data=read_vkft(path).subset(4096)
        if not np.array_equal(data.image_size,spec['image_size']) or len(data.keypoints)!=min(4096,spec['num_features']):raise ValueError('Planned native feature dimensions/count changed')
        if _fingerprint(path)!=state:raise ValueError('Native features changed while loading')
        self.load_seconds+=time.perf_counter()-start;self.loads+=1;self.cache[name]=(data,state)
        while len(self.cache)>self.capacity:self.cache.popitem(last=False)
        return data


def write_raw_cache(path,plan,pair_directory):
    """Write a complete VKMT v4 only after every original-index pair is present."""
    path=Path(path);partial=path.with_suffix(path.suffix+'.partial');table=plan['image_table'];by_name={row['name']:row for row in table}
    if len(by_name)!=len(table) or [r['image_id'] for r in table]!=list(range(len(table))):raise ValueError('Invalid independent image identity table')
    with partial.open('wb') as f:
        f.write(b'VKMT'+struct.pack('<II',4,len(table)))
        for image in table:
            name=image['cache_name'].encode();f.write(struct.pack('<I',len(name))+name+struct.pack('<I',image['num_features']))
        f.write(struct.pack('<I',len(plan['pairs'])))
        for pair in plan['pairs']:
            with np.load(Path(pair_directory)/(pair['id']+'.npz'),allow_pickle=False) as data:matches=data['matches'].copy()
            left=by_name[pair['image0']];right=by_name[pair['image1']]
            if matches.ndim!=2 or matches.shape[1]!=2 or matches.dtype.kind not in 'iu' or np.any(matches<0) or np.any(matches>=[left['num_features'],right['num_features']]):raise ValueError('Raw original feature rows are invalid')
            if len(set(matches[:,0]))!=len(matches) or len(set(matches[:,1]))!=len(matches):raise ValueError('Raw matches must be one-to-one')
            f.write(struct.pack('<IIiI',left['image_id'],right['image_id'],0,len(matches)));f.write(matches.astype('<u4').tobytes())
        f.write(struct.pack('<I',0)) # No camera metadata is needed for a raw cache.
    index=read_index(partial)
    if len(index.pairs)!=len(plan['pairs']) or any(pair.config!=0 for pair in index.pairs):raise ValueError('Raw cache finalization failed')
    partial.replace(path)


def run_matching(plan_path,output,*,execute=False,device='cpu',allow_gpu=False,weights=None,warmup=2,limit=None,allow_background_pids=()):
    start=time.perf_counter()
    plan_path=Path(plan_path).resolve();output=Path(output).resolve();plan=json.loads(plan_path.read_text())
    if plan.get('schema')!='rumah-fresh-query-matching-plan-v1' or plan.get('status')!='ready' or plan.get('descriptor_budget')!=4096:
        raise ValueError('A validated fixed4096 fresh-query plan is required')
    query_names={row['name'] for row in plan['queries']};anchor_names={row['name'] for row in plan['anchors']}
    if query_names&anchor_names or any(row['split']!='train' for row in plan['anchors']):raise ValueError('Query/anchor ownership or evaluation isolation failed')
    pairs=plan['pairs']
    if not pairs or len({pair['id'] for pair in pairs})!=len(pairs) or len({(pair['image0'],pair['image1']) for pair in pairs})!=len(pairs):raise ValueError('Empty or duplicate query edges')
    if any(pair['image0'] not in query_names or pair['image1'] not in anchor_names for pair in pairs):raise ValueError('Only query-to-registered-anchor edges are allowed')
    if warmup<0 or (limit is not None and limit<1):raise ValueError('Invalid warmup/limit')
    if not execute:return {'executed':False,'pairs':len(plan['pairs']),'query_frames':plan['query_frame_count'],'plan_sha256':file_hash(plan_path)}
    if weights is None or not Path(weights).is_file():raise ValueError('Complete local LightGlue weights required; no download')
    identity={'plan_sha256':file_hash(plan_path),'weights_sha256':file_hash(weights),
              'code_sha256':{name:file_hash(Path(__file__).with_name(name)) for name in ('fresh_query_matching.py','matcher_benchmark.py')}}
    if output.exists():
        existing=json.loads((output/'run.json').read_text())
        if existing['identity']!=identity:raise ValueError('Resume plan, weights, or code changed')
    else:
        output.mkdir(parents=True);(output/'pairs').mkdir();write_json(output/'run.json',{'identity':identity,'plan':str(plan_path),'device':device,'raw_config':0})
    records={}
    if (output/'records.jsonl').exists():
        for line in (output/'records.jsonl').read_text().splitlines():
            row=json.loads(line)
            if row['pair'] in records:raise ValueError('Duplicate completed pair record')
            if file_hash(output/'pairs'/(row['pair']+'.npz'))!=row['artifact_sha256']:raise ValueError('Completed match artifact changed')
            records[row['pair']]=row
    valid_ids={p['id'] for p in plan['pairs']}
    if not set(records).issubset(valid_ids):raise ValueError('Results contain unknown query edges')
    pending=[p for p in plan['pairs'] if p['id'] not in records]
    if not pending:
        if not (output/'matches.bin').exists():write_raw_cache(output/'matches.bin',plan,output/'pairs')
        result=json.loads((output/'progress.json').read_text());result.update(status='complete',completed_pairs=len(records),matches_sha256=file_hash(output/'matches.bin'))
        write_json(output/'progress.json',result);return result
    resource=gpu_idle_guard(allow_gpu,device,allow_background_pids=allow_background_pids)
    cache=FeatureLRU(plan['features']);tick=time.perf_counter();backend=LightGlueBackend(weights,device,-1.,-1.);backend.sync();load_seconds=time.perf_counter()-tick
    count=0;matching_seconds=0.;warmup_seconds=0.
    def progress(status,error=None):
        result={'schema':'rumah-fresh-query-matching-result-v1','identity':identity,'status':status,'executed':True,
            'completed_pairs':len(records),'planned_pairs':len(plan['pairs']),'matched_this_run':count,
            'feature_load_and_validation_seconds_this_run':cache.load_seconds,'feature_loads_this_run':cache.loads,
            'model_load_seconds_this_run':load_seconds,'warmup_seconds_this_run':warmup_seconds,
            'matching_seconds_this_run':matching_seconds,'wall_seconds_this_run':time.perf_counter()-start,
            'backend':backend.info,'resource_preflight':resource,'old_match_cache_opened':False,
            'geometric_verification':'Not performed per pair; raw matches require independent fixed-fresh-map PnP gates',
            'timing_scope':'Fresh matching of cached native descriptors. Feature extraction excluded; plan retrieval separately timed.',
            'error':error}
        if status=='complete':result['matches_sha256']=file_hash(output/'matches.bin')
        write_json(output/'progress.json',result);return result
    try:
        first=pending[0];left=cache.get(first['image0']);right=cache.get(first['image1']);tick=time.perf_counter()
        for _ in range(warmup):backend.match(left,right)
        backend.sync();warmup_seconds=time.perf_counter()-tick;progress('running')
        for pair in pending[:limit] if limit is not None else pending:
            left=cache.get(pair['image0']);right=cache.get(pair['image1']);digest=pair_digest(pair,left,right)
            backend.sync();tick=time.perf_counter();matches,scores,extra=backend.match(left,right);backend.sync();elapsed=time.perf_counter()-tick
            original=map_matches(matches,scores,left,right);artifact=output/'pairs'/(pair['id']+'.npz')
            # A prior interrupted save has no completion record and is replaced.
            np.savez(artifact,matches=original,scores=scores,pair_digest=np.array(digest))
            row={'pair':pair['id'],'pair_digest':digest,'artifact_sha256':file_hash(artifact),'matches':len(original),
                 'seconds':elapsed,'feature_counts':[len(left.keypoints),len(right.keypoints)],'original_feature_indices':True,
                 'same_lens':pair['same_lens'],'proposal':pair['stratum'],'raw_config':0,**extra}
            with (output/'records.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n')
            records[pair['id']]=row;matching_seconds+=elapsed;count+=1
            if count%25==0:progress('running');print(json.dumps({'completed_pairs':len(records),'planned_pairs':len(plan['pairs'])}),flush=True)
        if len(records)==len(plan['pairs']):write_raw_cache(output/'matches.bin',plan,output/'pairs');return progress('complete')
        return progress('partial')
    except Exception as error:progress('failed',str(error));raise
    finally:backend.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    plan=sub.add_parser('plan')
    for name in ('dataset','anchor-model','staging-provenance','queries','output'):plan.add_argument('--'+name,type=Path,required=True)
    plan.add_argument('--eval-frames',default='all');plan.add_argument('--frames',type=int,nargs='*');plan.add_argument('--retrieval-exclusion-seconds',type=float,default=1.5)
    match=sub.add_parser('match');match.add_argument('--plan',type=Path,required=True);match.add_argument('--output',type=Path,required=True)
    match.add_argument('--run',action='store_true');match.add_argument('--device',default='cpu');match.add_argument('--allow-gpu',action='store_true');match.add_argument('--weights',type=Path)
    match.add_argument('--warmup',type=int,default=2);match.add_argument('--limit',type=int);match.add_argument('--allow-background-pids',type=int,nargs='*',default=[])
    a=p.parse_args()
    if a.command=='plan':
        result=build_plan(a.dataset,a.anchor_model,a.staging_provenance,a.queries,a.output,eval_frames=a.eval_frames,frames=a.frames,retrieval_exclusion_seconds=a.retrieval_exclusion_seconds)
        print(json.dumps({k:result[k] for k in ('query_frame_count','registered_anchor_images','pair_count','planning_seconds')}))
    else:print(json.dumps(run_matching(a.plan,a.output,execute=a.run,device=a.device,allow_gpu=a.allow_gpu,weights=a.weights,warmup=a.warmup,limit=a.limit,allow_background_pids=a.allow_background_pids),indent=2))


if __name__=='__main__':main()
