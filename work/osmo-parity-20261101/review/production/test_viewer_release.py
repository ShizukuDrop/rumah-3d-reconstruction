"""Synthetic release authorization checks; no model downloads, SSH or deployment."""
from pathlib import Path
import copy,importlib.util,json,tempfile,unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('viewer_deploy',HERE/'prepare-deploy.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class ViewerRelease(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.here=Path(self.tmp.name).resolve()/'review/production';self.here.mkdir(parents=True)
        self.baseline=d.VIEWER_BASELINE;self.release='20261103-osmo-viewer-v1'
        self.required=['viewerQuotaAndErrorsPassed','viewerControlsPassed','zeroModelBytesBeforeOpen','iphoneHashesPreserved','totalModelDownloadWithin50MB','reversibleShellPassed']
        asset={'url':'models/osmo-native-'+self.baseline['sha256'][:10]+'.sog','representation':'gaussian','format':'sog','fileBytes':self.baseline['bytes'],'downloadBytes':self.baseline['bytes'],'splats':self.baseline['splats'],'shDegree':2}
        candidate={key:self.baseline[key] for key in ['sha256','bytes','format','splats','shDegree']}
        candidate.update({'provisional':False,'newTraining':True,'cameras':'../cameras.json','packingReport':'../packing.json'})
        files=[{'path':'room-1234567890.json','sha256':'1'*64,'bytes':20},{'path':'room-viewer-ABCDEFGH.js','sha256':'2'*64,'bytes':30},{'path':asset['url'],'sha256':self.baseline['sha256'],'bytes':self.baseline['bytes']}]
        inherited=[{'path':url,'bytes':size,'sha256':digest} for url,size,digest in d.IPHONES.values()]
        self.audit={'build':{'build':self.release,'osmo':asset,'provisional':False,'newTrainingNotUsed':False,'manifestName':files[0]['path'],'choiceRequired':True,'automaticModelRetry':False,'prechoiceExternalRequests':0},'candidate':candidate,'manifest':{'models':{'osmo':copy.deepcopy(asset)}},'files':files,'inherited_files':inherited}
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

if __name__=='__main__':unittest.main()
