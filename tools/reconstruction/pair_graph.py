"""Build an explicit, deterministic matching graph over synchronized anchors.

Input frames have id, time_seconds, images (lens -> relative image name), selected,
and split. Optional room, protected and position fields add coverage evidence.
Rig constraints are emitted separately: they do not assert visible overlap.
Retrieval rows contain image1, image2 and score. Cross-lens edges additionally
require geometric_overlap=True or an exact verified edge from a supplied cache.
"""
from __future__ import annotations

import argparse
import bisect
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GraphOptions:
    local_neighbors: int = 2
    baseline_seconds: tuple[float, ...] = (0.35, 0.8, 1.6)
    retrieval_budget_per_image: int = 4
    retrieval_temporal_exclusion_seconds: float = 1.5
    failed_interval_padding_seconds: float = 0.15
    geometry_max_distance: float | None = None
    geometry_neighbors_per_image: int = 2
    include_eval: bool = False


def _key(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))


def _components(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    adjacency = {node: set() for node in nodes}
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    groups = []
    unseen = set(adjacency)
    while unseen:
        pending = [min(unseen)]
        unseen.remove(pending[0])
        component = []
        while pending:
            node = pending.pop()
            component.append(node)
            for neighbor in sorted(adjacency[node] & unseen):
                unseen.remove(neighbor)
                pending.append(neighbor)
        groups.append(sorted(component))
    return sorted(groups, key=lambda group: (-len(group), group))


def build_pair_graph(manifest: dict, *, retrieval: list[dict] | None = None,
                     verified_pairs: Iterable[tuple[str, str]] | None = None,
                     options: GraphOptions | None = None) -> dict:
    """Create candidate edges, auditable coverage links, and cache availability.

    Times and optional positions come from the input. No image matching or pose
    solving occurs here. Failed intervals expand only their nearby stored frames.
    """
    options = options or GraphOptions()
    if options.local_neighbors < 1 or options.retrieval_budget_per_image < 0 or options.geometry_neighbors_per_image < 0:
        raise ValueError('Invalid neighbor budget')
    scalars = (*options.baseline_seconds, options.retrieval_temporal_exclusion_seconds,
               options.failed_interval_padding_seconds)
    if not all(math.isfinite(x) and x >= 0 for x in scalars):
        raise ValueError('Time thresholds must be finite and non-negative')
    if options.geometry_max_distance is not None and (not math.isfinite(options.geometry_max_distance) or options.geometry_max_distance <= 0):
        raise ValueError('Geometry distance must be positive and use the input position units')
    frames = sorted(manifest['frames'], key=lambda frame: (frame['time_seconds'], str(frame['id'])))
    by_id = {}
    image_frame = {}
    image_lens = {}
    times_seen = set()
    for frame in frames:
        identity = str(frame['id'])
        seconds = frame['time_seconds']
        if identity in by_id or seconds in times_seen or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Frame IDs and finite non-negative timestamps must be unique')
        if frame.get('split', 'train') not in {'train', 'eval'}:
            raise ValueError('Unknown frame split')
        images = frame['images']
        if not isinstance(images, dict) or len(images) != 2:
            raise ValueError('Each synchronized frame must carry exactly two lens images')
        for lens, name in images.items():
            if not isinstance(name, str) or not name or name in image_frame:
                raise ValueError('Image names must be unique nonempty strings')
            image_frame[name] = frame
            image_lens[name] = lens
        position = frame.get('position')
        if position is not None and (len(position) != 3 or not all(math.isfinite(x) for x in position)):
            raise ValueError('Positions must have three finite coordinates')
        by_id[identity] = frame
        times_seen.add(seconds)
    if len({tuple(sorted(frame['images'])) for frame in frames}) > 1:
        raise ValueError('All frames must identify the same two rig members')
    allow_review = manifest.get('configuration', {}).get('allow_unknown_quality_for_experiment', False)
    quality_excluded = {str(frame['id']) for frame in frames
                        if frame.get('quality_action') == 'reject' or
                        (frame.get('quality_action') == 'review' and not allow_review)}
    if any(str(frame['id']) in quality_excluded and
           (frame.get('selected', True) or frame.get('protected', False)) for frame in frames):
        raise ValueError('Selected/protected frames cannot override rejected or unapproved quality')
    allowed = {str(frame['id']) for frame in frames
               if str(frame['id']) not in quality_excluded and
               (options.include_eval or frame.get('split', 'train') == 'train')}
    selected = {str(frame['id']) for frame in frames
                if str(frame['id']) in allowed and (frame.get('selected', True) or frame.get('protected', False))}
    expansion = set()
    for interval in manifest.get('failed_intervals', []):
        start, end = interval['start_seconds'], interval['end_seconds']
        if not math.isfinite(start) or not math.isfinite(end) or start > end:
            raise ValueError('Invalid failed interval')
        for frame in frames:
            identity = str(frame['id'])
            if identity in allowed and start - options.failed_interval_padding_seconds <= frame['time_seconds'] <= end + options.failed_interval_padding_seconds:
                expansion.add(identity)
    selected.update(expansion)
    bridges = manifest.get('bridges', [])
    for bridge in bridges:
        for side in ('from', 'to'):
            identity = str(bridge[side])
            if identity not in by_id:
                raise ValueError(f'Bridge names an unknown frame: {identity}')
            if identity in quality_excluded:
                raise ValueError('A protected bridge cannot override rejected or unapproved quality')
            if identity not in allowed:
                raise ValueError('A protected bridge cannot silently include held-out geometry')
            selected.add(identity)
    anchors = [frame for frame in frames if str(frame['id']) in selected]
    if len(anchors) < 2:
        raise ValueError('At least two eligible synchronized anchors are required')
    cache_supplied = verified_pairs is not None
    verified = {_key(*pair) for pair in verified_pairs or []}
    # Cache callers resolve filename stems before supplying these exact names.
    if any(first == second or first not in image_frame or second not in image_frame for first, second in verified):
        raise ValueError('Verified edges must identify existing distinct images')
    edges = {}
    rejected_cross_lens = []

    def add(first: str, second: str, reason: str, required: bool = False,
            geometric_overlap: bool = False) -> None:
        pair = _key(first, second)
        if first == second:
            raise ValueError('Self edges are invalid')
        cross_lens = image_lens[first] != image_lens[second]
        if cross_lens and not geometric_overlap and pair not in verified:
            rejected_cross_lens.append({'image1': pair[0], 'image2': pair[1], 'reason': 'No geometric overlap evidence'})
            return
        edge = edges.setdefault(pair, {'image1': pair[0], 'image2': pair[1], 'reasons': set(),
                                       'required': False, 'crossLens': cross_lens})
        edge['reasons'].add(reason)
        edge['required'] = edge['required'] or required

    def connect_frames(first: dict, second: dict, reason: str, required: bool = False) -> None:
        for lens in sorted(first['images']):
            add(first['images'][lens], second['images'][lens], reason, required)

    times = [frame['time_seconds'] for frame in anchors]
    for index, frame in enumerate(anchors):
        for neighbor in anchors[index + 1:index + 1 + options.local_neighbors]:
            connect_frames(frame, neighbor, 'temporal-neighbor')
        for delay in options.baseline_seconds:
            next_index = bisect.bisect_left(times, frame['time_seconds'] + delay, lo=index + 1)
            if next_index < len(anchors):
                connect_frames(frame, anchors[next_index], 'spaced-temporal-baseline')
        if index and frame.get('room') is not None and anchors[index - 1].get('room') is not None and frame['room'] != anchors[index - 1]['room']:
            connect_frames(anchors[index - 1], frame, 'room-transition', True)
        if index and (frame.get('protected') or anchors[index - 1].get('protected')):
            connect_frames(anchors[index - 1], frame, 'protected-coverage', True)
    for bridge in bridges:
        first, second = by_id[str(bridge['from'])], by_id[str(bridge['to'])]
        if first is second:
            raise ValueError('A bridge must join distinct frames')
        connect_frames(first, second, 'bridge:' + bridge.get('reason', 'specified-coverage'), True)

    names = {name for frame in anchors for name in frame['images'].values()}
    retrieval_counts = {name: 0 for name in names}
    retrieval_rows = retrieval if retrieval is not None else manifest.get('retrieval', [])
    for row in retrieval_rows:
        if row['image1'] not in image_frame or row['image2'] not in image_frame or not math.isfinite(row['score']):
            raise ValueError('Invalid retrieval identity or score')
    ranked = sorted(retrieval_rows, key=lambda row: (-row['score'], *_key(row['image1'], row['image2'])))
    retrieval_seen = set()
    for row in ranked:
        first, second = row['image1'], row['image2']
        pair = _key(first, second)
        if pair in retrieval_seen or first == second or first not in names or second not in names:
            continue
        retrieval_seen.add(pair)
        separation = abs(image_frame[first]['time_seconds'] - image_frame[second]['time_seconds'])
        if separation < options.retrieval_temporal_exclusion_seconds:
            continue
        if pair in edges or min(options.retrieval_budget_per_image - retrieval_counts[first],
                                options.retrieval_budget_per_image - retrieval_counts[second]) <= 0:
            continue
        add(first, second, row.get('kind', 'loop-retrieval'), geometric_overlap=row.get('geometric_overlap') is True)
        if pair in edges:
            retrieval_counts[first] += 1
            retrieval_counts[second] += 1

    # Optional provisional poses can propose revisits. They never verify an edge.
    geometry_candidates = []
    if options.geometry_max_distance is not None:
        for index, first in enumerate(anchors):
            if first.get('position') is None:
                continue
            for second in anchors[index + 1:]:
                if second.get('position') is None or second['time_seconds'] - first['time_seconds'] < options.retrieval_temporal_exclusion_seconds:
                    continue
                distance = math.dist(first['position'], second['position'])
                if distance <= options.geometry_max_distance:
                    for lens in sorted(first['images']):
                        pair = _key(first['images'][lens], second['images'][lens])
                        geometry_candidates.append((distance, pair))
    geometry_counts = {name: 0 for name in names}
    for distance, pair in sorted(geometry_candidates):
        first, second = pair
        if pair in edges or max(geometry_counts[first], geometry_counts[second]) >= options.geometry_neighbors_per_image:
            continue
        add(first, second, 'provisional-position-revisit')
        geometry_counts[first] += 1
        geometry_counts[second] += 1

    # Explicit overlap observations may justify same-time cross-lens matching.
    for row in manifest.get('overlap_evidence', []):
        first, second = row['image1'], row['image2']
        if first not in image_frame or second not in image_frame:
            raise ValueError('Overlap evidence names an unknown image')
        if first in names and second in names and row.get('geometric_overlap') is True:
            add(first, second, 'measured-overlap', geometric_overlap=True)
    candidates = []
    for pair, edge in sorted(edges.items()):
        edge['reasons'] = sorted(edge['reasons'])
        edge['availableVerified'] = pair in verified if cache_supplied else None
        first_position = image_frame[pair[0]].get('position')
        second_position = image_frame[pair[1]].get('position')
        if first_position is not None and second_position is not None:
            edge['provisionalBaselineUnits'] = math.dist(first_position, second_position)
        candidates.append(edge)
    available = [edge for edge in candidates if edge['availableVerified'] is True]
    rig_links = [tuple(sorted(frame['images'].values())) for frame in anchors]
    candidate_pairs = list(edges)
    available_pairs = [(edge['image1'], edge['image2']) for edge in available]
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {
        'schemaVersion': 1, 'manifestCanonicalSha256': manifest_hash, 'options': asdict(options),
        'anchorIds': [frame['id'] for frame in anchors], 'images': sorted(names),
        'expandedFrameIds': sorted(expansion), 'qualityExcludedFrameIds': sorted(quality_excluded),
        'selectedEvalExcluded': sum(frame.get('selected', True) and frame.get('split') == 'eval' for frame in frames) if not options.include_eval else 0,
        'candidateEdges': candidates, 'verifiedCacheProvided': cache_supplied,
        'availableVerifiedEdges': available,
        'missingVerifiedEdges': [edge for edge in candidates if edge['availableVerified'] is False],
        'rigConstraints': [{'frameId': frame['id'], 'images': sorted(frame['images'].values()), 'meaning': 'Rigid synchronized pose constraint; not an image correspondence'} for frame in anchors],
        'rejectedCrossLensCandidates': rejected_cross_lens,
        'candidateImageComponents': _components(names, candidate_pairs),
        'candidateRigComponents': _components(names, candidate_pairs + rig_links),
        'availableVerifiedImageComponents': _components(names, available_pairs) if cache_supplied else None,
        'availableVerifiedRigComponents': _components(names, available_pairs + rig_links) if cache_supplied else None,
        'maxAnchorGapSeconds': max(second - first for first, second in zip(times, times[1:])),
        'timingKind': 'graph-construction-and-cache-availability-not-fresh-matching',
        'sourceMatchingPerformed': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--retrieval', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-eval', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    retrieval = json.loads(args.retrieval.read_text(encoding='utf-8')) if args.retrieval else None
    verified = None
    if args.cache:
        try:
            from .match_cache import read_index, resolve_image_names
        except ImportError:
            from match_cache import read_index, resolve_image_names
        index = read_index(args.cache)
        names = [name for frame in manifest['frames'] for name in frame['images'].values()]
        resolved = resolve_image_names(index, names)
        by_cache_id = {number: name for name, number in resolved.items()}
        if len(by_cache_id) != len(names):
            raise ValueError('Ambiguous source image identity')
        verified = [(by_cache_id[p.image1], by_cache_id[p.image2]) for p in index.pairs
                    if p.config != 0 and p.count and p.image1 in by_cache_id and p.image2 in by_cache_id]
    graph = build_pair_graph(manifest, retrieval=retrieval, verified_pairs=verified,
                             options=GraphOptions(include_eval=args.include_eval))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(graph, handle, indent=2)
    print(json.dumps({'candidateEdges': len(graph['candidateEdges']),
                      'availableVerifiedEdges': len(graph['availableVerifiedEdges']),
                      'anchors': len(graph['anchorIds'])}, indent=2))


if __name__ == '__main__':
    main()
