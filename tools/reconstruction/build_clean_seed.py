"""Build a spatially uniform 2.0 M seed point cloud from the 3.5 M sparse seed.

turn-3 mandate step 2. V2 handed 3,507,037 points to a 1,700,000 cap, so the
loader truncated 51.5% of the seed at random and `num_added` stayed 0 for the
whole run (STICK_INVESTIGATION_REPORT.md sec. 1.4). Here we

  1. drop tracks whose point lies outside the p0.5..p99.5 room box (per axis),
  2. voxel-downsample one representative per occupied voxel, binary-searching the
     voxel edge so the survivor count lands at ~2,000,000.

Voxelisation is deterministic (integer floor of (p - min) / edge) and keeps the
first point of each voxel, so coverage is uniform instead of random.

Output keeps the input schema: x y z nx ny nz red green blue (binary_little_endian).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

import os

REPO = Path(__file__).resolve().parents[2]
RUN = Path(os.environ.get('STICK_RUN_ROOT') or REPO / '.local' / 'osmo-stick-20261103')
HERE = RUN / 'forensic-20261104'
DEFAULT_SRC = RUN / 'dense-pinhole-1200' / 'seed-sparse-train.ply'
DEFAULT_DST = RUN / 'optimization-v1' / 'appearance-coverage-v2-fixed-reference' / 'seed-clean-2m.ply'

NAMES = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'red', 'green', 'blue']
FLOAT_PROPS = set(NAMES[:6])
UCHAR_PROPS = set(NAMES[6:])


def read_ply(path):
    with path.open('rb') as fh:
        head = b''
        while b'end_header' not in head:
            chunk = fh.read(4096)
            if not chunk:
                raise ValueError('truncated header')
            head += chunk
        end = head.index(b'end_header') + len(b'end_header')
        end += 1 if head[end:end + 1] == b'\n' else 2
        header = head[:end].decode('ascii')
        props = [ln.split() for ln in header.splitlines() if ln.startswith('property')]
        count = int([ln for ln in header.splitlines() if ln.startswith('element vertex')][0].split()[2])
        names = [p[2] for p in props]
        floats = [p[2] for p in props if p[1] == 'float']
        uchars = [p[2] for p in props if p[1] == 'uchar']
        if set(names) != set(NAMES) or len(names) != len(NAMES):
            raise ValueError(f'unexpected ply schema: {names}')
        fh.seek(end)
        # interleaved: 6 float32 then 3 uint8 per vertex
        stride = len(floats) * 4 + len(uchars)
        raw = np.fromfile(fh, dtype=np.uint8, count=count * stride).reshape(count, stride)
    fpart = raw[:, :len(floats) * 4].copy().view(np.float32).reshape(count, len(floats))
    upart = raw[:, len(floats) * 4:]
    table = {name: fpart[:, i] for i, name in enumerate(floats)}
    for i, name in enumerate(uchars):
        table[name] = upart[:, i]
    return table, count, floats, uchars


def write_ply(path, table, floats, uchars, comment):
    count = table['x'].shape[0]
    lines = ['ply', 'format binary_little_endian 1.0', f'comment {comment}', f'element vertex {count}']
    lines += [f'property float {n}' for n in floats]
    lines += [f'property uchar {n}' for n in uchars]
    lines += ['end_header']
    header = ('\n'.join(lines) + '\n').encode('ascii')
    stride = len(floats) * 4 + len(uchars)
    blob = np.empty((count, stride), dtype=np.uint8)
    fpart = np.empty((count, len(floats)), dtype=np.float32)
    for i, name in enumerate(floats):
        fpart[:, i] = table[name]
    blob[:, :len(floats) * 4] = fpart.view(np.uint8).reshape(count, len(floats) * 4)
    for i, name in enumerate(uchars):
        blob[:, len(floats) * 4 + i] = table[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as fh:
        fh.write(header)
        fh.write(blob.tobytes())


def voxel_keep(points, mins, edge):
    keys = np.floor((points - mins) / edge).astype(np.int64)
    keys -= keys.min(axis=0)
    span = keys.max(axis=0) + 1
    if span[0] * span[1] * span[2] < 2 ** 62:
        flat = (keys[:, 0] * span[1] + keys[:, 1]) * span[2] + keys[:, 2]
        _, first = np.unique(flat, return_index=True)
    else:  # fall back to a structured view for very large grids
        view = np.ascontiguousarray(keys).view([('a', np.int64), ('b', np.int64), ('c', np.int64)]).ravel()
        _, first = np.unique(view, return_index=True)
    return np.sort(first)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default=str(DEFAULT_SRC))
    ap.add_argument('--output', default=str(DEFAULT_DST))
    ap.add_argument('--target', type=int, default=2_000_000)
    ap.add_argument('--keep-lo', type=float, default=0.5)
    ap.add_argument('--keep-hi', type=float, default=99.5)
    args = ap.parse_args()

    src, dst = Path(args.source), Path(args.output)
    t0 = time.time()
    table, count, floats, uchars = read_ply(src)
    xyz = np.column_stack([table['x'], table['y'], table['z']]).astype(np.float64)
    print(f'read {count:,} points from {src.name} in {time.time() - t0:.1f}s')

    lo = np.percentile(xyz, args.keep_lo, axis=0)
    hi = np.percentile(xyz, args.keep_hi, axis=0)
    inside = np.all((xyz >= lo) & (xyz <= hi), axis=1)
    print('p0.5 box: ' + ' '.join(f'{v:+.4f}' for v in lo))
    print('p99.5 box: ' + ' '.join(f'{v:+.4f}' for v in hi))
    print(f'outside box: {count - inside.sum():,} ({(count - inside.sum()) / count:.2%})')

    sub = {k: v[inside] for k, v in table.items()}
    p = xyz[inside]
    mins = p.min(axis=0)
    extent = p.max(axis=0) - mins
    print('filtered extent: ' + ' '.join(f'{v:.4f}' for v in extent))

    target = args.target
    edge = float(max(extent)) / 200.0
    best = None
    for it in range(24):
        keep = voxel_keep(p, mins, edge)
        n = int(keep.size)
        if best is None or abs(n - target) < abs(best['n'] - target):
            best = {'edge': edge, 'n': n, 'keep': keep}
        print(f'  iter {it}: edge {edge:.6f} -> {n:,} voxels')
        if abs(n - target) <= 0.002 * target:
            break
        # occupied-voxel count scales roughly as edge^-3; damp the step so the
        # representative set cannot oscillate between two lattice alignments.
        step = (n / target) ** (1.0 / 3.0)
        step = 1.0 + 0.8 * (step - 1.0)
        edge = best['edge'] * step

    keep = best['keep']
    out = {k: v[keep] for k, v in sub.items()}
    comment = (f'turn-3 uniform seed: p{args.keep_lo}-p{args.keep_hi} box filter + one point per '
               f'{best["edge"]:.6f}-unit voxel; source {src.name} {count} pts')
    write_ply(dst, out, floats, uchars, comment)

    report = {
        'source': str(src),
        'source_points': int(count),
        'output': str(dst),
        'output_points': int(keep.size),
        'target_points': target,
        'voxel_edge': float(best['edge']),
        'keep_percentile_lo': args.keep_lo,
        'keep_percentile_hi': args.keep_hi,
        'box_min': [float(v) for v in lo],
        'box_max': [float(v) for v in hi],
        'dropped_outside_box': int(count - inside.sum()),
        'dropped_outside_fraction': float((count - inside.sum()) / count),
        'candidate_extent': [float(v) for v in extent],
        'output_extent': [float(v) for v in (p[keep].max(axis=0) - p[keep].min(axis=0))],
        'elapsed_seconds': round(time.time() - t0, 2),
    }
    prov = Path(str(dst) + '.build.json')
    prov.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
