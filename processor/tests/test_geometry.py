import unittest
import numpy as np
from processor.pipeline import geometry, Composer, CalibrationRequired, matrix_for

class GeometryTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(42)
        background=rng.integers(0,256,(240,900,3),dtype=np.uint8)
        self.frames={3:background[:,:420],2:background[:,240:660],1:background[:,480:]}
        # Source coordinates and CAM 2 target coordinates for physical shared points.
        self.points={}
        for slot,shift in [(3,-240),(1,240)]:
            xs=(270,390) if slot==3 else (30,150)
            self.points[str(slot)]=[{'source':[x/420,y/240],'target':[(x+shift)/420,y/240]} for x,y in [(xs[0],30),(xs[1],30),(xs[0],200),(xs[1],200)]]
    def test_manual_stitch_has_order_and_consistent_pixels(self):
        H,masks,size,metrics=geometry(self.frames,{'points':self.points})
        self.assertTrue(890<=size[0]<=902)
        output=Composer(self.frames,H,masks,size).compose(self.frames)
        self.assertGreater(output.shape[1],850)
        self.assertEqual(output.shape[1]%2,0)
        self.assertLess(metrics['1']['median_error'],.01)
    def test_bad_points_are_rejected(self):
        with self.assertRaises(CalibrationRequired):
            matrix_for(self.frames[1],self.frames[2],[{'source':[.1,.1],'target':[.2,.1]}]*4)
    def test_blank_images_require_manual_calibration(self):
        with self.assertRaises(CalibrationRequired):matrix_for(np.zeros((240,420,3),np.uint8),np.zeros((240,420,3),np.uint8))

if __name__=='__main__':unittest.main()
