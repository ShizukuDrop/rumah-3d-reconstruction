import unittest
import numpy as np
from .motion import fisheye_bearings, robust_rotation


class MotionTests(unittest.TestCase):
    def test_fisheye_keeps_backwards_rays(self):
        camera={'model':'opencv-fisheye','params':[1000,1000,1920,1920,0,0,0,0]}
        rays,valid=fisheye_bearings([[1920,1920],[1920+1800,1920]],camera)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(rays[0],[0,0,1],atol=1e-8)
        self.assertLess(rays[1,2],0)
        np.testing.assert_allclose(np.linalg.norm(rays,axis=1),1,atol=1e-9)

    def test_rotation_is_not_translation(self):
        rng=np.random.default_rng(84)
        rays=rng.normal(size=(100,3));rays/=np.linalg.norm(rays,axis=1)[:,None]
        angle=.2
        expected=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
        rotation,residual,_=robust_rotation(rays,rays@expected.T)
        np.testing.assert_allclose(rotation,expected,atol=1e-8)
        self.assertLess(np.percentile(residual,75),1e-5)

    def test_translation_with_depth_variation_has_residual(self):
        rng=np.random.default_rng(81)
        points=rng.uniform([-2,-1,2],[2,1,8],size=(200,3))
        a=points/np.linalg.norm(points,axis=1)[:,None]
        other=points-[.3,0,0];b=other/np.linalg.norm(other,axis=1)[:,None]
        _,residual,_=robust_rotation(a,b)
        self.assertGreater(np.percentile(residual,75),.2)


if __name__=='__main__':unittest.main()
