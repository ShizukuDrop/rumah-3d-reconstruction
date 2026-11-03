import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from tools.reconstruction.descriptor_retrieval import retrieve


class RetrievalTests(unittest.TestCase):
    def test_revisit_retrieval_excludes_temporal_neighbors_and_other_lens(self):
        with tempfile.TemporaryDirectory() as tmp:
            records, frames = [], []
            for frame, seconds, direction in [(0, 0., (1., 0.)), (1, .5, (1., 0.)), (2, 5., (.99, .01))]:
                frames.append({'id': frame, 'time_seconds': seconds})
                for lens in ('cam0', 'cam1'):
                    path = Path(tmp) / f'{lens}-{frame}.bin'
                    data = struct.pack('<4s6I', b'VKFT', 6, 3840, 3840, 2, 2, 1) + bytes(32)
                    data += np.array([direction, direction], dtype='<f4').tobytes()
                    path.write_bytes(data)
                    records.append({'name': f'{lens}/{frame}.jpg', 'lens': lens, 'frameId': frame,
                                    'feature': {'destination': str(path), 'sha256': hashlib.sha256(data).hexdigest()}})
            result = retrieve({'images': records}, {'frames': frames}, proposals_per_image=1)
            self.assertFalse(result['overlapCertified'])
            self.assertFalse(result['baselineGeometryUsed'])
            self.assertEqual(len(result['featureProvenance']), 6)
            for row in result['candidates']:
                first, second = row['image1'], row['image2']
                self.assertEqual(first.split('/')[0], second.split('/')[0])
                self.assertIn('2.jpg', (first.split('/')[1], second.split('/')[1]))
            Path(records[0]['feature']['destination']).write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                retrieve({'images': records}, {'frames': frames})


if __name__ == '__main__':
    unittest.main()
