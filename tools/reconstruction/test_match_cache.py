import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.reconstruction.match_cache import image_ids, read_index, subset_matches


def fixture(pairs=None):
    pairs = pairs if pairs is not None else [(0, 2, 2, [(0, 1), (2, 0)]), (3, 1, 2, [(1, 2)]), (0, 3, 0, [(0, 0)])]
    data = bytearray(b'VKMT' + struct.pack('<II', 4, 4))
    for name in ['cam0/a', 'cam1/a', 'cam0/b', 'cam1/b']:
        encoded = name.encode()
        data += struct.pack('<I', len(encoded)) + encoded + struct.pack('<I', 3)
    data += struct.pack('<I', len(pairs))
    for first, second, config, matches in pairs:
        data += struct.pack('<IIiI', first, second, config, len(matches))
        for indices in matches:
            data += struct.pack('<II', *indices)
    data += struct.pack('<I', 2)
    for camera in [7, 11]:
        data += struct.pack('<IIIiBdI', camera, 3840, 3840, 5, 1, 2.0, 8)
        data += struct.pack('<8d', 1048, 1048, 1910, 1920, .04, .02, -.01, .001)
    data += struct.pack('<I4I2B', 4, 7, 11, 7, 11, 0, 1)
    return bytes(data)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'matches.bin'
        self.source.write_bytes(fixture())
        self.output = self.root / 'subset.bin'

    def tearDown(self):
        self.temporary.cleanup()

    def test_preserves_indices_features_and_camera_bytes(self):
        original = self.source.read_bytes()
        index = read_index(self.source)
        report = subset_matches(self.source, self.output, [(1, 3)])
        result = read_index(self.output)
        self.assertEqual(result.images, index.images)
        self.assertEqual(result.camera_ids, (7, 11, 7, 11))
        self.assertEqual((result.pairs[0].image1, result.pairs[0].image2), (3, 1))
        self.assertEqual(self.output.read_bytes()[result.camera_offset:], original[index.camera_offset:])
        self.assertEqual(self.output.read_bytes()[:result.pair_count_offset], original[:index.pair_count_offset])
        with self.output.open('rb') as handle:
            handle.seek(result.pairs[0].offset)
            self.assertEqual(handle.read(8), struct.pack('<II', 1, 2))
        self.assertEqual(report['sourceSha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(report['outputSha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(self.source.read_bytes(), original)

    def test_unverified_and_missing_pairs_are_not_claimed_as_verified(self):
        report = subset_matches(self.source, self.output, [(0, 2), (0, 3), (1, 2)])
        self.assertEqual(report['availableVerifiedPairs'], 1)
        self.assertEqual(report['missingRequestedPairs'], [[0, 3], [1, 2]])
        self.assertEqual(report['timingKind'], 'cached-subset-copy-not-fresh-matching')

    def test_filename_resolution_does_not_change_ids(self):
        self.assertEqual(image_ids(read_index(self.source), [('cam1/b.jpg', 'cam1/a')]), {(1, 3)})
        with self.assertRaisesRegex(ValueError, 'absent'):
            image_ids(read_index(self.source), [('missing.jpg', 'cam1/a')])

    def test_invalid_feature_index_cannot_publish_output(self):
        self.source.write_bytes(fixture([(0, 2, 2, [(3, 0)])]))
        with self.assertRaisesRegex(ValueError, 'missing feature'):
            subset_matches(self.source, self.output, [(0, 2)])
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('*.partial')), [])

    def test_wrong_source_hash_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            subset_matches(self.source, self.output, [(0, 2)], expected_source_sha256='0' * 64)
        self.assertFalse(self.output.exists())

    def test_refuses_overwrite_and_original_as_destination(self):
        for destination in [self.source, self.output]:
            destination.touch(exist_ok=True)
            with self.assertRaises(FileExistsError):
                subset_matches(self.source, destination, [(0, 2)])

    def test_truncated_camera_tail_rejected(self):
        self.source.write_bytes(fixture()[:-1])
        with self.assertRaises(ValueError):
            read_index(self.source)

    def test_duplicate_and_out_of_range_pairs_rejected(self):
        for pairs in [[(0, 4, 2, [])], [(0, 2, 2, []), (2, 0, 2, [])]]:
            self.source.write_bytes(fixture(pairs))
            with self.assertRaises(ValueError):
                read_index(self.source)

    def test_live_unknown_version_and_trailing_data_rejected(self):
        for data in [b'VKMT' + struct.pack('<II', 5, 0), fixture() + b'extra']:
            self.source.write_bytes(data)
            with self.assertRaises(ValueError):
                read_index(self.source)

    def test_index_skips_large_correspondence_payload(self):
        payload_matches = 500_000
        original = fixture([(0, 2, 2, [])])
        base = read_index(self.source)
        pair_header_offset = base.pair_count_offset + 4
        offset = pair_header_offset + 16
        data = original[:pair_header_offset] + struct.pack('<IIiI', 0, 2, 2, payload_matches)
        with self.source.open('wb') as handle:
            handle.write(data)
            handle.seek(payload_matches * 8, 1)
            handle.write(original[offset:])
        read_count = 0
        original_open = Path.open

        class CountingFile:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.handle.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.handle, name)

            def read(self, count=-1):
                nonlocal read_count
                result = self.handle.read(count)
                read_count += len(result)
                return result

        with patch.object(Path, 'open', lambda path, *args, **kwargs: CountingFile(original_open(path, *args, **kwargs))):
            index = read_index(self.source)
        self.assertEqual(index.pairs[0].count, payload_matches)
        self.assertLess(read_count, 1024)


if __name__ == '__main__':
    unittest.main()
