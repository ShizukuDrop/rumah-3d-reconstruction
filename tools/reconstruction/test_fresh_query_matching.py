import json
from pathlib import Path
import struct
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from .test_prepare_localization import make_fixture
from .fresh_query_matching import propose_edges,build_plan,run_matching
from .localization import file_hash
from .match_cache import read_index,resolve_image_names
from .prepare_localization import prepare_requests


class FakeBackend:
    calls=0
    def __init__(self,*args):self.info={'backend':'test-fixture'}
    def sync(self):pass
    def match(self,left,right):
        type(self).calls+=1;n=min(len(left.keypoints),len(right.keypoints))
        return np.column_stack([np.arange(n),np.arange(n)]),np.ones(n),{}
    def close(self):pass


class FreshMatchingTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);FakeBackend.calls=0
    def tearDown(self):self.tmp.cleanup()

    def fixture(self,unused_capture_frame=False):
        args=make_fixture(self.root)
        for path in args['feature_root'].rglob('*.bin'):
            raw=bytearray(path.read_bytes());offset=28+12*16;raw[offset:offset+12*128*4]=np.ones((12,128),'<f4').tobytes();path.write_bytes(raw)
        staging=json.loads(args['staging_provenance'].read_text())
        for row in staging['images']:row['feature']['sha256']=file_hash((args['feature_root']/row['name']).with_suffix('.bin'))
        args['staging_provenance'].write_text(json.dumps(staging))
        if unused_capture_frame:
            source_selection=args['dataset']/'analysis/frame-selection.json';capture=json.loads(source_selection.read_text())
            capture['selected'].append({'source_frame':2,'time_seconds':2/30,'filename':'frame_000002_train.jpg','split':'train'})
            source_selection.write_text(json.dumps(capture));views=json.loads(args['queries'].read_text());views['source_selection_sha256']=file_hash(source_selection)
            args['queries'].write_text(json.dumps(views))
            for lens in ('cam0','cam1'):
                (args['dataset']/'images'/lens/'frame_000002_train.jpg').write_bytes(b'unselected source')
                (args['dataset']/'masks'/lens/'frame_000002_train.png').write_bytes(b'mask')
        args['matches'].unlink() # A fresh plan cannot rely on any legacy match cache.
        out=self.root/'plan';plan=build_plan(args['dataset'],args['anchor_model'],args['staging_provenance'],args['queries'],out)
        return args,out/'plan.json',plan

    def test_temporal_budget_and_cross_lens_retrieval(self):
        query={'name':'cam0/query','frame_id':100,'time_seconds':10.,'lens':'cam0','split':'eval'}
        anchors=[{'name':f'{lens}/anchor{i}','frame_id':i,'time_seconds':float(t),'lens':lens,'split':'train'}
            for i,(lens,t) in enumerate([('cam0',8),('cam0',9),('cam0',11),('cam0',12),('cam1',3),('cam1',17),('cam0',1)])]
        descriptors={row['name']:np.zeros(128) for row in anchors+[query]};descriptors[query['name']][0]=1
        for row in anchors:descriptors[row['name']][0]=1 if row['lens']=='cam1' else .1
        edges=propose_edges([query],anchors,descriptors)
        self.assertEqual(len(edges),6);self.assertEqual(sum(row['stratum']=='descriptor_retrieval' for row in edges),2)
        self.assertTrue(all(not row['same_lens'] for row in edges if row['stratum']=='descriptor_retrieval'))
        self.assertTrue(all(row['query_split']=='eval' for row in edges))
        anchors[0]['split']='eval'
        with self.assertRaisesRegex(ValueError,'Evaluation'):propose_edges([query],anchors,descriptors)

    def test_plan_uses_capture_features_without_old_cache_or_gpu(self):
        args,path,plan=self.fixture();self.assertFalse(args['matches'].exists())
        self.assertEqual(plan['query_frame_count'],2);self.assertEqual(plan['pair_count'],4)
        self.assertEqual(len(plan['image_table']),6);self.assertFalse(plan['old_match_cache_opened'])
        with mock.patch('tools.reconstruction.fresh_query_matching.LightGlueBackend',side_effect=AssertionError('GPU/backend should not load')):
            result=run_matching(path,self.root/'not-created')
        self.assertFalse(result['executed']);self.assertFalse((self.root/'not-created').exists())

    def test_unselected_capture_frames_need_no_feature_extraction(self):
        args,path,plan=self.fixture(unused_capture_frame=True)
        self.assertEqual(len(plan['image_table']),6)
        self.assertFalse(any('000002' in row['name'] for row in plan['image_table']))

    @mock.patch('tools.reconstruction.fresh_query_matching.LightGlueBackend',FakeBackend)
    def test_raw_matching_resume_and_real_preparation_identity(self):
        args,path,plan=self.fixture();weights=self.root/'weights';weights.write_bytes(b'fixture');out=self.root/'matched'
        result=run_matching(path,out,execute=True,weights=weights,warmup=0,limit=1)
        self.assertEqual(result['status'],'partial');self.assertFalse((out/'matches.bin').exists())
        result=run_matching(path,out,execute=True,weights=weights,warmup=0)
        self.assertEqual(result['status'],'complete');self.assertEqual(FakeBackend.calls,4)
        run_matching(path,out,execute=True,weights=weights,warmup=0);self.assertEqual(FakeBackend.calls,4)
        index=read_index(out/'matches.bin');self.assertEqual(len(index.pairs),4);self.assertTrue(all(row.config==0 for row in index.pairs))
        self.assertEqual(resolve_image_names(index,['cam0/frame_000001_train.jpg'])['cam0/frame_000001_train.jpg'],1)
        args['matches']=out/'matches.bin';prepared=prepare_requests(**args,include_raw=True,match_provenance=out/'progress.json')
        self.assertEqual(prepared['request_count'],2);self.assertEqual(prepared['shared_anchor_points'],12)
        self.assertTrue(prepared['include_unverified_raw_matches'])
        self.assertEqual(prepared['matching_plan_sha256'],file_hash(path))

    @mock.patch('tools.reconstruction.fresh_query_matching.LightGlueBackend',FakeBackend)
    def test_changed_native_features_reject_execution(self):
        args,path,plan=self.fixture();weights=self.root/'weights';weights.write_bytes(b'fixture')
        feature=Path(plan['features'][plan['pairs'][0]['image0']]['path']);feature.write_bytes(feature.read_bytes()+b'x')
        with self.assertRaisesRegex(ValueError,'hash changed'):run_matching(path,self.root/'matched',execute=True,weights=weights,warmup=0)

    def test_query_query_edge_rejected_before_backend(self):
        args,path,plan=self.fixture();plan['pairs'][0]['image1']=plan['queries'][-1]['name'];path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError,'query-to-registered-anchor'):run_matching(path,self.root/'matched')

    @mock.patch('tools.reconstruction.fresh_query_matching.LightGlueBackend',FakeBackend)
    def test_explicit_reanchoring_uses_new_points_and_reports_unmatched_anchors(self):
        args,path,plan=self.fixture(unused_capture_frame=True);weights=self.root/'weights';weights.write_bytes(b'fixture');matched=self.root/'matched'
        run_matching(path,matched,execute=True,weights=weights,warmup=0)
        original=args['anchor_model'];model=original.parent/'repaired';shutil.copytree(original,model)
        raw=bytearray((model/'points3D.bin').read_bytes())
        for i in range(12):struct.pack_into('<d',raw,8+i*(51+16)+8,10+i*.1)
        (model/'points3D.bin').write_bytes(raw)
        staging=json.loads(args['staging_provenance'].read_text());images=bytearray((model/'images.bin').read_bytes());struct.pack_into('<Q',images,0,4)
        from tools.reconstruction.prepare_localization import read_feature_rows
        for j,lens in enumerate(('cam0','cam1')):
            name=f'{lens}/frame_000002_train.jpg';feature=(args['feature_root']/name).with_suffix('.bin')
            shutil.copyfile(args['feature_root']/lens/'frame_000000_train.bin',feature);xy,_=read_feature_rows(feature)
            q=[1,0,0,0] if j==0 else [0,0,1,0];t=[0,0,0] if j==0 else [0,0,-.01]
            images+=struct.pack('<i7di',90+j,*q,*t,11 if j==0 else 22)+name.encode()+b'\0'+struct.pack('<Q',len(xy))
            for point in xy:images+=struct.pack('<ddq',*point,-1)
            staging['images'].append({'name':name,'newImageId':2+j,'feature':{'sha256':file_hash(feature)}})
        (model/'images.bin').write_bytes(images);args['staging_provenance'].write_text(json.dumps(staging));args['anchor_model']=model;args['matches']=matched/'matches.bin'
        with self.assertRaisesRegex(ValueError,'allow-reanchor'):prepare_requests(**args,include_raw=True,match_provenance=matched/'progress.json')
        report=prepare_requests(**args,include_raw=True,match_provenance=matched/'progress.json',allow_reanchor=True)
        self.assertEqual(report['request_count'],2);self.assertEqual(report['reanchoring']['anchors_bound_to_match_cache'],2)
        self.assertEqual(len(report['reanchoring']['anchors_absent_from_cache_and_skipped_for_edges']),2)
        self.assertEqual(report['reanchoring']['matching_proposal_model'],str(original.resolve()))
        self.assertEqual(report['reanchoring']['current_fixed_model'],str(model.resolve()))
        with np.load(args['output']/'anchors.npz') as points:self.assertTrue(np.all(points['points3D'][:,0]>=10))
        self.assertNotEqual(report['reanchoring']['matching_proposal_model_sha256']['points3D.bin'],report['reanchoring']['current_fixed_model_sha256']['points3D.bin'])


if __name__=='__main__':unittest.main()
