"""Extract the exact native 3840x3840 lens frames behind the four QA poses from the original OSV (A056) and check their identity.

Decodes like select_frames.py ([0:v:i] -> cam{i}, select=eq(n,N), format=yuvj420p) but writes lossless PNG instead of the q1 JPEG.
Identity evidence: A056 size+SHA-256, ffprobe stream order, showinfo pts == N*1001/30000 s, the 640px sharpness of select_frames.py
against frame-selection.json at N and N+-3, and the upright 1200px crop of export-clean-cameras.py (clean-cameras-photos) at N and N+-1.
Usage: .venv-geometry/bin/python -B extract-qa-frames.py ~/Downloads/Rumah/CAM_20261031005909_0004_D.OSV [--out frames]
"""
from pathlib import Path
import argparse,hashlib,json,math,re,subprocess,sys
import numpy as np,cv2
Q=Path(__file__).resolve().parent;W=Q.parent;ROOT=W.parent.parent;OLD=ROOT/'osmo-clean-20261031';sys.path.insert(0,str(ROOT/'osmo-reconstruct-20261031'))
from export_web_cameras import upright_frame,remap_coordinates
TB=1001  # frame duration in the 1/30000 stream time base (30000/1001 fps)

def decode(ffmpeg,osv,lens,frames,chain,pattern,extra=()):
    """Decode source frames n in `frames` of [0:v:lens]; returns (files in pts order, pts list) from showinfo."""
    expr='+'.join(f'eq(n\\,{n})' for n in sorted(frames))
    log=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-y','-i',str(osv),'-filter_complex',f'[0:v:{lens}]select={expr},{chain},showinfo[c]','-map','[c]','-fps_mode','passthrough','-frames:v',str(len(frames)),*extra,str(pattern)],check=True,capture_output=True,text=True).stderr
    pts=[int(x) for x in re.findall(r'Parsed_showinfo.*? pts:\s*(\d+)',log)];files=[Path(str(pattern)%(i+1)) for i in range(len(pts))]
    if len(pts)!=len(frames) or not all(f.exists() for f in files):raise RuntimeError(f'Expected {len(frames)} frames, got {len(pts)}\n{log[-2000:]}')
    return files,pts

