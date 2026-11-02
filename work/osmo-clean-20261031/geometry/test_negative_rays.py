"""Small CPU geometry checks for candidate negative-ray classification."""
import argparse
import json
import unittest
import numpy as np
import negative_ray_audit as audit


def main(record=False):
    mesh = audit.trimesh.Trimesh(vertices=[[-5., -5., 2.], [5., -5., 2.], [0., 5., 2.]], faces=[[0, 1, 2]], process=False)
    rays = {'origins': np.array([[-.5, 0., 0.], [.5, 0., 0.]]),
            'targets': np.array([[-.2, 0., 4.], [.2, 0., 4.]]),
            'frame_keys': np.array(['frame_000010_train', 'frame_000020_train']),
            'point_ids': np.array([1, 2])}
    faces, ranges = audit.cast_rays(mesh, rays)
    candidate, report = audit.classify_face_evidence(faces, ranges, rays)
    assert candidate.tolist() == [0] and report['early_intersection_rays'] == 2
    checks = ['actual CPU triangle intersection flags two distinct-timestamp, distinct-point early contradictions']
    same_time = {**rays, 'frame_keys': np.array(['same', 'same'])}
    assert len(audit.classify_face_evidence(faces, ranges, same_time)[0]) == 0
    checks.append('two lens views at the same timestamp cannot satisfy temporal independence')
    same_point = {**rays, 'point_ids': np.array([1, 1])}
    assert len(audit.classify_face_evidence(faces, ranges, same_point)[0]) == 0
    checks.append('repeated evidence from a single sparse point cannot reject a face')
    same_origin = {**rays, 'origins': np.zeros((2, 3))}
    assert len(audit.classify_face_evidence(faces, ranges, same_origin)[0]) == 0
    checks.append('camera rotation without translated baseline cannot satisfy the witness gate')
    positive = {**rays, 'targets': np.array([[-.2, 0., 4.], [.2, 0., 2.]])}
    faces_p, ranges_p = audit.cast_rays(mesh, positive)
    assert len(audit.classify_face_evidence(faces_p, ranges_p, positive)[0]) == 0
    checks.append('observed surface support vetoes deleting the whole triangle')
    assert len(audit.classify_face_evidence(np.array([-1, -1]), np.array([np.inf, np.inf]), rays)[0]) == 0
    checks.append('no-hit and unknown evidence never rejects a face')
    result = {'passed': len(checks), 'checks': checks, 'gpu_used': False, 'capture_files_read': False, 'mesh_edited': False}
    if record:
        audit.save(audit.HERE/'negative-ray-synthetic-tests.json', result)
    print(json.dumps(result, indent=2))


class NegativeRays(unittest.TestCase):
    def test_negative_rays(self):
        main()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--record', action='store_true', help='Rewrite the committed evidence JSON')
    main(p.parse_args().record)
