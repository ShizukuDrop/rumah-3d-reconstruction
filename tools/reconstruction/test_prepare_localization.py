import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import numpy as np

from tools.reconstruction.localization import file_hash,load_request
from tools.reconstruction.prepare_localization import prepare_requests


def make_fixture(root,ambiguous=False,bad_track=False,compact=False):
    dataset=root/'capture';features=root/'features';workspace=root/'fresh/sfm';model=workspace/'sparse/0';model.mkdir(parents=True)
    xy=np.array([[100+40*(i%4),100+50*(i//4)] for i in range(12)],dtype='float32')
    names=[f'{lens}/frame_{i:06d}_{"eval" if i==29 else "train"}.jpg' for lens in ('cam0','cam1') for i in (0,1,29)]
    records=[]
    for i in (0,1,29):records.append(dict(source_frame=i,time_seconds=i/30,filename=f'frame_{i:06d}_{"eval" if i==29 else "train"}.jpg',split='eval' if i==29 else 'train'))
    for name in names:
        image=dataset/'images'/name;mask=(dataset/'masks'/name).with_suffix('.png');feature=(features/name).with_suffix('.bin')
        for path in (image,mask,feature):path.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(('source '+name).encode());mask.write_bytes(b'mask')
        keypoints=np.column_stack([xy,np.zeros((12,2))]).astype('<f4')
        binary=b'VKFT'+struct.pack('<6I',6,800,800,12,128,1)+keypoints.tobytes()+np.zeros((12,128),'<f4').tobytes()
        binary+=b'\0'+struct.pack('<dI',0,0)+struct.pack('<II',800,800)+b'\1'+np.ones(12,'<f4').tobytes()+b'\1';feature.write_bytes(binary)
    selection=dataset/'analysis/frame-selection.json';selection.parent.mkdir(parents=True);selection.write_text(json.dumps(dict(fps_numerator=30,fps_denominator=1,selected=records)))
    camera_spec={'model':'opencv-fisheye','width':800,'height':800,'params':[300,300,400,400,0,0,0,0]}
    (dataset/'sfm-manifest-native3840.json').write_text(json.dumps({'cameras':[{'prefix':lens,**camera_spec} for lens in ('cam0','cam1')]}))
    cameras=bytearray(struct.pack('<Q',2))
    for ident in (11,22):cameras+=struct.pack('<iiQQ8d',ident,5,800,800,*camera_spec['params'])
    (model/'cameras.bin').write_bytes(cameras)
    images=bytearray(struct.pack('<Q',2));anchor_names=[names[0],names[3]]
    for j,(image_id,name,camera_id) in enumerate(zip((57,83),anchor_names,(11,22))):
        q=[1,0,0,0] if j==0 else [0,0,1,0];t=[0,0,0] if j==0 else [0,0,-.01]
        points=xy[:-1] if compact else xy
        images+=struct.pack('<i7di',image_id,*q,*t,camera_id)+name.encode()+b'\0'+struct.pack('<Q',len(points))
        for i,p in enumerate(points):images+=struct.pack('<ddq',*p,1000+i)
    (model/'images.bin').write_bytes(images)
    points=bytearray(struct.pack('<Q',12))
    for i in range(12):
        points+=struct.pack('<Q3d3BdQ',1000+i,i*.1,0,3.,120,120,120,.1,2)
        points+=struct.pack('<iiii',57,i,83,(i+1)%12 if bad_track and i==0 else i)
    (model/'points3D.bin').write_bytes(points)
    (model/'rigs.txt').write_text("# Rig calibration cam_from_rig, in this model's units.\nrig cam0 cam0 1 0 0 0 0 0 0 0 0\nrig cam1 cam0 0 0 1 0 0 0 -0.01 0 0\n")
    staging={'status':'complete','featureCompactionPerformed':False,'resumeOldMapAllowed':False,'requiredAutoFlags':['--no-compact-unused-features'],
             'workspace':str(workspace),'sourceFeatureRoot':str(features),'images':[]}
    for j,name in enumerate(anchor_names):
        feature=(features/name).with_suffix('.bin');staging['images'].append({'name':name,'newImageId':j,'originalImageId':j*3,'feature':{'sha256':file_hash(feature)}})
    staging_path=root/'staging.json';staging_path.write_text(json.dumps(staging))
    raw=bytearray(b'VKMT'+struct.pack('<II',4,6))
    for name in names:
        stem=str(Path(name).with_suffix('')).replace('\\','/');raw+=struct.pack('<I',len(stem))+stem.encode()+struct.pack('<I',12)
    pairs=[(1,0,[(i,i) for i in range(12)]),(2,0,[(i,i) for i in range(12)]),(4,3,[(i,i) for i in range(12)]),(5,3,[(i,i) for i in range(12)])]
    if ambiguous:pairs.append((1,3,[(0,1)]))
    raw+=struct.pack('<I',len(pairs))
    for a,b,matches in pairs:
        raw+=struct.pack('<IIiI',a,b,2,len(matches))
        for pair in matches:raw+=struct.pack('<II',*pair)
    raw+=struct.pack('<I',0);cache=root/'matches.bin';cache.write_bytes(raw)
    views=[]
    for r in records:
        for lens in ('cam0','cam1'):
            selected=r['source_frame'] in (0,1)
            views.append({'frame_id':r['source_frame'],'time_seconds':r['time_seconds'],'split':r['split'],'lens':lens,'image':f'{lens}/{r["filename"]}',
                          'selected':selected,'status':'eligible_pending_pose' if selected else 'excluded'})
    query=root/'views.json';query.write_text(json.dumps({'source_selection_sha256':file_hash(selection),'views':views}))
    return {'anchor_model':model,'staging_provenance':staging_path,'feature_root':features,'matches':cache,'queries':query,'dataset':dataset,'output':root/'out'}


class PrepareLocalizationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_actual_binary_ids_feature_rows_and_shared_points(self):
        args=make_fixture(self.root);before={name:file_hash(args['anchor_model']/name) for name in ('images.bin','points3D.bin')}
        result=prepare_requests(**args)
        self.assertEqual(result['request_count'],2);self.assertEqual(result['shared_anchor_points'],12)
        self.assertEqual(result['skipped_registered_anchor_frames'],1)
        self.assertEqual([r['anchor_colmap_image_id'] for r in result['image_id_mapping']],[57,83])
        self.assertEqual([r['source_cache_image_id'] for r in result['image_id_mapping']],[0,3])
        self.assertEqual(before,{name:file_hash(args['anchor_model']/name) for name in before})
        for frame,split in ((1,'train'),(29,'eval')):
            request,xy,xyz,ci,fi,pi=load_request(args['output']/'requests'/f'frame-{frame:06d}.json')
            self.assertEqual(request['queries'][0]['split'],split);self.assertEqual(len(xy),24)
            self.assertTrue(all(q['ready_for_training'] is False for q in request['queries']))
            if split=='eval':self.assertTrue(all(q['requested_for_training'] is False for q in request['queries']))
        self.assertEqual(len(list(args['output'].glob('anchors.npz'))),1)

    def test_ambiguous_query_assignment_is_removed_not_voted_into_a_pose(self):
        args=make_fixture(self.root,ambiguous=True);result=prepare_requests(**args,min_correspondences=6,min_per_camera=3)
        row=next(r for r in result['queries'] if r['frame_id']==1)
        self.assertEqual(row['ambiguous_query_features_removed'],1)
        request,xy,xyz,ci,fi,pi=load_request(args['output']/row['request'])
        self.assertFalse(np.any((ci==0)&(fi==0)));self.assertEqual(len(xy),23)

    def test_compacted_features_are_rejected(self):
        args=make_fixture(self.root,compact=True)
        with self.assertRaisesRegex(ValueError,'compaction'):prepare_requests(**args)

    def test_point_tracks_must_confirm_fresh_image_identity(self):
        args=make_fixture(self.root,bad_track=True)
        with self.assertRaisesRegex(ValueError,'track'):prepare_requests(**args)
        self.assertEqual(list((args['output']/'requests').glob('*.json')),[])

    def test_missing_rig_never_uses_factory_calibration(self):
        args=make_fixture(self.root);(args['anchor_model']/'rigs.txt').write_text('unknown convention')
        with self.assertRaisesRegex(ValueError,'rig export convention'):prepare_requests(**args)

    def test_unverified_cache_records_are_not_silently_used(self):
        args=make_fixture(self.root)
        from tools.reconstruction.match_cache import read_index
        cache=read_index(args['matches']);data=bytearray(args['matches'].read_bytes())
        for row in cache.pairs:struct.pack_into('<i',data,row.offset-8,0)
        args['matches'].write_bytes(data)
        result=prepare_requests(**args)
        self.assertEqual(result['request_count'],0)
        self.assertTrue(all(r['status']=='insufficient_unambiguous_correspondences' for r in result['queries']))

    def test_changing_model_does_not_publish_requests(self):
        args=make_fixture(self.root)
        from tools.reconstruction.prepare_localization import read_needed_points
        def mutate(*a,**kw):
            result=read_needed_points(*a,**kw)
            with (args['anchor_model']/'images.bin').open('ab') as f:f.write(b'x')
            return result
        with mock.patch('tools.reconstruction.prepare_localization.read_needed_points',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'changed during preparation'):prepare_requests(**args)
        self.assertEqual(list((args['output']/'requests').glob('*.json')),[])

    def test_interrupted_preparation_report_blocks_request_use(self):
        args=make_fixture(self.root);prepare_requests(**args)
        report=args['output']/'preparation.json';data=json.loads(report.read_text());data['status']='preparing';report.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'incomplete'):load_request(args['output']/'requests/frame-000001.json')

    def test_fresh_cache_can_reindex_image_table_by_name(self):
        args=make_fixture(self.root)
        from tools.reconstruction.match_cache import read_index
        cache=read_index(args['matches']);source=args['matches'].read_bytes()
        raw=bytearray(b'VKMT'+struct.pack('<II',4,len(cache.images)))
        for image in reversed(cache.images):
            encoded=image.name.encode();raw+=struct.pack('<I',len(encoded))+encoded+struct.pack('<I',image.num_features)
        raw+=struct.pack('<I',len(cache.pairs))
        for pair in cache.pairs:
            raw+=struct.pack('<IIiI',5-pair.image1,5-pair.image2,pair.config,pair.count)
            raw+=source[pair.offset:pair.offset+pair.count*8]
        raw+=struct.pack('<I',0);args['matches'].write_bytes(raw)
        result=prepare_requests(**args)
        self.assertEqual([row['source_cache_image_id'] for row in result['image_id_mapping']],[5,2])
        self.assertEqual([row['staged_original_cache_image_id'] for row in result['image_id_mapping']],[0,3])
        self.assertEqual(result['request_count'],2)


if __name__=='__main__':unittest.main()
