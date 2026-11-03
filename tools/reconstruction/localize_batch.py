"""Resume serial CPU fixed-map localization without restarting training or a mapper.

python -m tools.reconstruction.localize_batch --preparation inputs/preparation.json
  --output results [--limit 8] [--frames 10 29] [--retry-errors]

All runtime is cache-assisted localization against fresh anchor geometry, not an
end-to-end fresh reconstruction time. Rejected or failed poses are never exported.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import time

from .localization import file_hash, localize_fixed_rig, AnchorLookupCache


def write_json(path, value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    # Windows readers/antivirus may briefly deny delete-sharing on the old
    # destination. Preserve the valid previous JSON and retry only replacement;
    # never discard completed computation because a status reader held the file.
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.025*min(attempt+1,8))


def summarize(preparation, results):
    """Count all requested source frames; room gaps stay visible after failures."""
    counts={'accepted':0,'rejected':0,'errors':0,'pending':0,'insufficient_correspondences':0}
    region_rows={}
    def add(regions,split,status,frame):
        for name in regions or ['unassigned']:
            row=region_rows.setdefault((name,split),{'region':name,'split':split,'registered_anchor_frames':[],
                'accepted_query_frames':[],'rejected_query_frames':[],'pending_query_frames':[],
                'failed_query_frames':[],'insufficient_correspondence_frames':[]})
            row[status].append(frame)
    for anchor in preparation['registered_anchors']:
        regions=sorted({r for view in anchor.get('appearance',{}).values() for r in (view.get('regions') or [])})
        add(regions,anchor['split'],'registered_anchor_frames',anchor['frame_id'])
    for query in preparation['queries']:
        result=results.get(query['frame_id'])
        if not query['request']:key='insufficient_correspondences';region_key='insufficient_correspondence_frames'
        elif result is None:key='pending';region_key='pending_query_frames'
        elif result.get('execution_status')=='error':key='errors';region_key='failed_query_frames'
        elif result.get('accepted'):key='accepted';region_key='accepted_query_frames'
        else:key='rejected';region_key='rejected_query_frames'
        counts[key]+=1;add(query.get('regions',[]),query['split'],region_key,query['frame_id'])
    return {'counts':counts,'registered_anchor_frames':len(preparation['registered_anchors']),
        'per_region_split':list(region_rows.values()),
        'quality_policy':'A registered or accepted pose alone does not make a training view eligible.',
        'training_ready':False}


def run_batch(preparation,output,*,limit=None,frames=None,retry_errors=False):
    preparation=Path(preparation).resolve();output=Path(output).resolve()
    spec=json.loads(preparation.read_text(encoding='utf-8'))
    if spec.get('status')!='complete' or not spec.get('fresh_points_only') or spec.get('map_mutated'):
        raise ValueError('Completed, immutable fresh-anchor preparation is required')
    if limit is not None and limit<1:raise ValueError('Limit must be positive')
    source_hash=file_hash(preparation)
    code_hash={name:file_hash(Path(__file__).with_name(name)) for name in ('localize_batch.py','localization.py','motion.py')}
    identity={'preparation_sha256':source_hash,'code_sha256':code_hash,'pycolmap_version':importlib.metadata.version('pycolmap')}
    queue=[row for row in spec['queries'] if row.get('request')]
    if frames is not None:
        wanted=set(frames)
        if not wanted.issubset({row['frame_id'] for row in queue}):raise ValueError('Unknown or unprepared query frame')
        queue=[row for row in queue if row['frame_id'] in wanted]
    if output.exists():
        previous=json.loads((output/'batch.json').read_text())
        if previous['identity']!=identity:raise ValueError('Resume inputs, code, or PyCOLMAP version changed; use a new output directory')
    else:
        output.mkdir(parents=True);(output/'results').mkdir()
        write_json(output/'batch.json',{'schema':'rumah-localization-batch-v1','identity':identity,
            'preparation':str(preparation),'device':'CPU','workers':1,'map_mutated':False,
            'timing_kind':'cache-assisted fixed-fresh-map localization; feature extraction and matching excluded'})
    results={}
    for row in spec['queries']:
        path=output/'results'/f'frame-{row["frame_id"]:06d}.json'
        if not path.exists():continue
        result=json.loads(path.read_text());request=preparation.parent/row['request']
        if result.get('request_sha256')!=file_hash(request):raise ValueError('Stored result does not match its original request')
        if result.get('accepted') and ('rig_from_world' not in result or 'camera_from_world' not in result):raise ValueError('Partial accepted result')
        results[row['frame_id']]=result
    start=time.perf_counter();attempts=0;anchor_cache=AnchorLookupCache()
    def progress(status,current=None):
        value={'schema':'rumah-localization-progress-v1','status':status,'identity':identity,
            'attempted_this_run':attempts,'current_frame':current,'elapsed_this_run_seconds':time.perf_counter()-start,
            'completed_results':len(results),'summary':summarize(spec,results),'shared_anchor_cache':anchor_cache.stats()}
        write_json(output/'progress.json',value);return value
    progress('running')
    for row in queue:
        old=results.get(row['frame_id'])
        if old is not None and not (retry_errors and old.get('execution_status')=='error'):continue
        if limit is not None and attempts>=limit:break
        request=preparation.parent/row['request'];progress('running',row['frame_id']);attempts+=1
        try:
            result=localize_fixed_rig(request,anchor_cache=anchor_cache);result['execution_status']='complete'
        except Exception as error:
            result={'request_sha256':file_hash(request),'accepted':False,'execution_status':'error',
                    'error_type':type(error).__name__,'error':str(error),'map_mutated':False}
        if file_hash(preparation)!=source_hash:raise ValueError('Preparation changed while localization was running')
        write_json(output/'results'/f'frame-{row["frame_id"]:06d}.json',result);results[row['frame_id']]=result
        print(json.dumps({'frame':row['frame_id'],'accepted':result['accepted'],'execution_status':result['execution_status'],
                          'inliers':result.get('inliers'),'elapsed_seconds':result.get('elapsed_seconds')}),flush=True)
        progress('running')
    summary=summarize(spec,results)
    return progress('complete' if summary['counts']['pending']==0 else 'partial')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--limit',type=int);p.add_argument('--frames',type=int,nargs='*');p.add_argument('--retry-errors',action='store_true');a=p.parse_args()
    result=run_batch(a.preparation,a.output,limit=a.limit,frames=a.frames,retry_errors=a.retry_errors)
    print(json.dumps({'status':result['status'],'counts':result['summary']['counts']}))


if __name__=='__main__':main()
