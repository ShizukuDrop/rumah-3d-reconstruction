"""CPU integration checks with tiny synthetic fisheye data, no capture/model access."""
from pathlib import Path
import argparse
import json
import sys
import tempfile
import unittest
import numpy as np
import cv2
import normalize_fresh_sfm as prep


def main(record=False):
    original_fresh, original_here = prep.FRESH, prep.HERE
    original_argv = sys.argv
    checks = []
    with tempfile.TemporaryDirectory(prefix='synthetic-preparation-') as tmp:
        root = Path(tmp).resolve()
        prep.FRESH = prep.HERE = root  # report/output guards accept the system temp fixture only
        model = root/'sfm/sparse/0'; image_dir = root/'dataset/images'; mask_dir = root/'dataset/masks'
        cameras = {cid: {'id': cid, 'model': 'OPENCV_FISHEYE', 'model_id': 5, 'width': 64, 'height': 64,
                         'params': np.array([12., 12., 32., 32., 0., 0., 0., 0.])} for cid in (1, 2)}
        xyz = {1: [-1., 0., 5.], 2: [0., 1., 5.], 3: [1., -1., 5.], 4: [1.5, 1., 5.], 5: [0., -1.5, 5.]}
        points = {pid: {'id': pid, 'xyz': np.array(p), 'rgb': np.array([255, 255, 255], np.uint8),
                        'error': 0., 'track_len': 0, 'image_ids': [], 'point2D_idxs': []} for pid, p in xyz.items()}
        records = [{'source_frame': frame, 'filename': f'frame_{frame:06d}_{"eval" if frame == 30 else "train"}.jpg',
                    'split': 'eval' if frame == 30 else 'train'} for frame in (0, 10, 20, 30)]
        images = {}
        for k, record in enumerate(records):
            for lens in (0, 1):
                iid = len(images) + 1
                center = np.array([k*.1, lens*.02, 1.])
                ids = [pid for pid in points if (pid != 2 or k in (0, 3)) and (pid != 3 or k == 3)]
                obs, valid = prep.Fisheye(cameras[lens+1]).project(np.array([xyz[pid] for pid in ids]) - center)
                assert valid.all()
                name = f'cam{lens}/{record["filename"]}'
                im = {'id': iid, 'qvec': np.array([1., 0., 0., 0.]), 'tvec': -center, 'camera_id': lens+1,
                      'name': name, 'points2D_xy': obs, 'point3D_ids': np.array(ids), 'n_points2D': len(ids)}
                images[iid] = im
                for j, pid in enumerate(ids):
                    points[pid]['image_ids'].append(iid); points[pid]['point2D_idxs'].append(j)
                    points[pid]['track_len'] += 1
                path = image_dir/name; path.parent.mkdir(parents=True, exist_ok=True)
                rgb = np.full((64, 64, 3), [80, 40, 10] if k < 3 else [0, 0, 250], np.uint8)
                assert cv2.imwrite(str(path), rgb)
                mask = np.full((64, 64), 255, np.uint8)
                if k < 3:
                    j = ids.index(4); xx, yy = np.floor(obs[j]).astype(int); mask[yy, xx] = 0
                path = mask_dir/Path(name).with_suffix('.png'); path.parent.mkdir(parents=True, exist_ok=True)
                assert cv2.imwrite(str(path), mask)
        prep.write_model_text(model, cameras, images, points)
        selection = root/'selection.json'; selection.write_text(json.dumps({'selected': records}))
        rules = {'visually_verified': True, 'verification': 'Synthetic fixture only', 'regions': [
            {'name': 'bathroom', 'source_frame_min': 0, 'source_frame_max': 10, 'enforce': False},
            {'name': 'entry', 'source_frame_min': 0, 'source_frame_max': 10, 'enforce': False},
            {'name': 'bathroom_second', 'source_frame_min': 20, 'source_frame_max': 30, 'enforce': False}],
            'repeat_visit_groups': [{'name': 'synthetic_repeat', 'region_names': ['bathroom', 'bathroom_second']}]}
        coverage = root/'coverage.json'; coverage.write_text(json.dumps(rules))
        report = root/'report.json'
        sys.argv = ['normalize_fresh_sfm.py', '--sfm-root', str(root/'sfm'), '--selection', str(selection),
                    '--coverage', str(coverage), '--source-up', 'z', '--unit-camera-height', '--mask-erode-px', '0',
                    '--minimum-seed-points', '1', '--report', str(report), '--apply']
        prep.main()
        c, ims, pts = prep.read_model(root/'dataset/sparse/0')
        assert set(pts) == {1, 5}, set(pts)
        checks.append('two lenses at one timestamp are not two independent training observations')
        checks.append('eval-only and masked train points are excluded')
        assert all(not any(prep.split_name(ims[int(i)]['name']) == 'eval' for i in p['image_ids']) for p in pts.values())
        assert all(np.all(im['point3D_ids'] == -1) for im in ims.values() if prep.split_name(im['name']) == 'eval')
        checks.append('train point tracks and eval image links remain mutually consistent after text round-trip')
        assert all(np.max(np.abs(p['rgb'].astype(int) - [10, 40, 80])) < 5 for p in pts.values())
        checks.append('seed colors come only from train RGB, not old points3D colors or eval RGB')
        audit = json.loads(report.read_text())
        assert audit['seed_filter']['eval_rgb_files_opened'] == 0
        assert audit['projection_ray_identity_max_error'] < 1e-10
        checks.append('one Y-up similarity preserves projection rays')
        repeat = audit['repeat_visit_audit'][0]
        assert repeat['direct_cross_visit_sparse_tracks'] == 4
        assert repeat['cross_visit_tracks_with_two_timestamps_in_each_visit'] == 3
        assert repeat['registered_images_per_visit'] == [4, 4]
        assert Path(audit['continuity_preview']).is_file()
        checks.append('repeat-room audit counts cross-visit tracks separately from one-instant lens duplicates')
        missing = dict(images); missing.pop(1)
        assert not prep.coverage(missing, records, rules, .9)['passes']
        checks.append('registration gates count complete synchronized pairs')
        # Native fisheye validity must include >90-degree rays, not pinhole z>0.
        camera = prep.Fisheye(cameras[1]); angle = np.deg2rad(100.)
        ray = np.array([[np.sin(angle), 0., np.cos(angle)]])
        xy, valid = camera.project(ray); recovered, back_valid = camera.unproject(xy)
        assert valid.all() and back_valid.all() and np.max(np.abs(recovered-ray)) < 1e-7
        checks.append('fisheye projection round-trips a 100-degree behind-hemisphere ray')
        # Re-running cannot overwrite working results.
        try:
            prep.main()
            raise AssertionError('Expected overwrite refusal')
        except FileExistsError:
            checks.append('existing seed and prepared model cannot be overwritten')
        prep.FRESH, prep.HERE = original_fresh, original_here
        sys.argv = original_argv
    result = {'passed': len(checks), 'checks': checks, 'capture_files_read': False, 'gpu_used': False}
    if record:
        prep.save(prep.HERE/'preparation-synthetic-tests.json', result)
    print(json.dumps(result, indent=2))


class SyntheticPreparation(unittest.TestCase):
    def test_synthetic_preparation(self):
        main()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--record', action='store_true', help='Rewrite the committed evidence JSON')
    main(p.parse_args().record)
