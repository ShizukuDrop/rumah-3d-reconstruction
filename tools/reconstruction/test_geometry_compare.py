import unittest
import numpy as np
from .geometry_compare import similarity, compare


class GeometryComparisonTests(unittest.TestCase):
    def test_world_axes_and_scale_do_not_create_pose_error(self):
        points = np.array([[0,0,0],[1,0,0],[0,2,0],[0,0,3]],float)
        Q = np.array([[0,-1,0],[1,0,0],[0,0,1.]])
        scale,t = 2.3,np.array([4,-2,5])
        reference,candidate,frames = {},{},[]
        for i,p in enumerate(points):
            names={lens:f'{lens}/frame_{i:06d}_train.jpg' for lens in ['cam0','cam1']}
            for name in names.values():
                candidate[name]={'center':p,'R':np.eye(3)}
                reference[name]={'center':scale*Q@p+t,'R':Q.T}
            frames.append({'id':i,'selected':True,'images':names})
        out=compare(reference,candidate,{'frames':frames},[{'name':'room','source_frame_min':0,'source_frame_max':3}])
        self.assertLess(out['center_difference_reference_units']['p100'],1e-12)
        self.assertLess(out['orientation_difference_degrees']['p100'],1e-5)
        self.assertEqual(out['coverage'][0]['registered_complete_selected_pairs'],4)
        self.assertFalse(out['reference_is_ground_truth'])

    def test_collinear_fit_is_not_claimed_determined(self):
        with self.assertRaises(ValueError):similarity([[0,0,0],[1,0,0],[2,0,0]],[[0,0,0],[2,0,0],[4,0,0]])


if __name__ == '__main__':unittest.main()
