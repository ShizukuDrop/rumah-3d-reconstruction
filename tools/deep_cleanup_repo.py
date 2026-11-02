"""Dated, exact-file deep cleanup authorized by the 2026-11-01 handoff mandate.

Default plans only. --apply rechecks containment, identity, bytes, hashes, cloud
receipts, canonical models, retained code and PDF preservation before deleting.
Never traverses or mutates the external capture tree or a directory junction.
"""
from pathlib import Path
from collections import defaultdict,Counter
import argparse,hashlib,json,os,re,shutil,time
import repo_audit as audit

ROOT=audit.ROOT.resolve();D=audit.AUDIT
RETIRED=['work/osmo-web-20261031','work/osmo-web-20261031-v2','work/osmo-web-20261031-v3','work/fullheight-20261029','work/osmo-ux-report-20261031/code','tmp']
CANONICAL={
 'A003':'work/mobile-20261029/public-phone.glb',
 'A006':'work/osmo-clean-20261031/review/checkpoints/explicit-full-final.ply',
 'A013':'work/osmo-clean-20261031/review/clean-final.sog',
 'A018':'work/osmo-parity-20261101/review/final-sharp.sog',
 'A034':'work/osmo-parity-20261101/review/qa/new-full-50000.ply',
}
ACTIVE=['work/osmo-clean-20261031','work/osmo-parity-20261101','work/osmo-reconstruct-20261031','work/osmo-improve-20261031','work/osmo-format-20261031','work/mobile-20261029']
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def guarded(p):
    absolute=p.resolve(strict=True)
    if absolute==ROOT or not absolute.is_relative_to(ROOT) or p.is_symlink():raise ValueError('Unsafe cleanup path: '+str(p))
    for ancestor in [p,*p.parents]:
        if ancestor==ROOT:break
        if ancestor.is_symlink() or getattr(ancestor,'is_junction',lambda:False)():raise ValueError('Linked path refused: '+str(p))
    return absolute
def current_public_names():
    keep=set(CANONICAL.values())
    for phase in ['osmo-clean-20261031','osmo-parity-20261101']:
        prod=ROOT/'work'/phase/'review/production';build=read(prod/'build-report.json');manifest=read(prod/'public'/build['manifestName'])
        for value in manifest['models'].values():
            keep.add((prod/'public'/value['url']).relative_to(ROOT).as_posix())
        for name in read(ROOT/'work/mobile-20261029/iphone-baseline/asset-files.json')['files']:
            keep.add('work/mobile-20261029/iphone-baseline/'+name['path'])
    return keep
def references():
    found=[]
    for prefix in ACTIVE:
        for base,dirs,files in os.walk(ROOT/prefix):
            dirs[:]=[n for n in dirs if n not in audit.DEPENDENCIES and n not in {'public','deployment','__pycache__'}]
            for name in files:
                p=Path(base)/name
                if p.suffix not in audit.CODE_EXT or name=='build-entry.js':continue
                text=p.read_text(encoding='utf-8',errors='replace')
                if re.search(r'osmo-web-20261031|fullheight-20261029',text):found.append(p.relative_to(ROOT).as_posix())
    if found:raise ValueError('Retired code/data path remains in retained source: '+', '.join(found))
    return {'retainedSourceScanPassed':True,'retiredRuntimePathMatches':[],'scope':ACTIVE,'historicalJsonProvenanceNotTreatedAsAnImport':True}
