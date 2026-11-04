"""Carve the camera-trajectory free-space tube and prune the mid-air dollhouse fog.

Starts from the raw V3 splat.ply and applies, in order:

Stage 1 - the proven V3c geometry rules (NO k-NN isolation rule, so bathroom tiles stay
          pinhole-free):
  prune  alpha < 0.02
  prune  outside the seed's p0..p100 box + 0.35 units
  prune  needle_ratio = s3/s2 > 5.0                                (any size)
  prune  needle_ratio > 3.2 AND (s3 > 0.003 OR alpha > 0.06)
  shrink 2.2 < needle_ratio <= 3.2: s3 <- 2.2 * s2                 (cigar -> disk, s1 untouched)
  floor  s1 >= 1e-5 numerically only

Stage 2 - Rule A, the camera-trajectory free-space tube. The operator physically walked the
  camera through every registered centre C_t, so the space around each C_t is empty air:
  prune  any splat within Euclidean distance < --lens-radius (0.28) of ANY C_t
         (camera lens / selfie-stick clearance sphere)
  prune  any splat with horizontal distance_xz < --body-radius (0.35) AND
         -0.50 <= (y - y_t) <= +0.22 of ANY C_t, when the splat looks non-solid
         (alpha < 0.50 OR s3/s2 > 2.0)  (operator body / stick clearance cylinder)

Stage 3 - Rule B, translucent mid-air fog:
  prune  alpha < --fog-alpha (0.06; 0.08 variant counted for the report)
  prune  alpha < 0.18 AND s3 > 0.020                                (large translucent puffs)

Camera centres come from forensic-20261104/poses-cache.npz (6,462 registered centres in the
trained splat frame, the same source the footprint gate and the presets use). As a frame
sanity check the script also parses dense/sparse/0/images.txt directly and reports how many of
those COLMAP centres match the npz set.

The PLY is rewritten with a structured dtype so every property (including the 45 SH
coefficients) is copied byte-exactly for survivors; scale edits are written back onto the
original (unsorted) scale slots so quaternions stay meaningful.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

import os

REPO = Path(__file__).resolve().parents[2]
RUN = Path(os.environ.get('STICK_RUN_ROOT') or REPO / '.local' / 'osmo-stick-20261103')
HERE = RUN / 'forensic-20261104'
CKPT = RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt'
DEFAULT_IN = CKPT / 'splat.ply'
DEFAULT_OUT = CKPT / 'splat-cleaned-v3d.ply'
BOX_SOURCE = RUN / 'optimization-v1/appearance-coverage-v2-fixed-reference/seed-clean-2m.ply'
POSES = HERE / 'poses-cache.npz'
IMAGES_TXT = RUN / 'dense/sparse/0/images.txt'

TYPES = {'float': '<f4', 'float32': '<f4', 'double': '<f8', 'float64': '<f8',
         'uchar': 'u1', 'uint8': 'u1', 'char': 'i1', 'int8': 'i1',
         'short': '<i2', 'int16': '<i2', 'ushort': '<u2', 'uint16': '<u2',
         'int': '<i4', 'int32': '<i4', 'uint': '<u4', 'uint32': '<u4'}


def load(path):
    with path.open('rb') as fh:
        head = b''
        while b'end_header' not in head:
            chunk = fh.read(4096)
            if not chunk:
                raise ValueError('truncated header')
            head += chunk
        end = head.index(b'end_header') + len(b'end_header')
        end += 1 if head[end:end + 1] == b'\n' else 2
        text = head[:end].decode('ascii')
        props = [(p.split()[2], TYPES[p.split()[1]])
                 for p in text.splitlines() if p.startswith('property')]
        count = int([ln for ln in text.splitlines() if ln.startswith('element vertex')][0].split()[2])
        dtype = np.dtype(props)
        fh.seek(end)
        table = np.fromfile(fh, dtype=dtype, count=count)
    return head[:end], text, count, table


def write(path, header, table):
    lines = header.decode('ascii').splitlines()
    for index, line in enumerate(lines):
        if line.startswith('element vertex'):
            lines[index] = f'element vertex {table.size}'
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as fh:
        fh.write(('\n'.join(lines) + '\n').encode('ascii'))
        table.tofile(fh)


def box_of(path):
    _, _, _, table = load(path)
    xyz = np.column_stack([table['x'], table['y'], table['z']]).astype(np.float64)
    return (np.percentile(xyz, 0.0, axis=0), np.percentile(xyz, 100.0, axis=0))


def parse_images_txt(path):
    """COLMAP pose lines -> centres (same math as detrend_temporal_height.py)."""
    centres = []
    with path.open('r', encoding='utf-8', errors='replace') as fh:
        for i, line in enumerate(fh):
            if i % 2:
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            qw, qx, qy, qz = (float(v) for v in parts[1:5])
            tx, ty, tz = (float(v) for v in parts[5:8])
            norm = qw * qw + qx * qx + qy * qy + qz * qz
            if norm <= 0:
                continue
            s = 2.0 / norm
            r = np.array([
                [1 - s * (qy * qy + qz * qz), s * (qx * qy - qz * qw), s * (qx * qz + qy * qw)],
                [s * (qx * qy + qz * qw), 1 - s * (qx * qx + qz * qz), s * (qy * qz - qx * qw)],
                [s * (qx * qz - qy * qw), s * (qy * qz + qx * qw), 1 - s * (qx * qx + qy * qy)],
            ])
            centres.append(-r.T @ np.array([tx, ty, tz]))
    return np.array(centres, dtype=np.float64)


def alpha_stats(alpha):
    return {
        'share_lt_0.02': float(np.mean(alpha < 0.02)),
        'share_0.02_to_0.10': float(np.mean((alpha >= 0.02) & (alpha < 0.10))),
        'share_lt_0.10': float(np.mean(alpha < 0.10)),
        'share_lt_0.18': float(np.mean(alpha < 0.18)),
        'p50': float(np.median(alpha)), 'p90': float(np.percentile(alpha, 90)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(DEFAULT_IN))
    ap.add_argument('--output', default=str(DEFAULT_OUT))
    ap.add_argument('--box-from', default=str(BOX_SOURCE))
    ap.add_argument('--margin', type=float, default=0.35)
    # stage 1 - V3c geometry rules (mandate-tightened thresholds)
    ap.add_argument('--opacity-min', type=float, default=0.02)
    ap.add_argument('--needle-ratio-hard', type=float, default=5.0)
    ap.add_argument('--needle-ratio', type=float, default=3.2)
    ap.add_argument('--needle-min-axis', type=float, default=0.003)
    ap.add_argument('--needle-min-alpha', type=float, default=0.06)
    ap.add_argument('--cigar-ratio', type=float, default=2.2)
    ap.add_argument('--axis-floor', type=float, default=1e-5)
    # stage 2 - Rule A, trajectory free-space tube
    ap.add_argument('--lens-radius', type=float, default=0.28)
    ap.add_argument('--body-radius', type=float, default=0.35)
    ap.add_argument('--body-below', type=float, default=-0.50)
    ap.add_argument('--body-above', type=float, default=0.22)
    ap.add_argument('--body-max-alpha', type=float, default=0.50)
    ap.add_argument('--body-needle-ratio', type=float, default=2.0)
    ap.add_argument('--cylinder-k', type=int, default=24,
                    help='xz-nearest centres tested per splat for the cylinder rule')
    # stage 3 - Rule B, fog
    ap.add_argument('--fog-alpha', type=float, default=0.06)
    ap.add_argument('--fog-alpha-alt', type=float, default=0.08)
    ap.add_argument('--puff-alpha', type=float, default=0.18)
    ap.add_argument('--puff-min-s3', type=float, default=0.020)
    ap.add_argument('--report', default=str(HERE / 'trajectory-fog-clean-v3d.json'))
    args = ap.parse_args()

    t0 = time.time()
    src, dst = Path(args.input), Path(args.output)
    header, text, count, table = load(src)
    print(f'read {count:,} splats from {src.name} in {time.time() - t0:.1f}s')

    xyz = np.column_stack([table['x'], table['y'], table['z']]).astype(np.float64)
    scales = np.sort(np.exp(np.column_stack([table['scale_0'], table['scale_1'],
                                             table['scale_2']]).astype(np.float64)), axis=1)
    s1, s2, s3 = scales[:, 0], scales[:, 1], scales[:, 2]
    alpha = 1.0 / (1.0 + np.exp(-table['opacity'].astype(np.float64)))
    needle_ratio = s3 / np.maximum(s2, 1e-12)

    report = {'input': str(src), 'input_splats': int(count),
              'input_bytes': src.stat().st_size,
              'before': {'alpha': alpha_stats(alpha),
                         'needle_ratio_p99': float(np.percentile(needle_ratio, 99)),
                         'needle_ratio_max': float(needle_ratio.max())}}

    # ---- camera centres + frame cross-check
    poses = np.load(POSES, allow_pickle=True)
    centres = poses['centre'].astype(np.float64)
    cam_tree3 = cKDTree(centres)
    cam_tree2 = cKDTree(centres[:, [0, 2]])
    frames = poses['frame'].astype(np.int64)
    frame_stats = {
        'centres': int(len(centres)),
        'timestamps': int(np.unique(frames).size),
        'y_p05': float(np.percentile(centres[:, 1], 5)),
        'y_p50': float(np.percentile(centres[:, 1], 50)),
        'y_p95': float(np.percentile(centres[:, 1], 95)),
        'centres_below_y_0.5': int((centres[:, 1] < 0.5).sum()),
    }
    if IMAGES_TXT.exists():
        txt_centres = parse_images_txt(IMAGES_TXT)
        d, _ = cam_tree3.query(txt_centres, k=1, workers=-1)
        frame_stats['images_txt'] = {
            'parsed': int(len(txt_centres)),
            'matched_within_1e-3': int((d < 1e-3).sum()),
            'match_distance_p50': float(np.percentile(d, 50)),
            'match_distance_p99': float(np.percentile(d, 99)),
            'match_distance_max': float(d.max()),
        }
    report['cameras'] = frame_stats
    print('cameras:', json.dumps(frame_stats))

    alive = np.ones(count, dtype=bool)
    pruned = {}

    def prune(mask, label):
        nonlocal alive
        new = mask & alive
        pruned[label] = int(new.sum())
        alive &= ~new
        return pruned[label]

    # ================= Stage 1 - proven V3c rules =================
    box_lo, box_hi = box_of(Path(args.box_from))
    inside = np.all((xyz >= box_lo - args.margin) & (xyz <= box_hi + args.margin), axis=1)
    prune(alpha < args.opacity_min, 'stage1_dead_alpha')
    prune(~inside, 'stage1_out_of_box')
    prune(needle_ratio > args.needle_ratio_hard, 'stage1_needle_hard_gt_%g' % args.needle_ratio_hard)
    prune((needle_ratio > args.needle_ratio)
          & ((s3 > args.needle_min_axis) | (alpha > args.needle_min_alpha)),
          'stage1_needle_soft_gt_%g' % args.needle_ratio)
    print('stage 1 (V3c rules):', json.dumps(pruned))
    print(f'  alive after stage 1: {int(alive.sum()):,}')

    # ================= Stage 2 - Rule A, trajectory tube =================
    idx = np.flatnonzero(alive)
    live_xyz = xyz[idx]
    live_alpha = alpha[idx]
    live_ratio = needle_ratio[idx]

    # lens clearance sphere: nearest-centre distance < lens-radius
    d1, _ = cam_tree3.query(live_xyz, k=1, workers=-1)
    lens_mask = np.zeros(len(idx), dtype=bool)
    lens_hit = d1 < args.lens_radius
    lens_mask[lens_hit] = True
    prune_lens = idx[lens_mask]
    alive[prune_lens] = False
    pruned['ruleA_lens_sphere_lt_%g' % args.lens_radius] = int(len(prune_lens))
    print(f'  Rule A lens sphere d<{args.lens_radius}: {len(prune_lens):,}')

    # body / stick clearance cylinder on the survivors
    idx = np.flatnonzero(alive)
    live_xyz = xyz[idx]
    live_alpha = alpha[idx]
    live_ratio = needle_ratio[idx]
    k = min(args.cylinder_k, len(centres))
    dd, jj = cam_tree2.query(live_xyz[:, [0, 2]], k=k, workers=-1)
    cand = centres[jj]                                   # (n, k, 3)
    dxz = dd                                             # nearest-in-xz distances per candidate
    dy = live_xyz[:, [1]] - cand[:, :, 1]
    in_window = (dxz < args.body_radius) & (dy >= args.body_below) & (dy <= args.body_above)
    non_solid = (live_alpha < args.body_max_alpha) | (live_ratio > args.body_needle_ratio)
    body_mask = in_window.any(axis=1) & non_solid
    prune_body = idx[body_mask]
    alive[prune_body] = False
    pruned['ruleA_body_cylinder_r%g_dy[%g,%g]' % (args.body_radius, args.body_below, args.body_above)] = \
        int(len(prune_body))
    coverage = dd.min(axis=1)                            # how far the k-th xz reach is, min over k
    print(f'  Rule A body cylinder dxz<{args.body_radius}: {len(prune_body):,}')
    print(f'  cylinder query coverage: nearest xz distance p50={np.percentile(coverage, 50):.4f} '
          f'p99={np.percentile(coverage, 99):.4f} (k={k}); min over candidates '
          f'p99={np.percentile(dd[:, -1], 99):.4f} means every splat sees centres within '
          f'{np.percentile(dd[:, -1], 99):.3f} units in xz')
    print(f'  alive after Rule A: {int(alive.sum()):,}')

    # ================= Stage 3 - Rule B, fog =================
    idx = np.flatnonzero(alive)
    live_alpha = alpha[idx]
    live_s3 = s3[idx]
    live_ratio = needle_ratio[idx]
    haze = idx[live_alpha < args.fog_alpha]
    alive[haze] = False
    pruned['ruleB_haze_alpha_lt_%g' % args.fog_alpha] = int(len(haze))
    idx = np.flatnonzero(alive)
    live_alpha = alpha[idx]
    live_s3 = s3[idx]
    puffs = idx[(live_alpha < args.puff_alpha) & (live_s3 > args.puff_min_s3)]
    alive[puffs] = False
    pruned['ruleB_puff_alpha_lt_%g_s3_gt_%g' % (args.puff_alpha, args.puff_min_s3)] = int(len(puffs))
    pruned['total'] = int(count - alive.sum())
    print('stage 3 (Rule B fog):', json.dumps({k: v for k, v in pruned.items() if k.startswith('ruleB')}))
    print(f'  final splats: {int(alive.sum()):,}')

    # ================= write output =================
    sub = table[alive]
    kept_scales = scales[alive]
    kept_ratio = needle_ratio[alive]

    world = kept_scales.copy()
    cigar = (kept_ratio > args.cigar_ratio) & (kept_ratio <= args.needle_ratio)
    if cigar.any():
        world[cigar, 2] = args.cigar_ratio * world[cigar, 1]
    floored = world[:, 0] < args.axis_floor
    world[:, 0] = np.maximum(world[:, 0], args.axis_floor)
    original = np.column_stack([sub['scale_0'], sub['scale_1'], sub['scale_2']]).astype(np.float64)
    order = np.argsort(original, axis=1)
    log_new = np.empty_like(original)
    log_new[np.arange(world.shape[0])[:, None], order] = np.log(world)
    for index, column in enumerate(('scale_0', 'scale_1', 'scale_2')):
        sub[column] = log_new[:, index].astype(sub[column].dtype)

    write(dst, header, sub)

    kept_alpha = alpha[alive]
    fog_alt = int((kept_alpha < args.fog_alpha_alt).sum())  # survivors still below the alt cut
    report.update({
        'output': str(dst), 'output_splats': int(sub.size),
        'output_bytes': dst.stat().st_size,
        'pruned': pruned,
        'pruned_fraction': float(1 - sub.size / count),
        'modified': {'cigars_shrunk_2.2x': int(cigar.sum()),
                     'axis_floored_numeric': int(floored.sum())},
        'survivors_below_fog_alpha_alt_%g' % args.fog_alpha_alt: fog_alt,
        'after': {'alpha': alpha_stats(kept_alpha),
                  'needle_ratio_p99': float(np.percentile(kept_ratio, 99)),
                  'needle_ratio_max': float(kept_ratio.max())},
        'thresholds': {k: getattr(args, k) for k in (
            'margin', 'opacity_min', 'needle_ratio_hard', 'needle_ratio', 'needle_min_axis',
            'needle_min_alpha', 'cigar_ratio', 'axis_floor', 'lens_radius', 'body_radius',
            'body_below', 'body_above', 'body_max_alpha', 'body_needle_ratio', 'cylinder_k',
            'fog_alpha', 'fog_alpha_alt', 'puff_alpha', 'puff_min_s3')},
        'box': {'lo': box_lo.tolist(), 'hi': box_hi.tolist(), 'source': str(args.box_from)},
        'elapsed_seconds': round(time.time() - t0, 1),
    })
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('pruned', 'modified', 'before', 'after')}, indent=2))
    print(f'wrote {dst} in {report["elapsed_seconds"]}s')


if __name__ == '__main__':
    main()
