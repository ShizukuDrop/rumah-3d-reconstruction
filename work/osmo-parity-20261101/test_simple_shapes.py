"""Self-check for simple_shapes.py helpers; no model file needed."""
import unittest
import numpy as np
import simple_shapes as s

class SimpleShapes(unittest.TestCase):
    def test_rectangles_cover_an_l_shaped_floor_exactly(self):
        mask=np.zeros((10,10),bool);mask[:,:4]=True;mask[6:,:]=True
        rects=s.largest_rectangles(mask,1);cover=np.zeros_like(mask)
        for r0,c0,r1,c1 in rects:
            self.assertFalse(cover[r0:r1,c0:c1].any(),'rectangles must not overlap');cover[r0:r1,c0:c1]=True
        self.assertTrue((cover==mask).all());self.assertEqual(len(rects),2)
    def test_small_leftovers_are_not_covered(self):
        mask=np.zeros((8,8),bool);mask[:4,:4]=True;mask[7,7]=True
        self.assertEqual(s.largest_rectangles(mask,2),[(0,0,4,4)])
    def test_short_steps_straighten_and_long_ones_stay(self):
        mask=np.zeros((20,20),bool);mask[2:18,2:12]=True;mask[2:4,12]=True  # 1-cell step along 2 cells of the edge
        out=s.straighten(mask,2);self.assertFalse(out[:,12].any());self.assertTrue(out[2:18,2:12].all())
        mask[2:4,12]=False;mask[2:10,12:15]=True  # a 3-cell step is a real jog
        self.assertTrue((s.straighten(mask,2)==mask).all())
    def test_colours_are_clamped_hex(self):
        self.assertEqual(s.hexcolor([1.2,.5,-.1]),'#ff8000')

if __name__=='__main__':unittest.main()
