"""Read-only project inventory, file-purpose catalog and deduplicated asset queue.

Does not follow directory links, delete files, train models or contact servers.
Every file is catalogued. Classification is a review aid, never proof of disuse.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,ast,csv,hashlib,json,os,re,shutil,time

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/'docs/repo-audit-2026-11-01'
CAP=Path('C:/Users/bombe/OneDrive/Documents/ChatGPT/Ruang Kamare/roomscan-reconstruction/data/20261031_OSMO360')
DEPENDENCIES={'node_modules','pydeps','qa-deps','tsdfdeps','site-packages','vendor','runtime','.venv'}
MODEL_EXT={'.glb','.ply','.sog','.spz','.splat','.ksplat','.rad'}
CODE_EXT={'.py','.js','.mjs','.ps1','.sh','.html','.css','.ts','.c','.cpp','.h','.bat'}
TEXT_EXT=CODE_EXT|{'.json','.jsonl','.txt','.md','.yaml','.yml','.toml','.csv','.sftp','.example'}
PHASES={
 'hosting':'Original public-site and Proxmox LXC 710 delivery; includes local access helpers.',
 'mobile-20261029':'iPhone mobile viewer, mesh packing and shared Node dependency lockfiles.',
 'fullheight-20261029':'Historical iPhone ceiling / cabinet-height repair and deployment evidence.',
 'import-osmo-20261031':'Verified card-to-project transfer of OSV original and LRF proxy.',
 'osmo-format-20261031':'OSV format, colour, calibration and fisheye approximation investigations.',
 'osmo-reconstruct-20261031':'Reusable COLMAP/fisheye I/O and earlier depth-guided reconstruction.',
 'osmo-improve-20261031':'Surface, photometric and photo-baking utilities reused by later work.',
 'osmo-normal-audit-20261031':'Evidence about depth normals and scene orientation.',
 'osmo-web-20261031':'Historical first Osmo mesh delivery; not the current public release.',
 'osmo-web-20261031-v2':'Historical chooser / quota changes and delivery experiments.',
 'osmo-web-20261031-v3':'Historical mesh release and source for retained iPhone assets.',
 'osmo-clean-20261031':'Current public Gaussian release sources plus clean calibration/masks/pipeline.',
 'osmo-parity-20261101':'Latest local rejected rebuild, corrected controls, pilots, surface tests and gates.',
 'osmo-ux-report-20261031':'Previous 73-page quality report, source snapshot and partial historical graph.',
 'osmo-pdf-audit':'Earlier video-to-model report authoring and verification.',
 'report':'Original architectural report and Nikon/Samsung/iPhone reference evidence.',
 'recovery-report':'Historical iPhone recovery verification and supporting evidence.',
 'cleanup-20261031':'Prior cleanup plan, deletion receipts and protected-file checks.',
 'disk-audit-20261031':'Historical storage inventory; read as historical, not current sizes.',
 'tools':'Workspace inventory, cleanup, backup and audit-document helpers added for this handoff.',
 'docs':'Auditor handoff records and machine-readable inventories.',
 'output':'Recent finalized PDFs; current audit PDF is generated after the inventory snapshot.',
 'outputs':'Earlier user-facing exports, offline viewers, reports and verification receipts.',
 'tmp':'Intermediate PDF renders and diagnostic derivatives; original evidence is classified separately.',
 '(root)':'Start-here README, Git exclusions and the small cloud-asset identity manifest.',
}
PURPOSE={
 'room-viewer.js':'Interactive 3D camera, mode switching, controls, rendering and loading states.',
 'room-shell.html':'Chooser and viewer page markup; explicit Open gates model downloads.',
 'chooser.js':'Starts the selected viewer only after the explicit Open action.',
 'choice-core.js':'Canonical model-choice aliases and one-launch lifecycle logic.',
 'loader-core.js':'Model selection, budgets, streaming progress, cancellation and deadlines.',
 'native-delivery.js':'Gaussian format mapping, splat budgets and first visible-draw readiness.',
 'delivery-policy.js':'Mesh download, decoded geometry and texture limits.',
 'gaussian-cutaway.js':'Experimental reversible splat ceiling / wall cutaway; visual gate failed.',
 'build.mjs':'Builds a local web bundle and manifest; contains stage-specific paths.',
 'build-entry.js':'Generated substituted build input; derived from room-viewer.js and manifest.',
 'candidate.json':'Exact selected Osmo artifact path, bytes, SHA and calibrated camera set.',
 'build-report.json':'Bundle/manifest names, policy and build provenance; identifies asset closure.',
 'release-approval.json':'Exact release sign-off or refusal. Latest review is explicitly refused.',
 'prepare-deploy.py':'Audits file closure and hashes; packages only an approved exact release.',
 'deploy-native.ps1':'Explicit remote deployment runner; changes production only on execution.',
 'repromote-native.ps1':'Operational repromotion helper; inspect exact release before execution.',
 'verify-public-native.py':'Public HTML / headers and bounded model verification; not a new rebuild.',
 'rollback-native.template.sh':'Template for returning the public symlink to the previous release.',
 'deploy-native.template.sh':'Remote atomic deployment template for the approved package.',
 'remote.py':'Local SSH/SFTP access helper reused by deployment runners; keep access material private.',
 'seed_fisheye.py':'COLMAP camera/image/track reader, fisheye rays, world transforms and seed export.',
 'build_explicit_pinhole.py':'Materializes calibrated pinhole RGB/masks from native fisheye source frames.',
 'normalize_fresh_sfm.py':'Checks scene continuity and applies one audited +Y-up normalization.',
 'operator_pinhole.py':'Projects operator-mask evidence between native fisheye and pinhole coordinates.',
 'select_frames.py':'Selects native capture timestamps and records original source timing.',
 'build_masks.py':'Builds per-frame operator and mirror exclusion masks.',
 'mirror_annotations.py':'Reviewed mirror-region annotations; source masking evidence.',
 'publish_masks.py':'Publishes reviewed source masks into the clean dataset.',
 'fit_explicit_depth.py':'Fits/checks depth in the explicit calibrated pinhole frame.',
 'validate_explicit_depth.py':'Cross-time visibility/consistency checks and trusted depth/seed construction.',
 'run_logged_job.py':'Runs a command with durable status, timing, log and exit-code records.',
 'continue_explicit_full.py':'Stage orchestration for the explicit full-scene training pipeline.',
 'photo_bake_agent.py':'Native source-photo projection and visibility-tested mesh texture baker.',
 'photo-bake-implementation.py':'Pilot-specific copied/adapted photo-bake implementation; provenance source.',
 'pack-sog.py':'Official SOG packing wrapper with source count, SH and hash provenance.',
 'pack-spz.mjs':'Native Gaussian SPZ packing experiment.',
 'export-clean-cameras.py':'Exports calibrated camera presets, source crops and scene framing metadata.',
 'occupied_bounds.py':'Computes robust dense occupied bounds, fitted planes and framing samples.',
 'prepare-highres.py':'Builds the controlled 1600px Lanczos dataset and reuses exact trusted guidance.',
 'pilot-runs.py':'Matched 1200/1600 small training experiments; not automatic full promotion.',
 'start-full.py':'Executed 50k high-resolution training request; inspect prior status before rerun.',
 'diagnostic-pilots.py':'8k geometry/primitive/exposure diagnostic groups.',
 'sparse-init-pilot.py':'8k RGB-only diagnostic replacing the dense starting cloud with sparse features.',
 'verify-input-contract.py':'Verifies camera/seed/guidance identity and preserved original/iPhone hashes.',
 'record-acceptance.py':'Writes the four explicit release-gate decisions and supporting evidence.',
 'audit-staging.py':'Local package/file audit and test that the failed review cannot be approved.',
 'EXECUTION-STATE.json':'Latest execution summary: completed compute, failed visual acceptance, no deployment.',
 'acceptance-gates.json':'Four mandatory gates, their actual failures/passes and hashed screenshots.',
 'fuse-trusted.py':'GPU TSDF fusion of validated training-only Euclidean ray ranges.',
 'poisson-surface.py':'Screened Poisson from oriented validated samples and accurate SfM anchors.',
 'carve-poisson.py':'Removes closures contradicted by at least five distinct trusted timestamps.',
 'projected-poisson-uv.py':'Fast local planar UV patches and atlas packing on preserved compact geometry.',
 'unwrap-trusted.py':'Conformal atlas trial; slower superseded Poisson attempts are recorded.',
 'bake-coherent.py':'Chart-consistent source-photo selection with masks and first-hit visibility.',
 'simplify-poisson.mjs':'Boundary-preserving compact geometry and measured simplifier error.',
 'poisson-preview.py':'Regenerates typed vertex buffers from retained NPZ/seed geometry.',
 'unpack-vertex.py':'Regenerates mesh typed buffers from the retained vertex-colour PLY.',
 'pack-vertex.mjs':'Packs the vertex-colour mesh preview from generated typed buffers.',
 'pack-textured.mjs':'Packs/simplifies a textured mesh preview.',
 'pack-baked.mjs':'Packs the photo-baked mesh; image data and source geometry remain separately audited.',
 'prepare-qa.py':'Creates fixed-pose source references and model links for comparisons.',
 'qa-viewer.js':'Local-only fixed-pose model comparison renderer.',
 'qa-capture.mjs':'Captures the four exact 1920x1080 views and surface overviews.',
 'score-qa.py':'Masked same-pose comparison scores and fixed 600px crops.',
 'display-ablation.mjs':'Eight display-only blur/DPR/splat-budget comparisons.',
 'verify-controls.mjs':'Browser navigation, explicit-open, preset and release-state checks.',
 'verify-choice-and-phone-policy.mjs':'Pre-choice network checks and emulated touch/DPR policy checks.',
 'make-acceptance-report.py':'Builds the 20-page execution/failed-acceptance PDF.',
 'serve.mjs':'Local review HTTP server; does not publish production.',
 'server.mjs':'Stage-specific local review HTTP server.',
 'review-server.mjs':'Stage-specific local preview server.',
 'repo_audit.py':'Creates this full inventory, role catalog and unique model/video upload queue.',
}
ROLES={
 'CORE':('First-party source / configuration','KEEP','Authored logic or configuration; inspect dependencies before removal.'),
 'TEST':('First-party verification','KEEP','Regression/validation evidence for the corresponding source stage.'),
 'AUDIT':('Audit record / provenance','KEEP','Records inputs, hashes, settings, gate results or historical operations.'),
 'MODEL':('3D model / point cloud','ASSET','Binary export; keep outside Git and map to the Drive backup.'),
 'MEDIA':('Source or reference image/video','REVIEW','May be source masking/evaluation evidence; not disposable solely by extension.'),
 'REPORT':('Report / user-facing export','KEEP','Previously delivered document or offline scene package.'),
 'VENDOR':('Third-party dependency','LOCAL','Reinstall only after preserving lock/version/license and platform requirements.'),
 'RUNTIME':('Pinned binary/runtime','LOCAL','Required local execution tool; not project source. Keep pinned version provenance.'),
 'BUILD':('Generated browser build','GENERATED','Rebuild from source; current index/manifest closure is important for local preview.'),
 'CACHE':('Regenerable cache','DELETE','Python bytecode or equivalent cache; no authored source.'),
 'TEMP':('Temporary diagnostic/report derivative','REVIEW','Confirm a retained source or completed report before deletion.'),
 'BUFFER':('Generated typed geometry buffer','DELETE*','Delete only when a retained source NPZ/PLY and regeneration script exist.'),
 'FIXTURE':('Generated test fixture','DELETE','Temporary deployment-test sandbox; not a real release.'),
 'ARCHIVE':('Packaged archive / transport copy','REVIEW','Often redundant, but check only-copy and historical restoration requirements.'),
 'OTHER':('Unresolved file role','REVIEW','No deletion authorized on name alone; inspect before removal.'),
}

def digest(path):
    h=hashlib.sha256();md=hashlib.md5()
    with path.open('rb') as f:
        while chunk:=f.read(8*1024*1024):h.update(chunk);md.update(chunk)
    return h.hexdigest(),md.hexdigest()

def phase_for(rel):
    parts=Path(rel).parts
    if len(parts)==1:return '(root)'
    if parts[0]=='work' and len(parts)>1:return parts[1]
    return parts[0]

def classify(rel):
    p=Path(rel);parts=set(p.parts);name=p.name;ext=p.suffix.lower();slash=p.as_posix()
    if '__pycache__' in parts or ext in {'.pyc','.pyo'}:return 'CACHE'
    if any(part.startswith('deploy-audit-fixture-') for part in p.parts):return 'FIXTURE'
    if any(part.startswith('source-v20') for part in p.parts):return 'VENDOR'
    if parts&DEPENDENCIES:
        return 'RUNTIME' if 'runtime' in parts else 'VENDOR'
    if ext in MODEL_EXT:return 'MODEL'
    if p.parts[0]=='tmp':return 'TEMP'
    if ext=='.tmp' or name.endswith('.pid'):return 'TEMP'
    if '.before-' in name:return 'CORE' if any(x in name for x in ['.py.','.js.','.mjs.','.html.']) else 'AUDIT'
    if '.failed-' in name or '.first-failed' in name or name.startswith('.graphify_'):return 'AUDIT'
    if ext in {'.pdf','.docx','.pptx'} or p.parts[0]=='outputs' and ext=='.html':return 'REPORT'
    if ext in {'.zip','.tar','.gz','.7z'}:return 'ARCHIVE'
    if ext in {'.png','.jpg','.jpeg','.webp','.mov','.mp4','.osv','.lrf','.insv'}:return 'MEDIA'
    if ext=='.bin' and name in {'position.bin','normal.bin','color.bin','indices.bin','compact-position.bin','compact-normal.bin','compact-indices.bin'}:return 'BUFFER'
    if 'public' in parts or name=='build-entry.js' or name.endswith('-bundle.js'):return 'BUILD'
    if '.test.' in name or name.startswith('test_') or name.startswith('test-'):return 'TEST'
    if ext in CODE_EXT|{'.proto'} or name in {'package.json','package-lock.json','.gitignore','README.md','README.txt'}:return 'CORE'
    if ext in {'.json','.jsonl','.log','.md','.txt','.csv','.sftp','.npz','.npy','.headers','.yaml','.yml','.toml'}:return 'AUDIT'
    return 'OTHER'

def purpose(path,rel,role):
    p=Path(rel);name=p.name;phase=phase_for(rel)
    if name in PURPOSE:return PURPOSE[name],'reviewed filename + source context'
    if role in {'VENDOR','RUNTIME'}:
        anchor=next((x for x in p.parts if x in DEPENDENCIES or x.startswith('source-v20')),'third-party');idx=p.parts.index(anchor) if anchor in p.parts else 0;package=p.parts[idx+1] if idx+1<len(p.parts) else anchor
        return f'{ROLES[role][0]}: {package}; file within {anchor}.','package/path classification'
    if role=='CORE' or role=='TEST':
        if path.suffix=='.py' and path.stat().st_size<1000000:
            try:
                doc=ast.get_docstring(ast.parse(path.read_text(encoding='utf-8-sig')))
                if doc:
                    intro=re.sub(r'\s+',' ',doc.split('\n\n',1)[0]).strip()
                    if len(intro)>300:
                        sentences=re.split(r'(?<=[.!?])\s+',intro);short=''
                        for sentence in sentences:
                            candidate=(short+' '+sentence).strip()
                            if len(candidate)>300:break
                            short=candidate
                        intro=short or intro[:297].rsplit(' ',1)[0]+'...'
                    return intro,'module introductory docstring'
            except (SyntaxError,UnicodeError,OSError):pass
        return (('Verification helper: ' if role=='TEST' else 'Stage utility: ')+name.replace('_',' ').replace('-',' ')+'. '+PHASES.get(phase,''))[:250],'name/path inference; verify before deletion'
    if role=='MODEL':
        if 'iphone' in name.lower() or 'iPhone' in name:return 'iPhone scene export; compare hash with the protected Fast/Full assets.','asset name + manifest context'
        if 'osmo-parity-20261101' in p.parts:return 'Latest Osmo experiment/model; rejected visual acceptance, not a public release.','stage and acceptance record'
        if 'osmo-clean-20261031' in p.parts:return 'Clean Osmo model/checkpoint; current release and historical variants coexist.','stage and manifest context'
        return 'Historical scene/model export; preserve identity and upload mapping before removal.','file type + stage'
    if role=='MEDIA':
        if any(x in p.parts for x in ['masks','masking']):return 'Mask/source review evidence used to exclude operator/mirror pixels.','path and capture workflow'
        if 'sources' in p.parts:return 'Source photograph used by a web comparison preset.','path and viewer workflow'
        if 'qa' in p.parts or 'display-ablation' in p.parts:return 'Fixed-view rendering, reference or crop supporting visual acceptance.','path and QA workflow'
        return 'Reference/evidence image in '+phase+'.','file type + stage; inspect exact use'
    if role=='BUFFER':return 'Transient numeric geometry array; reconstruct from retained source NPZ/PLY.','known packing pipeline'
    if role=='CACHE':return 'Generated Python bytecode; interpreter recreates it from retained source.','cache format'
    if role=='FIXTURE':return 'Synthetic deployment-test file produced in a temporary fixture directory.','temporary fixture path'
    if role=='AUDIT':
        if name.endswith('.npz'):return 'Intermediate geometry/measurements; may be the only full-precision surface source.','file type + experiment context'
        if 'request' in name or 'train-job' in name:return 'Executed/proposed command, inputs and output paths; inspect status before rerunning.','filename + pipeline convention'
        if 'approval' in name or 'acceptance' in name:return 'Quality acceptance/refusal record; not permission to publish another model.','filename + release workflow'
        if 'manifest' in name:return 'Asset or input inventory with identities and file references.','manifest convention'
        if 'verification' in name or 'audit' in name or 'report' in name:return 'Validation/measurement result; historical unless regenerated against current files.','filename convention'
        if name.endswith('.log') or name.endswith('.jsonl'):return 'Append-only process/request/deletion log; useful for forensic review.','log format'
        return 'Stage metadata, parameters or provenance: '+name+'.','filename/path inference'
    return ROLES[role][2],'file type/path classification'

def scan():
    rows=[];errors=[];started=time.monotonic()
    for base,dirs,files in os.walk(ROOT,followlinks=False):
        dirs[:]=[d for d in dirs if d not in {'.git','.local'} and not (Path(base)/d).is_symlink() and not (hasattr(Path(base)/d,'is_junction') and (Path(base)/d).is_junction())]
        for name in files:
            p=Path(base)/name;rel=p.relative_to(ROOT).as_posix()
            if p.is_relative_to(AUDIT) or p.is_relative_to(ROOT/'tmp/pdfs/repo-audit-20261101') or p==ROOT/'output/pdf/Rumah_Repository_Map_and_Cleanup_Audit_2026-11-01.pdf':continue # exclude this generated audit pack from its own inventory
            try:
                st=p.stat();role=classify(rel);desc,basis=purpose(p,rel,role)
                row={'path':rel,'bytes':st.st_size,'extension':p.suffix.lower(),'phase':phase_for(rel),'role':role,'action':ROLES[role][1],'purpose':desc,'basis':basis,'device':str(st.st_dev),'file_id':str(st.st_ino),'links':st.st_nlink,'modified_ns':st.st_mtime_ns}
                if role in {'CORE','TEST'} and st.st_size<2_000_000:row['sha256']=digest(p)[0]
                rows.append(row)
            except OSError as e:errors.append({'path':rel,'error':str(e)})
    rows.sort(key=lambda x:x['path'].casefold());groups=defaultdict(list)
    for r in rows:groups[(r['device'],r['file_id'])].append(r)
    byphase={}
    for phase in sorted({r['phase'] for r in rows}):
        rs=[r for r in rows if r['phase']==phase];byphase[phase]={'description':PHASES.get(phase,''),'files':len(rs),'logical_bytes':sum(r['bytes'] for r in rs),'roles':dict(Counter(r['role'] for r in rs))}
    summary={'workspace':str(ROOT),'hasGitMetadata':(ROOT/'.git').exists(),'files':len(rows),'logical_bytes':sum(r['bytes'] for r in rows),'unique_local_file_identity_bytes':sum(g[0]['bytes'] for g in groups.values()),'hardlink_groups':sum(len(g)>1 for g in groups.values()),'roles':dict(Counter(r['role'] for r in rows)),'phases':byphase,'errors':errors,'seconds':time.monotonic()-started,'scope':'Workspace only; docs/repo-audit-2026-11-01 inventory outputs excluded to prevent self-reference. External capture and runtimes listed separately. Unique identity bytes are not guaranteed reclaimable bytes: links may exist outside the workspace.'}
    return rows,summary

def save_inventory(label):
    AUDIT.mkdir(parents=True,exist_ok=True);rows,summary=scan();(AUDIT/f'inventory-{label}.json').write_text(json.dumps({'summary':summary,'roles':ROLES,'files':rows},indent=2),encoding='utf-8')
    with (AUDIT/f'file-catalog-{label}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        columns=['path','bytes','phase','role','action','purpose','basis','sha256','file_id','links'];w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
    print(json.dumps({'label':label,**{k:v for k,v in summary.items() if k not in ['phases','errors','scope']}},indent=2),flush=True)
    return rows,summary

def assets(rows):
    if (AUDIT/'deep-cleanup-result.json').exists():raise SystemExit('The A001-A056 archive is permanent. After deep cleanup use deep_cleanup_repo.py --refresh-manifest; do not replace the dated upload queue with only remaining local files.')
    candidates=[ROOT/r['path'] for r in rows if r['role']=='MODEL' and r['bytes']>=4096 and 'fixture' not in r['path']]
    # Source files are outside this workspace. OSV is the actual high-quality
    # capture; LRF is retained/uploaded as the matching low-resolution proxy.
    candidates += list((CAP/'originals').glob('*'))
    seed=CAP/'clean-v3/explicit-full-v1/dataset/seed-dense-train.ply'
    if seed.exists():candidates.append(seed)
    byidentity={};aliases=defaultdict(list)
    for p in candidates:
        s=p.stat();key=(s.st_dev,s.st_ino);aliases[key].append(str(p.resolve()));byidentity.setdefault(key,p)
    groups={};hash_count=0
    for key,p in byidentity.items():
        sha,md5=digest(p);hash_count+=1
        if sha not in groups:groups[sha]={'sha256':sha,'md5':md5,'bytes':p.stat().st_size,'extension':p.suffix.lower(),'source':str(p.resolve()),'aliases':[],'kind':'source-video' if p.suffix.lower() in {'.osv','.lrf'} else 'model'}
        groups[sha]['aliases'].extend(aliases[key])
        if hash_count%10==0:print('Hashed unique model/source files',hash_count,'/',len(byidentity),flush=True)
    entries=sorted(groups.values(),key=lambda r:(r['kind'],r['source'].casefold()))
    for i,r in enumerate(entries,1):
        r['asset_id']=f'A{i:03d}';p=Path(r['source']);phase=phase_for(p.relative_to(ROOT).as_posix()) if p.is_relative_to(ROOT) else 'external-osmo'
        r['phase']=phase;r['drive_name']=f'{phase}__{p.stem}__{r["sha256"][:10]}{r["extension"]}'
        if r['sha256'].startswith('2b811d1241'):r['drive_name']='iPhone-Fast__2b811d1241.glb';r['status']='protected live iPhone Fast'
        elif r['sha256'].startswith('16f8963b04'):r['drive_name']='iPhone-Full__16f8963b04.glb';r['status']='protected live iPhone Full'
        elif r['sha256'].startswith('cbb33c91b5'):r['drive_name']='Osmo-LIVE-20261031__cbb33c91b5.sog';r['status']='current public Osmo'
        elif r['sha256'].startswith('db0e94c2fa'):r['drive_name']='Osmo-REVIEW-REJECTED-20261101__db0e94c2fa.sog';r['status']='new rebuild, visual acceptance failed'
        elif r['kind']=='source-video':r['drive_name']=p.name;r['status']='original source' if r['extension']=='.osv' else 'matching preview proxy'
        else:r['status']='retained historical/experimental export; not automatically approved'
    data={'scope':'Unique non-vendor local 3D export files >=4KiB, all raw/uncompressed and packed variants; native OSV and LRF source; original trusted dense seed. Byte-identical files uploaded once and all local aliases recorded. Full optimizer checkpoints, extracted RGB and all external datasets are not claimed backed up.','entries':entries,'uniqueAssets':len(entries),'bytes':sum(r['bytes'] for r in entries),'sha256Provenance':'Locally computed from complete file contents','remoteHashVerification':'Drive connector metadata currently exposes size/parent identity, not checksums. Do not label local SHA as a Drive-readback hash.'}
    (AUDIT/'asset-upload-queue.json').write_text(json.dumps(data,indent=2),encoding='utf-8');print(json.dumps({'uniqueAssets':len(entries),'uploadBytes':data['bytes'],'models':sum(r['kind']=='model' for r in entries),'videos':sum(r['kind']=='source-video' for r in entries)},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--label',default='current');p.add_argument('--assets',action='store_true');p.add_argument('--capture',type=Path,default=CAP,help='External 20261031_OSMO360 capture folder for --assets');a=p.parse_args();CAP=a.capture
    if not re.fullmatch(r'[a-z0-9_-]+',a.label):p.error('Use a simple lowercase inventory label.')
    if (AUDIT/'deep-cleanup-result.json').exists() and a.label in {'before','after'}:p.error('Dated snapshots are preserved; use --label current or another new label.')
    rows,_=save_inventory(a.label)
    if a.assets:assets(rows)
