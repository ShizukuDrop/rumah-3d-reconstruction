"""Run three 1-step `--init-ply` eval passes that dump rendered held-out views.

Why: spirula's internal eval scores the whole 1200x1200 frame, which includes the black
fisheye padding and the operator's masked-out pixels. That is what dragged V2 and V3 down to
~12.3 dB. Here each model is re-rendered with `--save-eval-images 1` so the PNGs can be scored
again strictly inside the white keep-masks.

One Adam step from the trained PLY, no densification (refine starts at 500), identical eval
split for all three models.
"""
import json
import subprocess
import sys
from pathlib import Path

import os

REPO = Path(__file__).resolve().parents[2]
RUN = Path(os.environ.get('STICK_RUN_ROOT') or REPO / '.local' / 'osmo-stick-20261103')
WORKSPACE = REPO
EXE = WORKSPACE / 'work/osmo-clean-20261031/runtime/spirula-2026.10.30/spirula.exe'
DATA = RUN / 'optimization-v1/appearance-coverage-v2-fixed-reference'
OUT = RUN / 'optimization-v1/eval-masked'

MODELS = {
    'v2': RUN / 'optimization-v1/appearance-training-v2/selected/step-000006000.ckpt/splat.ply',
    'v3raw': RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/splat.ply',
    'v3cleaned': RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/splat-cleaned.ply',
    'v3clean2': RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/splat-cleaned-v2.ply',
    'v3clean3': RUN / 'optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/splat-cleaned-v2-noiso.ply',
}

BASE = [
    'train', '3dgs',
    '--data', str(DATA),
    '--num-iterations', '1',
    '--quality', 'high',
    '--primitive', 'mip',
    '--sh-degree', '2',
    '--eval-mode', 'filename',
    '--validation-fraction', '0',
    '--save-eval-images', '1',
    '--eval-lpips', '0',
    '--load-masks', '1',
    '--apply-loss-for-mask', '0',
    '--mask-boundary-offset', '-0.002',
    '--cache-images', 'disk',
    '--max-train-batch-size', '2',
    '--max-batch-per-epoch', '6695',
    '--split-batch', '1',
    '--scene-center', 'none',
    '--orientation-method', 'none',
    '--center-method', 'none',
    '--auto-scale-poses', '0',
    '--train-frame', 'points',
    '--disable-viewer', '1',
    '--keep-viewer-alive', '0',
    '--device', '0',
    '--use-ppisp', '1',
    '--use-bilateral-grid', '1',
    '--use-bilateral-grid-for-geometry', '0',
    '--floater-suppression', 'strong',
    '--distraction-robustness', 'mild',
    '--steps-per-save', '6000',
]


def main():
    only = sys.argv[1:] or None
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for label, model in MODELS.items():
        if only and label not in only:
            continue
        if not model.exists():
            print(f'{label}: missing {model}')
            summary[label] = {'missing': str(model)}
            continue
        target = OUT / label
        target.mkdir(parents=True, exist_ok=True)
        command = [str(EXE)] + BASE + [
            '--output-dir-prefix', str(target),
            '--output-dir-name', 'selected',
            '--init-ply', str(model),
            '--cap-max', '3600000',
        ]
        log = target / 'eval.log'
        print(f'--- {label} ---', flush=True)
        with log.open('w', encoding='utf-8') as handle:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, encoding='utf-8', errors='replace')
            for line in proc.stdout:
                handle.write(line)
                if 'psnr' in line or 'Eval' in line or 'error' in line:
                    print('   ' + line.rstrip(), flush=True)
            code = proc.wait()
        metrics = target / 'selected' / 'metrics.json'
        summary[label] = {'exit_code': code, 'model': str(model), 'model_bytes': model.stat().st_size,
                          'metrics': json.loads(metrics.read_text()) if metrics.exists() else None}
        (target / 'command.json').write_text(json.dumps({'command': command, 'exit_code': code}, indent=2) + '\n',
                                             encoding='utf-8')
        print(f'{label}: exit={code}', flush=True)
    (OUT / 'runs.json').write_text(json.dumps(summary, indent=2)[:8000] + '\n', encoding='utf-8')
    print(json.dumps({k: (v.get('metrics') or {}).get('avg_psnr') if isinstance(v.get('metrics'), dict) else None
                      for k, v in summary.items()}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
