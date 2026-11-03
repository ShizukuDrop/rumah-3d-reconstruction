"""Strictly merge disjoint native VKMT v4 verified caches without renumbering.

Both the complete image table and the complete calibration tail must match
byte for byte. Every source cache and every associated feature file is hashed.
Duplicate pair keys, raw/degenerate pairs, changed features, unknown formats,
or calibration differences stop publication. There is no metadata override.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import time

from .match_cache import CacheIndex, _fingerprint, _read, read_index


def camera_metadata(index: CacheIndex) -> dict:
    """Expose differences for diagnosis, never normalize them for a merge."""
    with index.path.open('rb') as handle:
        handle.seek(index.camera_offset)
        count = struct.unpack('<I', _read(handle, 4))[0]
        cameras = []
        for _ in range(count):
            identity, width, height, model, prior, scale, parameters = struct.unpack('<IIIiBdI', _read(handle, 29))
            values = struct.unpack('<' + 'd' * parameters, _read(handle, parameters * 8))
            cameras.append({'id': identity, 'width': width, 'height': height, 'model': model,
                            'focalPrior': prior, 'coordinateScale': scale, 'parameters': list(values)})
        identities, measured = [], []
        if count:
            images = struct.unpack('<I', _read(handle, 4))[0]
            identities = list(struct.unpack('<' + 'I' * images, _read(handle, images * 4)))
            measured = list(_read(handle, count))
    return {'cameras': cameras, 'imageCameraIds': identities, 'focalMeasured': measured}


def _same_bytes(left: CacheIndex, right: CacheIndex, left_offset: int,
                right_offset: int, count: int) -> bool:
    with left.path.open('rb') as first, right.path.open('rb') as second:
        first.seek(left_offset)
        second.seek(right_offset)
        while count:
            size = min(count, 1 << 20)
            if _read(first, size) != _read(second, size):
                return False
            count -= size
    return True


def _feature_table(index: CacheIndex, manifest: dict) -> tuple[str, list[tuple[Path, tuple]]]:
    if set(manifest) != {image.name for image in index.images}:
        raise ValueError('Feature manifest must identify every exact native image name once')
    identities, fingerprints = [], []
    for image in index.images:
        item = manifest[image.name]
        expected = item['sha256'].lower()
        if not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('A feature SHA-256 is required')
        path = Path(item['path']).resolve(strict=True)
        before = _fingerprint(path.stat())
        with path.open('rb') as handle:
            magic, version, width, height, count, dimension, dtype = struct.unpack('<4s6I', _read(handle, 28))
            if magic != b'VKFT' or version != 6 or dtype != 1 or not width or not height or not dimension:
                raise ValueError('Expected unchanged float32 VKFT v6 features')
            if count != image.num_features or path.stat().st_size < 28 + count * (16 + dimension * 4):
                raise ValueError('Feature row count/size disagrees with the native image table')
            handle.seek(0)
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
        if actual != expected or _fingerprint(path.stat()) != before:
            raise ValueError('Feature identity changed or SHA-256 mismatched')
        identities.append([image.name, count, actual])
        fingerprints.append((path, before))
    canonical = json.dumps(identities, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest(), fingerprints


def merge_verified_matches(sources: list[Path], output: Path, *,
                           expected_source_sha256: list[str],
                           feature_manifests: list[dict]) -> dict:
    """Copy verified records verbatim after strict identity compatibility checks.

    Feature manifests are native-name -> {path, sha256}, one per source. Input
    cache order and each record's oriented feature columns are retained. This
    function performs no feature extraction, matching, or geometric estimation.
    """
    started = time.perf_counter()
    if len(sources) < 2 or len(expected_source_sha256) != len(sources) or len(feature_manifests) != len(sources):
        raise ValueError('At least two sources, their SHA-256 values, and feature manifests are required')
    if any(not re.fullmatch('[a-fA-F0-9]{64}', value) for value in expected_source_sha256):
        raise ValueError('Exact source SHA-256 values are required')
    indices = [read_index(path) for path in sources]
    if len({index.path for index in indices}) != len(indices):
        raise ValueError('Duplicate source cache')
    output = Path(output).resolve()
    if output.exists() or output in {index.path for index in indices}:
        raise FileExistsError(output)
    first = indices[0]
    if not first.camera_ids:
        raise ValueError('Calibrated camera metadata is required')
    all_pairs = set()
    for index in indices:
        if index.images != first.images or index.pair_count_offset != first.pair_count_offset or not _same_bytes(first, index, 0, 0, first.pair_count_offset):
            raise ValueError('Image identity table bytes differ; renumbering is forbidden')
        if index.size - index.camera_offset != first.size - first.camera_offset or not _same_bytes(first, index, first.camera_offset, index.camera_offset, first.size - first.camera_offset):
            raise ValueError('Camera calibration tail bytes differ (including focal-measured flags); inspect camera_metadata; no override is permitted')
        if not index.pairs:
            raise ValueError('No verified delta pairs to merge')
        for pair in index.pairs:
            if pair.config not in {2, 3} or pair.count <= 0:
                raise ValueError('Only native verified nondegenerate pair records may be merged')
            if pair.key in all_pairs:
                raise ValueError('Duplicate pair key across source caches')
            all_pairs.add(pair.key)
    feature_hashes, feature_fingerprints = [], []
    for index, manifest in zip(indices, feature_manifests):
        table_hash, fingerprints = _feature_table(index, manifest)
        feature_hashes.append(table_hash)
        feature_fingerprints.extend(fingerprints)
    if len(set(feature_hashes)) != 1:
        raise ValueError('Feature SHA tables differ even though names/counts match')
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=output.name + '.', suffix='.partial', dir=output.parent)
    temporary = Path(temporary_name)
    output_digest, source_hashes = hashlib.sha256(), []
    copied_matches = 0
    try:
        with os.fdopen(descriptor, 'wb') as destination:
            def emit(data: bytes) -> None:
                destination.write(data)
                output_digest.update(data)

            for number, (index, expected) in enumerate(zip(indices, expected_source_sha256)):
                digest = hashlib.sha256()
                with index.path.open('rb') as original:
                    if _fingerprint(os.fstat(original.fileno())) != index.fingerprint:
                        raise ValueError('Source cache changed before copy')

                    def consume(count: int, copy: bool, pair=None) -> None:
                        while count:
                            chunk = _read(original, min(count, 1 << 20))
                            digest.update(chunk)
                            if pair is not None:
                                for a, b in struct.iter_unpack('<II', chunk):
                                    if a >= index.images[pair.image1].num_features or b >= index.images[pair.image2].num_features:
                                        raise ValueError('Correspondence indexes a missing original feature')
                            if copy:
                                emit(chunk)
                            count -= len(chunk)

                    consume(index.pair_count_offset, number == 0)
                    consume(4, False)
                    if number == 0:
                        emit(struct.pack('<I', len(all_pairs)))
                    for pair in index.pairs:
                        consume(16, True)
                        consume(pair.count * 8, True, pair)
                        copied_matches += pair.count
                    consume(index.size - index.camera_offset, number == len(indices) - 1)
                    if original.read(1) or _fingerprint(os.fstat(original.fileno())) != index.fingerprint:
                        raise ValueError('Source cache changed during copy')
                if digest.hexdigest() != expected.lower():
                    raise ValueError('Source cache SHA-256 mismatch')
                source_hashes.append(digest.hexdigest())
            for path, fingerprint in feature_fingerprints:
                if _fingerprint(path.stat()) != fingerprint:
                    raise ValueError('Feature file changed while merging caches')
            destination.flush()
            os.fsync(destination.fileno())
        merged = read_index(temporary)
        if merged.images != first.images or len(merged.pairs) != len(all_pairs):
            raise ValueError('Merged cache validation failed')
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {'sources': [{'path': str(index.path), 'sha256': digest, 'pairs': len(index.pairs)}
                        for index, digest in zip(indices, source_hashes)],
            'output': str(output), 'outputSha256': output_digest.hexdigest(),
            'outputBytes': output.stat().st_size, 'images': len(first.images),
            'verifiedPairs': len(all_pairs), 'copiedMatches': copied_matches,
            'featureTableSha256': feature_hashes[0], 'featureFilesHashed': len(feature_fingerprints),
            'imageTableBytesIdentical': True, 'calibrationTailBytesIdentical': True,
            'featureIndicesPreserved': True, 'pairOrientationPreserved': True,
            'duplicatePairsRejected': True, 'semanticOverridesApplied': False,
            'freshMatchingPerformed': False, 'timingKind': 'strict-cache-merge-not-new-matching',
            'seconds': time.perf_counter() - started}
