"""Restore hash-verified downloads into this checkout without external writes.

Download the named private Drive files in a browser first. This utility never
handles Google credentials. Existing differing files are never overwritten.
Default restoration is the five retained canonical models, not all experiments.
iPhone Full and the obsolete mobile trial were retired by the user on 2026-11-03.
"""
from pathlib import Path,PurePosixPath
import argparse,gzip,hashlib,json,os,shutil,zipfile
from deep_cleanup_repo import RETIRED

ROOT=Path(__file__).resolve().parents[1]
CANONICAL={'A003':'work/mobile-20261029/public-phone.glb','A006':'work/osmo-clean-20261031/review/checkpoints/explicit-full-final.ply','A013':'work/osmo-clean-20261031/review/clean-final.sog','A018':'work/osmo-parity-20261101/review/final-sharp.sog','A034':'work/osmo-parity-20261101/review/qa/new-full-50000.ply'}
RETIRED_ASSET_IDS={'A001','A002'}
# Non-default exports whose only retained consumer reads a fixed path (work/osmo-clean-20261031/review/server.mjs).
CONSUMED={'A046':'outputs/restored-legacy/osmo-lite-30ed8cb766.glb'}
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def target(rel):
    if PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts or '\\' in rel:raise ValueError('Unsafe relative restore path')
    if any(PurePosixPath(rel.casefold()).is_relative_to(x) for x in RETIRED):raise ValueError('Retired folder destination refused (removed by the dated cleanup): '+rel)
    p=ROOT/rel
    if not p.resolve().is_relative_to(ROOT):raise ValueError('Restore escaped checkout')
    for ancestor in [p,*p.parents]:
        if ancestor==ROOT:break
        if ancestor.is_symlink() or getattr(ancestor,'is_junction',lambda:False)():raise ValueError('Linked restore destination refused')
    return p
def verify(p,row):
    if not p.is_file():raise FileNotFoundError('Missing file: '+str(p))
    if p.stat().st_size!=row['bytes'] or sha(p)!=row['sha256']:raise ValueError('File identity differs: '+str(p))
def place(src,dst,row):
    verify(src,row)
    if dst.exists():verify(dst,row);return
    dst.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(src,dst)
    except OSError:shutil.copyfile(src,dst)
    verify(dst,row)
def find(downloads,name,size):
    # Browser downloads of a Drive folder may arrive in subfolders; prefer the size match to skip partial copies (place() still hashes).
    found=[p for p in downloads.rglob(name) if p.is_file()]
    if not found:raise FileNotFoundError(name+' not found under --downloads '+str(downloads))
    return next((p for p in found if p.stat().st_size==size),found[0])
def archive(path,metadata,runtime=False):
    verify(path,{'bytes':metadata['archive_bytes'],'sha256':metadata['archive_sha256']})
    with zipfile.ZipFile(path) as z:
        for row in metadata['files']:
            dst=target(row['path']);entry=row.get('archive_entry',row['path'])
            if dst.exists():verify(dst,row);continue
            info=z.getinfo(entry)
            if info.file_size!=row['bytes']:raise ValueError('Archive entry size differs')
            dst.parent.mkdir(parents=True,exist_ok=True)
            try:
                with z.open(info) as src,dst.open('xb') as out:shutil.copyfileobj(src,out)
                verify(dst,row)
            except Exception:
                if dst.exists():dst.unlink()
                raise
def iphone_baseline(source_workspace=None,check=False):
    base=ROOT/'work/mobile-20261029/iphone-baseline';manifest=read(base/'manifest.json');catalog=read(base/'asset-files.json');by_path={r['path']:r for r in catalog['files']}
    for key,asset_id in [('phone','A003')]:
        model=manifest['models'][key];raw=base/model['url'];encoded=raw.with_suffix(raw.suffix+'.gz')
        if not check:
            place(target(CANONICAL[asset_id]),raw,by_path[model['url']])
            if not encoded.exists() and source_workspace:
                original=source_workspace/'work/mobile-20261029/iphone-baseline'/(model['url']+'.gz')
                if original.is_file():place(original,encoded,by_path[model['url']+'.gz'])
            if not encoded.exists():
                # Preserve Lite's original Node level 6 transfer encoding,
                # including the Windows OS header byte 10.
                with encoded.open('xb') as out:
                    with gzip.GzipFile(filename='',fileobj=out,mode='wb',compresslevel=6,mtime=0) as packed:
                        with raw.open('rb') as src:shutil.copyfileobj(src,packed)
                with encoded.open('r+b') as out:out.seek(9);out.write(bytes([10]))
        with gzip.open(encoded,'rb') as f:decoded=hashlib.file_digest(f,'sha256').hexdigest()
        if decoded!=by_path[model['url']]['sha256']:raise ValueError('Gzip does not decode to protected iPhone bytes')
        if encoded.stat().st_size!=model['downloadBytes']:print('Transfer encoding size differs across zlib versions; native model hash remains exact:',encoded.name)
    for row in catalog['files']:
        if not row['path'].endswith('.gz'):verify(base/row['path'],row)
def main():
    p=argparse.ArgumentParser();p.add_argument('--downloads',type=Path);p.add_argument('--from-workspace',type=Path);p.add_argument('--reference-archive',type=Path);p.add_argument('--runtime-archive',type=Path);p.add_argument('--ids',nargs='+',default=list(CANONICAL));p.add_argument('--check',action='store_true');a=p.parse_args()
    retired=sorted(set(a.ids)&RETIRED_ASSET_IDS)
    if retired:raise ValueError('Assets retired by the user on 2026-11-03 cannot be restored: '+', '.join(retired)+'; retain iPhone Lite A003 and Osmo only')
    manifest=read(ROOT/'assets-manifest.json');by_id={m['asset_id']:m for m in manifest['assets']}
    for asset_id in a.ids:
        row=by_id[asset_id];inside=[x['path'] for x in row.get('historical_local_paths',row['local_paths']) if x['in_workspace']]
        rel=CANONICAL.get(asset_id) or CONSUMED.get(asset_id) or next((x for x in [row.get('canonical_local_path'),*inside] if x in inside),None)
        if rel is None:raise ValueError('External capture restoration is manual; this utility never writes outside the checkout: '+asset_id)
        dst=target(rel)
        if dst.exists():verify(dst,row);continue
        if a.check:raise FileNotFoundError('Missing '+asset_id+': '+rel)
        source=find(a.downloads,row['drive_name'],row['bytes']) if a.downloads else a.from_workspace/rel if a.from_workspace else None
        if source is None:raise ValueError('Provide --downloads for verified browser downloads')
        place(source,dst,row)
    if not a.check:
        for arg,name in [(a.reference_archive,'viewer-resources.json'),(a.runtime_archive,'runtime-assets.json')]:
            if arg:meta=read(ROOT/'docs'/name);archive(arg if arg.exists() or not a.downloads else find(a.downloads,arg.name,meta['archive_bytes']),meta)
        if a.from_workspace:
            for row in read(ROOT/'docs/viewer-resources.json')['files']:place(a.from_workspace/row['path'],target(row['path']),row)
    else:
        for row in read(ROOT/'docs/viewer-resources.json')['files']:verify(target(row['path']),row)
    # Only Lite is retained. A subset restore/check without A003 skips its transfer copies.
    if target(CANONICAL['A003']).exists():iphone_baseline(a.from_workspace,a.check)
    print(json.dumps({'verifiedAssetIds':a.ids,'referenceFiles':len(read(ROOT/'docs/viewer-resources.json')['files']),'externalWrites':0,'networkRequests':0}))
if __name__=='__main__':main()
