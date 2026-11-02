"""Synthetic checks for restore_assets.py; never touches the real checkout or network."""
from pathlib import Path
from unittest import mock
import contextlib,gzip,hashlib,io,json,os,shutil,sys,tempfile,unittest,zipfile

sys.path.insert(0,str(Path(__file__).parent))
import restore_assets as r

def row(data,**extra):return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),**extra}
def write(p,data):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
SOG,LEGACY,KEPT,REF,FAST=b'sog-live',b'legacy-glb',b'kept-glb',b'reference-jpg',b'iphone-fast'*40

class RestoreAssetChecks(unittest.TestCase):
    def setUp(self):
        # Resolved: macOS temp dirs sit behind the /var -> /private/var symlink, which target() would refuse.
        self.root,self.dl=[Path(tempfile.mkdtemp()).resolve() for _ in 'rd']
        for d in (self.root,self.dl):self.addCleanup(shutil.rmtree,d)
        patch=mock.patch.object(r,'ROOT',self.root);patch.start();self.addCleanup(patch.stop)
        hist=lambda *paths:[{'path':p,'in_workspace':not p.startswith('C:'),'exists':False} for p in paths]
        assets=[
         {'asset_id':'A003','drive_name':'iPhone-Fast.glb',**row(FAST),'local_paths':hist(r.CANONICAL['A003'])},
         {'asset_id':'A013','drive_name':'Osmo-LIVE.sog',**row(SOG),'local_paths':hist(r.CANONICAL['A013'])},
         {'asset_id':'A045','drive_name':'old.glb',**row(b'old'),'local_paths':[],'historical_local_paths':hist('work/osmo-web-20261031-v2/public/models/old.glb'),'canonical_local_path':None},
         {'asset_id':'A046','drive_name':'osmo-lite.glb',**row(LEGACY),'local_paths':[],'historical_local_paths':hist('work/osmo-web-20261031-v3/public/models/osmo-lite.glb'),'canonical_local_path':None},
         {'asset_id':'A004','drive_name':'kept.glb',**row(KEPT),'local_paths':[],'historical_local_paths':hist('work/osmo-web-20261031/kept.glb','work/mobile-20261029/kept.glb'),'canonical_local_path':'work/mobile-20261029/kept.glb'},
         {'asset_id':'A056','drive_name':'CAM.OSV',**row(b'osv'),'local_paths':hist('C:\\capture\\CAM.OSV'),'canonical_local_path':'C:\\capture\\CAM.OSV'}]
        write(self.root/'assets-manifest.json',json.dumps({'assets':assets}).encode())
        self.zip=self.dl/'nested/viewer-reference.zip';self.zip.parent.mkdir()
        with zipfile.ZipFile(self.zip,'w') as z:z.writestr('work/ref/a.jpg',REF)
        write(self.root/'docs/viewer-resources.json',json.dumps({'archive_bytes':self.zip.stat().st_size,'archive_sha256':hashlib.sha256(self.zip.read_bytes()).hexdigest(),'files':[{'path':'work/ref/a.jpg',**row(REF)}]}).encode())
    def main(self,*args):
        with mock.patch.object(sys,'argv',['restore_assets.py',*map(str,args)]),contextlib.redirect_stdout(io.StringIO()) as out:r.main()
        return out.getvalue()

    def test_target_rejects_traversal_backslash_absolute_and_retired(self):
        for rel in ['../x.glb','a/../../x.glb','/etc/x.glb','work\\x.glb','work/osmo-web-20261031/x.glb','Work/OSMO-WEB-20261031-v3/x.glb','tmp/x.glb']:
            with self.subTest(rel=rel),self.assertRaises(ValueError):r.target(rel)
        self.assertEqual(r.target('work/osmo-web-20261031-v4/x.glb'),self.root/'work/osmo-web-20261031-v4/x.glb')

    def test_target_rejects_symlinked_destinations(self):
        (self.root/'inside').mkdir()
        try:os.symlink(self.dl,self.root/'escape',target_is_directory=True);os.symlink(self.root/'inside',self.root/'linked',target_is_directory=True)
        except OSError:self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(ValueError,'escaped'):r.target('escape/x.glb')
        with self.assertRaisesRegex(ValueError,'Linked'):r.target('linked/x.glb')

    def test_place_refuses_to_overwrite_a_differing_file(self):
        src=write(self.dl/'a.sog',SOG);dst=write(self.root/'b.sog',b'different')
        with self.assertRaisesRegex(ValueError,'File identity differs'):r.place(src,dst,row(SOG))
        self.assertEqual(dst.read_bytes(),b'different')

    def test_downloads_prefers_size_match_and_reports_missing(self):
        write(self.dl/'Osmo-LIVE.sog',SOG[:3]);write(self.dl/'sub/deeper/Osmo-LIVE.sog',SOG)
        self.main('--downloads',self.dl,'--ids','A013')
        self.assertEqual((self.root/r.CANONICAL['A013']).read_bytes(),SOG)
        with self.assertRaisesRegex(FileNotFoundError,'not found under --downloads'):self.main('--downloads',self.dl,'--ids','A046')

    def test_destination_prefers_canonical_then_consumer_and_refuses_retired_or_external(self):
        write(self.dl/'kept.glb',KEPT);write(self.dl/'osmo-lite.glb',LEGACY)
        self.main('--downloads',self.dl,'--ids','A004','A046')
        self.assertEqual((self.root/'work/mobile-20261029/kept.glb').read_bytes(),KEPT)
        self.assertEqual((self.root/r.CONSUMED['A046']).read_bytes(),LEGACY)
        self.assertFalse((self.root/'work/osmo-web-20261031').exists())
        with self.assertRaisesRegex(ValueError,'Retired'):self.main('--downloads',self.dl,'--ids','A045')
        with self.assertRaisesRegex(ValueError,'External capture'):self.main('--downloads',self.dl,'--ids','A056')

    def test_missing_archive_path_is_found_under_downloads(self):
        write(self.dl/'Osmo-LIVE.sog',SOG)
        self.main('--downloads',self.dl,'--ids','A013','--reference-archive',self.root/'nowhere'/self.zip.name)
        self.assertEqual((self.root/'work/ref/a.jpg').read_bytes(),REF)
        self.main('--check','--ids','A013')

    def test_retired_iphone_assets_are_refused_before_any_restore_or_check(self):
        write(self.dl/'Osmo-LIVE.sog',SOG)
        for asset_id in ['A001','A002']:
            for mode in [('--downloads',self.dl),('--check',)]:
                with self.subTest(asset_id=asset_id,mode=mode),self.assertRaisesRegex(ValueError,'retired by the user on 2026-11-03'):
                    self.main(*mode,'--ids','A013',asset_id)
                self.assertFalse((self.root/r.CANONICAL['A013']).exists(),'retired ID must fail before earlier IDs are written')

    def test_iphone_baseline_needs_only_a003_and_check_decodes_gzip(self):
        write(self.dl/'Osmo-LIVE.sog',SOG);write(self.dl/'iPhone-Fast.glb',FAST)
        # No baseline metadata exists, so reaching iphone_baseline() here would raise.
        self.main('--downloads',self.dl,'--ids','A013','--reference-archive',self.zip)
        self.main('--check','--ids','A013')
        base=self.root/'work/mobile-20261029/iphone-baseline'
        files={'models/fast.glb':FAST,'overview.jpg':REF}
        write(base/'manifest.json',json.dumps({'models':{'phone':{'url':'models/fast.glb','downloadBytes':1}}}).encode())
        write(base/'asset-files.json',json.dumps({'files':[{'path':k,**row(v)} for k,v in files.items()]+[{'path':k+'.gz',**row(b'')} for k in files if k.endswith('.glb')]}).encode())
        write(base/'overview.jpg',REF)
        out=self.main('--downloads',self.dl,'--ids','A003')
        self.assertIn('differs across zlib versions',out)
        self.assertEqual(gzip.decompress((base/'models/fast.glb.gz').read_bytes()),FAST)
        self.main('--check','--ids','A003')
        (base/'models/fast.glb.gz').write_bytes(gzip.compress(KEPT))
        with self.assertRaisesRegex(ValueError,'Gzip does not decode'):self.main('--check','--ids','A003')
        (base/'models/fast.glb.gz').unlink()
        with self.assertRaises(FileNotFoundError):self.main('--check','--ids','A003')
        self.main('--downloads',self.dl,'--ids','A003')
        write(base/'overview.jpg',b'tampered-jpg!')
        with self.assertRaisesRegex(ValueError,'File identity differs'):self.main('--check','--ids','A003')

if __name__=='__main__':unittest.main()
