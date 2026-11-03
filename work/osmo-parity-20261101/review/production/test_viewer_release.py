"""Synthetic release authorization checks; no model downloads, SSH or deployment."""
from pathlib import Path
import copy,hashlib,importlib.util,io,json,os,subprocess,tarfile,tempfile,unittest,urllib.error
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('viewer_deploy',HERE/'prepare-deploy.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
spec=importlib.util.spec_from_file_location('viewer_public',HERE/'verify-public-native.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class ViewerRelease(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.here=Path(self.tmp.name).resolve()/'review/production';self.here.mkdir(parents=True)
        self.baseline=d.VIEWER_BASELINE;self.release='20261103-osmo-viewer-v2'
        self.required=['viewerQuotaAndErrorsPassed','viewerControlsPassed','zeroModelBytesBeforeOpen','iphoneHashesPreserved','totalModelDownloadWithin50MB','reversibleShellPassed']
        asset={'url':'models/osmo-native-'+self.baseline['sha256'][:10]+'.sog','representation':'gaussian','format':'sog','fileBytes':self.baseline['bytes'],'downloadBytes':self.baseline['bytes'],'splats':self.baseline['splats'],'shDegree':2}
        candidate={key:self.baseline[key] for key in ['sha256','bytes','format','splats','shDegree']}
        candidate.update({'provisional':False,'newTraining':True,'cameras':'../cameras.json','packingReport':'../packing.json'})
        files=[{'path':'room-1234567890.json','sha256':'1'*64,'bytes':20},{'path':'room-viewer-ABCDEFGH.js','sha256':'2'*64,'bytes':30},{'path':asset['url'],'sha256':self.baseline['sha256'],'bytes':self.baseline['bytes']}]
        inherited=[{'path':url,'bytes':size,'sha256':digest} for url,size,digest in d.IPHONES.values()]
        self.audit={'build':{'build':self.release,'osmo':asset,'provisional':False,'newTrainingNotUsed':False,'manifestName':files[0]['path'],'choiceRequired':True,'automaticModelRetry':False,'prechoiceExternalRequests':0},'candidate':candidate,'manifest':{'models':{'osmo':copy.deepcopy(asset),'phone':{'url':d.IPHONES['phone'][0]}}},'files':files,'inherited_files':inherited}
        self.approved={'releaseKind':'viewer-update','approvedForDeployment':True,'releaseId':self.release,'modelSha256':self.baseline['sha256'],'baselineRelease':self.baseline['release'],'baselineModelSha256':self.baseline['sha256'],'reconstructionAccepted':False,'userAuthorization':{'action':'deploy-viewer-update','source':'user-message','instruction':'Merge and implement the viewer changes','recordedAt':'2026-11-03T12:00:00+07:00'},'qualityChecks':{**dict.fromkeys(self.required,True),'fourDetailSharpnessLeapAccepted':False},'knownLimitations':['training-not-rerun','photographic-sharpness-unaccepted','inferred-shape-overlay','display-only-sharpening','transient-lod-memory','physical-phones-unverified'],'physicalPhones':'unverified','transientLodMemoryLimitationAcknowledged':True,'publicFiles':copy.deepcopy(files),'inheritedFiles':copy.deepcopy(inherited),'manifestSha256':'1'*64,'evidence':[]}
        packing={key:self.baseline[key] for key in ['sha256','bytes','format','splats','shDegree','sourceSha256']};packing.update(sourceCountPreserved=True,sourceShDegreePreserved=True)
        baseline={'approvedForDeployment':False,'releaseId':self.baseline['release'],'modelSha256':self.baseline['sha256'],'gates':{'sharpness':{'visualAccepted':False}},'qualityChecks':{'fourDetailSharpnessLeapAccepted':False}}
        cameras={'coordinateFrame':'+Y up','presets':[{'sourceTimeSeconds':t} for t in [0,8,16,24,32,40,52]]}
        for key,path,data in [('freshCameraExportSha256',self.here/'../cameras.json',cameras),('packingReportSha256',self.here/'../packing.json',packing),('baselineAcceptanceSha256',self.here/'../../acceptance-gates.json',baseline),('baselineApprovalSha256',self.here/'release-approval.json',baseline)]:
            row=self.write(path,data);self.approved[key]=row['sha256'];self.approved['evidence'].append(row)
        checked={'passed':True,'releaseId':self.release,'modelSha256':self.baseline['sha256'],'manifestSha256':'1'*64,'checks':dict.fromkeys(self.required,True)}
        row=self.write(self.here/'viewer-checks.json',checked);self.approved['viewerVerification']=row;self.approved['evidence'].append(row)
        self.approval=self.here/'viewer-update-approval.json'
    def write(self,path,data):
        path=path.resolve();path.write_text(json.dumps(data),encoding='utf-8')
        return {'path':str(path),'bytes':path.stat().st_size,'sha256':d.sha(path)}
    def gate(self):
        self.approval.write_text(json.dumps(self.approved),encoding='utf-8')
        return d.quality_gate(self.audit,self.approval,self.here)
    def reject(self,text):
        with self.assertRaisesRegex(ValueError,text):self.gate()
    def test_exact_viewer_update_accepted_without_falsifying_photographic_gates(self):
        self.assertEqual(self.gate()['releaseKind'],'viewer-update')
        self.assertFalse(self.gate()['reconstructionAccepted'])
        self.assertFalse(json.loads((self.here/'release-approval.json').read_text())['approvedForDeployment'])
    def test_original_failed_reconstruction_approval_still_refused(self):
        with self.assertRaisesRegex(ValueError,'does not approve'):d.quality_gate(self.audit,self.here/'release-approval.json',self.here)
    def test_false_viewer_approval_refused(self):
        self.approved['approvedForDeployment']=False;self.reject('not approved')
    def test_arbitrary_model_cannot_use_viewer_update_exception(self):
        for key,value in [('sha256','3'*64),('bytes',40000000),('splats',1000000),('shDegree',3),('format','spz')]:
            with self.subTest(key=key):
                old=self.audit['candidate'][key];self.audit['candidate'][key]=value
                self.reject('different model');self.audit['candidate'][key]=old
    def test_wrong_review_baseline_refused(self):
        self.approved['baselineRelease']='20261031-osmo-clean-v1';self.reject('exact reviewed A018')
    def test_cannot_claim_reconstruction_or_sharpness_is_accepted(self):
        self.approved['reconstructionAccepted']=True;self.reject('unaccepted')
        self.approved['reconstructionAccepted']=False;self.approved['qualityChecks']['fourDetailSharpnessLeapAccepted']=True;self.reject('sharpness gate passed')
    def test_user_authorization_is_required_and_scoped(self):
        for value in [None,{}, {'action':'deploy-new-model','source':'user-message','instruction':'yes','recordedAt':'2026-11-03T12:00:00Z'}]:
            with self.subTest(value=value):self.approved['userAuthorization']=value;self.reject('explicit user authorization')
    def test_unverified_phones_and_display_limitations_cannot_be_hidden(self):
        for value in ['physical-phones-unverified','inferred-shape-overlay','display-only-sharpening','training-not-rerun']:
            with self.subTest(value=value):
                self.approved['knownLimitations'].remove(value);self.reject('known reconstruction/display limitations');self.approved['knownLimitations'].append(value)
    def test_changed_bundle_or_inherited_assets_invalidate_review(self):
        self.audit['files'][1]['sha256']='4'*64;self.reject('every built and inherited file')
        self.audit['files'][1]['sha256']='2'*64;self.audit['inherited_files'][0]['sha256']='5'*64;self.reject('every built and inherited file')
    def test_quota_failure_refused_even_with_manual_approval(self):
        self.audit['build']['prechoiceExternalRequests']=1;self.reject('quota guarantees absent')
    def test_camera_change_after_review_refused(self):
        (self.here/'../cameras.json').write_text('{}');self.reject('evidence missing or changed')
    def test_camera_file_must_be_in_evidence(self):
        self.approved['evidence']=self.approved['evidence'][1:];self.reject('absent from evidence')
    def test_current_verification_must_identify_exact_manifest(self):
        path=self.here/'viewer-checks.json';data=json.loads(path.read_text());data['manifestSha256']='9'*64
        row=self.write(path,data);self.approved['viewerVerification']=row;self.approved['evidence'][-1]=row;self.reject('exact release/manifest/model')
    def test_later_checks_cannot_silently_change_baseline_sharpness_record(self):
        path=self.here/'../../acceptance-gates.json';data=json.loads(path.read_text());data['gates']['sharpness']['visualAccepted']=True
        row=self.write(path,data);self.approved['evidence'][2]=row;self.approved['baselineAcceptanceSha256']=row['sha256'];self.reject('rewrite the failed baseline sharpness')
    def test_full_cannot_return_as_a_model_choice_or_inherited_payload(self):
        self.audit['manifest']['models']['native']={};self.reject('exactly Lite and Osmo')
        del self.audit['manifest']['models']['native']
        self.audit['inherited_files'].append({'path':d.REMOVED_PUBLIC_FILES[0],'bytes':435614584,'sha256':'a'*64});self.reject('cannot be packaged or inherited')
    def test_retirement_unlinks_only_new_snapshot_full_leaves_and_preserves_rollback(self):
        root=Path(self.tmp.name).resolve();previous=root/'previous';new=root/'new'
        for target in [previous,new]:
            self.assertTrue(target.resolve().is_relative_to(root) and target.resolve()!=root)
            (target/'models').mkdir(parents=True)
        names=['iphone-full-room-16f8963b.glb','iphone-full-room-16f8963b.glb.gz','iPhone-Full-old.GLB.gz','iphone-phone-2b811d1241.glb']
        for name in names:
            source=previous/'models'/name;source.write_bytes(name.encode());os.link(source,new/'models'/name)
        template=(HERE/'deploy-native.template.sh').read_text(encoding='utf-8')
        script=template.split("<<'REMOVE_FULL'\n",1)[1].split('\nREMOVE_FULL',1)[0]
        bash=r'C:\Program Files\Git\bin\bash.exe' if os.name=='nt' else 'bash'
        run=subprocess.run([bash,'-s','--',str(new)],input=script,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        for name in names:
            self.assertEqual((previous/'models'/name).read_bytes(),name.encode())
            self.assertEqual((new/'models'/name).exists(),name.startswith('iphone-phone-'))
    def test_retired_head_accepts_only_404_and_never_masks_403(self):
        url='https://rumah.shizuku.rest/'+d.REMOVED_PUBLIC_FILES[0]
        for code in [403,404]:
            error=urllib.error.HTTPError(url,code,'test',{},io.BytesIO(b'not read'))
            self.addCleanup(error.close)
            with patch.object(p.urllib.request,'urlopen',side_effect=error) as opened:
                if code==404:self.assertEqual(p.request('https://rumah.shizuku.rest/',d.REMOVED_PUBLIC_FILES[0],'HEAD',allow_not_found=True)[0],404)
                else:
                    with self.assertRaises(urllib.error.HTTPError):p.request('https://rumah.shizuku.rest/',d.REMOVED_PUBLIC_FILES[0],'HEAD',allow_not_found=True)
                self.assertIn('Mozilla/5.0',opened.call_args.args[0].get_header('User-agent'))

    def add_stick(self):
        """Build a synthetic receipt graph without using any production review files."""
        self.release = d.STICK_RELEASE
        self.audit['build']['build'] = self.release
        self.approved.update(releaseKind='stick-addition', releaseId=self.release)
        self.approved['userAuthorization']['action'] = 'deploy-stick-addition'
        self.approved['qualityChecks'].update(dict.fromkeys(d.STICK_RELEASE_CHECKS, True))
        root = self.here / 'stick'
        dataset = root / 'pinhole'
        dataset.mkdir(parents=True)
        checkpoint = root / 'training/run/checkpoint/splat.ply'
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b'synthetic checkpoint')
        checkpoint_sha = d.sha(checkpoint)

        def bind(field, path, data=None):
            if data is not None:
                row = self.write(path, data)
            else:
                row = {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': d.sha(path)}
            self.approved[field] = row['sha256']
            self.approved['evidence'] = [old for old in self.approved['evidence'] if old['path'] != row['path']] + [row]
            return row

        self.bind_stick = bind
        bind('stickTrainingPlySha256', checkpoint)
        self.stick_digest = '3' * 64
        asset = {'url': 'models/osmo-native-' + self.stick_digest[:10] + '.sog',
                 'representation': 'gaussian', 'cameraSet': d.STICK_KEY, 'format': 'sog',
                 'fileBytes': 24, 'downloadBytes': 24, 'splats': 9, 'shDegree': 2, 'provisional': False}
        self.audit['build']['stick'] = asset
        self.audit['manifest']['models'][d.STICK_KEY] = asset
        self.audit['files'].append({'path': asset['url'], 'bytes': 24, 'sha256': self.stick_digest})
        self.approved['publicFiles'] = copy.deepcopy(self.audit['files'])
        self.approved['stickModelSha256'] = self.stick_digest
        packing = {'sha256': self.stick_digest, 'bytes': 24, 'format': 'sog', 'splats': 9, 'shDegree': 2,
                   'source': str(checkpoint), 'sourceSha256': checkpoint_sha,
                   'sourceCountPreserved': True, 'sourceShDegreePreserved': True}
        bind('stickPackingReportSha256', root / 'packing.json', packing)
        norm = {'applied': True, 'old_reconstruction_opened': False, 'learned_depth_opened': False,
                'transform': {'coordinate_frame': '+Y up'}, 'output_model': str(root / 'native/sparse/0')}
        bind('stickNormalizationSha256', root / 'norm.json', norm)
        presets = [{'position': [0, 1, 0], 'quaternion': [0, 0, 0, 1], 'sourceTimeSeconds': t,
                    'intrinsics': [600, 600, 600, 600], 'imageWidth': 1200, 'imageHeight': 1200}
                   for t in [1, 9, 15, 24, 54, 76, 101]]
        camera_set = {'bounds': [[-1, 0, -1], [1, 3, 1]], 'framingPoints': [],
                      'occupiedShell': {'footprint': {'source': {'sha256': checkpoint_sha}}},
                      'startCamera': presets[0], 'homeTarget': [0, 1, 1], 'presets': presets}
        self.audit['manifest']['cameraSets'] = {d.STICK_KEY: copy.deepcopy(camera_set)}
        cameras = {**camera_set, 'normalizationEvidence': 'norm.json', 'coordinateFrame': '+Y up'}
        camera_row = bind('stickCameraExportSha256', root / 'cameras.json', cameras)
        hashes = {}
        for name in ['seed-sparse-train.ply', 'sparse/0/cameras.txt', 'sparse/0/images.txt', 'sparse/0/points3D.txt']:
            path = dataset / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            hashes[name] = d.sha(path)
        bind('stickPinholeAuditSha256', dataset / 'explicit-pinhole-audit.json',
             {'outputDataset': str(dataset), 'sourceDataset': str(root / 'native'), 'sha256': hashes,
              'worldCoordinateFrame': '+Y up; identical to audited fresh SfM, no new similarity'})
        self.stick_training = {'status': 'finished', 'exit_code': 0,
                               'provenance': {'coldStart': True, 'learnedDepth': False},
                               'command': ['spirula', 'train', '3dgs', '--data', str(dataset),
                                           '--seed-pointcloud', str(dataset / 'seed-sparse-train.ply'),
                                           '--output-dir-prefix', str(root / 'training'), '--output-dir-name', 'run',
                                           '--load-depths', '0', '--load-normals', '0', '--scene-center', 'none',
                                           '--orientation-method', 'none', '--center-method', 'none',
                                           '--auto-scale-poses', '0', '--train-frame', 'points', '--eval-mode', 'filename']}
        self.stick_training_path = root / 'train.json'
        bind('stickTrainingEvidenceSha256', self.stick_training_path, self.stick_training)
        self.stick_qa = {'passed': True, 'releaseId': self.release, 'modelSha256': self.stick_digest,
                         'cameraExportSha256': camera_row['sha256'], 'trainingPlySha256': checkpoint_sha,
                         'checks': {'coverageAccepted': True, 'heldoutAppearanceAccepted': True,
                                    'packedAppearanceAccepted': True}}
        self.stick_qa_path = root / 'qa.json'
        bind('stickQaReportSha256', self.stick_qa_path, self.stick_qa)
        candidate = {'file': 'stick.sog', 'sha256': self.stick_digest, 'bytes': 24, 'format': 'sog',
                     'splats': 9, 'shDegree': 2, 'packingReport': 'packing.json', 'cameras': 'cameras.json',
                     'trainingEvidence': 'train.json', 'qaReport': 'qa.json', 'newTraining': True, 'provisional': False}
        self.audit['stick_config'] = root / 'candidate.json'
        self.audit['stick_candidate'] = candidate
        config = bind('stickConfigSha256', self.audit['stick_config'], candidate)
        self.audit['build']['stickCandidateSha256'] = config['sha256']
        viewer_path = self.here / 'viewer-checks.json'
        checked = json.loads(viewer_path.read_text())
        checked.update(releaseId=self.release, stickModelSha256=self.stick_digest)
        checked['checks']['stickAllChoicesVerified'] = True
        self.approved['viewerVerification'] = bind('viewerVerificationFixtureSha256', viewer_path, checked)

    def test_stick_addition_keeps_held_rejected_and_uses_a_separate_gate(self):
        self.add_stick()
        self.assertEqual(self.gate()['stickModelSha256'], self.stick_digest)
        self.assertFalse(self.gate()['reconstructionAccepted'])
        self.approved['releaseKind'] = 'viewer-update'
        self.reject('exactly Lite and Osmo')

    def test_stick_over_budget_or_unaccepted_visual_qa_cannot_release(self):
        self.add_stick()
        asset = self.audit['build']['stick']
        asset['fileBytes'] = d.STICK_LIMIT + 1
        self.reject('within 30 MB')
        asset['fileBytes'] = 24
        self.stick_qa['checks']['coverageAccepted'] = False
        self.bind_stick('stickQaReportSha256', self.stick_qa_path, self.stick_qa)
        self.reject('coverage or appearance remains unaccepted')

    def test_stick_receipt_cannot_approve_resumed_training(self):
        self.add_stick()
        self.stick_training['command'] += ['--resume', 'old.ckpt']
        self.bind_stick('stickTrainingEvidenceSha256', self.stick_training_path, self.stick_training)
        self.reject('without an existing checkpoint')

    def test_public_verification_heads_both_native_models(self):
        self.add_stick()
        assets = self.audit['build']
        rows = [row for row in self.audit['files'] if row['path'].endswith('.sog')]
        info = {'build': self.release, 'model': assets['osmo'], 'stick': assets['stick'],
                'files': rows, 'inherited_files': self.audit['inherited_files']}
        with patch.object(p, 'model_head', side_effect=lambda base, row, fmt: {'path': row['path'], 'format': fmt}), \
             patch.object(p, 'request') as request:
            checked = p.verify(info, 'https://example.invalid')
        request.assert_not_called()
        self.assertEqual({row['path']: row['format'] for row in checked['asset_checks']},
                         {assets['osmo']['url']: 'sog', assets['stick']['url']: 'sog', d.IPHONES['phone'][0]: 'glb'})

    def test_collect_and_package_binds_both_gaussians_and_their_source_photos(self):
        root = Path(self.tmp.name) / 'work'
        here = root / 'parity/review/production'
        public = here / 'public'
        public.mkdir(parents=True)
        baseline = root / 'mobile-20261029/iphone-baseline'
        phone_path = d.IPHONES['phone'][0]
        phone_bytes = b'glTF synthetic Lite bytes'
        phone = {'url': phone_path, 'fileBytes': len(phone_bytes)}
        phone_cameras = {'presets': [], 'photos': []}
        for target in [baseline, public]:
            path = target / phone_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(phone_bytes)
            path.with_suffix('.glb.gz').write_bytes(b'synthetic compressed Lite bytes')
        self.write(baseline / 'manifest.json', {'models': {'phone': phone}, 'cameraSets': {'iphone': phone_cameras}})
        model_rows = {'phone': phone}
        camera_sets = {'iphone': phone_cameras}
        config_rows = {}
        source_names = []
        for key in ['osmo', d.STICK_KEY]:
            payload = b'PK\x03\x04 synthetic Gaussian ' + key.encode()
            digest = hashlib.sha256(payload).hexdigest()
            url = f'models/osmo-native-{digest[:10]}.sog'
            (public / url).write_bytes(payload)
            model_rows[key] = {'url': url, 'fileBytes': len(payload), 'downloadBytes': len(payload),
                               'cameraSet': key, 'representation': 'gaussian', 'format': 'sog',
                               'provisional': False, 'splats': 9, 'shDegree': 2}
            config_rows[key] = {'sha256': digest, 'bytes': len(payload), 'format': 'sog', 'splats': 9,
                                'shDegree': 2, 'newTraining': True, 'provisional': False, 'releaseId': d.STICK_RELEASE}
            photo = b'synthetic reference ' + key.encode()
            photo_name = f'sources/osmo-{hashlib.sha256(photo).hexdigest()[:10]}.jpg'
            source_names.append(photo_name)
            (public / 'sources').mkdir(exist_ok=True)
            (public / photo_name).write_bytes(photo)
            camera_sets[key] = {'presets': [{'source': photo_name}], 'photos': [{'source': photo_name}]}
        self.write(here / 'candidate.json', config_rows['osmo'])
        stick_config = self.write(here / 'stick.json', config_rows[d.STICK_KEY])
        manifest = json.dumps({'models': model_rows, 'cameraSets': camera_sets}).encode()
        manifest_name = f'room-{hashlib.sha256(manifest).hexdigest()[:10]}.json'
        (public / manifest_name).write_bytes(manifest)
        bundle = 'room-viewer-ABCDEFGH.js'
        (public / bundle).write_text(manifest_name)
        choices = ''.join(f'<input type="radio" name="model-choice" value="{key}">' for key in model_rows)
        (public / 'index.html').write_text(choices + f'<button id="open-model"></button><div id="viewer-app" hidden></div><script>"{bundle}"</script>')
        (public / 'robots.txt').write_text('User-agent: *\nDisallow: /\n')
        self.write(here / 'build-report.json', {
            'build': d.STICK_RELEASE, 'manifestName': manifest_name, 'bundleName': bundle, 'choiceRequired': True,
            'automaticModelRetry': False, 'prechoiceExternalRequests': 0, 'deploymentAuthorized': False,
            'osmo': model_rows['osmo'], 'stick': model_rows[d.STICK_KEY],
            'sourceStickCandidate': stick_config['path'], 'stickCandidateSha256': stick_config['sha256'],
            'lodPolicy': {'lodSplatCount': 1_500_000, 'baseSplats': 9, 'lod': True, 'nonLod': False, 'extSplats': True},
            'metafile': {'outputs': {f'public/{bundle}': {}}},
        })
        with patch.object(d, 'IPHONES', {'phone': (phone_path, len(phone_bytes), hashlib.sha256(phone_bytes).hexdigest())}):
            audit = d.collect(here)
            expected = {model_rows[key]['url'] for key in ['osmo', d.STICK_KEY]} | set(source_names)
            self.assertTrue(expected.issubset({row['path'] for row in audit['files']}))
            for name in ['deploy-native.template.sh', 'rollback-native.template.sh']:
                (here / name).write_bytes((HERE / name).read_bytes())
            approval = here / 'approval.json'
            approval.write_text('{}')
            with patch.object(d, 'quality_gate', return_value={}):
                info = d.package(audit, approval, '/var/www/rumah/releases/20261103-osmo-viewer-v4', here)
            with tarfile.open(here / 'deployment/native-site.tar') as archive:
                self.assertTrue(expected.issubset(set(archive.getnames())))
                self.assertNotIn(phone_path, archive.getnames())
            runner = (here / 'deployment/deploy-native.sh').read_text()
            for key in ['osmo', d.STICK_KEY]:
                model = model_rows[key]
                self.assertIn(f"{model['url']} {model['fileBytes']}", runner)
            self.assertEqual(info['stick_model_sha256'], config_rows[d.STICK_KEY]['sha256'])
            (here / 'stick.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Stick config changed after build'):
                d.collect(here)

if __name__=='__main__':unittest.main()
