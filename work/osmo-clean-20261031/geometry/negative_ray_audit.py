"""CPU observed-free-space audit. Reports contradicted faces, never edits a mesh.

A reliable unmasked SfM observation establishes an empty camera-to-point segment.
A triangle intersecting that segment substantially before the point contradicts
the observation. No-hit rays and unobserved triangles are UNKNOWN, not grounds
for deletion. This is in-sample SfM consistency, not independent depth truth.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import numpy as np
import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'osmo-improve-20261031/qa-deps'))
from normalize_fresh_sfm import FRESH, read_model, qvec_to_rotmat, Fisheye, split_name, fresh_path, digest, save
import trimesh
try:
    from trimesh.ray.ray_pyembree import RayMeshIntersector
except ImportError:  # ponytail: embreex missing; trimesh's rtree intersector gives the same first hits, slower on full meshes
    from trimesh.ray.ray_triangle import RayMeshIntersector


def collect_rays(model, masks_dir, per_image_cap=200, max_error=2.5, min_track=5, max_theta=85):
    cameras, images, points = read_model(model)
    rows = defaultdict(list)
    rng = np.random.default_rng(20261031)
    for im in sorted(images.values(), key=lambda im: im['name']):
        if split_name(im['name']) != 'train':
            continue
        cam = cameras[im['camera_id']]
        inds = np.array([i for i, pid in enumerate(im['point3D_ids'])
                         if int(pid) in points and points[int(pid)]['track_len'] >= min_track], dtype=int)
        if not len(inds):
            continue
        xyz = np.array([points[int(im['point3D_ids'][i])]['xyz'] for i in inds])
        obs = im['points2D_xy'][inds]
        r = qvec_to_rotmat(im['qvec']); center = -r.T @ im['tvec']; pc = xyz @ r.T + im['tvec']
        pred, valid = Fisheye(cam).project(pc)
        err = np.linalg.norm(pred - obs, axis=1)
        theta = np.rad2deg(np.arctan2(np.linalg.norm(pc[:, :2], axis=1), pc[:, 2]))
        mask_path = masks_dir/Path(im['name']).with_suffix('.png')
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None or mask.shape != (cam['height'], cam['width']):
            raise ValueError(f'Valid native mask required: {mask_path}')
        mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
        xy = np.floor(obs).astype(int)
        good = valid & np.isfinite(err) & (err <= max_error) & (theta <= max_theta)
        good &= (xy[:, 0] >= 0) & (xy[:, 0] < cam['width']) & (xy[:, 1] >= 0) & (xy[:, 1] < cam['height'])
        ix = np.flatnonzero(good); good[ix] &= mask[xy[ix, 1], xy[ix, 0]] > 127
        ix = np.flatnonzero(good)
        if len(ix) > per_image_cap:
            ix = rng.choice(ix, per_image_cap, replace=False)
        for j in sorted(ix):
            rows['origins'].append(center); rows['targets'].append(xyz[j])
            rows['point_ids'].append(int(im['point3D_ids'][inds[j]]))
            rows['names'].append(im['name']); rows['frame_keys'].append(Path(im['name']).stem)
            rows['reprojection_px'].append(float(err[j]))
    if not rows['origins']:
        raise ValueError('No reliable unmasked train rays')
    return {k: np.asarray(v) for k, v in rows.items()}


def classify_face_evidence(face_ids, distances, rays, abs_tolerance=.01, rel_tolerance=.025,
                           minimum_frames=2, minimum_points=2, minimum_relative_baseline=.02):
    expected = np.linalg.norm(rays['targets'] - rays['origins'], axis=1)
    tolerance = np.maximum(abs_tolerance, rel_tolerance * expected)
    hit = (face_ids >= 0) & np.isfinite(distances)
    early = hit & (distances < expected - tolerance)
    close = hit & (np.abs(distances - expected) <= tolerance)
    behind = hit & (distances > expected + tolerance)
    positive_faces = set(map(int, face_ids[close]))
    by_face = defaultdict(list)
    for i in np.flatnonzero(early):
        by_face[int(face_ids[i])].append(int(i))
    candidates, details = [], []
    for face, obs in sorted(by_face.items()):
        idx = np.asarray(obs)
        frames = set(map(str, rays['frame_keys'][idx])); points = set(map(int, rays['point_ids'][idx]))
        centers = rays['origins'][idx]
        extent = float(np.linalg.norm(np.ptp(centers, axis=0)))
        scale = float(np.median(expected[idx]))
        # Bounding-box diagonal is only an early upper bound; actual pair distance
        # must establish the minimum baseline so a loose box cannot invent one.
        actual = 0.0
        if extent >= minimum_relative_baseline*scale:
            for i in range(len(centers)-1):
                other = np.flatnonzero(rays['frame_keys'][idx[i+1:]] != rays['frame_keys'][idx[i]]) + i + 1
                if len(other):
                    actual = max(actual, float(np.linalg.norm(centers[other] - centers[i], axis=1).max()))
        accepted = (len(frames) >= minimum_frames and len(points) >= minimum_points and
                    actual >= minimum_relative_baseline*scale and face not in positive_faces)
        if accepted:
            candidates.append(face)
        details.append({'face_id': face, 'early_ray_count': len(obs), 'distinct_timestamp_count': len(frames),
                        'distinct_point_count': len(points), 'max_distinct_timestamp_center_baseline': actual,
                        'relative_baseline': actual/max(scale, 1e-12), 'near_surface_support_veto': face in positive_faces,
                        'review_candidate': accepted})
    return np.asarray(candidates, dtype=np.int64), {
        'rays': len(expected), 'early_intersection_rays': int(early.sum()),
        'near_surface_rays': int(close.sum()), 'behind_surface_rays': int(behind.sum()), 'no_hit_rays': int((~hit).sum()),
        'early_intersection_faces': len(by_face), 'review_candidate_faces': len(candidates),
        'absolute_tolerance_nonmetric_world_units': abs_tolerance, 'relative_range_tolerance': rel_tolerance,
        'minimum_distinct_timestamps': minimum_frames, 'minimum_distinct_sparse_points': minimum_points,
        'minimum_center_baseline_fraction_of_range': minimum_relative_baseline,
        'face_evidence': details}


def cast_rays(mesh, rays):
    origins = rays['origins']; vectors = rays['targets'] - origins
    directions = vectors / np.linalg.norm(vectors, axis=1)[:, None]
    face_ids = np.full(len(origins), -1, dtype=np.int64)
    distances = np.full(len(origins), np.inf)
    intersector = RayMeshIntersector(mesh)
    for start in range(0, len(origins), 1024):
        end = min(start+1024, len(origins))
        faces, ids, locations = intersector.intersects_id(origins[start:end], directions[start:end],
                                                         multiple_hits=False, return_locations=True)
        face_ids[start+ids] = faces
        # ray_triangle returns shape (0,) rather than (0, 3) when a whole batch misses.
        distances[start+ids] = np.linalg.norm(np.asarray(locations).reshape(-1, 3) - origins[start+ids], axis=1)
    return face_ids, distances


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mesh', type=Path, required=True)
    p.add_argument('--model', type=Path, default=FRESH/'dataset/sparse/0')
    p.add_argument('--masks-dir', type=Path, default=FRESH/'dataset/masks')
    p.add_argument('--output', type=Path, default=HERE/'negative-ray-audit.json')
    p.add_argument('--rays-per-image', type=int, default=200)
    p.add_argument('--absolute-tolerance', type=float, default=.01)
    p.add_argument('--relative-tolerance', type=float, default=.025)
    a = p.parse_args()
    model = fresh_path(a.model); mesh_path = fresh_path(a.mesh); masks = fresh_path(a.masks_dir)
    output = a.output.resolve()
    if not output.is_relative_to(HERE) or output.suffix != '.json':
        raise ValueError('Output must be a JSON report under the geometry helper directory')
    if output.exists() or output.with_suffix('.npz').exists():
        raise FileExistsError('Refusing audit overwrite')
    rays = collect_rays(model, masks, a.rays_per_image)
    scene = trimesh.load_scene(mesh_path, process=False)
    mesh = scene.to_geometry()
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError('Expected a triangle mesh')
    faces, distance = cast_rays(mesh, rays)
    candidates, stats = classify_face_evidence(faces, distance, rays, a.absolute_tolerance, a.relative_tolerance)
    report = {'mesh': str(mesh_path), 'mesh_sha256': digest(mesh_path), 'mesh_faces': len(mesh.faces),
              'source_model': str(model), 'ray_type': 'unmasked, low-reprojection-error TRAIN sparse feature observations',
              'maximum_native_reprojection_error_px': 2.5, 'minimum_point_track_length': 5,
              'maximum_fisheye_angle_deg_for_strict_witnesses': 85, 'per_image_ray_cap': a.rays_per_image,
              'old_mesh_or_old_probe_used': False, 'mesh_changed': False,
              'candidate_face_area': float(np.asarray(mesh.area_faces)[candidates].sum()),
              'candidate_area_fraction': float(np.asarray(mesh.area_faces)[candidates].sum()/max(mesh.area, 1e-12)),
              'evidence': stats,
              'limitations': ['In-sample geometric consistency; sparse observations may be wrong or reflected even after masks.',
                              'Unknown or no-hit rays never reject a face; unobserved walls are not deleted by this audit.',
                              'Back shells behind observed surfaces can survive: this is not a watertightness or visibility algorithm.',
                              'Face IDs refer to the exact flattened mesh hash, not another export.',
                              'Review candidates before any deletion; no texture, mesh, or production artifact was edited.']}
    save(output, report)
    np.savez_compressed(output.with_suffix('.npz'), candidate_face_ids=candidates,
                        first_hit_faces=faces, first_hit_ranges=distance, **rays)
    print(json.dumps({k: report[k] for k in ('mesh_faces', 'candidate_face_area', 'candidate_area_fraction', 'mesh_changed')}, indent=2))


if __name__ == '__main__':
    main()
