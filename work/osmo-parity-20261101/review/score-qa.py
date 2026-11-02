from pathlib import Path
import hashlib,json,math,os,sys
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFont
W=Path(__file__).resolve().parent
boxes={'fridge':(950,480,1550,1080),'fan':(400,300,1000,900),'dining':(200,400,800,1000),'bathroom':(660,180,1260,780)}

def gray(a):return cv2.cvtColor(np.asarray(a,dtype='f4'),cv2.COLOR_RGB2GRAY)
def psnr(a,b,m):return 10*math.log10(255**2/float(np.mean((np.asarray(a,float)-b)[m]**2)))
def ssim(a,b,m):
    """Wang et al. 2004 SSIM of the luminance (11px Gaussian, sigma 1.5, 8-bit constants), mean inside m."""
    a,b=gray(a).astype('f8'),gray(b).astype('f8');g=lambda x:cv2.GaussianBlur(x,(11,11),1.5);ma,mb=g(a),g(b);va,vb,cov=g(a*a)-ma*ma,g(b*b)-mb*mb,g(a*b)-ma*mb;c1,c2=(.01*255)**2,(.03*255)**2
    return float((((2*ma*mb+c1)*(2*cov+c2))/((ma*ma+mb*mb+c1)*(va+vb+c2)))[m].mean())
def gradient(a,m):g=gray(a);return float(np.hypot(cv2.Sobel(g,cv2.CV_32F,1,0),cv2.Sobel(g,cv2.CV_32F,0,1))[m].mean())

def reference_mask(folder,metadata,label,shape):
    """Use the declared mask only; explicit null preserves old unmasked QA semantics."""
    poses=[p for p in metadata.get('poses',[]) if p.get('label')==label]
    if len(poses)!=1 or 'mask' not in poses[0]:raise ValueError(f'Expected one pose with explicit mask metadata for {label}; regenerate QA references')
    pose=poses[0];name=pose['mask']
    if name is None:return np.ones(shape,bool),'none'
    if not isinstance(name,str) or not name:raise ValueError(f'Invalid mask metadata for {label}')
    path=(folder/name).resolve()
    if not path.is_relative_to(folder.resolve()):raise ValueError(f'QA mask for {label} is outside its reference folder')
    if not path.is_file():raise FileNotFoundError(f'Declared QA mask missing for {label}: {path}')
    with Image.open(path) as image:mask=np.array(image.convert('L'))>127
    if mask.shape!=shape:raise ValueError(f'QA mask shape {mask.shape} != reference shape {shape} for {label}')
    if not mask.any():raise ValueError(f'QA mask has no valid pixels for {label}')
    kind=pose.get('maskKind','source-keep')  # Earlier masked references used the source keep mask.
    if kind not in ('camera-validity','source-keep'):raise ValueError(f'Unknown QA mask kind {kind!r} for {label}')
    return mask,kind
def align(gt,pr,box,mask):
    """ECC-register the render to the reference inside box (crop to crop): phase-correlation start, ECC translation, then ECC affine if it
    stays small (|A-I|<=.02) and does not lower the correlation. Returns the aligned crop, its valid pixels and the evidence."""
    x0,y0,x1,y1=box;t,r=gray(gt[y0:y1,x0:x1]),gray(pr)[y0:y1,x0:x1];m=mask.astype('u1')*255;ones=np.full(t.shape,255,'u1');criteria=(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,200,1e-6)
    (dx,dy),_=cv2.phaseCorrelate(t,r,cv2.createHanningWindow(t.shape[::-1],cv2.CV_32F));warp=np.array([[1,0,dx],[0,1,dy]],'f4');evidence={'phaseShiftPx':[dx,dy],'motion':'none'}
    try:
        cc,warp=cv2.findTransformECCWithMask(t,r,m,ones,warp,cv2.MOTION_TRANSLATION,criteria,5);evidence.update(motion='translation',correlation=float(cc))
        try:
            ca,affine=cv2.findTransformECCWithMask(t,r,m,ones,warp.copy(),cv2.MOTION_AFFINE,criteria,5)
            if np.abs(affine[:,:2]-np.eye(2)).max()<=.02 and ca>=cc:warp=affine;evidence.update(motion='affine',correlation=float(ca))
        except cv2.error:pass
    except cv2.error:warp=np.eye(2,3,dtype='f4')
    full=warp.copy();full[:,2]+=(x0,y0);flags=cv2.WARP_INVERSE_MAP;size=(x1-x0,y1-y0)  # crop-coordinate warp -> sample the full render, so shifted-in pixels are real
    aligned=cv2.warpAffine(np.asarray(pr,'f4'),full,size,flags=flags|cv2.INTER_LANCZOS4);valid=cv2.warpAffine(np.full(np.shape(pr)[:2],255,'u1'),full,size,flags=flags|cv2.INTER_NEAREST)>0
    c=np.array([size[0]/2,size[1]/2]);evidence.update(warp=warp.tolist(),shiftPx=(warp@[*c,1]-c).tolist());return aligned,valid,evidence  # shiftPx: displacement at the crop centre

