"""Read the existing paired capture without copying or changing its images."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import math


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_capture(dataset, selection=None, camera_manifest=None):
    dataset = Path(dataset).resolve()
    selection = Path(selection or dataset/'analysis/frame-selection.json').resolve()
    camera_manifest = Path(camera_manifest or dataset/'sfm-manifest-native3840.json').resolve()
    original = json.loads(selection.read_text())
    camera_spec = json.loads(camera_manifest.read_text())
    cameras = {c['prefix']: c for c in camera_spec['cameras']}
    if set(cameras) != {'cam0', 'cam1'}:
        raise ValueError('This experiment requires the explicitly calibrated two-lens capture')
    rate = original['fps_numerator']/original['fps_denominator']
    frames, seen = [], set()
    for row in original['selected']:
        index, name, split = row['source_frame'], row['filename'], row['split']
        if index in seen or Path(name).name != name or split not in ('train', 'eval'):
            raise ValueError('Duplicate frame, unsafe filename or unknown split')
        if f'_{split}.' not in name or not math.isclose(row['time_seconds'], index/rate, abs_tol=1e-7):
            raise ValueError('Filename, split and source-frame timestamp disagree')
        seen.add(index)
        images, masks = {}, {}
        for lens in cameras:
            images[lens] = f'{lens}/{name}'
            masks[lens] = f'{lens}/{Path(name).stem}.png'
            for group, relative in (('images', images[lens]), ('masks', masks[lens])):
                path = (dataset/group/relative).resolve()
                if not path.is_relative_to(dataset/group) or not path.is_file():
                    raise ValueError(f'Missing or escaped {group}: {relative}')
        frames.append({'id': index, 'time_seconds': row['time_seconds'], 'split': split,
                       'images': images, 'masks': masks})
    frames.sort(key=lambda row: row['id'])
    return {'schema_version': 1, 'dataset': str(dataset), 'fps': rate,
            'source_selection_sha256': sha256(selection),
            'camera_manifest_sha256': sha256(camera_manifest),
            'cameras': cameras, 'rigs': camera_spec.get('rigs', []), 'frames': frames,
            'timestamp_basis': 'Existing paired source-frame selection; both lens paths use the identical frame index.'}
