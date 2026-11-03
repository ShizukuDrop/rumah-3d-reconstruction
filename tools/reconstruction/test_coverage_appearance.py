import unittest
import tempfile
from pathlib import Path

from tools.reconstruction.capture import sha256
from tools.reconstruction.coverage_appearance import CoverageAppearanceConfig, select_coverage_appearance, apply_scoped_reviews


def fixture(count=31):
    frames=[];quality={};faces=[]
    for index in range(count):
        split='eval' if index%10==9 else 'train'
        images={lens:f'{lens}/frame_{index:06d}_{split}.jpg' for lens in ('cam0','cam1')}
        frames.append({'id':index,'time_seconds':index/30,'split':split,'images':images})
        quality[str(index)]={'views':{lens:{'verdict':'sharp','confirmed':True,'training_eligible':True} for lens in images}}
        faces.extend({'sourceFrame':index,'sourceSplit':split,'sourceName':name} for name in images.values())
    return {'frames':frames},{'decisions':quality},{'views':faces},{'views':[]},[]


class CoverageAppearanceTests(unittest.TestCase):
    def test_dense_protected_coverage_and_temporal_floor_are_independent_of_old_subset(self):
        args=list(fixture());args[-1]=[{'name':'bathroom','source_frame_min':0,'source_frame_max':5}]
        result=select_coverage_appearance(*args)
        selected=[r for r in result['views'] if r['selected']]
        self.assertEqual(sum(r['frame_id']<=5 for r in selected),12)
        self.assertTrue(any(r['frame_id']>5 for r in selected))
        self.assertEqual(result['selected_eval_views'],0)
        self.assertTrue(all(r['split']=='train' for r in selected))
        self.assertFalse(result['training_ready'])
        for lens in ('cam0','cam1'):
            times=sorted(r['time_seconds'] for r in selected if r['lens']==lens)
            self.assertLessEqual(max(b-a for a,b in zip(times,times[1:])),.15+1e-8)

    def test_unknown_and_confirmed_blur_cannot_be_rescued_to_training(self):
        args=list(fixture());args[-1]=[{'name':'bathroom_second','source_frame_min':0,'source_frame_max':30}]
        for index in range(1,30):
            args[1]['decisions'][str(index)]['views']['cam0']={'verdict':'unknown','confirmed':False,'training_eligible':False}
        args[1]['decisions']['15']['views']['cam0']={'verdict':'blur','confirmed':True,'training_eligible':False}
        result=select_coverage_appearance(*args)
        self.assertEqual([r['frame_id'] for r in result['views'] if r['selected'] and r['lens']=='cam0'],[0,30])
        queue=result['review_queue'];self.assertTrue(queue)
        self.assertTrue(all(r['status']=='review_required' and not r['selected_for_training'] for r in queue))
        self.assertNotIn('cam0/frame_000015_train.jpg',[r['image'] for r in queue])
        self.assertTrue(any(r['region']=='bathroom_second' and r['lens']=='cam0' for r in result['unresolved_gaps']))

    def test_reference_absence_never_gets_old_pose_fallback(self):
        args=list(fixture());name='cam1/frame_000012_train.jpg'
        args[2]['views']=[r for r in args[2]['views'] if r['sourceName']!=name]
        args[3]['views']=[{'image':name,'split':'train','selected':True,'status':'eligible_pending_pose'}]
        result=select_coverage_appearance(*args)
        row=next(r for r in result['views'] if r['image']==name)
        self.assertFalse(row['selected']);self.assertFalse(row['reference_pose_available'])
        self.assertIn('missing_fixed_reference_pose',row['reasons'])

    def test_previous_passed_views_preserved_and_reference_identity_checked(self):
        args=list(fixture());name='cam0/frame_000003_train.jpg'
        args[3]['views']=[{'image':name,'split':'train','selected':True,'status':'eligible_pending_pose'}]
        result=select_coverage_appearance(*args)
        self.assertTrue(next(r for r in result['views'] if r['image']==name)['selected'])
        args[2]['views'][0]['sourceSplit']='eval'
        with self.assertRaisesRegex(ValueError,'identity'):
            select_coverage_appearance(*args)

    def test_missing_quality_decision_is_not_assumed_sharp(self):
        args=list(fixture());del args[1]['decisions']['4']
        with self.assertRaisesRegex(ValueError,'quality decision'):
            select_coverage_appearance(*args)

    def scoped_fixture(self, root):
        name='cam0/frame_000003_train.jpg';image=root/'images'/name;mask=(root/'masks'/name).with_suffix('.png')
        image.parent.mkdir(parents=True);mask.parent.mkdir(parents=True)
        image.write_bytes(b'exact inspected source');mask.write_bytes(b'exact inspected mask')
        quality={'3':{'views':{'cam0':{'verdict':'unknown','confirmed':False,'training_eligible':False}}}}
        evidence={'views':[{'image':name,'frame_id':3,'lens':'cam0','quality_status':'review_required',
            'source_image_sha256':sha256(image),'source_mask_sha256':sha256(mask)}]}
        review={'reviewer':'root','scope':'single_native_view','evidence_index_sha256':'a'*64,
            'approved_views':[{'image':name,'verdict':'sharp','mask_reviewed':True,
                'approved_for_isolated_appearance_experiment':True,'observation':'Static grout detail is distinguishable in both native crops.'}]}
        return quality,evidence,review,image,mask

    def test_scoped_approval_binds_exact_image_mask_and_does_not_modify_original_quality(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);q,e,r,image,mask=self.scoped_fixture(root)
            result=apply_scoped_reviews(q,root,r,e,index_sha256='a'*64)
            self.assertEqual(q['3']['views']['cam0']['verdict'],'unknown')
            self.assertTrue(result['3']['views']['cam0']['training_eligible'])
            mask.write_bytes(b'changed mask')
            with self.assertRaisesRegex(ValueError,'pixels or mask changed'):
                apply_scoped_reviews(q,root,r,e,index_sha256='a'*64)

    def test_blanket_or_incomplete_review_cannot_promote_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);q,e,r,_,_=self.scoped_fixture(root)
            r['scope']='whole_lens'
            with self.assertRaisesRegex(ValueError,'per-view'):
                apply_scoped_reviews(q,root,r,e,index_sha256='a'*64)
            r['scope']='single_native_view';r['approved_views'][0]['mask_reviewed']=False
            with self.assertRaisesRegex(ValueError,'mask review'):
                apply_scoped_reviews(q,root,r,e,index_sha256='a'*64)

    def test_confirmed_blur_cannot_use_unknown_promotion_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);q,e,r,_,_=self.scoped_fixture(root)
            q['3']['views']['cam0'].update(verdict='blur',confirmed=True)
            with self.assertRaisesRegex(ValueError,'Only unknown quality'):
                apply_scoped_reviews(q,root,r,e,index_sha256='a'*64)

    def test_mask_rejection_is_distinct_from_blur_and_removed_from_reproposal(self):
        args=list(fixture());args[-1]=[{'name':'bathroom','source_frame_min':0,'source_frame_max':30}]
        for index in range(1,30):
            args[1]['decisions'][str(index)]['views']['cam0']={'verdict':'unknown','confirmed':False,'training_eligible':False,
                'appearance_blocked':{'kind':'mask_rejection','reason':'Operator kept by mask'}}
        result=select_coverage_appearance(*args)
        row=next(r for r in result['coverage'] if r['region']=='bathroom' and r['lens']=='cam0')
        self.assertEqual(row['confirmed_blur_available'],0)
        self.assertGreater(row['mask_rejected_available'],0)
        self.assertFalse(any(r['lens']=='cam0' for r in result['review_queue']))


if __name__=='__main__':unittest.main()
