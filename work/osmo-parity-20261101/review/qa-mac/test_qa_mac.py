"""Checks for prepare-qa.py's pixel-centre remap and score-qa.py's registered metrics. Run: .venv-geometry/bin/python -B test_qa_mac.py"""
from pathlib import Path
import importlib.util,unittest
import numpy as np,cv2
W=Path(__file__).resolve().parent.parent
def load(name):spec=importlib.util.spec_from_file_location(name.replace('-','_'),W/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
prepare,score=load('prepare-qa'),load('score-qa')

class QATests(unittest.TestCase):
    def test_reference_maps_match_the_shared_pinhole_convention(self):
        from seed_fisheye import Fisheye,pinhole_face_maps
        fish=Fisheye({'model':'OPENCV_FISHEYE','width':400,'height':400,'params':[120.,121.,199.3,201.1,.04,.02,-.01,.001]});face=cv2.Rodrigues(np.array([.3,-.5,.2]))[0]
        for got,want in zip(prepare.qa_maps(fish,face,96,96,48),pinhole_face_maps(fish,face,96)):np.testing.assert_array_equal(got,want)

    def test_registration_recovers_a_subpixel_shift_and_metrics_behave(self):
        rng=np.random.default_rng(0);gt=cv2.GaussianBlur(rng.uniform(0,255,(1080,1920,3)).astype('f4'),(0,0),2.5);gt=(gt-gt.min())/(gt.max()-gt.min())*255
        pr=cv2.warpAffine(gt,np.array([[1,0,1.625],[0,1,-.6875]],'f4'),(1920,1080),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)  # 1/32 px: warpAffine's exact grid
        box=(660,180,1260,780);x0,y0,x1,y1=box;mask=np.ones((600,600),bool);aligned,valid,ecc=score.align(gt,pr,box,mask);crop=gt[y0:y1,x0:x1]
        np.testing.assert_allclose(ecc['shiftPx'],[1.625,-.6875],atol=.06);self.assertIn(ecc['motion'],('translation','affine'))
        self.assertGreater(score.psnr(crop,aligned,valid),score.psnr(crop,pr[y0:y1,x0:x1],mask)+10)
        self.assertAlmostEqual(score.ssim(crop,crop,mask),1,places=6);self.assertGreater(score.ssim(crop,aligned,valid),score.ssim(crop,pr[y0:y1,x0:x1],mask))
        self.assertAlmostEqual(score.gradient(crop,mask)/score.gradient(crop,mask),1);self.assertLess(score.gradient(cv2.GaussianBlur(crop,(0,0),1.5),mask)/score.gradient(crop,mask),.8)

if __name__=='__main__':unittest.main()
