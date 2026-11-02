import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import contextlib
import io
import json
import numpy as np

spec=importlib.util.spec_from_file_location('seed_fisheye',Path(__file__).with_name('seed_fisheye.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)

def camera(width=400,height=400):
    return {'id':1,'model':'OPENCV_FISHEYE','model_id':5,'width':width,'height':height,
            'params':np.array([100.,100.,width/2,height/2,.01,-.002,.0001,0.])}

class SeedGeometryChecks(unittest.TestCase):
    def test_fisheye_projection_inverts_rays_past_ninety_degrees(self):
        model=s.Fisheye(camera())
        angles=np.radians([0,25,60,89,95,102]);rays=np.column_stack([np.sin(angles),np.zeros(len(angles)),np.cos(angles)])
        xy,ok=model.project(rays);back,back_ok=model.unproject(xy)
        self.assertTrue(ok.all() and back_ok.all())
        np.testing.assert_allclose(back,rays,atol=1e-8)
        self.assertLess(back[-1,2],0,'>180-degree full-FOV rays must preserve negative camera Z')
        self.assertTrue(np.all(np.diff(xy[:,0])>0))

    def test_scaled_intrinsics_and_half_pixel_resampling_agree(self):
        full=s.Fisheye(camera());small=s.Fisheye(camera(),100,100)
        xy=np.array([[200.5,200.5],[250.5,180.5],[380.5,200.5]])
        a,ok=full.unproject(xy);b,okb=small.unproject(xy/4)
        np.testing.assert_allclose(a,b,atol=1e-12);self.assertTrue(ok.all() and okb.all())
        values=np.arange(16,dtype=np.float32).reshape(4,4)
        np.testing.assert_equal(s.sample_map(values,np.array([[.5,.5],[3.5,3.5],[1.5,2.5]])),[0,15,9])

    def test_pinhole_face_rgb_matches_its_written_camera_model(self):
        # Ramp images hold each source pixel's continuous coordinate, so the resampled
        # face must read back model.project() wherever the PINHOLE model puts a ray.
        model=s.Fisheye(camera());size=256;f=size/2;cv2=s.cv2
        face=np.array([[0,0,-1],[0,1,0],[1,0,0]],float)
        mx,my,valid=s.pinhole_face_maps(model,face,size);self.assertGreater(valid.mean(),.3)
        ramp=np.meshgrid(np.arange(model.width,dtype=np.float32)+.5,np.arange(model.height,dtype=np.float32)+.5)
        faced=[cv2.remap(r,mx,my,cv2.INTER_LINEAR) for r in ramp]
        rng=np.random.default_rng(3);q=np.column_stack([rng.uniform(-.8,.8,(200,2)),np.ones(200)])
        pixel=q[:,:2]*f+f;native,ok=model.project(q@face);ok&=valid[pixel[:,1].astype(int),pixel[:,0].astype(int)]
        read=np.column_stack([s.sample_map(img,pixel) for img in faced])
        # cv2.remap quantizes to 1/32 px; the convention bug this guards against is ~0.5 px.
        np.testing.assert_allclose(read[ok],native[ok],atol=.08)

    def test_voxel_reduce_reports_the_voxel_it_used_when_growth_does_not_converge(self):
        p=np.array([[0,0,0],[1000,0,0.]]);one=np.ones((2,3))
        xyz,_,_,size=s.voxel_reduce(p,one,one,np.ones(2),.001,1)
        self.assertEqual(len(xyz),1);self.assertAlmostEqual(size,.001*(2**(1/3)*1.02)**14,places=12)
        self.assertEqual(len(np.unique(np.floor(p/size),axis=0)),2,'the last unique() at this size still kept both points')
        xyz,_,_,size=s.voxel_reduce(np.random.default_rng(1).random((500,3)),np.ones((500,3)),np.ones((500,3)),np.ones(500),.01,50)
        self.assertLessEqual(len(np.unique(np.floor(xyz/size),axis=0)),50);self.assertEqual(len(xyz),len(np.unique(np.floor(xyz/size),axis=0)))

    def test_affine_uses_euclidean_range_and_rejects_bad_fits(self):
        rng=np.random.default_rng(8);x=rng.uniform(.5,7,800);y=1.4*x+.7+rng.normal(0,.015,800)
        bad=rng.choice(800,80,replace=False);y[bad]*=rng.uniform(1.5,2.2,len(bad))
        fit=s.robust_affine_ray_fit(x,y)
        self.assertAlmostEqual(fit['scale'],1.4,delta=.02);self.assertAlmostEqual(fit['offset'],.7,delta=.03)
        self.assertGreater(fit['inlier_fraction'],.85)
        with self.assertRaises(ValueError):s.robust_affine_ray_fit(np.ones(60),np.ones(60))
        with self.assertRaises(ValueError):s.robust_affine_ray_fit(x,8-x)

    def test_standard_binary_id_five_reads_eight_params_and_signed_missing_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);cam=camera()
            with (p/'cameras.bin').open('wb') as f:
                f.write(struct.pack('<Q',2))
                for cid in [1,2]:f.write(struct.pack('<iiQQ8d',cid,5,400,400,*cam['params']))
            with (p/'images.bin').open('wb') as f:
                f.write(struct.pack('<Q',1));f.write(struct.pack('<i4d3di',1,1,0,0,0,0,0,0,1));f.write(b'cam0/frame_000001.jpg\0')
                f.write(struct.pack('<Qddqddq',2,200.5,200.5,7,120.5,100.5,-1))
            with (p/'points3D.bin').open('wb') as f:
                f.write(struct.pack('<QQ3d3BdQii',1,7,0,0,4,20,30,40,.2,1,1,0))
            cameras,images,points=s.read_model(p)
            self.assertEqual(len(cameras),2);self.assertEqual(cameras[2]['model'],'OPENCV_FISHEYE')
            self.assertEqual(len(cameras[2]['params']),8);self.assertEqual(images[1]['point3D_ids'].tolist(),[7,-1])
            self.assertEqual(points[7]['image_ids'].tolist(),[1])
            out=p/'text';s.write_model_text(out,cameras,images,points)
            c2,i2,p2=s.read_model(out);np.testing.assert_equal(c2[2]['params'],cameras[2]['params'])
            np.testing.assert_equal(i2[1]['point3D_ids'],images[1]['point3D_ids'])
            np.testing.assert_equal(p2[7]['rgb'],points[7]['rgb'])
            with self.assertRaises(FileExistsError):s.write_model_text(p,cameras,images,points)

    def test_temporal_test_compares_ray_distances_not_z_values(self):
        c=camera(200,200);c['params']=np.array([70.,70.,100.,100.,0,0,0,0]);model=s.Fisheye(c)
        yy,xx=np.meshgrid(np.arange(200)+.5,np.arange(200)+.5,indexing='ij');ray,valid=model.unproject(np.stack([xx,yy],axis=-1))
        valid&=ray[:,:,2]>.2;depth=(3/np.maximum(ray[:,:,2],1e-6)).astype(np.float32)
        neighbor={'R':np.eye(3),'t':np.array([-.15,0,0]),'model':model,'depth':depth,'valid':valid}
        world=np.array([[0,0,3],[.5,.2,3],[-2,.5,3]],dtype=float)
        self.assertTrue(s.temporal_agreement(world,neighbor).all())
        neighbor['depth']=np.full_like(depth,3.)
        result=s.temporal_agreement(world,neighbor)
        self.assertTrue(result[0]);self.assertFalse(result[-1],'Oblique rays must not compare against constant Z-depth')

    def test_uint16_depth_maps_are_millimetres_without_input_changes(self):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'depth.png';raw=np.array([[0,1500],[3200,65535]],np.uint16);cv2.imwrite(str(p),raw)
            depth,valid=s.load_depth(p)
            np.testing.assert_allclose(depth[0,1],1.5);np.testing.assert_allclose(depth[1,0],3.2)
            np.testing.assert_equal(valid,[[False,True],[True,False]])
            np.testing.assert_equal(cv2.imread(str(p),cv2.IMREAD_UNCHANGED),raw)

    def test_end_to_end_translated_fisheye_views_recover_a_flat_plane(self):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            dataset=Path(tmp)/'dataset'
            for leaf in ['images/cam0','depths/cam0','masks/cam0','normals/cam0']:(dataset/leaf).mkdir(parents=True)
            c=camera(128,128);c['params']=np.array([50.,50.,64.,64.,0,0,0,0]);model=s.Fisheye(c)
            yy,xx=np.meshgrid(np.arange(128)+.5,np.arange(128)+.5,indexing='ij')
            rays,valid=model.unproject(np.stack([xx,yy],axis=-1));valid&=rays[:,:,2]>.3
            depth=np.where(valid,3/np.maximum(rays[:,:,2],1e-5)*1000,0).astype(np.uint16)
            world=np.array([[x,y,3.] for x in np.linspace(-2,2,16) for y in np.linspace(-1,1,12)])
            images={};points={}
            for iid in range(1,7):
                name=f'cam0/frame_{iid:06}.jpg';t=np.array([-.12*(iid-1),0.,0.]);xy,ok=model.project(world+t)
                images[iid]={'id':iid,'qvec':np.array([1.,0,0,0]),'tvec':t,'camera_id':1,'name':name,
                             'points2D_xy':xy,'point3D_ids':np.arange(1,len(world)+1,dtype=np.int64)}
                cv2.imwrite(str(dataset/'images'/name),np.full((128,128,3),128,np.uint8))
                cv2.imwrite(str((dataset/'depths'/name).with_suffix('.png')),depth)
                cv2.imwrite(str((dataset/'masks'/name).with_suffix('.png')),valid.astype(np.uint8)*255)
            for pid,p in enumerate(world,1):
                points[pid]={'xyz':p,'rgb':np.array([128,128,128],np.uint8),'error':.01,'image_ids':np.arange(1,7),
                             'point2D_idxs':np.full(6,pid-1,dtype=np.int32)}
            s.write_model_text(dataset/'sparse/0',{1:c},images,points)
            with contextlib.redirect_stdout(io.StringIO()):
                result=s.main(['--dataset',str(dataset),'--max-points','2000','--max-candidates','5000'])
            self.assertEqual(result,0)
            report=json.loads((dataset.parent/'analysis/seed-fisheye.json').read_text())
            self.assertEqual(report['accepted_fit_frames'],6);self.assertLessEqual(report['output_points'],2000)
            with (dataset/'seed.ply').open('rb') as f:
                while f.readline().strip()!=b'end_header':pass
                values=np.frombuffer(f.read(),dtype=np.dtype([('p','<f4',(3,)),('n','<f4',(3,)),('rgb','u1',(3,))]))
            self.assertGreater(len(values),500)
            np.testing.assert_allclose(values['p'][:,2],3,atol=.015)
            self.assertGreater(np.mean(values['n'][:,2]<-.98),.98)

if __name__=='__main__':unittest.main()
