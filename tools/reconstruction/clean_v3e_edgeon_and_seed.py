"""V3e: seed-supported surface filter + edge-on 2D disk guard, on top of the full V3d rules.

Starts from the raw V3 splat.ply. Pipeline, all counts incremental (disjoint):

Stage 1 - proven V3c geometry rules (no k-NN isolation rule):
  prune  alpha < 0.02
  prune  outside seed box + 0.35
  prune  s3/s2 > 5.0
  prune  s3/s2 > 3.2 AND (s3 > 0.003 OR alpha > 0.06)
  shrink 2.2 < s3/s2 <= 3.2: s3 <- 2.2 * s2

Rule A - camera-trajectory free-space tube (6,462 registered centres, poses-cache.npz):
  prune  Euclidean d < 0.28 of any centre                  (lens / stick clearance sphere)
  prune  d_xz < 0.35 AND -0.50 <= dy <= +0.22 AND non-solid (alpha < 0.50 OR s3/s2 > 2.0)

Rule B - translucent mid-air fog:
  prune  alpha < 0.06
  prune  alpha < 0.18 AND s3 > 0.020

Rule C - unsupported mid-air floaters, measured against the multi-view triangulated seed
  (seed-clean-2m.ply, ~2M points; d_seed_k3 = distance to the 3rd-nearest seed point):
  prune  d_seed_k3 > 0.045 AND y > 0.08 (not floor) AND (alpha < 0.55 OR d_cam < 0.75
         OR s2/s1 > 10.0)
  prune  0.28 <= d_cam < 0.65 AND d_seed_k3 > 0.025 AND (alpha < 0.45 OR s2/s1 > 8.0
         OR s3/s2 > 2.0)

Rule D - edge-on razor-disk streaks (flat disks s2/s1 >> 10, s3 > 0.004, off-surface or
  semi-transparent; crisp on-surface alpha >= 0.35 surfels with d_seed_k3 <= 0.020 are
  untouched by construction):
  target  (d_seed_k3 > 0.020 OR alpha < 0.35) AND s2/s1 > 12.0 AND s3 > 0.004
  prune   target AND d_cam < 0.80 AND alpha < 0.28       (near-field translucent wafer)
  clamp   otherwise: s1 >= s2 / 5.0 AND s3 <= 1.8 * s2   (can never render as a hair streak)
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
DEFAULT_OUT = CKPT / 'splat-cleaned-v3e.ply'
SEED_PLY = RUN / 'optimization-v1/appearance-coverage-v2-fixed-reference/seed-clean-2m.ply'
BOX_SOURCE = SEED_PLY
POSES = HERE / 'poses-cache.npz'

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(DEFAULT_IN))
    ap.add_argument('--output', default=str(DEFAULT_OUT))
    ap.add_argument('--box-from', default=str(BOX_SOURCE))
    ap.add_argument('--seed-from', default=str(SEED_PLY))
    ap.add_argument('--margin', type=float, default=0.35)
    # stage 1
    ap.add_argument('--opacity-min', type=float, default=0.02)
    ap.add_argument('--needle-ratio-hard', type=float, default=5.0)
    ap.add_argument('--needle-ratio', type=float, default=3.2)
    ap.add_argument('--needle-min-axis', type=float, default=0.003)
    ap.add_argument('--needle-min-alpha', type=float, default=0.06)
    ap.add_argument('--cigar-ratio', type=float, default=2.2)
    ap.add_argument('--axis-floor', type=float, default=1e-5)
    # rule A
    ap.add_argument('--lens-radius', type=float, default=0.28)
    ap.add_argument('--body-radius', type=float, default=0.35)
    ap.add_argument('--body-below', type=float, default=-0.50)
    ap.add_argument('--body-above', type=float, default=0.22)
    ap.add_argument('--body-max-alpha', type=float, default=0.50)
    ap.add_argument('--body-needle-ratio', type=float, default=2.0)
    ap.add_argument('--cylinder-k', type=int, default=24)
    # rule B
    ap.add_argument('--fog-alpha', type=float, default=0.06)
    ap.add_argument('--puff-alpha', type=float, default=0.18)
    ap.add_argument('--puff-min-s3', type=float, default=0.020)
    # rule C
    ap.add_argument('--seed-far', type=float, default=0.045)
    ap.add_argument('--seed-far-corridor', type=float, default=0.025)
    ap.add_argument('--floor-max-y', type=float, default=0.08)
    ap.add_argument('--far-max-alpha', type=float, default=0.55)
    ap.add_argument('--far-max-dcam', type=float, default=0.75)
    ap.add_argument('--far-max-disk', type=float, default=10.0)
    ap.add_argument('--corridor-dcam', type=float, default=0.65)
    ap.add_argument('--corridor-max-alpha', type=float, default=0.45)
    ap.add_argument('--corridor-max-disk', type=float, default=8.0)
    ap.add_argument('--corridor-max-needle', type=float, default=2.0)
    ap.add_argument('--seed-k', type=int, default=3)
    # rule D
    ap.add_argument('--disk-ratio', type=float, default=12.0)
    ap.add_argument('--disk-min-s3', type=float, default=0.004)
    ap.add_argument('--disk-off-seed', type=float, default=0.020)
    ap.add_argument('--disk-max-alpha', type=float, default=0.35)
    ap.add_argument('--disk-prune-dcam', type=float, default=0.80)
    ap.add_argument('--disk-prune-alpha', type=float, default=0.28)
    ap.add_argument('--disk-thickness', type=float, default=5.0, help='clamp s1 >= s2 / this')
    ap.add_argument('--disk-max-needle', type=float, default=1.8, help='clamp s3 <= this * s2')
    ap.add_argument('--report', default=str(HERE / 'edgeon-seed-clean-v3e.json'))
    args = ap.parse_args()

    t0 = time.time()
    src, dst = Path(args.input), Path(args.output)
    header, text, count, table = load(src)
    print(f'read {count:,} splats from {src.name} in {time.time() - t0:.1f}s')

    xyz = np.column_stack([table['x'], table['y'], table['z']]).astype(np.float64)
    scales = np.sort(np.exp(np.column_stack([table['scale_0'], table['scale_1'],
                                             table['scale_2']]).astype(np.float64)), axis=1)
    s2, s3 = scales[:, 1], scales[:, 2]
    alpha = 1.0 / (1.0 + np.exp(-table['opacity'].astype(np.float64)))
    needle_ratio = s3 / np.maximum(s2, 1e-12)
    disk_ratio = s2 / np.maximum(scales[:, 0], 1e-12)

    # ---- camera centres
    poses = np.load(POSES, allow_pickle=True)
    centres = poses['centre'].astype(np.float64)
    cam_tree3 = cKDTree(centres)
    cam_tree2 = cKDTree(centres[:, [0, 2]])

    # ---- seed point tree (multi-view triangulated surfaces)
    _, _, seed_count, seed_table = load(Path(args.seed_from))
    seed_xyz = np.column_stack([seed_table['x'], seed_table['y'], seed_table['z']]).astype(np.float64)
    del seed_table
    seed_tree = cKDTree(seed_xyz)
    del seed_xyz
    print(f'seed tree: {seed_count:,} points from {Path(args.seed_from).name}, '
          f'built in {time.time() - t0:.1f}s')

    alive = np.ones(count, dtype=bool)
    pruned = {}

    def prune(mask, label):
        nonlocal alive
        new = mask & alive
        pruned[label] = int(new.sum())
        alive &= ~new
        return pruned[label]

    # ================= Stage 1 =================
    _, _, _, box_table = load(Path(args.box_from))
    box_xyz = np.column_stack([box_table['x'], box_table['y'], box_table['z']]).astype(np.float64)
    box_lo = np.percentile(box_xyz, 0.0, axis=0)
    box_hi = np.percentile(box_xyz, 100.0, axis=0)
    del box_table, box_xyz
    inside = np.all((xyz >= box_lo - args.margin) & (xyz <= box_hi + args.margin), axis=1)
    prune(alpha < args.opacity_min, 'stage1_dead_alpha')
    prune(~inside, 'stage1_out_of_box')
    prune(needle_ratio > args.needle_ratio_hard, 'stage1_needle_hard')
    prune((needle_ratio > args.needle_ratio)
          & ((s3 > args.needle_min_axis) | (alpha > args.needle_min_alpha)), 'stage1_needle_soft')
    print('stage 1:', json.dumps(pruned))

    # ================= Rule A =================
    idx = np.flatnonzero(alive)
    d1, _ = cam_tree3.query(xyz[idx], k=1, workers=-1)
    lens = idx[d1 < args.lens_radius]
    alive[lens] = False
    pruned['ruleA_lens_sphere'] = int(len(lens))

    idx = np.flatnonzero(alive)
    dd, jj = cam_tree2.query(xyz[idx][:, [0, 2]], k=min(args.cylinder_k, len(centres)), workers=-1)
    cand = centres[jj]
    dy = xyz[idx][:, [1]] - cand[:, :, 1]
    in_window = (dd < args.body_radius) & (dy >= args.body_below) & (dy <= args.body_above)
    body = in_window.any(axis=1) & ((alpha[idx] < args.body_max_alpha)
                                    | (needle_ratio[idx] > args.body_needle_ratio))
    prune_body = idx[body]
    alive[prune_body] = False
    pruned['ruleA_body_cylinder'] = int(len(prune_body))
    print('Rule A:', json.dumps({k: pruned[k] for k in ('ruleA_lens_sphere', 'ruleA_body_cylinder')}))

    # ================= Rule B =================
    idx = np.flatnonzero(alive)
    haze = idx[alpha[idx] < args.fog_alpha]
    alive[haze] = False
    pruned['ruleB_haze'] = int(len(haze))
    idx = np.flatnonzero(alive)
    puffs = idx[(alpha[idx] < args.puff_alpha) & (s3[idx] > args.puff_min_s3)]
    alive[puffs] = False
    pruned['ruleB_puffs'] = int(len(puffs))
    print('Rule B:', json.dumps({k: pruned[k] for k in ('ruleB_haze', 'ruleB_puffs')}))

    # ================= distances for Rules C / D =================
    idx = np.flatnonzero(alive)
    live_xyz = xyz[idx]
    d_seed, _ = seed_tree.query(live_xyz, k=args.seed_k, workers=-1)
    d_seed_k3 = d_seed[:, -1]
    d_cam, _ = cam_tree3.query(live_xyz, k=1, workers=-1)
    live_alpha, live_needle, live_disk = alpha[idx], needle_ratio[idx], disk_ratio[idx]
    live_y = live_xyz[:, 1]
    print(f'distances on {len(idx):,} survivors: d_seed_k3 p50={np.percentile(d_seed_k3, 50):.4f} '
          f'p90={np.percentile(d_seed_k3, 90):.4f} p99={np.percentile(d_seed_k3, 99):.4f}; '
          f'd_cam p50={np.percentile(d_cam, 50):.4f} ({time.time() - t0:.1f}s)')

    # ================= Rule C =================
    far_floater = ((d_seed_k3 > args.seed_far) & (live_y > args.floor_max_y)
                   & ((live_alpha < args.far_max_alpha) | (d_cam < args.far_max_dcam)
                      | (live_disk > args.far_max_disk)))
    prune_c1 = idx[far_floater]
    alive[prune_c1] = False
    pruned['ruleC_far_floater'] = int(len(prune_c1))

    idx_after_c1 = np.flatnonzero(alive)
    rows = np.searchsorted(idx, idx_after_c1)   # positions into the post-B survivor arrays
    corridor = ((d_cam[rows] >= args.lens_radius) & (d_cam[rows] < args.corridor_dcam)
                & (d_seed_k3[rows] > args.seed_far_corridor)
                & ((live_alpha[rows] < args.corridor_max_alpha)
                   | (live_disk[rows] > args.corridor_max_disk)
                   | (live_needle[rows] > args.corridor_max_needle)))
    prune_c2 = idx_after_c1[corridor]
    alive[prune_c2] = False
    pruned['ruleC_corridor'] = int(len(prune_c2))
    print('Rule C:', json.dumps({k: pruned[k] for k in ('ruleC_far_floater', 'ruleC_corridor')}))

    # ================= Rule D =================
    idx = np.flatnonzero(alive)
    rows2 = np.searchsorted(idx, idx_after_c1)  # positions of post-C1 survivors in post-C2 set
    target = (((d_seed_k3[rows2] > args.disk_off_seed) | (alpha[rows2] < args.disk_max_alpha))
              & (disk_ratio[rows2] > args.disk_ratio) & (s3[rows2] > args.disk_min_s3))
    d_prune = target & (d_cam[rows2] < args.disk_prune_dcam) & (alpha[rows2] < args.disk_prune_alpha)
    prune_d = idx[rows2[d_prune]]
    alive[prune_d] = False
    pruned['ruleD_nearfield_wafer'] = int(len(prune_d))
    d_clamp_rows = rows2[target & ~d_prune]     # positions into post-C2 (pre-D-prune) set
    print('Rule D:', json.dumps({'ruleD_nearfield_wafer': pruned['ruleD_nearfield_wafer'],
                                 'ruleD_thickness_clamped': int(len(d_clamp_rows))}))
    print(f'  final splats: {int(alive.sum()):,}')

    # ================= write output =================
    sub = table[alive]
    kept_scales = scales[alive]
    world = kept_scales.copy()

    # cigar shrink (stage 1), on kept rows
    kept_needle = needle_ratio[alive]
    cigar = (kept_needle > args.cigar_ratio) & (kept_needle <= args.needle_ratio)
    world[cigar, 2] = args.cigar_ratio * world[cigar, 1]

    # rule D thickness clamps on the kept rows that carry them
    clamp_global = idx_after_c1[d_clamp_rows]
    clamp_kept = np.isin(np.flatnonzero(alive), clamp_global) if len(clamp_global) \
        else np.zeros(len(sub), dtype=bool)
    s2_k = world[:, 1]
    before_s1 = world[:, 0].copy()
    before_s3 = world[:, 2].copy()
    world[clamp_kept, 0] = np.maximum(world[clamp_kept, 0], s2_k[clamp_kept] / args.disk_thickness)
    world[clamp_kept, 2] = np.minimum(world[clamp_kept, 2], args.disk_max_needle * s2_k[clamp_kept])
    s1_raised = int((world[:, 0] > before_s1 + 1e-12).sum())
    s3_lowered = int((world[:, 2] < before_s3 - 1e-12).sum())

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
    report = {
        'input': str(src), 'input_splats': int(count),
        'output': str(dst), 'output_splats': int(sub.size),
        'output_bytes': dst.stat().st_size,
        'seed': {'file': str(args.seed_from), 'points': int(seed_count), 'k': args.seed_k},
        'pruned': pruned, 'pruned_fraction': float(1 - sub.size / count),
        'modified': {'cigars_shrunk_2.2x': int(cigar.sum()),
                     'ruleD_s1_raised_to_s2_over_5': s1_raised,
                     'ruleD_s3_clamped_to_1.8x_s2': s3_lowered,
                     'axis_floored_numeric': int(floored.sum())},
        'after': {'alpha_lt_0.10': float(np.mean(kept_alpha < 0.10)),
                  'alpha_0.02_to_0.10': float(np.mean((kept_alpha >= 0.02) & (kept_alpha < 0.10))),
                  'alpha_median': float(np.median(kept_alpha)),
                  'needle_ratio_p99': float(np.percentile(kept_needle, 99)),
                  'needle_ratio_max': float(kept_needle.max())},
        'distance_percentiles': {'d_seed_k3_p50': float(np.percentile(d_seed_k3, 50)),
                                 'd_seed_k3_p90': float(np.percentile(d_seed_k3, 90)),
                                 'd_seed_k3_p99': float(np.percentile(d_seed_k3, 99)),
                                 'd_cam_p50': float(np.percentile(d_cam, 50)),
                                 'd_cam_p90': float(np.percentile(d_cam, 90))},
        'thresholds': {k: getattr(args, k) for k in (
            'margin', 'opacity_min', 'needle_ratio_hard', 'needle_ratio', 'needle_min_axis',
            'needle_min_alpha', 'cigar_ratio', 'axis_floor', 'lens_radius', 'body_radius',
            'body_below', 'body_above', 'body_max_alpha', 'body_needle_ratio', 'cylinder_k',
            'fog_alpha', 'puff_alpha', 'puff_min_s3', 'seed_far', 'seed_far_corridor',
            'floor_max_y', 'far_max_alpha', 'far_max_dcam', 'far_max_disk', 'corridor_dcam',
            'corridor_max_alpha', 'corridor_max_disk', 'corridor_max_needle', 'seed_k',
            'disk_ratio', 'disk_min_s3', 'disk_off_seed', 'disk_max_alpha', 'disk_prune_dcam',
            'disk_prune_alpha', 'disk_thickness', 'disk_max_needle')},
        'box': {'lo': box_lo.tolist(), 'hi': box_hi.tolist()},
        'elapsed_seconds': round(time.time() - t0, 1),
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('pruned', 'modified', 'after',
                                             'distance_percentiles')}, indent=2))
    print(f'wrote {dst} in {report["elapsed_seconds"]}s')


if __name__ == '__main__':
    main()