def make_plan():
    if (D/'deep-cleanup-journal.jsonl').exists():raise ValueError('Existing execution journal: do not replace this dated plan.')
    manifest=read(ROOT/'assets-manifest.json');assert manifest['summary']['all_verified'] and len(manifest['assets'])==56
    known={a['sha256']:a for a in manifest['assets']};by_id={a['asset_id']:a for a in manifest['assets']}
    keep=current_public_names();refs=references()
    for asset_id,rel in CANONICAL.items():
        p=ROOT/rel;guarded(p);assert sha(p)==by_id[asset_id]['sha256'],asset_id
    rows,summary=audit.scan();targets=[];cache={}
    for r in rows:
        rel=r['path'];p=ROOT/rel;reason=None
        if any(rel==prefix or rel.startswith(prefix+'/') for prefix in RETIRED):reason='Retired release / duplicate report source / finalized PDF scratch'
        elif rel in {'work/hosting/site.tar','work/hosting/public/models/iphone-full-room-16f8963b.glb.gz','outputs/iPhone_Wide_Full_Native_Offline.html','outputs/ARCHIVED_iPhone_Wide_Small_Review.html'} or rel.startswith('outputs/') and p.suffix.lower()=='.zip':reason='Redundant transport / embedded offline model export'
        elif rel.startswith(('work/osmo-clean-20261031/review/','work/osmo-parity-20261101/review/')) and p.suffix.lower() in audit.MODEL_EXT and rel not in keep:reason='Cloud-backed superseded trial or stale model alias'
        if not reason:continue
        assert rel not in keep
        assert not (p.suffix.lower()=='.pdf' and (rel.startswith('output/pdf/') or rel.startswith('outputs/')))
        guarded(p);key=(r['device'],r['file_id']);digest=cache.get(key)
        if not digest:digest=cache[key]=sha(p)
        asset=known.get(digest)
        if p.suffix.lower() in audit.MODEL_EXT:
            assert asset and asset['upload_status']=='verified' and asset['verified_remote_bytes']==r['bytes'],'No complete cloud model receipt: '+rel
        targets.append({**r,'sha256':digest,'reason':reason,'asset_id':asset['asset_id'] if asset else None,'restore_url':asset.get('drive_url') if asset else None})
    selected={r['path'] for r in targets};protected=[]
    for r in rows:
        if r['path'] not in selected and (r['role'] in {'CORE','TEST'} or r['path'] in keep or Path(r['path']).suffix.lower()=='.pdf'):
            protected.append({'path':r['path'],'bytes':r['bytes'],'sha256':sha(ROOT/r['path'])})
    groups=defaultdict(list)
    for r in targets:groups[(r['device'],r['file_id'])].append(r)
    released=sum(g[0]['bytes'] for g in groups.values() if len(g)==g[0]['links'])
    plan={'authorizedDate':'2026-11-01','workspace':str(ROOT),'references':refs,'canonical':CANONICAL,'filesBefore':summary['files'],'logicalBytesBefore':summary['logical_bytes'],'targets':targets,'protected':protected,'targetFiles':len(targets),'logicalBytesSelected':sum(r['bytes'] for r in targets),'estimatedBytesReleased':released,'hardlinkNote':'Only file identities whose complete link count is selected count as releasable; external hardlinks are never deleted.','families':dict(Counter(r['reason'] for r in targets))}
    (D/'deep-cleanup-plan.json').write_text(json.dumps(plan,indent=2));print(json.dumps({k:v for k,v in plan.items() if k not in {'targets','protected','references'}},indent=2))

def refresh_manifest(force=False):
    # The tracked manifest records the dated cleanup; rerunning on another checkout would rewrite it with that machine's local state.
    if not force and (D/'deep-cleanup-result.json').exists() and read(D/'deep-cleanup-result.json').get('complete'):raise SystemExit('Dated deep cleanup is complete; assets-manifest.json is the tracked 2026-11-01 record. Pass --force to rewrite its local_paths/local_status/canonical_local_path from this checkout.')
    p=ROOT/'assets-manifest.json';m=read(p)
    for a in m['assets']:
        historical=a.get('historical_local_paths',a['local_paths']);a['historical_local_paths']=historical
        existing=[]
        for row in historical:
            file=ROOT/row['path'] if row['in_workspace'] else Path(row['path'])
            if file.is_file():existing.append({**row,'exists':True})
        for prefix in ['work/mobile-20261029/iphone-baseline/models']:
            for f in (ROOT/prefix).glob('*'):
                if f.suffix.lower() in audit.MODEL_EXT and f.stat().st_size==a['bytes'] and sha(f)==a['sha256']:
                    rel=f.relative_to(ROOT).as_posix()
                    if rel not in {r['path'] for r in existing}:existing.append({'path':rel,'in_workspace':True,'exists':True})
        a['local_paths']=existing;a['local_status']='present' if existing else 'Drive archived; no registered local path'
        a['canonical_local_path']=CANONICAL.get(a['asset_id'],existing[0]['path'] if existing else None)
    m['version']=2;m['local_paths_refreshed']='2026-11-01 after mandated deep cleanup';m['summary']['assetsWithRemainingLocalPaths']=sum(bool(a['local_paths']) for a in m['assets']);m['summary']['archiveOnlyAssets']=sum(not a['local_paths'] for a in m['assets']);p.write_text(json.dumps(m,indent=2),encoding='utf-8')
    return m['summary']

