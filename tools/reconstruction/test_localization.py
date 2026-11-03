import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.reconstruction.localization import Gates, NativeCamera, AnchorLookupCache, assess_pose, file_hash, load_request, localize_fixed_rig, refine_native_pose


def fixture(folder, fisheye=False):
    rng=np.random.default_rng(41);n=48
    angle=.06;c,s=np.cos(angle),np.sin(angle)
    truth=np.array([[c,-s,0,.2],[s,c,0,-.1],[0,0,1,.05],[0,0,0,1.]])
    members=[np.eye(4),np.diag([-1.,1.,-1.,1.])];members[1][0,3]=.06
    cameras=[];queries=[];allxyz=[]
    def save(name,**arrays):
        path=folder/name;np.savez(path,**arrays);return {'path':name,'sha256':file_hash(path)}
    for i,e in enumerate(members):
        if fisheye:
            theta=rng.uniform(.1,1.85,n);phi=rng.uniform(-np.pi,np.pi,n);depth=rng.uniform(2.5,4.5,n)
            local=np.column_stack([np.sin(theta)*np.cos(phi),np.sin(theta)*np.sin(phi),np.cos(theta)])*depth[:,None]
            xy=np.column_stack([np.cos(phi),np.sin(phi)])*theta[:,None]*200+400
        else:
            local=np.column_stack([rng.uniform(-1.4,1.4,n),rng.uniform(-1.1,1.1,n),rng.uniform(2.5,4.5,n)])
            xy=local[:,:2]/local[:,2,None]*400+400
        world=(np.linalg.inv(e@truth)@np.column_stack([local,np.ones(n)]).T).T[:,:3];allxyz.extend(world)
        cameras.append({'id':f'cam{i}','model':'OPENCV_FISHEYE' if fisheye else 'PINHOLE','width':800,'height':800,'params':[200,200,400,400,0,0,0,0] if fisheye else [400,400,400,400],'cam_from_rig':e.tolist()})
        queries.append({'camera_id':f'cam{i}','frame_id':'f100','time_seconds':3.3,'split':'eval','source_sha256':str(i+1)*64,
                        'features':save(f'q{i}.npz',keypoints=xy,original_indices=np.arange(n,dtype=np.int64))})
    request={'cameras':cameras,'queries':queries,'anchors':save('anchors.npz',point_ids=np.arange(2*n,dtype=np.int64),points3D=np.array(allxyz)),
             'correspondences':save('corr.npz',camera_idxs=np.repeat(np.arange(2,dtype=np.int64),n),query_feature_ids=np.tile(np.arange(n,dtype=np.int64),2),point3D_ids=np.arange(2*n,dtype=np.int64))}
    path=folder/'request.json';path.write_text(json.dumps(request));return path,request,truth


class LocalizationTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_identity_and_split_are_required(self):
        path,request,_=fixture(self.folder);load_request(path)
        request['queries'][1]['split']='train';path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError,'split'):load_request(path)

    def test_anchor_tampering_is_rejected(self):
        path,_,_=fixture(self.folder)
        with (self.folder/'anchors.npz').open('ab') as f:f.write(b'changed')
        with self.assertRaisesRegex(ValueError,'identity'):load_request(path)

    def test_shared_anchor_cache_is_read_only_and_detects_mutation(self):
        path,request,_=fixture(self.folder);cache=AnchorLookupCache()
        plain=load_request(path);cached=load_request(path,anchor_cache=cache)
        np.testing.assert_array_equal(plain[2],cached[2]);load_request(path,anchor_cache=cache)
        self.assertEqual(cache.misses,1);self.assertEqual(cache.hits,1)
        lookup=cache.get(self.folder,request['anchors'])
        with self.assertRaises(ValueError):lookup[0][0]=99
        with (self.folder/'anchors.npz').open('ab') as stream:stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'changed after validation'):load_request(path,anchor_cache=cache)

    def test_ambiguous_correspondence_is_rejected(self):
        path,request,_=fixture(self.folder)
        file=self.folder/'corr.npz'
        with np.load(file) as d:data={k:d[k].copy() for k in d.files}
        data['query_feature_ids'][1]=data['query_feature_ids'][0];np.savez(file,**data)
        request['correspondences']['sha256']=file_hash(file);path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError,'Ambiguous'):load_request(path)

    def test_partial_record_is_rejected(self):
        path,request,_=fixture(self.folder);file=self.folder/'corr.npz'
        with np.load(file) as d:data={k:d[k].copy() for k in d.files}
        data['point3D_ids']=data['point3D_ids'][:-1];np.savez(file,**data)
        request['correspondences']['sha256']=file_hash(file);path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError,'Incomplete'):load_request(path)

    @unittest.skipUnless(importlib.util.find_spec('pycolmap'),'PyCOLMAP optional CPU dependency absent')
    def test_real_cpu_generalized_rig_pose_and_fixed_calibration(self):
        path,_,truth=fixture(self.folder);before={p.name:file_hash(p) for p in self.folder.iterdir()}
        result=localize_fixed_rig(path)
        self.assertTrue(result['accepted'],result)
        np.testing.assert_allclose(result['rig_from_world'],truth,atol=1e-5)
        self.assertEqual(before,{p.name:file_hash(p) for p in self.folder.iterdir()})
        self.assertEqual(result['queries'][0]['split'],'eval')

    @unittest.skipUnless(importlib.util.find_spec('pycolmap'),'PyCOLMAP optional CPU dependency absent')
    def test_wrong_pose_and_localized_inliers_fail_gates(self):
        import pycolmap as pc
        path,request,truth=fixture(self.folder);_,xy,xyz,ci,_,_=load_request(path)
        cameras=[pc.Camera(model=c['model'],width=c['width'],height=c['height'],params=c['params']) for c in request['cameras']]
        e=[np.array(c['cam_from_rig']) for c in request['cameras']];bad=truth.copy();bad[0,3]+=1
        assessment=assess_pose(xy,xyz,ci,cameras,e,bad,np.ones(len(xy),bool),Gates())
        self.assertFalse(assessment['accepted']);self.assertIn('reprojection_residual',assessment['rejection_reasons'])
        mask=np.zeros(len(xy),bool);mask[:8]=True
        self.assertFalse(assess_pose(xy,xyz,ci,cameras,e,truth,mask,Gates())['accepted'])

    @unittest.skipUnless(importlib.util.find_spec('pycolmap'),'PyCOLMAP optional CPU dependency absent')
    def test_noninvertible_fisheye_ray_is_not_silently_localized(self):
        path,request,_=fixture(self.folder)
        for camera in request['cameras']:
            camera.update(model='OPENCV_FISHEYE',params=[200,200,400,400,0,0,0,0])
        p=self.folder/'q0.npz'
        with np.load(p) as d:arrays={k:d[k].copy() for k in d.files}
        arrays['keypoints'][0]=[799,799];np.savez(p,**arrays)
        request['queries'][0]['features']['sha256']=file_hash(p);path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError,'cannot invert'):localize_fixed_rig(path)

    @unittest.skipUnless(importlib.util.find_spec('pycolmap'),'PyCOLMAP optional CPU dependency absent')
    def test_full_fisheye_bearings_beyond_ninety_degrees(self):
        path,_,truth=fixture(self.folder,fisheye=True)
        result=localize_fixed_rig(path)
        self.assertTrue(result['accepted'],result)
        self.assertGreater(result['bearing_adapter']['negative_native_z_correspondences'],0)
        np.testing.assert_allclose(result['rig_from_world'],truth,atol=1e-5)

    @unittest.skipUnless(importlib.util.find_spec('pycolmap'),'PyCOLMAP optional CPU dependency absent')
    def test_native_consensus_removes_virtual_threshold_outliers_without_relaxing_gates(self):
        import pycolmap as pc
        path,request,truth=fixture(self.folder,fisheye=True);_,xy,xyz,ci,_,_=load_request(path)
        cameras=[NativeCamera(c,pc.Camera(model=c['model'],width=c['width'],height=c['height'],params=c['params'])) for c in request['cameras']]
        e=[np.array(c['cam_from_rig']) for c in request['cameras']];outliers=np.r_[np.arange(10),np.arange(48,58)]
        xy[outliers,0]+=12
        before=assess_pose(xy,xyz,ci,cameras,e,truth,np.ones(len(xy),bool),Gates())
        self.assertFalse(before['accepted']);self.assertGreater(before['p95_px'],4)
        pose,mask,report=refine_native_pose(xy,xyz,ci,cameras,e,truth,Gates())
        self.assertFalse(mask[outliers].any());self.assertEqual(int(mask.sum()),len(xy)-len(outliers))
        self.assertEqual(report['before']['outliers'],20);self.assertEqual(report['after']['outliers'],20)
        self.assertTrue(assess_pose(xy,xyz,ci,cameras,e,pose,mask,Gates())['accepted'])
        np.testing.assert_allclose(pose,truth,atol=1e-6)
        wrong=truth.copy();wrong[0,3]+=2
        pose,mask,report=refine_native_pose(xy,xyz,ci,cameras,e,wrong,Gates())
        self.assertFalse(assess_pose(xy,xyz,ci,cameras,e,pose,mask,Gates())['accepted'])


if __name__=='__main__':unittest.main()
