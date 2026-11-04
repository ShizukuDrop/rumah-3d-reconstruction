"""Prune true 1D needles from a trained splat PLY without touching flat 2D surfels.

Why the previous cleaner cost quality: `clean_needles_and_floaters.py` measured
aspect = s3 / s1, which is large for every flat surface disk as well (a wall surfel has
s3 = s2 >> s1). It then floored s1 to s3/25 on 556,121 splats - thickening valid thin disks -
and pruned only when s3 > 0.04, which let every short hair needle through.

A 3D Gaussian with sorted axes s1 <= s2 <= s3 is
  * a 2D surface disk when s3/s2 ~ 1 and s2/s1 is large,
  * a 1D hair        when s3/s2 is large.

So this version keys on `needle_ratio = s3 / s2`:

  prune  alpha < 0.02
  prune  outside the seed's p0..p100 box + 0.35 units
  prune  needle_ratio > 6.0                              (any size)
  prune  needle_ratio > 4.0 AND (s3 > 0.004 OR alpha > 0.08)
  shrink 3.0 < needle_ratio <= 4.0: set s3 <- 3.0 * s2   (cigar -> disk, never inflating s1)
  prune  isolated free-space floaters: 8th-neighbour distance > 0.06 AND alpha < 0.50
  floor  s1 >= 1e-5 only, numerically

Nothing else is modified; the PLY is rewritten with a structured dtype so every property
(including the 45 SH coefficients) is copied byte-exactly.
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
DEFAULT_IN = RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/splat.ply'
DEFAULT_OUT = RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/splat-cleaned-v2.ply'
BOX_SOURCE = RUN / 'optimization-v1/appearance-coverage-v2-fixed-reference/seed-clean-2m.ply'

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


def box_of(path, quantiles=(0.0, 100.0)):
    _, _, _, table = load(path)
    xyz = np.column_stack([table['x'], table['y'], table['z']]).astype(np.float64)
    return (np.percentile(xyz, quantiles[0], axis=0), np.percentile(xyz, quantiles[1], axis=0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(DEFAULT_IN))
    ap.add_argument('--output', default=str(DEFAULT_OUT))
    ap.add_argument('--box-from', default=str(BOX_SOURCE))
    ap.add_argument('--margin', type=float, default=0.35)
    ap.add_argument('--opacity-min', type=float, default=0.02)
    ap.add_argument('--needle-ratio-hard', type=float, default=6.0)
    ap.add_argument('--needle-ratio', type=float, default=4.0)
    ap.add_argument('--needle-min-axis', type=float, default=0.004)
    ap.add_argument('--needle-min-alpha', type=float, default=0.08)
    ap.add_argument('--cigar-ratio', type=float, default=3.0)
    ap.add_argument('--isolated-k', type=int, default=8)
    ap.add_argument('--isolated-distance', type=float, default=0.06)
    ap.add_argument('--isolated-max-alpha', type=float, default=0.50)
    ap.add_argument('--axis-floor', type=float, default=1e-5)
    ap.add_argument('--report', default=str(HERE / 'true-1d-clean.json'))
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
    disk_ratio = s2 / np.maximum(s1, 1e-12)

    box_lo, box_hi = box_of(Path(args.box_from))
    inside = np.all((xyz >= box_lo - args.margin) & (xyz <= box_hi + args.margin), axis=1)

    dead = alpha < args.opacity_min
    far = ~inside
    hair_hard = needle_ratio > args.needle_ratio_hard
    hair_soft = (needle_ratio > args.needle_ratio) & ((s3 > args.needle_min_axis) | (alpha > args.needle_min_alpha))
    needle = hair_hard | hair_soft
    keep = ~(dead | far | needle)
    print(f'  dead alpha<{args.opacity_min}: {int(dead.sum()):,}')
    print(f'  outside box + {args.margin}: {int(far.sum()):,}')
    print(f'  needles s3/s2>{args.needle_ratio_hard:g}: {int(hair_hard.sum()):,}')
    print(f'  needles s3/s2>{args.needle_ratio:g} big/opaque: {int(hair_soft.sum()):,}')
    print(f'  kept so far: {int(keep.sum()):,}')

    sub = table[keep]
    kept_xyz = xyz[keep]
    kept_needle = needle_ratio[keep]
    kept_alpha = alpha[keep]
    kept_scales = scales[keep]

    # ---- isolated free-space floaters on the surviving set
    tree = cKDTree(kept_xyz)
    distances, _ = tree.query(kept_xyz, k=args.isolated_k + 1, workers=-1)
    d8 = distances[:, -1]
    isolated = (d8 > args.isolated_distance) & (kept_alpha < args.isolated_max_alpha)
    print(f'  isolated d8>{args.isolated_distance} & alpha<{args.isolated_max_alpha}: {int(isolated.sum()):,}')

    keep2 = ~isolated
    sub = sub[keep2]
    kept_scales = kept_scales[keep2]
    kept_needle = kept_needle[keep2]
    print(f'  final splats: {sub.size:,}')

    # ---- cigar -> disk: shrink s3 to cigar_ratio * s2, never inflate s1
    world = kept_scales.copy()
    cigar = (kept_needle > args.cigar_ratio) & (kept_needle <= args.needle_ratio)
    if cigar.any():
        world[cigar, 2] = args.cigar_ratio * world[cigar, 1]
    floored = world[:, 0] < args.axis_floor
    world[:, 0] = np.maximum(world[:, 0], args.axis_floor)
    # the PLY stores log-scales in scale_0/1/2 without a guaranteed order; recompute the
    # sorted triple back onto the original slots so quaternions stay meaningful
    original = np.column_stack([sub['scale_0'], sub['scale_1'], sub['scale_2']]).astype(np.float64)
    order = np.argsort(original, axis=1)
    log_new = np.empty_like(original)
    log_new[np.arange(world.shape[0])[:, None], order] = np.log(world)
    for index, column in enumerate(('scale_0', 'scale_1', 'scale_2')):
        sub[column] = log_new[:, index].astype(sub[column].dtype)

    write(dst, header, sub)

    report = {
        'input': str(src), 'input_splats': int(count), 'input_bytes': src.stat().st_size,
        'output': str(dst), 'output_splats': int(sub.size), 'output_bytes': dst.stat().st_size,
        'pruned': {'dead': int(dead.sum()), 'out_of_box': int(far.sum()),
                   'needle_hard': int(hair_hard.sum()), 'needle_soft': int(hair_soft.sum()),
                   'isolated': int(isolated.sum()),
                   'total': int(count - sub.size),
                   'total_fraction': float(1 - sub.size / count)},
        'modified': {'cigars_shrunk': int(cigar.sum()), 'axis_floored_numeric': int(floored.sum())},
        'thresholds': {'margin': args.margin, 'needle_ratio_hard': args.needle_ratio_hard,
                       'needle_ratio': args.needle_ratio, 'needle_min_axis': args.needle_min_axis,
                       'needle_min_alpha': args.needle_min_alpha, 'cigar_ratio': args.cigar_ratio,
                       'isolated_k': args.isolated_k, 'isolated_distance': args.isolated_distance,
                       'isolated_max_alpha': args.isolated_max_alpha, 'axis_floor': args.axis_floor},
        'box': {'lo': box_lo.tolist(), 'hi': box_hi.tolist(), 'source': str(args.box_from)},
        'before': {'needle_ratio_p50': float(np.median(needle_ratio)),
                   'needle_ratio_p90': float(np.percentile(needle_ratio, 90)),
                   'needle_ratio_p99': float(np.percentile(needle_ratio, 99)),
                   'needle_ratio_max': float(needle_ratio.max()),
                   'share_gt_4': float(np.mean(needle_ratio > 4)),
                   'share_gt_6': float(np.mean(needle_ratio > 6)),
                   'disk_ratio_p50': float(np.median(disk_ratio)),
                   'alpha_lt_0.1': float(np.mean(alpha < 0.1))},
        'after': {'needle_ratio_p50': float(np.median(kept_needle)),
                  'needle_ratio_p99': float(np.percentile(kept_needle, 99)),
                  'needle_ratio_max': float(kept_needle.max()),
                  'share_gt_4': float(np.mean(kept_needle > 4)),
                  'alpha_lt_0.1': float(np.mean(kept_alpha < 0.1))},
        'elapsed_seconds': round(time.time() - t0, 1),
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('pruned', 'modified', 'before', 'after')}, indent=2))
    print(f'wrote {dst} in {report["elapsed_seconds"]}s')


if __name__ == '__main__':
    main()
