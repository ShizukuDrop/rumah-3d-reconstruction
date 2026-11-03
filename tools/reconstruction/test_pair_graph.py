import copy
import unittest

from tools.reconstruction.pair_graph import GraphOptions, build_pair_graph


def frames(count=8):
    return [{'id': i, 'time_seconds': float(i), 'split': 'train', 'selected': True,
             'images': {'cam0': f'cam0/{i}.jpg', 'cam1': f'cam1/{i}.jpg'}} for i in range(count)]


def edge_keys(graph):
    return {(edge['image1'], edge['image2']) for edge in graph['candidateEdges']}


class GraphTests(unittest.TestCase):
    def test_rig_constraints_never_claim_image_correspondence(self):
        result = build_pair_graph({'frames': frames()})
        self.assertTrue(all(not row['crossLens'] for row in result['candidateEdges']))
        self.assertEqual(len(result['candidateImageComponents']), 2)
        self.assertEqual(len(result['candidateRigComponents']), 1)
        self.assertIsNone(result['availableVerifiedRigComponents'])
        self.assertEqual(len(result['rigConstraints']), 8)

    def test_room_crossing_and_bridge_are_required(self):
        rows = frames()
        for row in rows:
            row['room'] = 'hall' if row['id'] < 4 else 'bedroom'
        result = build_pair_graph({'frames': rows, 'bridges': [{'from': 1, 'to': 7, 'reason': 'doorway'}]})
        required = {tuple((edge['image1'], edge['image2'])) for edge in result['candidateEdges'] if edge['required']}
        self.assertTrue({('cam0/3.jpg', 'cam0/4.jpg'), ('cam1/1.jpg', 'cam1/7.jpg')}.issubset(required))

    def test_failed_interval_expands_locally_and_keeps_eval_out(self):
        rows = frames()
        for row in rows:
            row['selected'] = row['id'] in {0, 7}
        rows[4]['split'] = 'eval'
        result = build_pair_graph({'frames': rows, 'failed_intervals': [{'start_seconds': 3, 'end_seconds': 4}]})
        self.assertEqual(result['anchorIds'], [0, 3, 7])
        self.assertEqual(result['expandedFrameIds'], ['3'])

    def test_explicit_bridge_cannot_leak_eval(self):
        rows = frames()
        rows[4]['split'] = 'eval'
        with self.assertRaisesRegex(ValueError, 'held-out'):
            build_pair_graph({'frames': rows, 'bridges': [{'from': 0, 'to': 4}]})

    def test_failure_expansion_never_restores_rejected_quality(self):
        rows = frames()
        for row in rows:
            row['selected'] = row['id'] in {0, 7}
        rows[3]['quality_action'] = 'reject'
        rows[4]['quality_action'] = 'review'
        manifest = {'frames': rows, 'failed_intervals': [{'start_seconds': 3, 'end_seconds': 5}]}
        graph = build_pair_graph(manifest)
        self.assertEqual(graph['anchorIds'], [0, 5, 7])
        self.assertEqual(graph['qualityExcludedFrameIds'], ['3', '4'])
        manifest['configuration'] = {'allow_unknown_quality_for_experiment': True}
        self.assertEqual(build_pair_graph(manifest)['anchorIds'], [0, 4, 5, 7])
        manifest['bridges'] = [{'from': 0, 'to': 3}]
        with self.assertRaisesRegex(ValueError, 'quality'):
            build_pair_graph(manifest)

    def test_protection_cannot_bypass_quality_rejection(self):
        rows = frames()
        rows[3].update(selected=False, protected=True, quality_action='reject')
        with self.assertRaisesRegex(ValueError, 'quality'):
            build_pair_graph({'frames': rows})

    def test_retrieval_uses_time_exclusion_and_budget(self):
        rows = frames()
        retrieval = [{'image1': 'cam0/0.jpg', 'image2': f'cam0/{i}.jpg', 'score': 10-i} for i in range(1, 8)]
        options = GraphOptions(local_neighbors=1, baseline_seconds=(), retrieval_budget_per_image=2,
                               retrieval_temporal_exclusion_seconds=3)
        graph = build_pair_graph({'frames': rows}, retrieval=retrieval, options=options)
        loops = [row for row in graph['candidateEdges'] if 'loop-retrieval' in row['reasons']]
        self.assertEqual({row['image2'] for row in loops}, {'cam0/3.jpg', 'cam0/4.jpg'})

    def test_cross_lens_requires_overlap_evidence(self):
        manifest = {'frames': frames()}
        retrieval = [{'image1': 'cam0/0.jpg', 'image2': 'cam1/7.jpg', 'score': 1}]
        graph = build_pair_graph(manifest, retrieval=retrieval)
        self.assertEqual(len(graph['rejectedCrossLensCandidates']), 1)
        retrieval[0]['geometric_overlap'] = True
        accepted = build_pair_graph(manifest, retrieval=retrieval)
        self.assertIn(('cam0/0.jpg', 'cam1/7.jpg'), edge_keys(accepted))
        self.assertIsNone(next(row['availableVerified'] for row in accepted['candidateEdges'] if row['crossLens']))

    def test_same_timestamp_overlap_is_separate_from_rig_constraint(self):
        manifest = {'frames': frames(), 'overlap_evidence': [
            {'image1': 'cam0/0.jpg', 'image2': 'cam1/0.jpg', 'geometric_overlap': True}]}
        graph = build_pair_graph(manifest)
        self.assertIn(('cam0/0.jpg', 'cam1/0.jpg'), edge_keys(graph))
        self.assertEqual(len(graph['rigConstraints']), 8)

    def test_cache_availability_reports_actual_disconnected_graph(self):
        graph = build_pair_graph({'frames': frames(4)}, verified_pairs=[('cam0/0.jpg', 'cam0/1.jpg')])
        self.assertEqual(len(graph['availableVerifiedEdges']), 1)
        self.assertEqual(len(graph['availableVerifiedRigComponents']), 3)
        self.assertTrue(graph['missingVerifiedEdges'])
        self.assertFalse(graph['sourceMatchingPerformed'])

    def test_provisional_position_only_proposes_a_revisit(self):
        rows = frames(5)
        for row in rows:
            row['position'] = [row['id'] * 10., 0., 0.]
        rows[4]['position'] = [.1, 0., 0.]
        graph = build_pair_graph({'frames': rows}, options=GraphOptions(local_neighbors=1, baseline_seconds=(), geometry_max_distance=.2))
        edge = next(row for row in graph['candidateEdges'] if row['image1'] == 'cam0/0.jpg' and row['image2'] == 'cam0/4.jpg')
        self.assertIn('provisional-position-revisit', edge['reasons'])
        self.assertAlmostEqual(edge['provisionalBaselineUnits'], .1)
        self.assertIsNone(edge['availableVerified'])

    def test_input_order_does_not_change_edges(self):
        manifest = {'frames': frames()}
        shuffled = copy.deepcopy(manifest)
        shuffled['frames'].reverse()
        self.assertEqual(build_pair_graph(manifest)['candidateEdges'], build_pair_graph(shuffled)['candidateEdges'])

    def test_incomplete_pair_duplicate_time_and_unknown_split_rejected(self):
        for mutation in ['lens', 'time', 'split']:
            rows = frames()
            if mutation == 'lens':
                del rows[0]['images']['cam1']
            elif mutation == 'time':
                rows[1]['time_seconds'] = rows[0]['time_seconds']
            else:
                rows[1]['split'] = 'validation'
            with self.assertRaises(ValueError):
                build_pair_graph({'frames': rows})


if __name__ == '__main__':
    unittest.main()
