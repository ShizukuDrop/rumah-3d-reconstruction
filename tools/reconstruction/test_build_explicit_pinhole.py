"""Bounded CPU integration checks for explicit native-pose whitelist consumption."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/osmo-reconstruct-20261031'))
from seed_fisheye import Fisheye, qvec_to_rotmat, read_model, write_model_text


class WarperWhitelistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        cls.temp = tempfile.TemporaryDirectory(prefix='rumah-warper-test-')
        cls.base = Path(cls.temp.name)
        cls.source = cls.base / 'accepted-poses'
        cls.rgb = cls.base / 'native-rgb'
        cls.masks = cls.base / 'native-masks'
        camera = {'id': 1, 'model': 'OPENCV_FISHEYE', 'width': 256, 'height': 256,
                  'params': np.array([80., 81., 128., 127., 0., 0., 0., 0.])}
        cls.points = {i+1: {'id': i+1, 'xyz': np.array(xyz), 'rgb': np.array([10, 20, 30]),
                           'error': 0., 'image_ids': np.array([1, 2, 3, 4]), 'point2D_idxs': np.array([i]*4)}
                      for i, xyz in enumerate([[-.3, -.2, 3.], [.4, .3, 3.5], [0., .1, 2.5]])}
        fisheye = Fisheye(camera)
        cls.images = {}
        selection = []
        for i, (lens, split) in enumerate([('cam0', 'train'), ('cam1', 'train'), ('cam0', 'eval'), ('cam0', 'train')], 1):
            filename = f'frame_{i:06d}_{split}.jpg'; name = lens+'/'+filename
            q = np.array([np.cos(.15), 0., 0., np.sin(.15)])
            t = np.array([-.1*i, .07*i, .03*i])
            world = np.array([p['xyz'] for p in cls.points.values()])
            xy, valid = fisheye.project(world @ qvec_to_rotmat(q).T + t)
            assert valid.all()
            cls.images[i] = {'id': i, 'qvec': q, 'tvec': t, 'camera_id': 1, 'name': name,
                             'points2D_xy': xy, 'point3D_ids': np.arange(1, 4)}
            (cls.rgb / lens).mkdir(parents=True, exist_ok=True)
            (cls.masks / lens).mkdir(parents=True, exist_ok=True)
            colour = [0, 0, 210-i*30] if split == 'train' else [240, 0, 0]
            image = np.full((256, 256, 3), colour, dtype=np.uint8)
            mask = np.full((256, 256), 255, np.uint8); mask[:40, :40] = 0
            assert cv2.imwrite(str(cls.rgb / name), image)
            assert cv2.imwrite(str((cls.masks / name).with_suffix('.png')), mask)
            selection.append({'filename': filename, 'source_frame': i, 'split': split})
        write_model_text(cls.source / 'sparse/0', {1: camera}, cls.images, cls.points)
        cls.selection = cls.base / 'selection.json'
        cls.selection.write_text(json.dumps({'selected': selection}))
        cls.source_hash = cls.hash_model()
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def hash_model(cls):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (cls.source / 'sparse/0').iterdir()}

    def invoke(self, train=None, heldout=None, extra=(), success=True):
        type(self).counter += 1
        index = self.counter
        output = self.base / f'output-{index}'
        command = [sys.executable, str(ROOT / 'work/osmo-clean-20261031/build_explicit_pinhole.py'),
                   '--source', str(self.source), '--output', str(output), '--subset', 'all', '--size', '512',
                   '--selection', str(self.selection), '--images-dir', str(self.rgb), '--masks-dir', str(self.masks), '--workers', '1']
        for label, value in [('train', train), ('eval', heldout)]:
            if value is not None:
                path = self.base / f'{label}-{index}.json'; path.write_text(json.dumps(value))
                command += [f'--{label}-whitelist', str(path)]
        command += list(extra)
        result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                env={**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return output, json.loads((output / 'explicit-pinhole-audit.json').read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists(), 'Invalid whitelist must fail before output creation')
        return result.stderr

    def test_whitelist_paths_fresh_pose_masks_and_eval_seed_isolation(self):
        train = {'schema': 'rumah-quality-pose-whitelist-v1', 'training_ready': False,
                 'remaining_gate': 'Fresh geometry and visual quality acceptance',
                 'views': [{'image': self.images[i]['name'], 'frame_id': i, 'lens': self.images[i]['name'].split('/')[0],
                            'split': 'train', 'quality_status': 'passed'} for i in (1, 2)]}
        heldout = {'schema': 'rumah-heldout-pose-whitelist-v1', 'split': 'eval',
                   'point_geometry_uses_eval_images': False, 'pose_localization_uses_eval_pixels': True,
                   'views': [{'image': self.images[3]['name'], 'frame_id': 3, 'lens': 'cam0', 'split': 'eval'}]}
        output, report = self.invoke(train, heldout)
        self.assertEqual(report['sourceInputs'], 3)
        self.assertEqual(report['unlistedSourceImagesExcluded'], 1)
        self.assertEqual(report['seedPoints'], 3)
        self.assertFalse(report['trainingReady'])
        self.assertFalse(report['worldTransformApplied'])
        self.assertTrue(report['explicitWhitelistApplied'])
        self.assertIn('up axis undeclared', report['worldCoordinateFrame'])
        self.assertEqual({r['sourceName'] for r in report['views']}, {self.images[i]['name'] for i in (1, 2, 3)})
        cameras, images, points = read_model(output / 'sparse/0')
        by_name = {im['name']: im for im in images.values()}
        for row in report['views']:
            im = by_name[row['name']]
            if row['face'] == 0:
                source = next(v for v in self.images.values() if v['name'] == row['sourceName'])
                np.testing.assert_allclose(qvec_to_rotmat(im['qvec']), qvec_to_rotmat(source['qvec']), atol=1e-14)
                np.testing.assert_allclose(im['tvec'], source['tvec'], atol=1e-14)
            self.assertEqual(row['sourceSplit'], 'eval' if row['sourceFrame'] == 3 else 'train')
        for pid, point in points.items():
            np.testing.assert_array_equal(point['xyz'], self.points[pid]['xyz'])
        self.assertEqual(self.hash_model(), self.source_hash)
        # Training photos are red, held-out pixels are blue; seed colour must stay red.
        with (output / 'seed-sparse-train.ply').open('rb') as stream:
            while stream.readline().strip() != b'end_header':
                pass
            values = np.frombuffer(stream.read(), dtype=np.dtype([('xyz_normals', '<f4', (6,)), ('rgb', 'u1', (3,))]))
        self.assertTrue(np.all(values['rgb'][:, 0] > 140))
        self.assertTrue(np.all(values['rgb'][:, 2] < 5))

    def test_missing_or_wrong_split_duplicate_and_unpassed_are_rejected(self):
        good = [self.images[1]['name']]
        heldout = [self.images[3]['name']]
        cases = [(['cam0/frame_999999_train.jpg'], heldout, 'missing'),
                 ([self.images[3]['name']], heldout, 'split mismatch'),
                 (good+good, heldout, 'Duplicate'),
                 ({'views': [{'image': good[0], 'split': 'train', 'quality_status': 'review'}]}, heldout, 'unpassed'),
                 (good, None, 'both train and eval')]
        for train, evaluation, message in cases:
            with self.subTest(message=message):
                self.assertIn(message, self.invoke(train, evaluation, success=False))

    def test_no_whitelist_preserves_existing_all_selection(self):
        _, report = self.invoke()
        self.assertEqual(report['sourceInputs'], 4)
        self.assertFalse(report['explicitWhitelistApplied'])
        self.assertEqual(report['unlistedSourceImagesExcluded'], 0)

    def test_pose_only_queries_have_no_fabricated_seed_or_reprojection(self):
        source = self.base / 'pose-only'
        cameras, _, _ = read_model(self.source / 'sparse/0')
        images = {iid: {**im, 'points2D_xy': np.empty((0, 2)), 'point3D_ids': np.empty(0, np.int64)}
                  for iid, im in self.images.items()}
        write_model_text(source / 'sparse/0', cameras, images, {})
        output, report = self.invoke([self.images[1]['name']], [self.images[3]['name']],
                                     extra=('--source', str(source)))
        self.assertGreater(report['virtualViews'], 0)
        self.assertEqual(report['seedPoints'], 0)
        self.assertEqual(report['reprojection']['observations'], 0)
        self.assertIsNone(report['reprojection']['maxPixels'])
        self.assertFalse(report['trainingReady'])
        _, views, points = read_model(output / 'sparse/0')
        self.assertFalse(points)
        self.assertTrue(all(len(im['point3D_ids']) == 0 for im in views.values()))


if __name__ == '__main__':
    unittest.main()