if __name__=='__main__':
    Q=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else W/'qa';font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24) if os.name=='nt' else ImageFont.load_default(24)
    metadata=json.loads((Q/'metadata.json').read_text());models=list(metadata['models']);rows=[];sha={}
    for label,box in boxes.items():
        gt=np.array(Image.open(Q/(label+'-source.png')).convert('RGB'),dtype=float);mask,mask_kind=reference_mask(Q,metadata,label,gt.shape[:2]);masked=mask_kind!='none';x0,y0,x1,y1=box
        mask_description={'source-keep':'source keep-mask and valid camera region','camera-validity':'valid camera region only; operator/mirror pixels included','none':'NO keep mask (unavailable): full 600x600 crop box, operator/mirror pixels included'}[mask_kind]
        for model in models:
            path=Q/f'{model}-{label}.png'
            if not path.exists():continue
            if model not in sha:
                file=W/metadata['models'][model]['url'].removeprefix('/review/');sha[model]=None
                if file.exists():
                    with file.open('rb') as f:sha[model]=hashlib.file_digest(f,'sha256').hexdigest()
            image=Image.open(path).convert('RGB');pr=np.array(image,dtype=float);error=gt-pr;mse=float(np.mean(error[mask]**2));cm=mask[y0:y1,x0:x1];ce=error[y0:y1,x0:x1];cropMse=float(np.mean(ce[cm]**2))
            aligned,valid,ecc=align(gt,pr,box,cm);gc=gt[y0:y1,x0:x1];am=cm&valid
            row={'model':model,'modelSha256':sha[model],'view':label,'validFraction':float(mask.mean()),'psnrDb':10*math.log10(255**2/mse),'rmse255':math.sqrt(mse),'cropPSNR':10*math.log10(255**2/cropMse),'cropRMSE255':math.sqrt(cropMse),'cropSSIM':ssim(gc,pr[y0:y1,x0:x1],cm),
                 'alignedCropPSNR':psnr(gc,aligned,am),'alignedCropSSIM':ssim(gc,aligned,am),'gradientRatio':gradient(pr[y0:y1,x0:x1],cm)/gradient(gc,cm),'ecc':ecc,'cropBox':box,'mask':'keep' if masked else 'none','maskKind':mask_kind,
                 'GT':'Native photograph remapped by camera only; '+mask_description+'; cropPSNR/cropSSIM unregistered, aligned* after ECC registration of the render (ecc)'};rows.append(row)
            image.crop(box).save(Q/f'{model}-{label}-crop600.png')
        newest=sorted((k for k in models if k.startswith('new-full-')),key=lambda k:int(k.rsplit('-',1)[1]))
        groups=[('pilots',['source','pilot-base','pilot-sharp']),('delivery',['source','old-full','mesh-photo'])]
        if 'fusion-photo' in models:groups.append(('fusion',['source','old-full','fusion-photo']))
        if 'fusion-filled' in models:groups.append(('coherent',['source','old-full','fusion-filled']))
        if 'poisson-photo' in models:groups.append(('poisson',['source','old-full','poisson-photo']))
        if 'rgb-only-mip' in models:groups.append(('geometry-test',['source','pilot-sharp','rgb-only-mip']))
        if 'no-appearance-correction' in models:groups.append(('appearance-test',['source','rgb-only-3dgs','no-appearance-correction']))
        if 'sparse-rgb-only' in models:groups.append(('seed-test',['source','rgb-only-3dgs','sparse-rgb-only']))
        if newest:groups.append(('newest',['source','old-full',newest[-1]]))
        if 'final-sharp' in models:groups.append(('sog',['source','clean-final','final-sharp',*newest[-1:]]))
        for group,which in groups:
            paths=[Q/(label+'-source.png') if key=='source' else Q/f'{key}-{label}.png' for key in which]
            if not all(p.exists() for p in paths):continue
            sheet=Image.new('RGB',(600*len(which),650),'#172530');d=ImageDraw.Draw(sheet)
            for col,(key,path) in enumerate(zip(which,paths)):im=Image.open(path).convert('RGB');sheet.paste(im.crop(box),(col*600,50));d.text((col*600+12,10),key,font=font,fill='white')
            sheet.save(Q/f'{group}-{label}.png')
    keys=['psnrDb','cropPSNR','cropSSIM','alignedCropPSNR','alignedCropSSIM','gradientRatio']
    means={m:{'views':len(r),**{k:float(np.mean([x[k] for x in r])) for k in keys}} for m in models if (r:=[x for x in rows if x['model']==m])}
    report={'rows':rows,'modelMeans':means,'keepMasks':any(r['maskKind']=='source-keep' for r in rows),'maskKinds':sorted({r['maskKind'] for r in rows}),'scope':'Four fixed full-viewport 1920x1080 camera views. cropPSNR/cropSSIM are unregistered; alignedCropPSNR/SSIM register the render to the reference inside the 600x600 crop (phase correlation, ECC translation, small affine). gradientRatio = mean |Sobel grad| render / reference inside the crop mask (unregistered): <1 is softer than the photograph, >1 can also mean noise or artifacts. Three are source training timestamps and bathroom is appearance-held-out. Same-capture SfM is not independent geometry truth. Pilot steps and budgets match each other; original full uses a larger budget and more steps.','physicalPhoneTests':False}
    (Q/'scores.json').write_text(json.dumps(report,indent=2));print(json.dumps(means,indent=2))
