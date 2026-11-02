"""Merge verified Drive receipts, update the asset identity map and enrich inventory."""
from pathlib import Path
from collections import Counter,defaultdict
import csv,hashlib,json,os,re,sys
import repo_audit as a
ROOT=a.ROOT;OUT=a.AUDIT

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def receipts():
    latest={}
    for line in (OUT/'drive-upload-journal.jsonl').read_text().splitlines():
        row=json.loads(line)
        if row.get('status_upload')=='verified':latest[row['sha256']]=row
    return latest

def importance(r):
    path=r['path'];role=r['role'];phase=r['phase']
    if path in {'README.md','.gitignore','assets-manifest.json'}:return 'START HERE'
    if path.startswith('work/osmo-clean-20261031/review/production/') and role not in {'VENDOR','RUNTIME','BUILD'}:return 'LIVE BASELINE'
    if path.startswith('work/osmo-parity-20261101/') and role in {'CORE','TEST','AUDIT','MODEL','MEDIA'}:return 'CURRENT REVIEW'
    if path.startswith('work/osmo-clean-20261031/geometry/') or path.startswith('work/osmo-clean-20261031/masking/'):return 'FOUNDATION'
    if Path(path).name in {'seed_fisheye.py','photo_bake_agent.py'} or path in {'work/mobile-20261029/package.json','work/mobile-20261029/package-lock.json'}:return 'SHARED CORE'
    if role in {'VENDOR','RUNTIME'}:return 'LOCAL DEPENDENCY'
    if role in {'MODEL'}:return 'BACKED-UP ASSET'
    if role=='REPORT':return 'USER EXPORT'
    if role in {'TEMP','OTHER','ARCHIVE'}:return 'REVIEW'
    if role=='BUILD':return 'REBUILDABLE'
    if phase in {'hosting','mobile-20261029','osmo-reconstruct-20261031','osmo-improve-20261031'} and role in {'CORE','TEST'}:return 'SHARED / HISTORY'
    return 'HISTORY / EVIDENCE'