def apply():
    if (D/'deep-cleanup-result.json').exists() and read(D/'deep-cleanup-result.json').get('complete'):raise SystemExit('Dated deep cleanup is already complete; no deletions repeated.')
    plan=read(D/'deep-cleanup-plan.json');assert plan['workspace']==str(ROOT);references()
    journal=D/'deep-cleanup-journal.jsonl';done={}
    if journal.exists():done={r['path']:r for r in map(json.loads,journal.read_text(encoding='utf-8').splitlines())}
    for r in plan['protected']:
        p=ROOT/r['path'];assert p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Protected source/model/report changed: '+r['path']
    free_before=shutil.disk_usage(ROOT).free;deleted=[];cache={}
    with journal.open('a',encoding='utf-8') as log:
        for r in plan['targets']:
            p=ROOT/r['path']
            if r['path'] in done:
                assert not p.exists(),'Executed target reappeared: '+r['path'];continue
            guarded(p);st=p.stat();key=(st.st_dev,st.st_ino)
            assert st.st_size==r['bytes'] and str(st.st_ino)==r['file_id'] and str(st.st_dev)==r['device']
            digest=cache.get(key)
            if not digest:digest=cache[key]=sha(p)
            assert digest==r['sha256'],'Target changed: '+r['path']
            p.unlink();entry={k:r.get(k) for k in ['path','bytes','sha256','device','file_id','links','reason','asset_id','restore_url']};entry['deleted']=True;log.write(json.dumps(entry)+'\n');log.flush();deleted.append(entry)
    for prefix in RETIRED:
        folder=ROOT/prefix
        if not folder.exists():continue
        guarded(folder)
        for base,dirs,files in os.walk(folder,topdown=False):
            directory=Path(base);guarded(directory)
            if not any(directory.iterdir()):directory.rmdir()
    for r in plan['protected']:
        p=ROOT/r['path'];assert p.is_file() and sha(p)==r['sha256'],'Preservation failed: '+r['path']
    summary=refresh_manifest();rows,after=audit.scan()
    result={'complete':True,'filesDeleted':len(done)+len(deleted),'logicalBytesRemoved':plan['logicalBytesSelected'],'estimatedPhysicalBytesReleased':plan['estimatedBytesReleased'],'measuredVolumeFreeDelta':shutil.disk_usage(ROOT).free-free_before,'hardlinkCaveat':plan['hardlinkNote'],'remainingFiles':len(rows),'remainingLogicalBytes':after['logical_bytes'],'canonicalAssetsVerified':len(CANONICAL),'protectedSourceModelAndReportFilesVerified':len(plan['protected']),'externalFilesDeleted':0,'productionServerChanges':0,'assetSummary':summary,'journal':'docs/repo-audit-2026-11-01/deep-cleanup-journal.jsonl'}
    (D/'deep-cleanup-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--refresh-manifest',action='store_true');parser.add_argument('--force',action='store_true');args=parser.parse_args()
    if args.apply:apply()
    elif args.refresh_manifest:print(json.dumps(refresh_manifest(args.force),indent=2))
    else:make_plan()
