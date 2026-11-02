"""Restore hash-verified downloads into this checkout without external writes.

Download the named private Drive files in a browser first. This utility never
handles Google credentials. Existing differing files are never overwritten.
Default restoration is the six protected canonical models, not all experiments.
"""
from pathlib import Path,PurePosixPath
import argparse,gzip,hashlib,json,os,shutil,zipfile

ROOT=Path(__file__).resolve().parents[1]
CANONICAL={'A001':'outputs/iPhone_Wide_Full_Native.glb','A003':'work/mobile-20261029/public-phone.glb','A006':'work/osmo-clean-20261031/review/checkpoints/explicit-full-final.ply','A013':'work/osmo-clean-20261031/review/clean-final.sog','A018':'work/osmo-parity-20261101/review/final-sharp.sog','A034':'work/osmo-parity-20261101/review/qa/new-full-50000.ply'}
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def target(rel):
    if PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts or '\\' in rel:raise ValueError('Unsafe relative restore path')
    p=ROOT/rel
    if not p.resolve().is_relative_to(ROOT):raise ValueError('Restore escaped checkout')
    for ancestor in [p,*p.parents]:
        if ancestor==ROOT:break
        if ancestor.is_symlink() or getattr(ancestor,'is_junction',lambda:False)():raise ValueError('Linked restore destination refused')
    return p
def verify(p,row):
    if not p.is_file() or p.stat().st_size!=row['bytes'] or sha(p)!=row['sha256']:raise ValueError('File identity differs: '+str(p))
def place(src,dst,row):
    verify(src,row)
    if dst.exists():verify(dst,row);return
    dst.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(src,dst)
    except OSError:shutil.copyfile(src,dst)
    verify(dst,row)
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
def iphone_baseline(source_workspace=None):
    base=ROOT/'work/mobile-20261029/iphone-baseline';manifest=read(base/'manifest.json');catalog=read(base/'asset-files.json');by_path={r['path']:r for r in catalog['files']}
    for key,asset_id in [('phone','A003'),('native','A001')]:
        model=manifest['models'][key];raw=base/model['url'];place(target(CANONICAL[asset_id]),raw,by_path[model['url']]);encoded=raw.with_suffix(raw.suffix+'.gz')
        if not encoded.exists() and source_workspace:
            original=source_workspace/'work/mobile-20261029/iphone-baseline'/(model['url']+'.gz')
            if original.is_file():place(original,encoded,by_path[model['url']+'.gz'])
        if not encoded.exists():
            # Preserve the original transfer recipes: Full was Python level 1
            # with FNAME; Fast was Node level 6 with Windows OS header byte 10.
            with encoded.open('xb') as out:
                with gzip.GzipFile(filename=raw.name if key=='native' else '',fileobj=out,mode='wb',compresslevel=1 if key=='native' else 6,mtime=0) as packed:
                    with raw.open('rb') as src:shutil.copyfileobj(src,packed)
            if key=='phone':
                with encoded.open('r+b') as out:out.seek(9);out.write(bytes([10]))
        with gzip.open(encoded,'rb') as f:decoded=hashlib.file_digest(f,'sha256').hexdigest()
        if decoded!=by_path[model['url']]['sha256']:raise ValueError('Gzip does not decode to protected iPhone bytes')
        if encoded.stat().st_size!=model['downloadBytes']:print('Transfer encoding size differs across zlib versions; native model hash remains exact:',encoded.name)
    for row in catalog['files']:
        if not row['path'].endswith('.gz'):verify(base/row['path'],row)
def main():
    p=argparse.ArgumentParser();p.add_argument('--downloads',type=Path);p.add_argument('--from-workspace',type=Path);p.add_argument('--reference-archive',type=Path);p.add_argument('--runtime-archive',type=Path);p.add_argument('--ids',nargs='+',default=list(CANONICAL));p.add_argument('--check',action='store_true');a=p.parse_args()
    manifest=read(ROOT/'assets-manifest.json');by_id={m['asset_id']:m for m in manifest['assets']}
    for asset_id in a.ids:
        row=by_id[asset_id];rel=CANONICAL.get(asset_id) or next((x['path'] for x in row.get('historical_local_paths',row['local_paths']) if x['in_workspace']),None)
        if rel is None:raise ValueError('External capture restoration is manual; this utility never writes outside the checkout: '+asset_id)
        dst=target(rel)
        if dst.exists():verify(dst,row);continue
        if a.check:raise FileNotFoundError('Missing '+asset_id+': '+rel)
        # Browser downloads of a Drive folder may arrive in subfolders; skip partial copies (place() still hashes).
        source=next((p for p in a.downloads.rglob(row['drive_name']) if p.is_file() and p.stat().st_size==row['bytes']),a.downloads/row['drive_name']) if a.downloads else a.from_workspace/rel if a.from_workspace else None
        if source is None:raise ValueError('Provide --downloads for verified browser downloads')
        place(source,dst,row)
    if not a.check:
        for arg,name in [(a.reference_archive,'viewer-resources.json'),(a.runtime_archive,'runtime-assets.json')]:
            if arg:archive(arg,read(ROOT/'docs'/name))
        if a.from_workspace:
            for row in read(ROOT/'docs/viewer-resources.json')['files']:place(a.from_workspace/row['path'],target(row['path']),row)
        # The iPhone transfer copies derive from A001/A003; a subset restore without them skips this step.
        if all(target(CANONICAL[i]).exists() for i in ('A001','A003')):iphone_baseline(a.from_workspace)
    else:
        for row in read(ROOT/'docs/viewer-resources.json')['files']:verify(target(row['path']),row)
    print(json.dumps({'verifiedAssetIds':a.ids,'referenceFiles':len(read(ROOT/'docs/viewer-resources.json')['files']),'externalWrites':0,'networkRequests':0}))
if __name__=='__main__':main()
