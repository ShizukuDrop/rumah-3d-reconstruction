"""Local-only release failure checks, fixture archive and generated shell syntax."""
from pathlib import Path
from unittest.mock import patch
import hashlib,importlib.util,json,os,subprocess,tarfile,tempfile
HERE=Path(__file__).resolve().parent
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
deploy=module('native_deploy','prepare-deploy.py');public=module('native_public','verify-public-native.py');checks=[]
def reject(label,fn):
    try:fn()
    except (ValueError,FileExistsError):checks.append(label)
    else:raise AssertionError('Accepted invalid input: '+label)
landing=''.join(f'<input type="radio" name="model-choice" value="{key}">' for key in ['phone','osmo'])+'<button id="open-model"></button><div id="viewer-app" hidden></div><script>const lazy="room-viewer-ABCDEFGH.js";</script>'
deploy.audit_landing(landing,'room-viewer-ABCDEFGH.js');checks.append('valid Lite/Osmo choice gate')
reject('retired Full choice refused',lambda:deploy.audit_landing(landing+'<input type="radio" name="model-choice" value="native">','room-viewer-ABCDEFGH.js'))
for tag in ['<img src="preview.jpg">','<script src="viewer.js"></script>','<link rel="modulepreload" href="spark.js">','<style>body{background:url(photo.jpg)}</style>','<meta http-equiv="refresh" content="0;url=/viewer">']:
    reject('reject initial resource '+tag.split()[0],lambda tag=tag:deploy.audit_landing(landing+tag,'room-viewer-ABCDEFGH.js'))
reject('reject duplicate choice',lambda:deploy.audit_landing(landing+'<input type="radio" name="model-choice" value="osmo">','room-viewer-ABCDEFGH.js'))
for path in ['../private.json','/etc/passwd','models\\scene.sog','models/model;touch']:
    reject('reject unsafe path '+path,lambda path=path:deploy.safe_relative(path))
reject('old provisional model blocked',lambda:deploy.quality_gate({'build':{'provisional':True,'osmo':{}},'candidate':{}},HERE/'does-not-exist.json'))

class Response:
    status=200;headers={};reads=0
    def geturl(self):return 'https://rumah.shizuku.rest/model.sog'
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):self.reads+=1;return b'not read'
response=Response()
with patch.object(public.urllib.request,'urlopen',return_value=response):
    reject('ignored range rejected before model body is read',lambda:public.request('https://rumah.shizuku.rest/','model.sog',extra={'Range':'bytes=0-11'},limit=12))
    assert response.reads==0
checks.append('range failure reads zero model body bytes')

with tempfile.TemporaryDirectory(prefix='native-deploy-audit-',dir=HERE) as temporary:
    fixture=Path(temporary).resolve();assert fixture.is_relative_to(HERE) and fixture!=HERE
    root=fixture/'public';root.mkdir();files={'index.html':landing.encode(),'room-1234567890.json':b'{}','room-viewer-ABCDEFGH.js':b'// fixture','chunks/spark-ABCDEFGH.js':b'// lazy fixture','models/osmo-native-1234567890.sog':b'PK\x03\x04fixture','sources/osmo-1234567890.jpg':b'fixture'}
    rows=[]
    for name,data in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);rows.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    inherited=[]
    for path,size,digest in deploy.IPHONES.values():
        inherited += [{'path':path,'bytes':size,'sha256':digest},{'path':path+'.gz','bytes':10,'sha256':'0'*64}]
    audit={'build':{'build':'20261031-fixture','manifestName':'room-1234567890.json','bundleName':'room-viewer-ABCDEFGH.js','osmo':{'url':'models/osmo-native-1234567890.sog','fileBytes':len(files['models/osmo-native-1234567890.sog'])}},'candidate':{'sha256':'1'*64},'files':rows,'inherited_files':inherited,'application_bytes':30,'public':str(root)}
    for name in ['deploy-native.template.sh','rollback-native.template.sh']:(fixture/name).write_bytes((HERE/name).read_bytes())
    approval=fixture/'approval.json';approval.write_text('{}')
    with patch.object(deploy,'quality_gate',return_value={}):info=deploy.package(audit,approval,'/var/www/rumah/releases/20261031-osmo-v3',fixture)
    with tarfile.open(fixture/'deployment/native-site.tar') as tar:
        assert sorted(tar.getnames())==sorted(files) and all(member.isfile() for member in tar.getmembers())
        assert not any('iphone-' in name for name in tar.getnames())
    assert all('iphone-full-' not in r['path'] for r in info['files']+info['inherited_files'])
    assert info['removed_public_files']==deploy.REMOVED_PUBLIC_FILES
    script=(fixture/'deployment/deploy-native.sh').read_text(encoding='utf-8')
    assert '__GZIP_HEADS__' not in script and 'trap on_exit EXIT' in script and 'mv -Tf' in script
    for name in files:assert 'rm -f -- "$RELEASE/'+name+'"' in script
    assert '__DETACH__' not in script
    assert script.index('rm -f --')<script.index('tar --no-same-owner')
    assert script.index('cp -al')<script.index("<<'REMOVE_FULL'")<script.index('pct exec 710 -- ln -s "$RELEASE" "$NEXT"')
    assert 'test ! -e "$release/models/iphone-full-room-16f8963b.glb"' in script
    assert "'%{http_code}'" in script and '" = 404' in script
    assert 'curl -fsS --compressed' not in script and 'model GET' not in script
    for name in ['deploy-native.sh','rollback-native.sh']:
        result=subprocess.run([r'C:\Program Files\Git\bin\bash.exe' if os.name=='nt' else 'bash','-n',str(fixture/'deployment'/name)],capture_output=True)
        assert result.returncode==0,result.stderr.decode()
    checks += ['archive has only explicit regular public files','iPhone Lite excluded from upload and Full excluded from inheritance','new snapshot removes Full and origin requires its URLs to return 404','all replacement hardlinks detached before extraction','atomic promotion and guarded rollback generated','rendered deployment and rollback scripts pass bash -n','origin verification contains no full model GET']
    with patch.object(deploy,'quality_gate',return_value={}):reject('package cannot silently overwrite a prior release package',lambda:deploy.package(audit,approval,'/var/www/rumah/releases/20261031-osmo-v3',fixture))
print(json.dumps({'passed':len(checks),'checks':checks,'remoteCalls':0,'gpuWork':False},indent=2))
