"""Inspect and subset Spirula VKMT v4 matches without changing feature indices.

Indexing seeks over correspondence payloads. Subsetting streams the source once
to compute its SHA-256 and copies selected records verbatim. This is cache reuse,
so its runtime must never be reported as fresh feature matching performance.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import time
from typing import BinaryIO, Iterable


@dataclass(frozen=True)
class ImageEntry:
    name: str
    num_features: int


@dataclass(frozen=True)
class PairEntry:
    image1: int
    image2: int
    config: int
    count: int
    offset: int

    @property
    def key(self) -> tuple[int, int]:
        return tuple(sorted((self.image1, self.image2)))


@dataclass(frozen=True)
class CacheIndex:
    path: Path
    size: int
    fingerprint: tuple[int, int, int, int]
    images: tuple[ImageEntry, ...]
    pairs: tuple[PairEntry, ...]
    pair_count_offset: int
    camera_offset: int
    camera_ids: tuple[int, ...]
    inspection_seconds: float


def _fingerprint(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _read(handle: BinaryIO, count: int) -> bytes:
    data = handle.read(count)
    if len(data) != count:
        raise ValueError(f"Truncated VKMT data at byte {handle.tell()}")
    return data


def _u32(handle: BinaryIO) -> int:
    return struct.unpack('<I', _read(handle, 4))[0]


def _skip(handle: BinaryIO, count: int, size: int) -> None:
    if count < 0 or handle.tell() + count > size:
        raise ValueError('VKMT record exceeds file bounds')
    handle.seek(count, os.SEEK_CUR)


def read_index(path: str | Path) -> CacheIndex:
    """Read bounded metadata only, refusing partial/live/unknown cache formats."""
    started = time.perf_counter()
    path = Path(path).resolve()
    before = path.stat()
    size = before.st_size
    with path.open('rb') as handle:
        if _read(handle, 4) != b'VKMT' or _u32(handle) != 4:
            raise ValueError('Expected a complete Spirula VKMT v4 cache')
        count = _u32(handle)
        if count > (size - handle.tell()) // 8:
            raise ValueError('Impossible image count')
        images = []
        names = set()
        for _ in range(count):
            length = _u32(handle)
            if not 0 < length <= min(1 << 20, size - handle.tell()):
                raise ValueError('Invalid image name length')
            name = _read(handle, length).decode('utf-8')
            if name in names or '\x00' in name:
                raise ValueError('Duplicate or invalid image identity')
            names.add(name)
            images.append(ImageEntry(name, _u32(handle)))
        pair_count_offset = handle.tell()
        count = _u32(handle)
        if count > (size - handle.tell()) // 16:
            raise ValueError('Impossible or unfinished pair count')
        pairs = []
        seen_pairs = set()
        for _ in range(count):
            first, second, config, matches = struct.unpack('<IIiI', _read(handle, 16))
            if first >= len(images) or second >= len(images) or first == second:
                raise ValueError('Invalid image pair index')
            pair = PairEntry(first, second, config, matches, handle.tell())
            if pair.key in seen_pairs:
                raise ValueError('Duplicate image pair')
            seen_pairs.add(pair.key)
            pairs.append(pair)
            _skip(handle, matches * 8, size)
        camera_offset = handle.tell()
        camera_count = _u32(handle)
        if camera_count > len(images):
            raise ValueError('Impossible camera count')
        cameras = set()
        for _ in range(camera_count):
            camera_id, width, height, model, prior, scale, parameters = struct.unpack(
                '<IIIiBdI', _read(handle, 29))
            if camera_id in cameras or not width or not height or prior > 1:
                raise ValueError('Invalid camera metadata')
            if not math.isfinite(scale) or scale <= 0 or not 1 <= parameters <= 16:
                raise ValueError('Invalid camera scale or parameter count')
            values = struct.unpack('<' + 'd' * parameters, _read(handle, parameters * 8))
            if not all(math.isfinite(value) for value in values):
                raise ValueError('Non-finite camera parameter')
            cameras.add(camera_id)
        camera_ids = ()
        if camera_count:
            if _u32(handle) != len(images):
                raise ValueError('Camera identity table does not match images')
            camera_ids = tuple(_u32(handle) for _ in images)
            if not set(camera_ids).issubset(cameras):
                raise ValueError('Unknown camera identity')
            if any(value > 1 for value in _read(handle, camera_count)):
                raise ValueError('Invalid focal-measured flags')
        if handle.tell() != size:
            raise ValueError('Unexpected trailing cache bytes')
    if _fingerprint(path.stat()) != _fingerprint(before):
        raise ValueError('Source cache changed during inspection')
    return CacheIndex(path, size, _fingerprint(before), tuple(images), tuple(pairs),
                      pair_count_offset, camera_offset, camera_ids,
                      time.perf_counter() - started)


def resolve_image_names(index: CacheIndex, image_names: Iterable[str]) -> dict[str, int]:
    """Resolve exact cache stems, also accepting source image extensions."""
    names = {image.name: i for i, image in enumerate(index.images)}
    resolved = {}
    for name in image_names:
        normalized = name.replace('\\', '/')
        if normalized not in names and Path(normalized).suffix.lower() in {
            '.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.exr'}:
            normalized = str(Path(normalized).with_suffix('')).replace('\\', '/')
        if normalized not in names:
            raise ValueError(f'Image absent from cache: {name}')
        resolved[name] = names[normalized]
    return resolved


def image_ids(index: CacheIndex, image_pairs: Iterable[tuple[str, str]]) -> set[tuple[int, int]]:
    pairs = list(image_pairs)
    names = resolve_image_names(index, (name for pair in pairs for name in pair))
    result = set()
    for first, second in pairs:
        pair = tuple(sorted((names[first], names[second])))
        if pair[0] == pair[1]:
            raise ValueError('Self pairs are invalid')
        result.add(pair)
    return result


def subset_matches(source: str | Path, output: str | Path,
                   requested_pairs: Iterable[tuple[int, int]], *,
                   expected_source_sha256: str | None = None) -> dict:
    """Atomically publish selected verified records with the complete image table.

    No keypoint compaction, index renumbering, camera conversion, or new matching
    occurs. Missing requested pairs are explicitly reported. Full source hashing
    reads the cache once; use read_index for cheap inspection while gaming.
    """
    started = time.perf_counter()
    index = read_index(source)
    output = Path(output).resolve()
    if output == index.path or output.exists():
        raise FileExistsError(output)
    wanted = set()
    for first, second in requested_pairs:
        if not 0 <= first < len(index.images) or not 0 <= second < len(index.images) or first == second:
            raise ValueError('Requested pair has an invalid image index')
        wanted.add(tuple(sorted((first, second))))
    selected = {pair.key for pair in index.pairs
                if pair.key in wanted and pair.config != 0 and pair.count > 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=output.name + '.', suffix='.partial', dir=output.parent)
    temporary = Path(temporary)
    source_digest = hashlib.sha256()
    output_digest = hashlib.sha256()
    copied_matches = 0
    try:
        with os.fdopen(descriptor, 'wb') as destination, index.path.open('rb') as original:
            if _fingerprint(os.fstat(original.fileno())) != index.fingerprint:
                raise ValueError('Source changed before copy')

            def consume(count: int, copy: bool, pair: PairEntry | None = None) -> None:
                while count:
                    chunk = _read(original, min(count, 1 << 20))
                    source_digest.update(chunk)
                    if pair is not None:
                        for first, second in struct.iter_unpack('<II', chunk):
                            if first >= index.images[pair.image1].num_features or second >= index.images[pair.image2].num_features:
                                raise ValueError('Selected correspondence indexes a missing feature')
                    if copy:
                        destination.write(chunk)
                        output_digest.update(chunk)
                    count -= len(chunk)

            consume(index.pair_count_offset, True)
            consume(4, False)
            count_bytes = struct.pack('<I', len(selected))
            destination.write(count_bytes)
            output_digest.update(count_bytes)
            for pair in index.pairs:
                keep = pair.key in selected
                consume(16, keep)
                consume(pair.count * 8, keep, pair if keep else None)
                if keep:
                    copied_matches += pair.count
            consume(index.size - index.camera_offset, True)
            if original.read(1) or _fingerprint(os.fstat(original.fileno())) != index.fingerprint:
                raise ValueError('Source changed during copy')
            if expected_source_sha256 and source_digest.hexdigest() != expected_source_sha256.lower():
                raise ValueError('Source SHA-256 mismatch')
            destination.flush()
            os.fsync(destination.fileno())
        read_index(temporary)
        # A hard link publishes atomically without overwriting a concurrent result.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        'source': str(index.path), 'sourceSha256': source_digest.hexdigest(),
        'sourceBytes': index.size, 'output': str(output),
        'outputSha256': output_digest.hexdigest(), 'outputBytes': output.stat().st_size,
        'images': len(index.images), 'candidatePairs': len(wanted),
        'availableVerifiedPairs': len(selected), 'copiedMatches': copied_matches,
        'missingRequestedPairs': [list(pair) for pair in sorted(wanted - selected)],
        'imageIdsPreserved': True, 'featureIndicesPreserved': True,
        'cameraSectionPreserved': True, 'featureCompactionPerformed': False,
        'timingKind': 'cached-subset-copy-not-fresh-matching',
        'seconds': time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--graph', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--expected-source-sha256')
    args = parser.parse_args()
    index = read_index(args.source)
    if bool(args.graph) != bool(args.output):
        parser.error('--graph and --output are required together')
    if args.graph:
        graph = json.loads(args.graph.read_text(encoding='utf-8'))
        pairs = image_ids(index, ((row['image1'], row['image2']) for row in graph['candidateEdges']))
        report = subset_matches(args.source, args.output, pairs,
                                expected_source_sha256=args.expected_source_sha256)
        with args.output.with_suffix(args.output.suffix + '.json').open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
    else:
        report = {'source': str(index.path), 'bytes': index.size, 'images': len(index.images),
                  'pairs': len(index.pairs), 'verifiedPairs': sum(p.config != 0 and p.count > 0 for p in index.pairs),
                  'sourceSha256': None, 'inspectionSeconds': index.inspection_seconds,
                  'inspection': 'Metadata only; correspondence payloads skipped without hashing.'}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
