import unittest
import numpy as np
from .audit_localized_poses import pose_difference


class PoseAgreementTests(unittest.TestCase):
    def test_fixed_similarity_transforms_centers_and_camera_orientation(self):
        q=np.array([[0.,-1,0],[1,0,0],[0,0,1]]);t=np.array([3.,1,2]);scale=2.
        pose=np.eye(4);pose[:3,3]=[-1,-2,-3];center=-pose[:3,:3].T@pose[:3,3]
        similarity={'scale':scale,'rotation':q.tolist(),'translation':t.tolist()}
        reference={'center':scale*q@center+t,'R':pose[:3,:3]@q.T}
        result=pose_difference(pose,reference,similarity,10.)
        self.assertAlmostEqual(result['center_difference_reference_units'],0.)
        self.assertAlmostEqual(result['orientation_difference_degrees'],0.)
        reference['center']=reference['center']+np.array([1.,0,0])
        self.assertAlmostEqual(pose_difference(pose,reference,similarity,10.)['center_difference_fraction_trajectory_span'],.1)


if __name__=='__main__':unittest.main()
