import copy
import unittest

from tools.reconstruction.pair_graph import GraphOptions, build_pair_graph
from tools.reconstruction.targeted_repair import prepare_repair


def fixture():
    selection = {'configuration': {'allow_unknown_quality_for_experiment': True}, 'frames': [
        {'id': i, 'time_seconds': i * .1, 'split': 'train', 'selected': i in (0, 9),
         'images': {'cam0': f'cam0/{i}.jpg', 'cam1': f'cam1/{i}.jpg'},
         'quality_action': 'keep'} for i in range(10)]}
    quality = {str(i): {'action': 'keep', 'views': {
        lens: {'width_ratio': 1., 'verdict': 'sharp', 'confirmed': True}
        for lens in ('cam0', 'cam1')}} for i in range(10)}
    graph = build_pair_graph(selection, options=GraphOptions(local_neighbors=1, baseline_seconds=()))
    return selection, quality, graph


class RepairTests(unittest.TestCase):
    def test_preserves_edges_and_quality_not_mutating_parent(self):
        selection, quality, graph = fixture()
        before = copy.deepcopy((selection, quality, graph))
        selection2, graph2, report = prepare_repair(selection, quality, graph, intervals=((1, 8),), bin_frames=3)
        self.assertEqual((selection, quality, graph), before)
        keys = lambda g: {(e['image1'], e['image2']) for e in g['candidateEdges']}
        self.assertTrue(keys(graph) <= keys(graph2))
        self.assertEqual(report['addedAnchors'], 3)
        self.assertFalse(selection2['acceptance_passed'])
        self.assertTrue(all(e['availableVerified'] is None for e in graph2['candidateEdges']))

    def test_rejected_eval_and_confirmed_blur_cannot_be_rescued(self):
        selection, quality, graph = fixture()
        selection['frames'][1]['split'] = 'eval'
        selection['frames'][2]['quality_action'] = 'reject'
        quality['2']['action'] = 'reject'
        quality['3']['views']['cam0']['verdict'] = 'blur'
        repaired, _, report = prepare_repair(selection, quality, graph, intervals=((1, 8),), bin_frames=1)
        added = repaired['repair']['addedFrameIds']
        self.assertFalse({1, 2, 3} & set(added))
        self.assertEqual(report['evaluationFramesAdded'], 0)

    def test_keep_preferred_over_review_and_review_stays_pending(self):
        selection, quality, graph = fixture()
        for i in (1, 3, 4):
            selection['frames'][i]['quality_action'] = quality[str(i)]['action'] = 'review'
            for view in quality[str(i)]['views'].values():
                view.update(width_ratio=.5, confirmed=False, verdict='unknown')
        repaired, _, report = prepare_repair(selection, quality, graph, intervals=((1, 4),), bin_frames=2)
        self.assertEqual(repaired['repair']['addedFrameIds'], [2, 3])
        self.assertTrue(repaired['frames'][3]['requires_quality_review'])
        self.assertEqual(report['addedReviewPending'], 1)

    def test_pair_ranking_uses_worst_lens(self):
        selection, quality, graph = fixture()
        quality['1']['views']['cam0']['width_ratio'] = .5
        quality['1']['views']['cam1']['width_ratio'] = 1.4
        repaired, _, _ = prepare_repair(selection, quality, graph, intervals=((1, 2),), bin_frames=2)
        self.assertEqual(repaired['repair']['addedFrameIds'], [2])

    def test_cached_parent_verification_is_not_relabelled_as_fresh(self):
        selection, quality, graph = fixture()
        for edge in graph['candidateEdges']:
            edge['availableVerified'] = True
        graph['availableVerifiedEdges'] = copy.deepcopy(graph['candidateEdges'])
        graph['verifiedCacheProvided'] = True
        _, repaired_graph, _ = prepare_repair(selection, quality, graph, intervals=((1, 8),))
        self.assertFalse(repaired_graph['verifiedCacheProvided'])
        self.assertEqual(repaired_graph['availableVerifiedEdges'], [])
        self.assertTrue(all(edge['availableVerified'] is None for edge in repaired_graph['candidateEdges']))

    def test_unknown_quality_needs_explicit_experiment_opt_in(self):
        selection, quality, graph = fixture()
        selection['configuration']['allow_unknown_quality_for_experiment'] = False
        selection['frames'][1]['quality_action'] = quality['1']['action'] = 'review'
        repaired, _, _ = prepare_repair(selection, quality, graph, intervals=((1, 2),), bin_frames=1)
        self.assertEqual(repaired['repair']['addedFrameIds'], [2])

    def test_mismatched_parent_and_quality_are_rejected(self):
        selection, quality, graph = fixture()
        graph['anchorIds'].append(4)
        with self.assertRaisesRegex(ValueError, 'same anchors'):
            prepare_repair(selection, quality, graph, intervals=((1, 8),))
        graph['anchorIds'].pop()
        quality['1']['action'] = 'reject'
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            prepare_repair(selection, quality, graph, intervals=((1, 8),))


if __name__ == '__main__':
    unittest.main()
