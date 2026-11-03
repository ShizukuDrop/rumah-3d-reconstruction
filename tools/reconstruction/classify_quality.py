"""Evaluate cached measurements; keep provisional and confirmed decisions distinct."""
from pathlib import Path
from dataclasses import asdict
from collections import Counter
import argparse
import json
import time
import cv2
from .capture import load_capture
from .quality import QualityConfig, evaluate_pair


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--measurements',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--neighbors',type=int,default=4)
    args=parser.parse_args();cv2.setNumThreads(1)
    if args.output.exists():raise FileExistsError(args.output)
    if args.neighbors<2:parser.error('At least two temporal neighbors on each side are required')
    capture=load_capture(args.dataset);config=QualityConfig(**json.loads(args.config.read_text()))
    scan=json.loads((args.measurements/'status.json').read_text())
    if scan['state']!='complete' or scan['identity']['selection']!=capture['source_selection_sha256']:
        raise ValueError('Measurement scan incomplete or capture mismatch')
    frames=capture['frames']
    data={r['id']:json.loads((args.measurements/'frames'/f'{r["id"]:06d}.json').read_text()) for r in frames}
    for row in data.values():
        if row['signature']!=scan['signature']:raise ValueError('Mixed measurement identities')
    decisions={};counts=Counter();flagged=[];start=time.perf_counter()
    for i,frame in enumerate(frames):
        nearby=frames[max(0,i-args.neighbors):i]+frames[i+1:i+1+args.neighbors]
        nearby=[row for row in nearby if row['split']=='train']
        references={lens:[data[r['id']]['views'][lens] for r in nearby] for lens in ('cam0','cam1')}
        value=evaluate_pair(data[frame['id']]['views'],references,config);decisions[frame['id']]=value
        counts[value['action']]+=1
        for lens,v in value['views'].items():
            counts[f'{lens}:{v["verdict"]}']+=1
            if v['verdict']=='blur':flagged.append({'frame':frame['id'],'lens':lens,'seconds':frame['time_seconds'],
                                                  'confirmed':v['confirmed'],'reasons':v['reasons']})
        if (i+1)%500==0:print(f'Classified {i+1}/{len(frames)} pairs',flush=True)
    result={'configuration':asdict(config),'quality_scan_signature':scan['signature'],'decisions':decisions,
            'summary':dict(counts),'flagged_blur':flagged,'neighbor_count_each_side':args.neighbors,
            'elapsed_seconds':time.perf_counter()-start,'classification_source':'masked edges, common regions and tracked correspondence corroboration'}
    result['heldout_images_used_as_training_quality_references']=False
    args.output.parent.mkdir(exist_ok=True,parents=True)
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ('summary','flagged_blur','elapsed_seconds')}))


if __name__=='__main__':main()
