"""CPU geometric/semantic checks for operator segmentation view reprojection."""
import argparse
import unittest
import numpy as np
import cv2
import operator_pinhole as op


def main(record=False):
    camera = {'id': 1, 'model': 'OPENCV_FISHEYE', 'model_id': 5, 'width': 384, 'height': 384,
              'params': np.array([104.8, 104.8, 191.5, 191.5, .0458, .022, -.0146, .0014])}
    checks = []
    for phi in (0., 90., 180., 270.):
        mx, my, valid, meta = op.pinhole_map(camera, theta=75., phi=phi, roll=15., size=128, fov=90.)
        mask = np.full((128, 128), 255, np.uint8); mask[48:80, 48:80] = 0
        valid_image = valid.astype(np.uint8)*255
        excluded, coverage = op.unwarp_mask(mask, valid_image, meta, 'keep', rows_per_chunk=32)
        assert np.any(excluded) and np.any(coverage)
        assert not np.any(excluded[coverage == 0])
        back = cv2.remap(excluded, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0) > 0
        expected = (mask == 0) & valid
        iou = float((back & expected).sum()/max((back | expected).sum(), 1))
        assert iou > .90, (phi, iou)
        alt, _ = op.unwarp_mask(255-mask, valid_image, meta, 'exclude', rows_per_chunk=32)
        assert np.array_equal(alt, excluded)
        all_valid, _ = op.unwarp_mask(np.full_like(mask, 255), valid_image, meta, 'keep', rows_per_chunk=32)
        assert not np.any(all_valid)
        checks.append({'phi': phi, 'round_trip_iou': iou,
                       'native_coverage_fraction': float((coverage > 0).mean()), 'native_excluded_fraction': float((excluded > 0).mean())})
    result = {'passed': True, 'gpu_used': False, 'capture_files_read': False, 'views': checks,
              'semantics_verified': ['four native rim orientations', 'proper rotation, no reflection',
                                     'inverse exclusion stays inside validity coverage', 'keep/exclude polarity equivalence',
                                     'an all-keep view excludes no native pixels', 'binary mask round trip IoU above0.90']}
    if record:
        op.save(op.HERE/'operator-pinhole-synthetic-tests.json', result)
    print(result)


class OperatorPinhole(unittest.TestCase):
    def test_operator_pinhole(self):
        main()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--record', action='store_true', help='Rewrite the committed evidence JSON')
    main(p.parse_args().record)
