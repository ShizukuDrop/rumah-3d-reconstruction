"""Cache per-lens quality measurements for every source pair; no filtering here."""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
import argparse
import hashlib
import json
import time
import cv2
from .capture import load_capture, sha256
from .quality import QualityConfig, measure_view


def measure_frame(request):
    dataset,frame,config_values,signature=request
    cv2.setNumThreads(1)
    config=QualityConfig(**config_values);root=Path(dataset);views={}
    started=time.perf_counter()
    for lens in ('cam0','cam1'):
        image=root/'images'/frame['images'][lens];mask=root/'masks'/frame['masks'][lens]
        metric=measure_view(image,mask,config)
        metric.update(time_seconds=frame['time_seconds'],source_frame=frame['id'],split=frame['split'])
        metric['input_stat']={name:{'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
                              for name,p in [('image',image),('mask',mask)]}
        views[lens]=metric
    return {'frame':frame['id'],'time_seconds':frame['time_seconds'],'split':frame['split'],
            'views':views,'signature':signature,'seconds':time.perf_counter()-started}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--frames',type=int,nargs='*')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    if not 1<=args.workers<=8:parser.error('workers must be between 1 and 8')
    capture=load_capture(args.dataset)
    config=QualityConfig(**json.loads(args.config.read_text())) if args.config else QualityConfig()
    settings=asdict(config)
    source_hash=sha256(Path(__file__).with_name('quality.py'))
    identity={'selection':capture['source_selection_sha256'],'camera':capture['camera_manifest_sha256'],
              'config':settings,'quality_source_sha256':source_hash}
    signature=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    if args.output.exists() and not args.resume:raise FileExistsError(args.output)
    args.output.mkdir(parents=True,exist_ok=True)
    records=args.output/'frames';records.mkdir(exist_ok=True)
    frames=[r for r in capture['frames'] if args.frames is None or r['id'] in args.frames]
    pending=[];reused=0
    for frame in frames:
        dest=records/f'{frame["id"]:06d}.json'
        if dest.exists():
            stored=json.loads(dest.read_text())
            if stored['signature']!=signature:raise ValueError('Cache belongs to different source/configuration/code')
            for lens,view in stored['views'].items():
                for group,key in [('images','image'),('masks','mask')]:
                    path=Path(capture['dataset'])/group/frame[group][lens]
                    if view['input_stat'][key]!={'bytes':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns}:
                        raise ValueError(f'Input changed after measurement: {path}')
            reused+=1
        else:pending.append(frame)
    start=time.perf_counter();completed=reused
    def status(state):
        record={'state':state,'total_pairs':len(frames),'completed_pairs':completed,'reused_pairs':reused,
                'workers':args.workers,'elapsed_seconds':time.perf_counter()-start,'gpu_used':False,
                'identity':identity,'signature':signature,'dataset':capture['dataset']}
        temp=args.output/'status.partial';temp.write_text(json.dumps(record,indent=2));temp.replace(args.output/'status.json')
    status('running')
    try:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(measure_frame,(capture['dataset'],frame,settings,signature)) for frame in pending]
            for future in as_completed(futures):
                row=future.result();target=records/f'{row["frame"]:06d}.json'
                temp=target.with_suffix('.partial');temp.write_text(json.dumps(row,allow_nan=False));temp.replace(target)
                completed+=1
                if completed%100==0:status('running');print(f'Measured {completed}/{len(frames)} pairs',flush=True)
        status('complete')
    except BaseException:
        status('failed');raise
    print(json.dumps({'output':str(args.output),'completed_pairs':completed,'elapsed_seconds':time.perf_counter()-start}))


if __name__=='__main__':main()
