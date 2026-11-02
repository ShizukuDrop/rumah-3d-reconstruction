"""Fit positive, zero-offset depth scales against qualified training SfM anchors.

This only audits predicted depth. Accepted frames must later pass multi-view
pixel consistency before their depth is used to seed or supervise training.
"""
from pathlib import Path
import argparse,json,sys,time
import cv2,numpy as np
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W.parent/'osmo-reconstruct-20261031'))
from seed_fisheye import read_model,qvec_to_rotmat,sample_map
P=argparse.ArgumentParser();P.add_argument('--dataset',type=Path,required=True);a=P.parse_args();started=time.monotonic();cv2.setNumThreads(2)
report_path=a.dataset/'depth-scale-audit.json'
if report_path.exists():raise FileExistsError(report_path)
cameras,images,points=read_model(a.dataset/'sparse/0');provenance=json.loads((a.dataset/'explicit-pinhole-audit.json').read_text());by_name={v['name']:v for v in provenance['views']}
train_times={pid:{by_name[images[int(i)]['name']]['sourceFrame'] for i in point['image_ids'] if by_name[images[int(i)]['name']]['sourceSplit']=='train'} for pid,point in points.items()}
rows=[]
for number,im in enumerate(images.values(),1):
    meta=by_name[im['name']]
    if meta['sourceSplit']!='train':continue
    row={'name':im['name'],'sourceFrame':meta['sourceFrame'],'sourceName':meta['sourceName'],'acceptedScale':False,'offset':0.0}
    try:
        raw=cv2.imread(str((a.dataset/'depths'/im['name']).with_suffix('.png')),cv2.IMREAD_UNCHANGED)
        if raw is None or raw.dtype!=np.uint16:raise ValueError('Expected raw relative uint16 depth')
        H,DW=raw.shape;camera=cameras[im['camera_id']];fx,fy,cx,cy=camera['params'];mask=cv2.imread(str((a.dataset/'masks'/im['name']).with_suffix('.png')),0);mask=cv2.resize(mask,(DW,H),interpolation=cv2.INTER_NEAREST);mask=cv2.erode(mask,np.ones((7,7),np.uint8))
        idx=[j for j,pid in enumerate(im['point3D_ids']) if int(pid) in points and len(train_times[int(pid)])>=3 and points[int(pid)]['error']<=1.5]
        if len(idx)<40:raise ValueError('Fewer than 40 qualified multi-timestamp anchors')
        ids=im['point3D_ids'][idx];observed=im['points2D_xy'][idx];xyz=np.array([points[int(pid)]['xyz'] for pid in ids]);R=qvec_to_rotmat(im['qvec']);xc=xyz@R.T+im['tvec'];ranges=np.linalg.norm(xc,axis=1);uv=xc[:,:2]/xc[:,2,None]*[fx,fy]+[cx,cy]
        # Keypoints are COLMAP-continuous; sample_map converts them to cv2 pixel indices.
        xy=observed*[DW/camera['width'],H/camera['height']]
        depth=sample_map(raw.astype(np.float32),xy);valid=sample_map(mask,xy,nearest=True)>127
        valid&=(xc[:,2]>.02)&(np.linalg.norm(uv-observed,axis=1)<=2.5)&(depth>0)&np.isfinite(ranges)
        depth=depth[valid];ranges=ranges[valid];xy=xy[valid]
        if len(depth)<40:raise ValueError('Fewer than 40 unmasked accurate anchor observations')
        ratios=ranges/depth;scale=float(np.median(ratios))
        for _ in range(4):
            inside=np.abs(scale/ratios-1)<=.05
            if inside.sum()<10:break
            scale=float(np.median(ratios[inside]))
        residual=np.abs(scale*depth-ranges)/ranges;inside=residual<=.05
        cells=np.floor(xy[inside]/[DW/4,H/4]).astype(int);coverage=len(np.unique(cells,axis=0));median=float(np.median(residual));p90=float(np.percentile(residual,90));fraction=float(inside.mean())
        row.update(scale=scale,offset=0.0,observations=len(depth),inliersAt5Percent=int(inside.sum()),inlierFractionAt5Percent=fraction,medianRelativeResidual=median,p90RelativeResidual=p90,coveredGridCells4x4=coverage,depthShape=[H,DW])
        reasons=[]
        if not np.isfinite(scale) or scale<=0:reasons.append('Invalid positive scale')
        if fraction<.70:reasons.append('Fewer than 70% of anchors agree within 5%')
        if median>.03:reasons.append('Median relative error exceeds 3%')
        if p90>.10:reasons.append('90th percentile relative error exceeds 10%')
        if coverage<5:reasons.append('Anchor support covers fewer than five 4x4 cells')
        row['reasons']=reasons;row['acceptedScale']=not reasons
    except Exception as error:row['reason']=str(error)
    rows.append(row)
    if number%50==0:print(f'Depth scale checks {number}/{len(images)}; accepted {sum(r["acceptedScale"] for r in rows)}',flush=True)
report={'method':__doc__,'dataset':str(a.dataset.resolve()),'depthConvention':'Euclidean ray range; raw PNG relative levels -> audited fresh SfM scene units using one positive scale, offset exactly zero','framesAudited':len(rows),'acceptedScales':sum(r['acceptedScale'] for r in rows),'evalDepthUsed':False,'oldDepthOrCheckpointOpened':False,'notYetApprovedForTraining':True,'gates':{'pointTrackDistinctTrainingTimestamps':3,'maximumPointStoredErrorNativePixels':1.5,'actualVirtualReprojectionPixels':2.5,'minimumObservations':40,'anchorRelativeInlierTolerance':.05,'minimumInlierFraction':.70,'maximumMedianRelativeResidual':.03,'maximumP90RelativeResidual':.10,'minimumCovered4x4Cells':5},'frames':rows,'seconds':time.monotonic()-started}
report_path.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['method','frames']},indent=2))
