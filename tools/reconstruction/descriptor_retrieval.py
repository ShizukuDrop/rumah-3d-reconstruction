"""Bounded same-lens revisit proposals from mean-pooled cached ALIKED descriptors.

This is an appearance heuristic, not a learned global descriptor or overlap
certificate. It never reads prior poses or matches. Native geometric verification
must reject false candidates; pair_graph applies the final per-image budget.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .stage_anchor_dataset import _feature_header


def retrieve(staging: dict, selection: dict, *, temporal_exclusion: float = 1.5,
             proposals_per_image: int = 8) -> dict:
    if not np.isfinite(temporal_exclusion) or temporal_exclusion < 0 or proposals_per_image < 1:
        raise ValueError('Invalid retrieval exclusion or proposal budget')
    started = time.perf_counter()
    times = {row['id']: row['time_seconds'] for row in selection['frames']}
    records = sorted(staging['images'], key=lambda row: row['name'])
    descriptors, provenance = [], []
    for row in records:
        path = Path(row['feature']['destination'])
        header = _feature_header(path)
        if not header['featureCount']:
            raise ValueError(f'No descriptors to pool: {row["name"]}')
        before = path.stat()
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if digest != row['feature']['sha256']:
            raise ValueError('Staged feature identity changed before retrieval')
        matrix = np.memmap(path, dtype='<f4', mode='r',
                           offset=28 + header['featureCount'] * 16,
                           shape=(header['featureCount'], header['descriptorDimension']))
        vector = np.asarray(matrix.mean(axis=0, dtype=np.float64))
        del matrix
        if not np.isfinite(vector).all() or np.linalg.norm(vector) <= 1e-12:
            raise ValueError(f'Invalid pooled descriptor: {row["name"]}')
        vector = (vector / np.linalg.norm(vector)).astype(np.float32)
        if (before.st_size, before.st_mtime_ns) != (path.stat().st_size, path.stat().st_mtime_ns):
            raise ValueError('Feature changed while retrieving')
        descriptors.append(vector)
        provenance.append({'image': row['name'], 'featureSha256': digest,
                           'featureCount': header['featureCount'], 'lens': row['lens']})
    candidates = {}
    scored = 0
    for lens in sorted({row['lens'] for row in records}):
        indices = [i for i, row in enumerate(records) if row['lens'] == lens]
        vectors = np.stack([descriptors[i] for i in indices])
        scores = vectors @ vectors.T
        scored += len(indices) * (len(indices) - 1) // 2
        for local, index in enumerate(indices):
            eligible = [other for other, other_index in enumerate(indices)
                        if other != local and
                        abs(times[records[index]['frameId']] - times[records[other_index]['frameId']]) >= temporal_exclusion]
            ranked = sorted(eligible, key=lambda other: (-float(scores[local, other]), records[indices[other]]['name']))
            for other in ranked[:proposals_per_image]:
                first, second = sorted((records[index]['name'], records[indices[other]]['name']))
                candidates[(first, second)] = {'image1': first, 'image2': second,
                                               'score': float(scores[local, other]),
                                               'kind': 'mean-pooled-aliked-revisit'}
    rows = sorted(candidates.values(), key=lambda row: (-row['score'], row['image1'], row['image2']))
    return {'schemaVersion': 1, 'method': 'L2-normalized mean of original masked ALIKED local descriptors; cosine similarity',
            'overlapCertified': False, 'baselineGeometryUsed': False, 'baselineMatchesUsed': False,
            'sameLensOnly': True, 'temporalExclusionSeconds': temporal_exclusion,
            'proposalsPerImageBeforeGraphBudget': proposals_per_image,
            'scoredUniqueSameLensPairs': scored, 'featureProvenance': provenance,
            'candidates': rows, 'seconds': time.perf_counter() - started,
            'timingKind': 'CPU descriptor pooling/retrieval with identity hashing; not fresh feature matching'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = retrieve(json.loads(args.staging.read_text()), json.loads(args.selection.read_text()))
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({'proposedPairs': len(result['candidates']), 'seconds': result['seconds']}))


if __name__ == '__main__':
    main()
