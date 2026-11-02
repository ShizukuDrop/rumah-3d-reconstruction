"""Write a cleaner copy of a Gaussian PLY: drop splats that add almost nothing to any view.

Removed: near-invisible splats (opacity < 0.02), extreme needles (longest axis over 10x
the middle one and over 0.03 units), and splats more than 0.4 units beyond the room
footprint (unobserved exterior and reflection blobs seen through doorways). Floor
reflections stay: they are what makes the tiles look glossy in Walk. Kept splats are
copied byte for byte; pack the result with osmo-clean-20261031/review/pack-sog.py.

Usage: python -B clean_splats.py MODEL.ply review/calibrated-occupied-cameras.json OUT.ply
"""
from pathlib import Path
import base64,hashlib,json,sys
import numpy as np
from occupied_bounds import ply

MIN_ALPHA=.02;NEEDLE=10.;NEEDLE_MIN=.03;OUTSIDE=.4

def clean(model,shell,out):
    d=ply(Path(model));fp=shell['footprint'];W,H=fp['size'];c=fp['cellSize'];o=fp['origin']
    sdf=np.frombuffer(base64.b64decode(fp['sdfCm']),np.int8).reshape(W,H)/100
    i=np.clip(((d['x']-o[0])/c).astype(int),0,W-1);k=np.clip(((d['z']-o[1])/c).astype(int),0,H-1)
    alpha=1/(1+np.exp(-d['opacity'].astype(np.float64)));s=np.sort(np.exp(np.stack([d['scale_0'],d['scale_1'],d['scale_2']],1).astype(np.float64)),1)
    rules={'invisible':alpha<MIN_ALPHA,'needle':(s[:,2]>NEEDLE_MIN)&(s[:,2]>NEEDLE*s[:,1]),'outside':sdf[i,k]>OUTSIDE}
    drop=np.logical_or.reduce(list(rules.values()));keep=~drop
    with open(model,'rb') as f:
        header=b''
        while not header.endswith(b'end_header\n'):header+=f.readline()
    lines=[f'element vertex {int(keep.sum())}' if l.startswith('element vertex ') else l for l in header.decode().splitlines()]
    with open(out,'xb') as f:f.write(('\n'.join(lines)+'\n').encode());d[keep].tofile(f)
    return {'source':Path(model).name,'sourceSha256':hashlib.file_digest(open(model,'rb'),'sha256').hexdigest(),'output':Path(out).name,
        'sha256':hashlib.file_digest(open(out,'rb'),'sha256').hexdigest(),'splatsBefore':len(d),'splatsAfter':int(keep.sum()),
        'removedByRule':{k:int(v.sum()) for k,v in rules.items()},'removedTotal':int(drop.sum()),
        'thresholds':{'minAlpha':MIN_ALPHA,'needleRatio':NEEDLE,'needleMin':NEEDLE_MIN,'outsideFootprint':OUTSIDE}}

if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit(__doc__)
    model,cameras,out=sys.argv[1:]
    report=clean(model,json.loads(Path(cameras).read_text())['occupiedShell'],out)
    Path(out).with_suffix('.clean.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=1))
