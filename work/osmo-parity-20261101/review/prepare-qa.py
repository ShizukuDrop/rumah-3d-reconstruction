from pathlib import Path
import argparse,json,sys,os,math
import numpy as np,cv2
W=Path(__file__).resolve().parent;ROOT=W.parent.parent;OLD=ROOT/'osmo-clean-20261031';sys.path.insert(0,str(ROOT/'osmo-reconstruct-20261031'))
from seed_fisheye import read_model,qvec_to_rotmat,rotmat_to_qvec,Fisheye
CAP=Path('C:/Users/bombe/OneDrive/Documents/ChatGPT/Ruang Kamare/roomscan-reconstruction/data/20261031_OSMO360');source=CAP/'clean-v3/dataset'

def qa_maps(fish,view_to_source,WW,HH,f):
    """cv2.remap maps for a WWxHH pinhole (f, centre WW/2,HH/2), same convention as seed_fisheye.pinhole_face_maps:
    output pixel i holds the ray through i+0.5 and a fisheye sample at COLMAP-continuous u is cv2 index u-0.5."""
    yy,xx=np.mgrid[:HH,:WW]+.5;uv,valid=fish.project(np.stack([(xx-WW/2)/f,(yy-HH/2)/f,np.ones_like(xx)],axis=-1).reshape(-1,3)@view_to_source)
    valid&=(uv[:,0]>=0)&(uv[:,0]<fish.width)&(uv[:,1]>=0)&(uv[:,1]<fish.height)
    return (uv[:,0]-.5).reshape(HH,WW).astype('f4'),(uv[:,1]-.5).reshape(HH,WW).astype('f4'),valid.reshape(HH,WW)

if __name__=='__main__':
    a=argparse.ArgumentParser(description='Four full-viewport QA references remapped from native fisheye frames.');a.add_argument('--frames',type=Path,help='folder with native frames as cam0/frame_000027_train.(jpg|png) and optional masks/cam0/frame_000027_train.png; default: the Windows clean-v3 dataset');a.add_argument('--out',type=Path,default=W/'qa');args=a.parse_args()
    frames=args.frames or source/'images';masks=(args.frames or source)/'masks';out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if (source/'sparse/0').exists():cams,ims,_=read_model(source/'sparse/0');pose=lambda iid:(ims[iid]['name'],cams[ims[iid]['camera_id']],qvec_to_rotmat(ims[iid]['qvec']))
    else:
        # ponytail: in-repo copies of that audited sparse/0 (export-clean-cameras.py: opencvCameraToWorldRotation=R.T, sourceCalibration=params) when the dataset is absent.
        reg={p['sourceImageId']:p for p in json.loads((OLD/'review/clean-cameras-registered-poses.json').read_text())['poses']};cal={r['sourceCameraId']:r for r in json.loads((OLD/'review/clean-cameras.provenance.json').read_text())['references']}
        pose=lambda iid:(reg[iid]['name'],{'model':cal[reg[iid]['sourceCameraId']]['sourceModel'],'width':3840,'height':3840,'params':cal[reg[iid]['sourceCameraId']]['sourceCalibration']},np.array(reg[iid]['opencvCameraToWorldRotation']).T)
    camera_data=json.loads((OLD/'review/clean-cameras.json').read_text())
    models={
     'old-full':CAP/'clean-v3/explicit-full-v1/training/osmo-explicit-depth-v1/step-000050000.ckpt/splat.ply',
     'pilot-base':CAP/'parity-20261101/pilots/baseline-1200/training/baseline-1200/step-000008000.ckpt/splat.ply',
     'pilot-sharp':CAP/'parity-20261101/pilots/sharp-1600/training/sharp-1600/step-000008000.ckpt/splat.ply',
     'mesh-texture':W/'mesh-pilot/texture-preview.glb',
     'mesh-photo':W/'mesh-pilot/photo-baked.glb',
     'fusion-photo':W/'tsdf-pilot/photo-baked.glb',
     'fusion-coherent':W/'tsdf-pilot/coherent.glb',
     'fusion-filled':W/'tsdf-pilot/coherent-filled.glb',
     'poisson-photo':W/'poisson-projected/coherent-filled.glb',
     'new-full-50000':W/'qa/new-full-50000.ply','final-sharp':W/'final-sharp.sog','clean-final':OLD/'review/clean-final.sog',
    }
    for name in ['rgb-only-mip','rgb-only-3dgs','no-appearance-correction','sparse-rgb-only']:
        models[name]=CAP/f'parity-20261101/pilots/diagnostics/{name}/training/{name}/step-000008000.ckpt/splat.ply'
    assets=json.loads((out/'metadata.json').read_text())['models'] if (out/'metadata.json').exists() else {}
    for key,file in models.items():
        if not file.exists():continue
        dst=out/(key+file.suffix)
        if not dst.exists():os.link(file,dst)
        assets[key]={'url':'/review/'+dst.relative_to(W).as_posix(),'format':file.suffix[1:],'bytes':file.stat().st_size}
    poses=[];WW,HH=1920,1080;f=HH/2/math.tan(math.radians(75/2));masked=[]
    for label,index,down in [('fridge',0,.18),('fan',6,.10),('dining',4,.10),('bathroom',5,0)]:
        p=camera_data['presets'][index];q=p['quaternion'];r=qvec_to_rotmat(np.array([q[3],*q[:3]]));angle=-down;ca,sa=math.cos(angle),math.sin(angle);r=r@np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]])
        Rv=np.diag([1,-1,-1])@r.T;qnew=rotmat_to_qvec(r);name,camera,R=pose(p['sourceImageId']);fish=Fisheye(camera,max_theta_degrees=99);mx,my,keep=qa_maps(fish,Rv@R.T,WW,HH,f)
        file=next(x for x in [frames/name,(frames/name).with_suffix('.png')] if x.exists());raw=cv2.imread(str(file));mask_file=(masks/name).with_suffix('.png')
        if raw.shape[:2]!=(fish.height,fish.width):raise ValueError(f'{file} is {raw.shape[:2]}, calibration is {fish.height}x{fish.width}')
        rgb=cv2.remap(raw,mx,my,cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_CONSTANT)
        if mask_file.exists():keep&=cv2.remap(cv2.imread(str(mask_file),0),mx,my,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)>127;cv2.imwrite(str(out/(label+'-keep.png')),keep.astype('u1')*255);masked.append(label)
        rgb[~keep]=0;cv2.imwrite(str(out/(label+'-source.png')),rgb)
        poses.append({'label':label,'source':name,'sourceFrame':p['sourceFrame'],'split':p['split'],'position':p['position'],'quaternion':[*qnew[1:],qnew[0]],'fov':75,'width':WW,'height':HH,'intrinsics':[f,f,WW/2,HH/2],'mask':label+'-keep.png' if label in masked else None,'sourceFile':os.path.relpath(file,W)})
    (out/'metadata.json').write_text(json.dumps({'models':assets,'poses':poses,'sourcePhotographs':'Direct 3840 native RGB remap using audited calibration and exact camera pose; COLMAP pixel centres (ray through i+0.5, cv2.remap at u-0.5); binary masks unchanged where available; no learned image generation','keepMasks':masked},indent=2))
    print('Prepared QA models and four full-viewport source references',out,'masks:',masked or 'none')
