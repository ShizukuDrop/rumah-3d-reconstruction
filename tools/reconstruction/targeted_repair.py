"""Prepare a bounded repair graph without changing prior anchor identities.

Only nominated frame intervals receive extra synchronized anchors. The quality
gate stays authoritative: rejected/evaluation views cannot become anchors, and
unknown quality remains explicitly pending review. No images, features, poses,
or match payloads are opened here. The previous candidate edges are preserved,
but their previous verification is not claimed for this fresh experiment.
"""
from __future__ import annotations

import argparse
import bisect
import copy
import hashlib
import json
import math
from pathlib import Path

from .pair_graph import GraphOptions, _components, build_pair_graph


def _rank(frame: dict, quality: dict) -> tuple:
    views = quality['views']
    if set(views) != set(frame['images']):
        raise ValueError('Quality decisions must cover both synchronized lenses')
    ratios = [view.get('width_ratio', float('inf')) for view in views.values()]
    if any(not isinstance(value, (int, float)) or math.isnan(value) or value <= 0 for value in ratios):
        raise ValueError('Invalid relative sharpness measurement')
    return (frame['quality_action'] != 'keep', max(ratios), sum(ratios), int(frame['id']))


def prepare_repair(selection: dict, quality: dict, previous_graph: dict, *,
                   intervals: tuple[tuple[int, int], ...], bin_frames: int = 3,
                   min_interval_seconds: float = .066, local_neighbors: int = 4,
                   baseline_seconds: tuple[float, ...] = (.2, .5, 1., 2.5),
                   boundary_padding_seconds: float = .5) -> tuple[dict, dict, dict]:
    if bin_frames < 1 or local_neighbors < 1 or not intervals:
        raise ValueError('Nonempty intervals and positive budgets are required')
    if any(start > end for start, end in intervals):
        raise ValueError('Invalid target interval')
    if any(not math.isfinite(x) or x < 0 for x in (*baseline_seconds, min_interval_seconds, boundary_padding_seconds)):
        raise ValueError('Invalid temporal limits')
    result = copy.deepcopy(selection)
    frames = sorted(result['frames'], key=lambda frame: frame['time_seconds'])
    by_id = {int(frame['id']): frame for frame in frames}
    if len(by_id) != len(frames):
        raise ValueError('Frame identities must be unique integers')
    original = {int(frame['id']) for frame in frames if frame.get('selected', False)}
    if original != set(previous_graph['anchorIds']):
        raise ValueError('Previous graph and selection do not identify the same anchors')
    allow_review = result.get('configuration', {}).get('allow_unknown_quality_for_experiment', False)
    selected = set(original)
    selected_times = sorted(by_id[index]['time_seconds'] for index in selected)
    added = []
    summaries = []
    for start, end in intervals:
        if start not in by_id or end not in by_id:
            raise ValueError('Target boundaries must be known source frame IDs')
        local_added = []
        for lower in range(start, end + 1, bin_frames):
            upper = min(lower + bin_frames - 1, end)
            if any(identity in selected for identity in range(lower, upper + 1)):
                continue
            candidates = []
            for identity in range(lower, upper + 1):
                frame = by_id.get(identity)
                if frame is None or frame.get('split', 'train') != 'train':
                    continue
                action = frame.get('quality_action')
                if action != 'keep' and not (action == 'review' and allow_review):
                    continue
                decision = quality.get(str(identity))
                if decision is None or decision.get('action') != action:
                    raise ValueError('Quality decision identity/action mismatch')
                if any(view.get('confirmed') and view.get('verdict') in {'blur', 'blurred'} for view in decision['views'].values()):
                    continue
                timestamp = frame['time_seconds']
                offset = bisect.bisect_left(selected_times, timestamp)
                neighbors = selected_times[max(0, offset - 1):offset + 1]
                if any(abs(timestamp - other) < min_interval_seconds - 1e-9 for other in neighbors):
                    continue
                candidates.append(frame)
            if not candidates:
                continue
            chosen = min(candidates, key=lambda frame: _rank(frame, quality[str(frame['id'])]))
            identity = int(chosen['id'])
            chosen['selected'] = True
            chosen['requires_quality_review'] = chosen['quality_action'] == 'review'
            chosen['protected'] = True
            chosen['alignment_reasons'] = list(chosen.get('alignment_reasons', [])) + ['targeted-failure-gap-fill']
            chosen['repair_selection'] = {
                'interval': [start, end], 'bin': [lower, upper],
                'ranking': 'confirmed-keep first; lowest worst-lens relative edge width; summed ratio; source frame ID',
                'relative_width_ratios': {lens: view.get('width_ratio') for lens, view in quality[str(identity)]['views'].items()},
                'quality_is_approved': chosen['quality_action'] == 'keep',
            }
            selected.add(identity)
            bisect.insort(selected_times, chosen['time_seconds'])
            added.append(identity)
            local_added.append(identity)
        summaries.append({'frameInterval': [start, end], 'beforePairs': sum(start <= i <= end for i in original),
                          'afterPairs': sum(start <= i <= end for i in selected), 'addedFrameIds': local_added})
    anchors = [frame for frame in frames if int(frame['id']) in selected]
    times = [frame['time_seconds'] for frame in anchors]
    bridge_rows = list(result.get('bridges', []))
    for start, end in intervals:
        start_time, end_time = by_id[start]['time_seconds'], by_id[end]['time_seconds']
        lower, upper = start_time - boundary_padding_seconds, end_time + boundary_padding_seconds
        for index, frame in enumerate(anchors):
            if not lower <= frame['time_seconds'] <= upper:
                continue
            for neighbor in anchors[index + 1:index + 1 + local_neighbors]:
                if neighbor['time_seconds'] <= upper:
                    bridge_rows.append({'from': frame['id'], 'to': neighbor['id'], 'reason': 'targeted-near-neighbor'})
            for delay in baseline_seconds:
                following = bisect.bisect_left(times, frame['time_seconds'] + delay, lo=index + 1)
                if following < len(anchors) and anchors[following]['time_seconds'] <= upper:
                    bridge_rows.append({'from': frame['id'], 'to': anchors[following]['id'],
                                        'reason': 'targeted-spaced-baseline'})
    result['bridges'] = bridge_rows
    result['alignment_pair_count'] = len(selected)
    result['selected_unknown_quality_count'] = sum(frame.get('requires_quality_review', False) for frame in anchors)
    result['acceptance_passed'] = False
    if 'elapsed_seconds' in result:
        result['parent_selection_elapsed_seconds'] = result.pop('elapsed_seconds')
    result['acceptance_scope'] = 'Experimental targeted repair; added unknown-quality pairs require visual review and geometry must pass.'
    result['repair'] = {'targetIntervals': summaries, 'binFrames': bin_frames,
                        'minimumAddedAnchorIntervalSeconds': min_interval_seconds,
                        'localNeighbors': local_neighbors, 'baselineSeconds': list(baseline_seconds),
                        'boundaryPaddingSeconds': boundary_padding_seconds,
                        'addedFrameIds': added, 'originalAnchorsPreserved': True,
                        'sourceGeometryUsed': False, 'sourceMatchesUsedForSelection': False}
    for region in result.get('coverage', []):
        region['parent_selected_frame_ids'] = region.pop('selected_frame_ids', [])
        region['parent_anchor_pairs'] = region.pop('anchor_pairs', None)
        region['scope'] = 'Parent coverage report; use repair intervals for this variant and recompute geometry after solving.'
    options = GraphOptions(**{**previous_graph['options'], 'baseline_seconds': tuple(previous_graph['options']['baseline_seconds'])})
    graph = build_pair_graph(result, options=options)
    edges = {(edge['image1'], edge['image2']): edge for edge in graph['candidateEdges']}
    names = set(graph['images'])
    for previous in previous_graph['candidateEdges']:
        first, second = previous['image1'], previous['image2']
        if first not in names or second not in names or first == second:
            raise ValueError('Previous edge does not identify selected images')
        key = tuple(sorted((first, second)))
        current = edges.get(key)
        if current is None:
            current = copy.deepcopy(previous)
            current['availableVerified'] = None
            current['image1'], current['image2'] = key
            edges[key] = current
        current['reasons'] = sorted(set(current['reasons']) | set(previous['reasons']) | {'preserved-parent-candidate'})
        current['required'] = current['required'] or previous['required']
    graph['candidateEdges'] = [edge for _, edge in sorted(edges.items())]
    rig_pairs = [tuple(row['images']) for row in graph['rigConstraints']]
    graph['candidateImageComponents'] = _components(names, edges)
    graph['candidateRigComponents'] = _components(names, list(edges) + rig_pairs)
    graph['experimentStatus'] = 'review_pending'
    graph['selectionAccepted'] = False
    graph['selectedUnknownQualityPairs'] = result['selected_unknown_quality_count']
    graph['parentCandidateEdgesPreserved'] = len(previous_graph['candidateEdges'])
    graph['freshMatchingRequired'] = True
    report = {'anchorsBefore': len(original), 'anchorsAfter': len(selected), 'addedAnchors': len(added),
              'addedKeep': sum(by_id[i]['quality_action'] == 'keep' for i in added),
              'addedReviewPending': sum(by_id[i]['quality_action'] == 'review' for i in added),
              'candidateEdgesBefore': len(previous_graph['candidateEdges']), 'candidateEdgesAfter': len(edges),
              'candidateEdgesAdded': len(edges) - len(previous_graph['candidateEdges']),
              'candidateRigComponents': len(graph['candidateRigComponents']), 'intervals': summaries,
              'allParentAnchorsAndEdgesPreserved': True, 'evaluationFramesAdded': 0,
              'rejectedQualityFramesAdded': 0, 'geometryUsedForSelection': False,
              'status': 'review_pending; no staging/matching/mapping performed'}
    return result, graph, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--quality', type=Path, required=True)
    parser.add_argument('--parent-graph', type=Path, required=True)
    parser.add_argument('--interval', nargs=2, type=int, action='append', required=True)
    parser.add_argument('--bin-frames', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.selection, args.quality, args.parent_graph]
    data = [json.loads(path.read_text(encoding='utf-8-sig')) for path in inputs]
    result = prepare_repair(*data, intervals=tuple(map(tuple, args.interval)), bin_frames=args.bin_frames)
    args.output.mkdir(parents=True, exist_ok=False)
    provenance = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    for item in result:
        item['inputFileSha256'] = provenance
    result[1]['manifestCanonicalSha256'] = hashlib.sha256(json.dumps(
        result[0], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    for name, item in zip(('selection.json', 'pair-graph.json', 'repair-report.json'), result):
        with (args.output / name).open('x', encoding='utf-8') as handle:
            json.dump(item, handle, indent=2, allow_nan=False)
    print(json.dumps(result[2], indent=2))


if __name__ == '__main__':
    main()
