import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from .test_prepare_localization import make_fixture
from .prepare_localization import prepare_requests,read_images,_rotation
from .localization import file_hash
from .localize_batch import run_batch,write_json
from .export_localized_poses import export_poses,quaternion


def fake_result(request_path,**_):
    request=json.loads(Path(request_path).read_text())
    return {'request_sha256':file_hash(request_path),'accepted':True,'queries':request['queries'],
            'rig_from_world':np.eye(4).tolist(),'camera_from_world':[c['cam_from_rig'] for c in request['cameras']],
            'map_mutated':False,'intrinsics_refined':False,'rig_extrinsics_refined':False,'inliers':24}


class BatchExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.version=mock.patch('tools.reconstruction.localize_batch.importlib.metadata.version',return_value='test-fixture')
        self.version.start();self.addCleanup(self.version.stop)
    def tearDown(self):self.tmp.cleanup()

    def fixture(self,review=False):
        args=make_fixture(self.root)
        if review:
            data=json.loads(args['queries'].read_text())
            next(v for v in data['views'] if v['frame_id']==1 and v['lens']=='cam1')['status']='review_required'
            args['queries'].write_text(json.dumps(data))
        prepare_requests(**args);return args

    @mock.patch('tools.reconstruction.localize_batch.localize_fixed_rig',side_effect=fake_result)
    def test_resume_does_not_repeat_and_rejects_changed_request(self,estimate):
        args=self.fixture();prep=args['output']/'preparation.json';out=self.root/'results'
        first=run_batch(prep,out,limit=1);self.assertEqual(first['status'],'partial');self.assertEqual(estimate.call_count,1)
        final=run_batch(prep,out);self.assertEqual(final['status'],'complete');self.assertEqual(estimate.call_count,2)
        run_batch(prep,out);self.assertEqual(estimate.call_count,2)
        request=args['output']/'requests/frame-000001.json';request.write_text(request.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Stored result'):run_batch(prep,out)

    @mock.patch('tools.reconstruction.localize_batch.localize_fixed_rig',side_effect=ValueError('bad rays'))
    def test_errors_are_explicit_and_resume_only_retries_on_request(self,estimate):
        args=self.fixture();prep=args['output']/'preparation.json';out=self.root/'results'
        result=run_batch(prep,out);self.assertEqual(result['summary']['counts']['errors'],2)
        run_batch(prep,out);self.assertEqual(estimate.call_count,2)
        run_batch(prep,out,retry_errors=True,limit=1);self.assertEqual(estimate.call_count,3)
        data=json.loads((out/'results/frame-000001.json').read_text());self.assertNotIn('rig_from_world',data)

    @mock.patch('tools.reconstruction.localize_batch.localize_fixed_rig',side_effect=fake_result)
    def test_export_keeps_geometry_and_excludes_review_from_training(self,estimate):
        args=self.fixture(review=True);prep=args['output']/'preparation.json';out=self.root/'results';run_batch(prep,out)
        export=self.root/'export';result=export_poses(prep,out,args['queries'],export)
        self.assertEqual(result['fresh_anchor_images'],2);self.assertEqual(result['accepted_query_images_appended'],4)
        self.assertEqual(result['training_whitelisted_views'],3);self.assertEqual(result['eval_whitelisted_views'],2)
        self.assertEqual(file_hash(args['anchor_model']/'points3D.bin'),file_hash(export/'sparse/0/points3D.bin'))
        original=(args['anchor_model']/'images.bin').read_bytes();combined=(export/'sparse/0/images.bin').read_bytes()
        self.assertEqual(original[8:],combined[8:len(original)])
        images=read_images(export/'sparse/0/images.bin')
        self.assertTrue(all(np.all(im['point_ids']==-1) for ident,im in images.items() if ident not in (57,83)))
        self.assertEqual(set(p.name for p in (export/'sparse/0').iterdir()),{'cameras.bin','images.bin','points3D.bin'})
        whitelist=json.loads((export/'training-whitelist.json').read_text())
        self.assertNotIn('cam1/frame_000001_train.jpg',[r['image'] for r in whitelist['views']])
        self.assertFalse(whitelist['training_ready'])

    @mock.patch('tools.reconstruction.localize_batch.localize_fixed_rig',side_effect=fake_result)
    def test_incomplete_batch_requires_explicit_inspection_export(self,estimate):
        args=self.fixture();prep=args['output']/'preparation.json';out=self.root/'results';run_batch(prep,out,limit=1)
        with self.assertRaisesRegex(ValueError,'incomplete'):export_poses(prep,out,args['queries'],self.root/'export')

    def test_pose_quaternion_roundtrip_including_half_turns(self):
        rng=np.random.default_rng(5)
        for q in [np.array([1,0,0,0]),np.array([0,1,0,0]),np.array([0,0,1,0]),*rng.normal(size=(20,4))]:
            q=q/np.linalg.norm(q);rotation=_rotation(q)
            self.assertTrue(np.allclose(_rotation(quaternion(rotation)),rotation,atol=1e-9))

    def test_transient_windows_replace_lock_preserves_and_retries_progress(self):
        target=self.root/'progress.json';target.write_text('{"old":true}')
        original=Path.replace;attempts=[]
        def replace(path,destination):
            attempts.append(1)
            if len(attempts)<3:
                self.assertEqual(json.loads(target.read_text()),{'old':True})
                raise PermissionError('simulated Windows sharing lock')
            return original(path,destination)
        with mock.patch.object(Path,'replace',replace),mock.patch('tools.reconstruction.localize_batch.time.sleep') as sleep:
            write_json(target,{'new':True})
        self.assertEqual(len(attempts),3);self.assertEqual(sleep.call_count,2);self.assertEqual(json.loads(target.read_text()),{'new':True})

    def test_permanent_replace_failure_is_bounded_and_preserves_old_progress(self):
        target=self.root/'progress.json';target.write_text('{"old":true}')
        with mock.patch.object(Path,'replace',side_effect=PermissionError('permanent')) as replace,mock.patch('tools.reconstruction.localize_batch.time.sleep'):
            with self.assertRaises(PermissionError):write_json(target,{'new':True})
        self.assertEqual(replace.call_count,20);self.assertEqual(json.loads(target.read_text()),{'old':True})


if __name__=='__main__':unittest.main()
