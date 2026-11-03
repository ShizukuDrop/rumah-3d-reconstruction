import json
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tools.reconstruction.matcher_benchmark import CommandBackend, Features, fallback_decision, gpu_idle_guard, map_matches, pair_digest, read_vkft, run_benchmark, sha_file, verify_full_sphere_geometry


def features(n=12):
    return Features(np.column_stack([np.arange(n)+10,np.arange(n)+20]).astype('float32'),np.arange(n*128,dtype='float32').reshape(n,128),np.arange(n,dtype='float32'),np.array([3840,3840]),np.arange(n,dtype=np.int64)*3).validate()


class MatcherTests(unittest.TestCase):
    def test_original_row_mapping_survives_budget_truncation(self):
        f=features();small=f.subset(3)
        np.testing.assert_array_equal(small.original_indices,[27,30,33])
        mapped=map_matches(np.array([[0,2],[2,0]]),np.array([.8,.7]),small,small)
        np.testing.assert_array_equal(mapped,[[27,33],[33,27]])
        with self.assertRaises(ValueError):map_matches(np.array([[3,0]]),np.array([1.]),small,small)
        with self.assertRaises(ValueError):map_matches(np.array([[0,0],[0,1]]),np.array([1.,1.]),small,small)

    def test_digest_binds_exact_descriptor_rows_and_pair_identity(self):
        f=features();pair={'id':'a','image0':'left','image1':'right'}
        same=pair_digest(pair,f.subset(4096),f.subset(4096))
        self.assertEqual(same,pair_digest(pair,f.subset(4096),f.subset(4096)))
        changed=features();changed.descriptors[0,0]+=.1
        self.assertNotEqual(same,pair_digest(pair,f,changed))
        self.assertNotEqual(same,pair_digest({**pair,'id':'b'},f,f))

    def test_strict_vkft_original_pixels_and_partial_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.bin';f=features(6)
            keypoints=np.column_stack([f.keypoints,np.zeros((6,2))]).astype('<f4')
            raw=b'VKFT'+struct.pack('<6I',6,3840,3840,6,128,1)+keypoints.tobytes()+f.descriptors.astype('<f4').tobytes()
            raw+=b'\0'+struct.pack('<dI',0.,0)+struct.pack('<II',1600,1600)+b'\1'+f.scores.astype('<f4').tobytes()+b'\1'
            p.write_bytes(raw);decoded=read_vkft(p)
            np.testing.assert_array_equal(decoded.image_size,[3840,3840]);np.testing.assert_array_equal(decoded.keypoints,f.keypoints)
            for damaged in (raw[:-1],raw+b'x',raw[:100]):
                p.write_bytes(damaged)
                with self.assertRaises(ValueError):read_vkft(p)

    def test_plan_only_never_imports_torch_or_probes_gpu(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);specs={}
            for name in ('a','b'):
                f=features();p=root/(name+'.npz');np.savez(p,**f.__dict__)
                specs[name]={'path':p.name,'sha256':sha_file(p),'source_sha256':'a'*64,'split':'train'}
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'features':specs,'pairs':[{'id':'pair','image0':'a','image1':'b','stratum':'doorway'}]}))
            with patch('tools.reconstruction.matcher_benchmark.gpu_idle_guard',side_effect=AssertionError('must not probe GPU')):
                plan=run_benchmark(manifest,root/'out',device='cuda')
            self.assertFalse(plan['executed'])
            self.assertEqual(plan['arms']['fixed4096']['pair_tensors'],plan['arms']['adaptive4096']['pair_tensors'])
            with self.assertRaisesRegex(ValueError,'must never be halved'):
                run_benchmark(manifest,root/'invalid-hybrid',arms=['adaptive2048'],fallback_mode='protected')

    def test_gpu_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError,'explicit'):gpu_idle_guard(False)

    def test_fallback_uses_verified_geometry_and_protected_edge_policy(self):
        edge={'stratum':'cross_lens','protected':True}
        weak={'inliers':14,'occupied_cells':[5,5]}
        self.assertTrue(fallback_decision(edge,'adaptive4096',weak,'protected')['retry_fixed4096'])
        self.assertTrue(fallback_decision(edge,'adaptive4096',{'inliers':100,'occupied_cells':[2,5]},'protected')['retry_fixed4096'])
        self.assertFalse(fallback_decision(edge,'adaptive4096',{'inliers':18,'occupied_cells':[5,5]},'protected')['retry_fixed4096'])
        ordinary={'stratum':'adjacent'}
        self.assertFalse(fallback_decision(ordinary,'adaptive4096',weak,'protected')['retry_fixed4096'])
        self.assertTrue(fallback_decision(ordinary,'adaptive4096',weak,'all-weak')['retry_fixed4096'])
        self.assertFalse(fallback_decision(edge,'fixed4096',weak,'all-weak')['retry_fixed4096'])

    def test_external_adapter_rejects_unbound_results(self):
        script="import numpy as np,sys; np.savez(sys.argv[2],matches=np.empty((0,2),dtype='int64'),scores=np.empty(0),pair_digest=np.array('wrong'))"
        backend=CommandBackend([sys.executable,'-c',script,'{input}','{output}']);backend.digest='expected'
        with self.assertRaisesRegex(ValueError,'identity'):backend.match(features(),features())

    @unittest.skipUnless(importlib.util.find_spec('pycolmap'),'Optional PyCOLMAP dependency absent')
    def test_full_sphere_verifier_keeps_valid_back_facing_fisheye_rays(self):
        import pycolmap as pc
        from tools.reconstruction.localization import NativeCamera
        rng=np.random.default_rng(22);n=100;theta=rng.uniform(.1,1.85,n);phi=rng.uniform(-np.pi,np.pi,n)
        x=np.column_stack([np.sin(theta)*np.cos(phi),np.sin(theta)*np.sin(phi),np.cos(theta)])*rng.uniform(3,6,(n,1));y=x+[.25,0,0]
        spec=dict(model='OPENCV_FISHEYE',width=1000,height=1000,params=[200,200,500,500,0,0,0,0]);camera=NativeCamera(spec,pc.Camera(**spec))
        def view(xyz):return Features(camera.img_from_cam(xyz).astype('float32'),np.zeros((n,128),'float32'),np.ones(n,'float32'),np.array([1000,1000]),np.arange(n)).validate()
        result=verify_full_sphere_geometry(view(x),view(y),np.column_stack([np.arange(n),np.arange(n)]),spec,spec)
        self.assertGreater(result['negative_native_z_matches'],0)
        self.assertEqual(result['inliers'],n)


if __name__=='__main__':unittest.main()