def sharpness(path):
    """select_frames.py score: Laplacian variance inside the optical-interior mask of the 640px thumbnail."""
    yy,xx=np.mgrid[:640,:640];im=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
    return float(np.var(cv2.Laplacian(im,cv2.CV_32F)[((xx-320)**2+(yy-320)**2<240**2)&(yy<460)]))

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter);a.add_argument('osv',type=Path);a.add_argument('--out',type=Path,default=Q/'frames');a.add_argument('--ffmpeg',default='ffmpeg');a.add_argument('--ffprobe',default='ffprobe');args=a.parse_args()
    asset=next(x for x in json.loads((ROOT.parent/'assets-manifest.json').read_text())['assets'] if x['asset_id']=='A056')
    size=args.osv.stat().st_size
    with args.osv.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    if size!=asset['bytes'] or sha!=asset['local_sha256']:raise ValueError(f'{args.osv} is not A056: {size} B, sha256 {sha}')
    selection=json.loads((OLD/'frame-selection.json').read_text());candidates={c['source_frame']:c for c in selection['candidates']};selected={r['filename']:r for r in selection['selected']}
    streams=json.loads(subprocess.run([args.ffprobe,'-v','error','-show_streams','-of','json',str(args.osv)],check=True,capture_output=True,text=True).stdout)['streams']
    video=[s for s in streams if s['codec_type']=='video'][:2]  # [0:v:0]/[0:v:1]; the OSV also carries an attached-pic MJPEG as v:2
    for s in video:
        if (s['codec_name'],s['width'],s['height'],s['r_frame_rate'],s['time_base'],int(s['nb_frames']),int(s.get('start_pts',0)),s.get('has_b_frames',0))!=('hevc',*selection['native_size'],'30000/1001','1/30000',selection['source_frames_per_lens'],0,0):raise ValueError('Unexpected video stream '+json.dumps(s)[:400])
    if [s['index'] for s in video]!=[0,1]:raise ValueError('Expected the two lens streams first')
    # Factory slot 1/2 principal points are the ones COLMAP kept for cam0/cam1 (select_frames.py decoded [0:v:i] into cam{i}).
    factory=json.loads((ROOT/'osmo-format-20261031/calibration.json').read_text())['slots'];provenance=json.loads((OLD/'review/clean-cameras.provenance.json').read_text())
    colmap={r['sourceName'].split('/')[0]:r['sourceCalibration'] for r in provenance['references']}
    lens_check={f'cam{i}':{'stream':video[i]['index'],'trackId':video[i].get('id'),'factorySlot':str(i+1),'principalPointMatchesColmap':[factory[str(i+1)]['cx'],factory[str(i+1)]['cy']]==colmap[f'cam{i}'][2:4]} for i in range(2)}
    reg={p['name']:p for p in json.loads((OLD/'review/clean-cameras-registered-poses.json').read_text())['poses']};presets={p['name']:p for p in json.loads((OLD/'review/clean-cameras.json').read_text())['presets']}
    poses=json.loads((W/'qa/metadata.json').read_text())['poses'];tmp=args.out/'_decode';tmp.mkdir(parents=True,exist_ok=True);rows=[]
    for lens in sorted({int(p['source'][3]) for p in poses}):
        mine=[p for p in poses if int(p['source'][3])==lens]
        native,npts=decode(args.ffmpeg,args.osv,lens,{p['sourceFrame']+d for p in mine for d in (-1,0,1)},'format=yuvj420p,scale=in_color_matrix=bt601:in_range=full,format=rgb24',tmp/f'native-{lens}-%03d.png')
        thumbs,tpts=decode(args.ffmpeg,args.osv,lens,{p['sourceFrame']+d for p in mine for d in (-3,0,3)},'scale=640:640:flags=lanczos,format=yuvj420p',tmp/f'thumb-{lens}-%03d.jpg',('-q:v','1'))
        if any(t%TB for t in npts+tpts):raise ValueError('Non-frame-aligned pts')
        native=dict(zip([t//TB for t in npts],native));thumbs=dict(zip([t//TB for t in tpts],thumbs))
        for p in mine:
            n=p['sourceFrame'];name=p['source'];row=selected[Path(name).name]
            if row['source_frame']!=n or abs(row['time_seconds']-n*TB/30000)>1e-9:raise ValueError('frame-selection.json disagrees for '+name)
            out=args.out/Path(name).with_suffix('.png');out.parent.mkdir(parents=True,exist_ok=True);native[n].replace(out);native[n]=out
            im=cv2.imread(str(out));assert im.shape==(3840,3840,3),im.shape
            sharp={k-n:{'measured':sharpness(thumbs[k]),'recorded':candidates[k]['sharpness'][lens]} for k in sorted(thumbs) if abs(k-n)<=3}
            closest={d:min(sharp,key=lambda e:abs(sharp[e]['recorded']-v['measured'])) for d,v in sharp.items()}
            camera={'model':'OPENCV_FISHEYE','width':3840,'height':3840,'params':colmap[f'cam{lens}']};R=np.array(reg[name]['opencvCameraToWorldRotation']).T
            mx,my,valid=remap_coordinates(camera,R,upright_frame(R)[0],1200,1200);photo=OLD/'review'/presets[name]['sourceFile']
            ref=cv2.imread(str(photo)).astype(float);valid&=cv2.imread(str(photo.with_name(photo.stem+'-valid.png')),0)>127
            psnr={k-n:10*math.log10(255**2/np.mean((cv2.remap(cv2.imread(str(native[k])),mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT).astype(float)-ref)[valid]**2)) for k in sorted(native) if abs(k-n)<=1}
            ok=all(closest[d]==d for d in sharp) and max(psnr,key=psnr.get)==0
            rows.append({'label':p['label'],'source':name,'lens':lens,'stream':video[lens]['index'],'sourceFrame':n,'pts':n*TB,'ptsTime':n*TB/30000,'selectionTimeSeconds':row['time_seconds'],'file':str(out.relative_to(W)),'sharpnessByOffset':sharp,'closestRecordedOffset':closest,'uprightCropPsnrByOffset':psnr,'uprightCrop':str(photo.relative_to(ROOT.parent)),'identityConfirmed':ok})
            print(p['label'],name,'frame',n,'pts',n*TB,'sharpness',{d:round(v['measured'],1) for d,v in sharp.items()},'recorded',{d:round(v['recorded'],1) for d,v in sharp.items()},'crop PSNR',{d:round(v,2) for d,v in psnr.items()},'OK' if ok else 'MISMATCH')
    for f in tmp.iterdir():f.unlink()
    tmp.rmdir()
    report={'source':{'assetId':'A056','file':args.osv.name,'bytes':size,'sha256':sha},'ffmpeg':subprocess.run([args.ffmpeg,'-version'],capture_output=True,text=True).stdout.splitlines()[0],'lenses':lens_check,
        'decode':'[0:v:lens]select=eq(n,N),format=yuvj420p, then full-range BT.601 to RGB (what cv2 does to the q1 training JPEGs; 44.4 dB vs that JPEG path on frame 27) -> PNG','frames':rows,
        'masks':'Operator/mirror keep masks are not in this checkout or the OSV; references are unmasked.','allIdentityConfirmed':all(r['identityConfirmed'] for r in rows)}
    (Q/'extract-qa-frames.json').write_text(json.dumps(report,indent=2));print('All identities confirmed' if report['allIdentityConfirmed'] else 'IDENTITY MISMATCH',Q/'extract-qa-frames.json')
    if not report['allIdentityConfirmed']:sys.exit(1)

if __name__=='__main__':main()
