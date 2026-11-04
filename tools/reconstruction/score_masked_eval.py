"""Score the saved held-out renders strictly inside the operator keep-masks.

splat's own eval scores every pixel of the 1200x1200 frame. Two things inflate that error and
have nothing to do with model quality:

  * the reference keeps the black fisheye padding (42.8% of pixels in a sampled frame),
    while the renderer fills that area with room content, and
  * the operator's masks hide ~46% of the frame on purpose (median keep fraction 0.54).

`--save-eval-images 1` writes `eval-gt-NNNNN.png` / `eval-render-NNNNN.png` pairs, but the
index is not the sorted filename order, so this script first recovers the mapping by matching
16x16 thumbnails, then scores only `mask > 127` pixels.

PSNR/SSIM follow the convention already used elsewhere in this project: SSIM on RGB with an
11x11 Gaussian (sigma 1.5, range 255), restricted to window centres inside the keep-mask.
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

cv2.setNumThreads(1)
import os

REPO = Path(__file__).resolve().parents[2]
RUN = Path(os.environ.get('STICK_RUN_ROOT') or REPO / '.local' / 'osmo-stick-20261103')
HERE = RUN / 'forensic-20261104'
IMAGES = RUN / 'dense-pinhole-1200' / 'images'
MASKS = RUN / 'dense-pinhole-1200' / 'masks'
EVAL_ROOT = RUN / 'optimization-v1' / 'eval-masked'
OUT = HERE / 'masked-eval-scores.json'


def thumb(path, size=16):
    with Image.open(path) as im:
        small = im.convert('RGB').resize((size, size), Image.Resampling.BILINEAR)
        arr = np.asarray(small, dtype=np.float32).reshape(-1)
    arr -= arr.mean()
    norm = np.linalg.norm(arr)
    return arr / (norm if norm else 1.0)


def ssim_rgb(a, b, mask):
    a64, b64 = a.astype(np.float64), b.astype(np.float64)
    blur = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5, borderType=cv2.BORDER_REFLECT_101)
    ma, mb = blur(a64), blur(b64)
    va = np.maximum(blur(a64 * a64) - ma * ma, 0)
    vb = np.maximum(blur(b64 * b64) - mb * mb, 0)
    cov = blur(a64 * b64) - ma * mb
    ssim = ((2 * ma * mb + 6.5025) * (2 * cov + 58.5225)) / \
           ((ma * ma + mb * mb + 6.5025) * (va + vb + 58.5225))
    centers = cv2.erode(mask.astype(np.uint8), np.ones((11, 11), np.uint8),
                        borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    return float(ssim[centers].mean()) if centers.any() else None, int(centers.sum())


def score_pair(render_path, mask_path):
    render = np.array(Image.open(render_path).convert('RGB'))
    mask = np.array(Image.open(mask_path))
    keep = mask > 127
    if keep.shape != render.shape[:2]:
        raise ValueError(f'mask/geometry mismatch {keep.shape} vs {render.shape}')
    return keep, render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', nargs='+', default=['v2', 'v3raw', 'v3cleaned'])
    ap.add_argument('--limit', type=int, default=0, help='score only the first N views (0 = all)')
    args = ap.parse_args()

    names = sorted(p.name for p in IMAGES.glob('*_eval.jpg'))
    print(f'eval images: {len(names)}')

    # --- recover the index -> filename mapping SEPARATELY for each model: the eval order is
    # not guaranteed to be identical between runs, and reusing one run's order silently scores
    # the wrong reference image (which is exactly what a first attempt did).
    ds_thumbs = np.stack([thumb(IMAGES / n) for n in names])
    mappings = {}
    for model in args.models:
        gts = sorted((EVAL_ROOT / model / 'selected').glob('eval-gt-*.png'))
        if len(gts) != len(names):
            print(f'{model}: gt images {len(gts)} != eval images {len(names)}')
            continue
        gt_thumbs = np.stack([thumb(p) for p in gts])
        similarity = gt_thumbs @ ds_thumbs.T
        order = similarity.argmax(axis=1)
        best = similarity[np.arange(len(gts)), order]
        second = np.partition(similarity, -2, axis=1)[:, -2]
        if len(set(order.tolist())) != len(order):
            raise SystemExit(f'{model}: thumbnail matching is not one-to-one; refusing to score')
        mappings[model] = {int(i): names[int(j)] for i, j in enumerate(order)}
        print(f'{model}: mapping ok, margin mean {float(np.mean(best - second)):.4f} '
              f'min {float(np.min(best - second)):.4f}')

    count = len(names) if not args.limit else min(args.limit, len(names))
    report = {'eval_views': len(names), 'scored_views': count, 'models': {}}

    for model in args.models:
        sel = EVAL_ROOT / model / 'selected'
        renders = sorted(sel.glob('eval-render-*.png'))
        if not renders:
            print(f'{model}: no renders yet')
            report['models'][model] = {'missing': str(sel)}
            continue
        rows = []
        mapping = mappings.get(model)
        if mapping is None:
            print(f'{model}: no mapping')
            continue
        for index in range(min(count, len(renders))):
            name = mapping[index]
            render_path = sel / f'eval-render-{index:05d}.png'
            mask_path = MASKS / (Path(name).stem + '.png')
            keep, render = score_pair(render_path, mask_path)
            ref = np.array(Image.open(IMAGES / name).convert('RGB'))
            if ref.shape != render.shape:
                ref = np.array(Image.open(IMAGES / name).convert('RGB').resize(
                    (render.shape[1], render.shape[0]), Image.Resampling.BILINEAR))
            diff = render.astype(np.float64) - ref.astype(np.float64)
            mse_masked = float((diff[keep] ** 2).mean())
            mse_all = float((diff ** 2).mean())
            ssim_m, centers = ssim_rgb(render, ref, keep)
            rows.append({
                'index': index, 'image': name, 'mask_keep_fraction': float(keep.mean()),
                'masked': {
                    'psnr_db': float(10 * math.log10(255 ** 2 / mse_masked)) if mse_masked else None,
                    'mae_8bit': float(np.abs(diff[keep]).mean()),
                    'ssim_rgb': ssim_m, 'ssim_centers': centers,
                },
                'unmasked': {
                    'psnr_db': float(10 * math.log10(255 ** 2 / mse_all)) if mse_all else None,
                    'mae_8bit': float(np.abs(diff).mean()),
                },
            })
        def mean(key, field):
            values = [r[key][field] for r in rows if r[key][field] is not None]
            return float(np.mean(values)) if values else None
        summary = {
            'views': len(rows),
            'masked_psnr_db': mean('masked', 'psnr_db'),
            'masked_ssim_rgb': mean('masked', 'ssim_rgb'),
            'masked_mae_8bit': mean('masked', 'mae_8bit'),
            'masked_psnr_p10': float(np.percentile([r['masked']['psnr_db'] for r in rows], 10)),
            'masked_psnr_median': float(np.median([r['masked']['psnr_db'] for r in rows])),
            'unmasked_psnr_db': mean('unmasked', 'psnr_db'),
            'unmasked_mae_8bit': mean('unmasked', 'mae_8bit'),
            'mean_mask_keep_fraction': float(np.mean([r['mask_keep_fraction'] for r in rows])),
            'rows': rows,
        }
        report['models'][model] = summary
        print(f"{model}: masked PSNR {summary['masked_psnr_db']:.3f} dB  "
              f"SSIM {summary['masked_ssim_rgb']:.4f}  (unmasked "
              f"{summary['unmasked_psnr_db']:.3f} dB)  n={summary['views']}")

    OUT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