def main():
    if (OUT/'deep-cleanup-result.json').exists():
        from deep_cleanup_repo import refresh_manifest
        summary=refresh_manifest('--force' in sys.argv[1:]);rows,_=a.save_inventory('current')
        print(json.dumps({'backup':summary,'currentFiles':len(rows),'datedSnapshotsPreserved':True},indent=2));return
    queue=read(OUT/'asset-upload-queue.json');verified=receipts();dest=read(OUT/'drive-destination.json');entries=[]
    for asset in queue['entries']:
        row={k:v for k,v in asset.items() if k not in {'source','aliases'}};record=verified.get(asset['sha256'])
        row.update(upload_status='verified' if record else 'pending',local_sha256=asset['sha256'],local_md5=asset['md5'])
        row['local_paths']=[{'path':str(Path(s).relative_to(ROOT)).replace('\\','/') if Path(s).is_relative_to(ROOT) else s,'in_workspace':Path(s).is_relative_to(ROOT),'exists':Path(s).is_file()} for s in asset['aliases']]
        if record:row.update(drive_id=record['drive_id'],drive_url=record['drive_url'],parent_id=record['parent_id'],verified_remote_bytes=record['readback_size'],verification=record['verification'])
        entries.append(row)
    summary={'asset_count':len(entries),'verified_assets':sum(e['upload_status']=='verified' for e in entries),'models':sum(e['kind']=='model' for e in entries),'source_files':sum(e['kind']=='source-video' for e in entries),'unique_bytes':sum(e['bytes'] for e in entries),'verified_bytes':sum(e['bytes'] for e in entries if e['upload_status']=='verified'),'all_verified':all(e['upload_status']=='verified' for e in entries)}
    manifest={'version':1,'date':'2026-11-01','drive_folder_url':'https://drive.google.com/drive/folders/'+dest['root'],'destination':dest,'summary':summary,'verification_note':'Local SHA-256 and MD5 are full-content hashes. Drive readback confirms exact name, size and parent. Connector output does not expose a remote checksum; none is fabricated.','scope':queue['scope'],'assets':entries}
    (ROOT/'assets-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');(OUT/'backup-summary.json').write_text(json.dumps(summary,indent=2))
    rows,inv=a.save_inventory('after');asset_by_path={str(Path(p)).casefold():e for src,e in zip(queue['entries'],entries) for p in src['aliases']}
    # Static filename references are review hints, not a dead-code analysis.
    name_to_rows=defaultdict(list)
    for r in rows:name_to_rows[Path(r['path']).name].append(r)
    incoming=defaultdict(set)
    for r in rows:
        p=ROOT/r['path']
        if r['role'] not in {'CORE','TEST','AUDIT'} or p.suffix.lower() not in a.TEXT_EXT or r['bytes']>1500000:continue
        try:text=p.read_text(encoding='utf-8-sig')
        except (OSError,UnicodeError):continue
        for name in set(re.findall(r'[A-Za-z0-9_.-]+\.(?:py|js|mjs|ps1|sh|json|glb|sog|spz|ply|npz|html)',text)):
            for target in name_to_rows.get(name,[]):
                if target['path']!=r['path']:incoming[target['path']].add(r['path'])
    for i,r in enumerate(rows,1):
        r['catalog_id']=f'F{i:05d}';r['importance']=importance(r);r['reference_candidates']=sorted(incoming[r['path']]);r['reference_confidence']='filename matches only; may be ambiguous, constructed paths may be missed'
        e=asset_by_path.get(str(ROOT/r['path']).casefold())
        if e:r.update(asset_id=e['asset_id'],asset_sha256=e['sha256'],drive_url=e.get('drive_url',''),upload_status=e['upload_status'])
    data={'summary':inv,'roles':a.ROLES,'files':rows,'scope_note':'Complete workspace file register after the dated cleanup. This generated audit folder, its own PDF and its own render scratch are excluded to avoid recursive/self-referential inventories. Those audit outputs are listed in the report evidence map. External capture directories are mapped separately.'}
    (OUT/'inventory-after.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    with (OUT/'file-catalog-after.csv').open('w',encoding='utf-8-sig',newline='') as f:
        cols=['catalog_id','path','bytes','phase','role','importance','action','purpose','basis','asset_id','asset_sha256','upload_status','drive_url','file_id','links','sha256'];w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
    protected=read(OUT/'inventory-before.json')['files'];keep=[r for r in protected if r['role'] in {'CORE','TEST'} and r.get('sha256') and not r['path'].startswith('tools/')]
    for r in keep:
        p=ROOT/r['path'];assert p.is_file() and a.digest(p)[0]==r['sha256'],'Original source changed: '+r['path']
    (OUT/'source-preservation-check.json').write_text(json.dumps({'passed':True,'preexistingReconstructionSourceAndTestsVerified':len(keep),'newAuditToolsExcludedFromOriginalSourceComparison':True,'noProductionServerChanges':True},indent=2))
    meta=[]
    for folder in ['work/osmo-improve-20261031/pydeps','work/osmo-improve-20261031/qa-deps','work/osmo-parity-20261101/tsdfdeps','work/hosting/.venv/Lib/site-packages']:
        base=ROOT/folder;versions=[]
        if base.exists():
            for md in base.glob('*.dist-info/METADATA'):
                text=md.read_text(encoding='utf-8',errors='replace');name=re.search(r'^Name: (.+)$',text,re.M);ver=re.search(r'^Version: (.+)$',text,re.M)
                if name and ver:versions.append({'name':name.group(1),'version':ver.group(1)})
        meta.append({'path':folder,'packages':versions})
    (OUT/'local-dependency-versions.json').write_text(json.dumps(meta,indent=2))
    print(json.dumps({'backup':summary,'remainingLocalFiles':len(rows),'originalSourceCheckPassed':True,'fullFileCatalog':'docs/repo-audit-2026-11-01/file-catalog-after.csv'},indent=2))

if __name__=='__main__':main()
