"""Stage a fresh selected-anchor dataset without aliasing mutable feature files.

Images/masks may be hardlinked; feature files are always independent copies.
The staging time includes source hashing and copying, not feature extraction.
An existing destination is never overwritten. Failed staging stays inspectable.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import time


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _sha(path: Path) -> str:
    before = path.stat()
    with path.open('rb') as handle:
        value = hashlib.file_digest(handle, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Source changed while hashing: {path}')
    return value


def _relative(name: str) -> Path:
    posix = PurePosixPath(name.replace('\\', '/'))
    if not name or posix.is_absolute() or ':' in name or '..' in posix.parts:
        raise ValueError(f'Unsafe relative image name: {name!r}')
    return Path(*posix.parts)


def _source(root: Path, relative: Path) -> Path:
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Source escapes nominated root or is not a file: {path}')
    return path


def _feature_header(path: Path) -> dict:
    with path.open('rb') as handle:
        header = handle.read(28)
    if len(header) != 28:
        raise ValueError(f'Truncated feature header: {path}')
    magic, version, width, height, count, dimension, dtype = struct.unpack('<4s6I', header)
    if magic != b'VKFT' or version != 6 or dtype != 1 or not width or not height or not dimension:
        raise ValueError(f'Expected float32 VKFT v6 features: {path}')
    minimum = 28 + count * (16 + dimension * 4)
    if path.stat().st_size < minimum:
        raise ValueError(f'Truncated feature payload: {path}')
    return {'version': version, 'width': width, 'height': height,
            'featureCount': count, 'descriptorDimension': dimension, 'descriptorType': 'float32'}


def _materialize(source: Path, target: Path, hardlink: bool, expected_sha: str) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    method = 'copy'
    if hardlink:
        try:
            os.link(source, target)
            method = 'hardlink'
        except OSError:
            shutil.copyfile(source, target)
    else:
        shutil.copyfile(source, target)
    if _sha(target) != expected_sha:
        raise ValueError(f'Staged bytes do not match source hash: {target}')
    if not hardlink and os.path.samefile(source, target):
        raise ValueError('Feature copies must not share source file identity')
    return method


def stage_dataset(selection_path: Path, camera_manifest_path: Path, feature_root: Path,
                  mask_root: Path, output: Path, *, all_copy: bool = False,
                  source_cache: Path | None = None) -> dict:
    started = time.perf_counter()
    selection_path, camera_manifest_path = selection_path.resolve(), camera_manifest_path.resolve()
    selection, camera = _json(selection_path), _json(camera_manifest_path)
    image_root = Path(camera['image_dir'])
    if not image_root.is_absolute():
        image_root = camera_manifest_path.parent / image_root
    image_root = image_root.resolve(strict=True)
    feature_root, mask_root = feature_root.resolve(strict=True), mask_root.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f'Refusing an existing staging destination: {output}')
    if any(output.is_relative_to(root) or root.is_relative_to(output)
           for root in (image_root, feature_root, mask_root)):
        raise ValueError('Staging output must be separate from all source trees')
    selected = [row for row in selection['frames'] if row.get('selected', True)]
    if not selected:
        raise ValueError('No selected anchor frames')
    if any(row.get('split', 'train') != 'train' for row in selected):
        raise ValueError('Selected alignment anchors must exclude held-out evaluation frames')
    allow_review = selection.get('configuration', {}).get('allow_unknown_quality_for_experiment', False)
    if any(row.get('quality_action') == 'reject' or
           (row.get('quality_action') == 'review' and not allow_review) for row in selected):
        raise ValueError('Selected anchors contain rejected or unapproved quality')
    members = {entry['prefix'] for entry in camera['cameras']}
    if len(members) != 2:
        raise ValueError('This staging helper requires the calibrated two-lens capture')
    rows, used_names, used_feature_names, frame_ids = [], set(), set(), set()
    for frame in selected:
        if frame['id'] in frame_ids or set(frame['images']) != members:
            raise ValueError('Duplicate frame or incomplete synchronized lens pair')
        if len({Path(name.replace('\\', '/')).stem for name in frame['images'].values()}) != 1:
            raise ValueError('Lens pair does not share a synchronized frame stem')
        frame_ids.add(frame['id'])
        for lens, name in frame['images'].items():
            rel = _relative(name)
            if rel.parts[0] != lens or rel.as_posix() in used_names:
                raise ValueError('Image name has wrong lens prefix or is duplicated')
            used_names.add(rel.as_posix())
            feature_name = rel.with_suffix('.bin').as_posix()
            if feature_name in used_feature_names:
                raise ValueError('Image aliases collide in the native feature namespace')
            used_feature_names.add(feature_name)
            image = _source(image_root, rel)
            feature = _source(feature_root, rel.with_suffix('.bin'))
            mask = _source(mask_root, rel.with_suffix('.png'))
            rows.append({'frameId': frame['id'], 'lens': lens, 'name': rel.as_posix(),
                         'image': image, 'feature': feature, 'mask': mask,
                         'featureMetadata': _feature_header(feature)})
    # Native loadFeatureDir sorts relative feature paths before assigning IDs.
    rows.sort(key=lambda row: Path(row['name']).with_suffix('.bin').as_posix())
    original_ids = {}
    if source_cache:
        try:
            from .match_cache import read_index, resolve_image_names
        except ImportError:
            from match_cache import read_index, resolve_image_names
        index = read_index(source_cache)
        original_ids = resolve_image_names(index, [row['name'] for row in rows])
        for row in rows:
            if index.images[original_ids[row['name']]].num_features != row['featureMetadata']['featureCount']:
                raise ValueError('Source feature rows differ from the nominated match cache')
    output.mkdir(parents=True)
    report_path = output / 'staging-provenance.json'
    report = {'status': 'preparing', 'selection': str(selection_path),
              'selectionSha256': _sha(selection_path), 'sourceCameraManifest': str(camera_manifest_path),
              'sourceCameraManifestSha256': _sha(camera_manifest_path),
              'sourceImageRoot': str(image_root), 'sourceFeatureRoot': str(feature_root),
              'sourceMaskRoot': str(mask_root), 'sourceCache': str(source_cache) if source_cache else None,
              'sourceCacheSha256': None, 'sourceCachePayloadHashed': False,
              'sourceFeaturesPreserved': True, 'featureCompactionPerformed': False,
              'imageIdConvention': 'zero-based native VKMT feature order; resolve exported COLMAP IDs by image name',
              'reuseMode': 'fresh-subset-map-existing-feature-rows', 'resumeOldMapAllowed': False,
              'requiredAutoFlags': ['--reuse-features', 'keep', '--no-compact-unused-features'],
              'timingKind': 'staging-with-hashing-and-copying-not-feature-extraction',
              'timingIncludesExistingFeatureExtraction': False, 'images': []}
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        for new_id, row in enumerate(rows):
            rel = Path(row['name'])
            item = {key: row[key] for key in ('frameId', 'lens', 'name', 'featureMetadata')}
            item.update({'newImageId': new_id, 'originalImageId': original_ids.get(row['name']),
                         'nativeImageName': rel.with_suffix('').as_posix()})
            for kind, destination in [('image', output / 'images' / rel),
                                      ('mask', output / 'masks' / rel.with_suffix('.png')),
                                      ('feature', output / 'sfm' / 'features' / rel.with_suffix('.bin'))]:
                digest = _sha(row[kind])
                method = _materialize(row[kind], destination,
                                      hardlink=kind != 'feature' and not all_copy, expected_sha=digest)
                item[kind] = {'source': str(row[kind]), 'destination': str(destination),
                              'bytes': row[kind].stat().st_size, 'sha256': digest, 'method': method}
            report['images'].append(item)
        staged_camera = copy.deepcopy(camera)
        staged_camera['image_dir'] = (output / 'images').as_posix()
        staged_camera['mask_dir'] = (output / 'masks').as_posix()
        staged_camera_path = output / 'sfm-manifest.json'
        staged_camera_path.write_text(json.dumps(staged_camera, indent=2), encoding='utf-8')
        report.update({'status': 'complete', 'anchors': len(selected), 'imageCount': len(rows),
                       'cameraManifest': str(staged_camera_path),
                       'cameraManifestSha256': _sha(staged_camera_path),
                       'workspace': str(output / 'sfm'), 'seconds': time.perf_counter() - started})
    except Exception as exc:
        report.update({'status': 'failed', 'error': str(exc), 'seconds': time.perf_counter() - started})
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection', type=Path)
    parser.add_argument('--camera-manifest', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--masks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-cache', type=Path)
    parser.add_argument('--all-copy', action='store_true')
    args = parser.parse_args()
    report = stage_dataset(args.selection, args.camera_manifest, args.features, args.masks,
                           args.output, all_copy=args.all_copy, source_cache=args.source_cache)
    print(json.dumps({key: report[key] for key in ('status', 'anchors', 'imageCount', 'workspace', 'seconds')}))


if __name__ == '__main__':
    main()
