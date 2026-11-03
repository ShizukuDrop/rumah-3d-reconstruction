import unittest
from .selection import SelectionConfig, choose_frames, apply_manual_review


def capture(n=10):
    return {'fps':10,'source_selection_sha256':'test','frames':[
        {'id':i,'time_seconds':i/10,'split':'train','images':{'cam0':f'a/{i}.jpg','cam1':f'b/{i}.jpg'}} for i in range(n)]}


def good_quality(n=10):
    return {i:{'action':'keep','training_eligible':{'cam0':True,'cam1':True}} for i in range(n)}


def low_motion(a,b):
    return {'reference_frame':a['id'],'frame':b['id'],'lenses':{k:{'status':'measured','parallax_deg_p75':0,
                  'rotation_deg':0,'track_survival':1} for k in ('cam0','cam1')}}


class SelectionTests(unittest.TestCase):
    def test_confirmed_blur_is_not_rescued_for_gap(self):
        quality=good_quality()
        for i in range(1,9):quality[i]={'action':'reject','training_eligible':{'cam0':False,'cam1':True}}
        result=choose_frames(capture(),quality,low_motion)
        self.assertEqual([f['id'] for f in result['frames'] if f['selected']],[0,9])
        self.assertTrue(result['unresolved_gaps'])
        self.assertFalse(result['acceptance_passed'])
        self.assertTrue(result['frames'][5]['training']['cam1'])
        self.assertFalse(result['frames'][5]['training']['cam0'])

    def test_opposite_lens_motion_preserves_anchor(self):
        def movement(a,b):
            result=low_motion(a,b);result['lenses']['cam1']['parallax_deg_p75']=5
            return result
        result=choose_frames(capture(3),good_quality(3),movement)
        self.assertTrue(result['frames'][1]['selected'])
        self.assertIn('cam1:parallax',result['frames'][1]['alignment_reasons'])

    def test_holdout_remains_excluded(self):
        data=capture();data['frames'][0]['split']='eval'
        result=choose_frames(data,good_quality(),low_motion)
        self.assertFalse(result['frames'][0]['selected'])
        self.assertFalse(any(result['frames'][0]['training'].values()))

    def test_uncertain_experiment_never_passes_acceptance(self):
        quality=good_quality();quality[0]['action']='review'
        result=choose_frames(capture(),quality,low_motion,SelectionConfig(allow_unknown_quality_for_experiment=True))
        self.assertTrue(result['frames'][0]['selected'])
        self.assertFalse(result['acceptance_passed'])

    def test_clear_manual_label_cannot_erase_confirmed_blur(self):
        decision={'action':'reject','views':{k:{'verdict':'blur' if k=='cam0' else 'sharp',
                       'confirmed':True,'training_eligible':k!='cam0'} for k in ('cam0','cam1')}}
        label={'1:cam0':{'verdict':'sharp','reason':'test','evidence':'image'}}
        result=apply_manual_review(decision,label,1)
        self.assertEqual(result['action'],'reject')

    def test_missing_terminal_coverage_is_reported(self):
        quality=good_quality()
        for i in range(1,10):quality[i]['action']='reject'
        result=choose_frames(capture(),quality,low_motion)
        self.assertEqual(result['unresolved_gaps'][0]['boundary'],'end')


if __name__=='__main__':unittest.main()
