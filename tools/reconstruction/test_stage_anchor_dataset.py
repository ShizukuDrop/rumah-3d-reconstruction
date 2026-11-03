import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from tools.reconstruction.stage_anchor_dataset import stage_dataset


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images, self.masks, self.features = [self.root / name for name in ('images', 'masks', 'features')]
        self.frames = []
        for frame in (0, 10, 20):
            names = {}
            for lens in ('cam0', 'cam1'):
                rel = Path(lens) / f'frame_{frame:06d}_train.jpg'
                names[lens] = rel.as_posix()
                for directory, extension, payload in [
                    (self.images, '.jpg', b'image' + bytes([frame])),
                    (self.masks, '.png', b'mask' + bytes([frame])),
                    (self.features, '.bin', struct.pack('<4s6I', b'VKFT', 6, 3840, 3840, 2, 128, 1)
                     + bytes(2 * (16 + 128 * 4)) + b'fixture-trailer'),
                ]:
                    target = directory / rel.with_suffix(extension)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
            self.frames.append({'id': frame, 'images': names, 'selected': frame != 10, 'split': 'train'})
        self.selection = self.root / 'selection.json'
        self.selection.write_text(json.dumps({'frames': self.frames}))
        self.camera = self.root / 'camera.json'
        self.camera_data = {'image_dir': str(self.images), 'camera_mode': 'folder',
                            'cameras': [{'prefix': lens, 'model': 'opencv-fisheye', 'params': [1, 2, 3, 4]}
                                        for lens in ('cam0', 'cam1')],
                            'rigs': [{'kind': 'dual-fisheye', 'members': [{'prefix': 'cam0'}, {'prefix': 'cam1'}]}]}
        self.camera.write_text(json.dumps(self.camera_data))
        self.output = self.root / 'staged'

    def tearDown(self):
        self.temp.cleanup()

    def stage(self, **kwargs):
        return stage_dataset(self.selection, self.camera, self.features, self.masks, self.output, **kwargs)

    def test_subset_identity_independent_features_and_exact_calibration(self):
        report = self.stage()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['anchors'], 2)
        self.assertEqual([row['newImageId'] for row in report['images']], list(range(4)))
        self.assertEqual([row['frameId'] for row in report['images']], [0, 20, 0, 20])
        self.assertFalse(report['resumeOldMapAllowed'])
        for row in report['images']:
            self.assertEqual(row['featureMetadata']['featureCount'], 2)
            self.assertEqual(row['feature']['method'], 'copy')
            source, staged = Path(row['feature']['source']), Path(row['feature']['destination'])
            self.assertFalse(os.path.samefile(source, staged))
            original = source.read_bytes()
            staged.write_bytes(b'changed independently')
            self.assertEqual(source.read_bytes(), original)
        staged_camera = json.loads((self.output / 'sfm-manifest.json').read_text())
        self.assertEqual(staged_camera['cameras'], self.camera_data['cameras'])
        self.assertEqual(staged_camera['rigs'], self.camera_data['rigs'])
        self.assertEqual(json.loads(self.camera.read_text()), self.camera_data)
        self.assertFalse((self.output / 'images/cam0/frame_000010_train.jpg').exists())

    def test_all_copy_mode_does_not_alias_images(self):
        report = self.stage(all_copy=True)
        for row in report['images']:
            for kind in ('image', 'mask', 'feature'):
                self.assertEqual(row[kind]['method'], 'copy')
                self.assertFalse(os.path.samefile(row[kind]['source'], row[kind]['destination']))

    def test_selected_eval_is_rejected_before_output(self):
        self.frames[0]['split'] = 'eval'
        self.selection.write_text(json.dumps({'frames': self.frames}))
        with self.assertRaisesRegex(ValueError, 'held-out'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_outside_source_path_rejected(self):
        self.frames[0]['images']['cam0'] = '../frame_000000_train.jpg'
        self.selection.write_text(json.dumps({'frames': self.frames}))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_missing_or_unsynchronized_lens_rejected(self):
        self.frames[0]['images']['cam1'] = 'cam1/frame_000010_train.jpg'
        self.selection.write_text(json.dumps({'frames': self.frames}))
        with self.assertRaisesRegex(ValueError, 'synchronized'):
            self.stage()

    def test_never_overwrites_destination(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('keep')
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual(marker.read_text(), 'keep')

    def cache(self, feature_count=2):
        names = [Path(name).with_suffix('').as_posix()
                 for frame in self.frames for name in frame['images'].values()]
        data = b'VKMT' + struct.pack('<II', 4, len(names))
        for name in names:
            encoded = name.encode()
            data += struct.pack('<I', len(encoded)) + encoded + struct.pack('<I', feature_count)
        data += struct.pack('<II', 0, 0)
        path = self.root / 'source-matches.bin'
        path.write_bytes(data)
        return path

    def test_new_ids_map_to_original_full_cache_ids(self):
        report = self.stage(source_cache=self.cache())
        self.assertEqual([row['newImageId'] for row in report['images']], [0, 1, 2, 3])
        self.assertEqual([row['originalImageId'] for row in report['images']], [0, 4, 1, 5])

    def test_source_cache_feature_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'feature rows differ'):
            self.stage(source_cache=self.cache(feature_count=3))
        self.assertFalse(self.output.exists())

    def test_selected_quality_rejection_cannot_be_staged(self):
        self.frames[0]['quality_action'] = 'reject'
        self.selection.write_text(json.dumps({'frames': self.frames}))
        with self.assertRaisesRegex(ValueError, 'quality'):
            self.stage()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
