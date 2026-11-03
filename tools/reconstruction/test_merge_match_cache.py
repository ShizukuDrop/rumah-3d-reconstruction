import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from tools.reconstruction.match_cache import read_index
from tools.reconstruction.merge_match_cache import camera_metadata, merge_verified_matches
from tools.reconstruction.test_match_cache import fixture


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.a, self.b, self.out = [self.root / name for name in ('a.bin', 'b.bin', 'out.bin')]
        self.a.write_bytes(fixture([(0, 2, 2, [(0, 1), (2, 0)])]))
        self.b.write_bytes(fixture([(3, 1, 2, [(1, 2)])]))
        self.manifests = []
        for variant in ('a', 'b'):
            table = {}
            for image in read_index(self.a).images:
                path = self.root / variant / (image.name + '.bin')
                path.parent.mkdir(parents=True, exist_ok=True)
                data = struct.pack('<4s6I', b'VKFT', 6, 3840, 3840, 3, 2, 1) + bytes(3 * (16 + 2 * 4))
                path.write_bytes(data)
                table[image.name] = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()}
            self.manifests.append(table)

    def tearDown(self):
        self.temporary.cleanup()

    def merge(self, **changes):
        options = {'expected_source_sha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.a, self.b)],
                   'feature_manifests': self.manifests}
        options.update(changes)
        return merge_verified_matches([self.a, self.b], self.out, **options)

    def test_union_preserves_original_oriented_payload_and_calibration(self):
        originals = [p.read_bytes() for p in (self.a, self.b)]
        report = self.merge()
        output = read_index(self.out)
        self.assertEqual([(p.image1, p.image2) for p in output.pairs], [(0, 2), (3, 1)])
        with self.out.open('rb') as handle:
            handle.seek(output.pairs[1].offset)
            self.assertEqual(handle.read(8), struct.pack('<II', 1, 2))
        self.assertEqual(self.out.read_bytes()[output.camera_offset:], originals[0][read_index(self.a).camera_offset:])
        self.assertEqual(report['featureFilesHashed'], 8)
        self.assertEqual(report['outputSha256'], hashlib.sha256(self.out.read_bytes()).hexdigest())
        self.assertEqual([p.read_bytes() for p in (self.a, self.b)], originals)

    def test_duplicate_reversed_pair_cannot_publish(self):
        self.b.write_bytes(fixture([(2, 0, 2, [(1, 0)])]))
        with self.assertRaisesRegex(ValueError, 'Duplicate pair'):
            self.merge()
        self.assertFalse(self.out.exists())

    def test_even_only_focal_measured_flag_difference_is_rejected(self):
        data = bytearray(self.b.read_bytes())
        data[-1] = 0
        self.b.write_bytes(data)
        self.assertNotEqual(camera_metadata(read_index(self.a)), camera_metadata(read_index(self.b)))
        with self.assertRaisesRegex(ValueError, 'calibration tail'):
            self.merge()
        self.assertFalse(self.out.exists())

    def test_different_feature_bytes_with_same_name_count_are_rejected(self):
        item = self.manifests[1]['cam0/a']
        path = Path(item['path'])
        data = bytearray(path.read_bytes()); data[-1] = 1; path.write_bytes(data)
        item['sha256'] = hashlib.sha256(data).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Feature SHA tables differ'):
            self.merge()
        self.assertFalse(self.out.exists())

    def test_bad_indices_hash_and_unverified_records_do_not_publish(self):
        self.b.write_bytes(fixture([(3, 1, 2, [(3, 0)])]))
        with self.assertRaisesRegex(ValueError, 'missing original feature'):
            self.merge()
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob('*.partial')), [])
        self.b.write_bytes(fixture([(3, 1, 0, [(1, 2)])]))
        with self.assertRaisesRegex(ValueError, 'nondegenerate'):
            self.merge()
        self.b.write_bytes(fixture([(3, 1, 2, [(1, 2)])]))
        with self.assertRaisesRegex(ValueError, 'cache SHA-256'):
            self.merge(expected_source_sha256=['0' * 64, '0' * 64])
        self.assertFalse(self.out.exists())

    def test_image_identity_and_overwrite_protections(self):
        self.b.write_bytes(self.b.read_bytes().replace(b'cam0/a', b'cam0/c'))
        with self.assertRaisesRegex(ValueError, 'identity table'):
            self.merge()
        self.out.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            self.merge()
        self.assertEqual(self.out.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
