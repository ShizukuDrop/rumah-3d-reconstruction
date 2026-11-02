"""Audit/package an explicit native release. Local files only; never connects remotely."""
from pathlib import Path,PurePosixPath
from html.parser import HTMLParser
import argparse,hashlib,json,re,tarfile

HERE=Path(__file__).resolve().parent
IPHONES={
 'phone':('models/iphone-phone-2b811d1241.glb',21144604,'2b811d124120e70dcecc25d06e5dc397e2a28f310403a21fdfa1e290c41c9d2b'),
 'native':('models/iphone-full-room-16f8963b.glb',435614584,'16f8963b043a766317497ee4281f4cf39c6b2190fafaaed51334734723c8b207')}
ALLOWED=re.compile(r'(?:index\.html|robots\.txt|room-[0-9a-f]{10}\.json|room-viewer-[A-Z0-9]{8}\.js|chunks/[A-Za-z0-9_.-]+-[A-Z0-9]{8}\.js|models/osmo-native-[0-9a-f]{10}\.(?:spz|sog)|sources/osmo-[0-9a-f]{10}\.jpg|models/osmo-shapes-[0-9a-f]{10}\.json)')

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def safe_relative(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',name) or name.startswith('/') or '..' in PurePosixPath(name).parts or '\\' in name:raise ValueError('Unsafe asset path')
    return name

def local_row(public,name):
    safe_relative(name);path=public/name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(public):raise ValueError('Asset outside public or not a regular file: '+name)
    return {'path':name,'bytes':path.stat().st_size,'sha256':sha(path)}

class LandingAudit(HTMLParser):
    def __init__(self):
        super().__init__();self.resources=[];self.choices=[];self.hidden=False;self.open=False;self.style=False
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='input' and values.get('name')=='model-choice' and values.get('type')=='radio':self.choices.append(values.get('value'))
        if tag=='div' and values.get('id')=='viewer-app' and 'hidden' in values:self.hidden=True
        if tag=='button' and values.get('id')=='open-model':self.open=True
        if tag=='style':self.style=True
        if tag in {'link','iframe','object','embed','base'} or any(key in values for key in ('src','srcset','poster','background')):self.resources.append(tag)
        if tag in {'image','use','feimage'} and any(values.get(key,'') and not values[key].startswith('#') for key in ('href','xlink:href')):self.resources.append('svg')
        if tag=='meta' and values.get('http-equiv','').lower()=='refresh':self.resources.append('refresh')
        if re.search(r'url\s*\(|@import\b',values.get('style',''),re.I):self.resources.append('css')
    def handle_endtag(self,tag):
        if tag=='style':self.style=False
    def handle_data(self,data):
        if self.style and re.search(r'url\s*\(|@import\b',data,re.I):self.resources.append('css')

def audit_landing(entry,bundle):
    audit=LandingAudit();audit.feed(entry)
    if audit.resources:raise ValueError('Automatic landing resources: '+','.join(audit.resources))
    if sorted(audit.choices)!=['native','osmo','phone'] or not audit.hidden or not audit.open:raise ValueError('Missing explicit three-model choice gate')
    if bundle not in entry:raise ValueError('Landing does not point at the reviewed viewer bundle')
    if len(entry.encode())>80000:raise ValueError('Chooser HTML exceeds its 80 kB budget')

def collect(here=HERE):
    public=(here/'public').resolve();build=json.loads((here/'build-report.json').read_text(encoding='utf-8'));candidate=json.loads((here/'candidate.json').read_text(encoding='utf-8'))
    if build.get('choiceRequired') is not True or build.get('automaticModelRetry') is not False or build.get('prechoiceExternalRequests')!=0:raise ValueError('Choice/quota guarantees absent')
    manifest=json.loads((public/build['manifestName']).read_text(encoding='utf-8'));asset=manifest['models']['osmo']
    if set(manifest['models'])!={'phone','native','osmo'}:raise ValueError('Expected exactly three model choices')
    if asset!=build['osmo'] or asset['representation']!='gaussian' or asset['format'] not in {'sog','spz'}:raise ValueError('Native asset identity differs')
    if not 12<=asset['fileBytes']<=50000000 or asset['downloadBytes']!=asset['fileBytes'] or not 1<=asset['splats']<=3100000 or asset['shDegree'] not in range(4):raise ValueError('Native download/count/SH budget failed')
    if build['lodPolicy']!={'lodSplatCount':1500000,'baseSplats':asset['splats'],'lod':True,'nonLod':False,'extSplats':True}:raise ValueError('Unexpected phone rendering policy')
    entry=(public/'index.html').read_text(encoding='utf-8');audit_landing(entry,build['bundleName'])
    if build['manifestName'] not in (public/build['bundleName']).read_text(encoding='utf-8'):raise ValueError('Bundle points at another manifest')
    if 'deploymentAuthorized' not in build:raise ValueError('Unreviewed build report')
    names={'index.html','robots.txt',build['manifestName'],build['bundleName'],asset['url']}
    if asset.get('simple'):names.add(asset['simple']['url'])  # optional simple-shape file behind the viewer toggle
    # Derive chunk closure from esbuild's outputs, never from an unconstrained folder walk.
    for filename in build['metafile']['outputs']:
        path=Path(filename)
        if not path.is_absolute():path=here/path
        path=path.resolve()
        if not path.is_relative_to(public):raise ValueError('Build output escaped public directory')
        names.add(path.relative_to(public).as_posix())
    for preset in [*manifest['cameraSets']['osmo']['presets'],*manifest['cameraSets']['osmo']['photos']]:names.add(preset['source'])
    for name in names:
        if not ALLOWED.fullmatch(safe_relative(name)):raise ValueError('Not an approved public asset: '+name)
    rows=[local_row(public,name) for name in sorted(names)];by_name={r['path']:r for r in rows}
    if by_name[asset['url']]['sha256']!=candidate['sha256'] or by_name[asset['url']]['bytes']!=asset['fileBytes']:raise ValueError('Native candidate changed after build')
    if candidate['sha256'][:10] not in asset['url']:raise ValueError('Native model filename is not content-addressed')
    if asset.get('simple') and (by_name[asset['simple']['url']]['bytes']!=asset['simple']['fileBytes'] or by_name[asset['simple']['url']]['sha256'][:10] not in asset['simple']['url']):raise ValueError('Simple shapes changed after build')
    if by_name[build['manifestName']]['sha256'][:10] not in build['manifestName']:raise ValueError('Manifest filename is not content-addressed')
    with (public/asset['url']).open('rb') as f:header=f.read(12)
    if asset['format']=='sog' and header[:4]!=b'PK\x03\x04':raise ValueError('Not a SOG ZIP')
    if asset['format']=='spz' and not (header[:2]==b'\x1f\x8b' or header[:4]==b'NGSP'):raise ValueError('Not an SPZ file')
    old_dir=here.parent.parent.parent/'mobile-20261029/iphone-baseline';old=json.loads((old_dir/'manifest.json').read_text(encoding='utf-8'))
    inherited=set()
    for key,(url,length,digest) in IPHONES.items():
        if manifest['models'][key]!=old['models'][key] or manifest['models'][key]['url']!=url or manifest['models'][key]['fileBytes']!=length:raise ValueError('iPhone metadata changed')
        row=local_row(public,url)
        if row['sha256']!=digest or row['bytes']!=length:raise ValueError('iPhone model bytes changed')
        inherited.update([url,url+'.gz']);preview=manifest['models'][key].get('preview')
        if preview:inherited.add(preview)
    if manifest['cameraSets']['iphone']!=old['cameraSets']['iphone']:raise ValueError('iPhone cameras changed')
    for preset in [*manifest['cameraSets']['iphone']['presets'],*manifest['cameraSets']['iphone']['photos']]:
        if preset.get('source'):inherited.add(preset['source'])
    inherited_rows=[local_row(public,name) for name in sorted(inherited)]
    for row in inherited_rows:
        reference=old_dir/row['path']
        if sha(reference)!=row['sha256']:raise ValueError('Inherited iPhone source or gzip differs')
    # Dependencies may be fetched only after Open. Keep their exact total measurable.
    application_bytes=sum(r['bytes'] for r in rows if r['path'].endswith(('.js','.json')))
    if application_bytes>6000000:raise ValueError('Lazy application JS/manifest exceeds 6 MB')
    return {'build':build,'candidate':candidate,'manifest':manifest,'files':rows,'inherited_files':inherited_rows,'application_bytes':application_bytes,'public':str(public)}

def quality_gate(audit,approval,here=HERE):
    build=audit['build'];candidate=audit['candidate'];asset=build['osmo']
    if build.get('provisional') is not False or build.get('newTrainingNotUsed') is not False or candidate.get('newTraining') is not True:raise ValueError('Old/provisional baseline cannot be deployed as new reconstruction')
    if not re.fullmatch(r'20\d{6}-[a-z0-9-]+',build['build']):raise ValueError('Unsafe release name')
    approved=json.loads(approval.read_text(encoding='utf-8'))
    if approved.get('approvedForDeployment') is not True or approved.get('releaseId')!=build['build'] or approved.get('modelSha256')!=candidate['sha256']:raise ValueError('Root release review does not approve this exact model/release')
    manifest_sha=next(r['sha256'] for r in audit['files'] if r['path']==build['manifestName'])
    if approved.get('manifestSha256')!=manifest_sha:raise ValueError('Root review identifies another build manifest')
    required=['sevenSourceViewsReviewed','returnBathroomContinuityAccepted','heldoutAppearanceAccepted','compressionComparedAtMatchedPoses','viewerQuotaAndErrorsPassed','cleanFullHeightDollhouseAccepted','topAndReversibleShellAccepted','fourDetailSharpnessLeapAccepted','totalModelDownloadWithin50MB','zeroModelBytesBeforeOpen','iphoneHashesPreserved']
    if not all(approved.get('qualityChecks',{}).get(name) is True for name in required):raise ValueError('New-model quality checks incomplete')
    if approved.get('physicalPhones') not in ['unverified','verified']:raise ValueError('Physical device verification must be stated accurately')
    if approved.get('transientLodMemoryLimitationAcknowledged') is not True:raise ValueError('Record the remaining transient LoD memory limit')
    evidence=approved.get('evidence',[])
    if not evidence:raise ValueError('Review must link concrete local evidence')
    for row in evidence:
        path=(here/row['path']).resolve()
        if not path.is_file() or sha(path)!=row['sha256']:raise ValueError('Review evidence missing or changed')
    packing=json.loads((here/candidate['packingReport']).read_text(encoding='utf-8'));source=Path(packing['source']).resolve()
    if not any(part in source.parts for part in ['clean-v3','parity-20261101']) or 'training' not in source.parts:raise ValueError('Packing did not come from an audited clean training output')
    if packing['sha256']!=candidate['sha256'] or packing['splats']!=asset['splats'] or packing['shDegree']!=asset['shDegree'] or packing.get('sourceCountPreserved') is not True or packing.get('sourceShDegreePreserved') is not True:raise ValueError('Packing/count/SH provenance mismatch')
    if sha(source)!=packing['sourceSha256']:raise ValueError('Source checkpoint changed after packing')
    cameras_path=(here/candidate['cameras']).resolve();cameras=json.loads(cameras_path.read_text(encoding='utf-8'));presets=cameras['presets']
    if len(presets)<7 or not any(49<=p['sourceTimeSeconds']<=56 for p in presets):raise ValueError('Missing return-bathroom QA camera')
    if cameras['coordinateFrame']!='+Y up':raise ValueError('Fresh cameras must declare the normalized frame')
    norm=json.loads(Path(cameras['normalizationEvidence']).read_text(encoding='utf-8'))
    if norm.get('applied') is not True or norm.get('old_reconstruction_opened') is not False or norm.get('learned_depth_opened') is not False:raise ValueError('Fresh normalization evidence failed')
    if sha(cameras_path)!=approved.get('freshCameraExportSha256'):raise ValueError('Fresh cameras changed after review')
    return approved

def package(audit,approval,previous,here=HERE):
    quality_gate(audit,approval,here)
    if not re.fullmatch(r'/var/www/rumah/releases/20\d{6}-[a-z0-9-]+',previous):raise ValueError('Unsafe expected previous release')
    release='/var/www/rumah/releases/'+audit['build']['build'];staging='/var/lib/vz/rumah-deploy/'+audit['build']['build']
    if release==previous:raise ValueError('New and previous releases must differ')
    output=here/'deployment';output.mkdir(exist_ok=True)
    if any(output.iterdir()):raise FileExistsError('Use a fresh reviewed release package; deployment/ already contains artifacts')
    archive=output/'native-site.tar'
    with tarfile.open(archive,'w') as tar:
        for row in audit['files']:
            path=Path(audit['public'])/row['path'];info=tar.gettarinfo(str(path),arcname=row['path'])
            info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644
            with path.open('rb') as f:tar.addfile(info,f)
    digest=sha(archive);rows=audit['files']+audit['inherited_files']
    info={'release':release,'previous':previous,'staging':staging,'container':710,'archive_sha256':digest,'archive_bytes':archive.stat().st_size,'remote_archive':staging+'/native-site-'+digest+'.tar.partial','files':audit['files'],'inherited_files':audit['inherited_files'],'build':audit['build']['build'],'manifest':audit['build']['manifestName'],'bundle':audit['build']['bundleName'],'model':audit['build']['osmo'],'model_sha256':audit['candidate']['sha256'],'index_sha256':next(r['sha256'] for r in rows if r['path']=='index.html'),'approval_sha256':sha(approval),'application_bytes':audit['application_bytes'],'model_transfer_in_verification':'HEAD only; bounded 12-byte range if length absent','automatic_rollback':True}
    template=(here/'deploy-native.template.sh').read_text(encoding='utf-8')
    values={'RELEASE':release,'PREVIOUS':previous,'TASK':staging,'REMOTE_ARCHIVE':info['remote_archive'],'ARCHIVE_SHA':digest,'INDEX_SHA':info['index_sha256'],'MANIFEST':info['manifest'],'MANIFEST_SHA':next(r['sha256'] for r in rows if r['path']==info['manifest']),'MODEL':info['model']['url'],'MODEL_BYTES':str(info['model']['fileBytes']),'HASHES':'\n'.join(r['sha256']+'  '+r['path'] for r in rows),'DETACH':'\n'.join('pct exec 710 -- rm -f -- "$RELEASE/'+r['path']+'"' for r in audit['files']),'PHONE_INODES':' '.join(r['path'] for r in audit['inherited_files'] if r['path'].endswith(('.glb','.glb.gz'))),'JS_HEADS':' '.join(r['path'] for r in rows if r['path'].endswith('.js'))}
    inherited_by_name={r['path']:r for r in audit['inherited_files']}
    values['GZIP_HEADS']='\n'.join(url+' '+str(length)+' '+str(inherited_by_name[url+'.gz']['bytes']) for url,length,_ in IPHONES.values())
    for name,value in values.items():template=template.replace('__'+name+'__',value)
    if re.search(r'__[A-Z_]+__',template):raise ValueError('Unfilled runner marker')
    (output/'deploy-native.sh').write_bytes(template.encode())
    rollback=(here/'rollback-native.template.sh').read_text(encoding='utf-8').replace('__RELEASE__',release).replace('__PREVIOUS__',previous).replace('__TASK__',staging)
    (output/'rollback-native.sh').write_bytes(rollback.encode())
    info['runner_sha256']=sha(output/'deploy-native.sh');info['rollback_sha256']=sha(output/'rollback-native.sh')
    (output/'deployment-manifest.json').write_text(json.dumps(info,indent=2))
    return info

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--audit-only',action='store_true');p.add_argument('--approval',type=Path);p.add_argument('--previous',default='/var/www/rumah/releases/20261031-osmo-v3');args=p.parse_args()
    audit=collect()
    if args.audit_only:print(json.dumps({'auditPassed':True,'provisional':audit['build']['provisional'],'files':len(audit['files']),'applicationBytes':audit['application_bytes'],'nativeBytes':audit['build']['osmo']['fileBytes'],'iphoneHashesPreserved':True,'remoteCalls':0,'packageCreated':False},indent=2))
    else:
        if not args.approval:p.error('--approval is required for a final reviewed release package')
        info=package(audit,args.approval,args.previous);print(json.dumps({k:info[k] for k in ['release','previous','archive_bytes','archive_sha256','remote_archive']},indent=2))
