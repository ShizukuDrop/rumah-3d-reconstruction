"""CPU/local-HTTP handoff checks; never trains or contacts production hosts."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,platform,socket,subprocess,sys,time,urllib.request

ROOT=Path(__file__).resolve().parents[1]
PHASES=['osmo-clean-20261031','osmo-parity-20261101']
def run(command,cwd=ROOT):
    p=subprocess.run([str(x) for x in command],cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError('Command failed: '+' '.join(map(str,command))+'\n'+p.stdout[-5000:]+p.stderr[-5000:])
    return {'command':[str(x) for x in command],'passed':True,'stdoutTail':p.stdout[-1300:],'stderrTail':p.stderr[-300:]}
def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def preview(prod):
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    process=subprocess.Popen(['node',str(prod/'serve.mjs'),'--port',str(port)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=flags)
    base=f'http://127.0.0.1:{port}/'
    try:
        for attempt in range(50):
            try:
                with urllib.request.urlopen(base,timeout=2) as r:html=r.read()
                break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Local preview did not start')
        assert len(html)<80000 and b'open-model' in html
        build=json.loads((prod/'build-report.json').read_text(encoding='utf-8'));m=json.loads((prod/'public'/build['manifestName']).read_text(encoding='utf-8'))
        for item in m['models'].values():
            with urllib.request.urlopen(urllib.request.Request(base+item['url'],method='HEAD'),timeout=5) as response:assert int(response.headers['Content-Length'])==item['fileBytes']
        item=m['models']['osmo'];request=urllib.request.Request(base+item['url'],headers={'Range':'bytes=0-11'})
        with urllib.request.urlopen(request,timeout=5) as response:
            assert response.status==206 and response.read(13)==b'PK\x03\x04'+(prod/'public'/item['url']).read_bytes()[4:12]
        return {'passed':True,'landingBytes':len(html),'modelHeads':3,'modelRangeBytes':12,'productionRequests':0}
    finally:
        process.terminate()
        try:process.communicate(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.communicate()
def main():
    p=argparse.ArgumentParser();p.add_argument('--geometry-python',type=Path,default=Path(sys.executable));p.add_argument('--skip-build',action='store_true');a=p.parse_args();checks=[]
    suites=[ROOT/'work'/phase/'review/production'/name for phase in PHASES for name in ['loader-core.test.mjs','choice-gate.test.mjs','model-selection.test.mjs','native-delivery.test.mjs']]+[ROOT/'work/osmo-parity-20261101/review/production/cutaway.test.mjs']
    checks.append(run(['node','--test',*suites]))
    for rel in ['work/osmo-reconstruct-20261031/test_seed_fisheye.py','work/osmo-clean-20261031/geometry/test_operator_pinhole.py','work/osmo-clean-20261031/geometry/test_preparation_synthetic.py','work/osmo-clean-20261031/geometry/test_negative_rays.py']:
        f=ROOT/rel;checks.append(run([a.geometry_python.absolute(),'-B',f],f.parent))
    checks.append(run([sys.executable,'-B',ROOT/'tools/test_restore_assets.py']))
    checks.append(run([sys.executable,'-B',ROOT/'tools/restore_assets.py','--check']))
    phases=[]
    for i,phase in enumerate(PHASES):
        prod=ROOT/'work'/phase/'review/production'
        if not a.skip_build:checks.append(run(['node','build.mjs'],prod))
        checks.append(run([sys.executable,'-B',prod/'audit-deploy-native.py']))
        checks.append(run([sys.executable,'-B',prod/'prepare-deploy.py','--audit-only']))
        deploy=load_module(prod/'prepare-deploy.py','handoff_deploy_'+str(i));audit=deploy.collect();refusal=None
        if phase=='osmo-parity-20261101':
            try:deploy.quality_gate(audit,prod/'release-approval.json')
            except ValueError as e:refusal=str(e)
            else:raise AssertionError('Rejected review model was approved')
        phases.append({'phase':phase,'preview':preview(prod),'fileClosurePassed':True,'reviewDeploymentRefusal':refusal})
    result={'passed':True,'date':time.strftime('%Y-%m-%d'),'platform':platform.platform(),'checks':checks,'phases':phases,'trainingJobsLaunched':0,'productionRequests':0,'physicalPhoneValidation':False}
    out=ROOT/'docs/repo-audit-2026-11-01'/('handoff-validation.json' if os.name=='nt' else f'handoff-validation-{sys.platform}.json');out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({'passed':True,'commandGroups':len(checks),'phases':phases,'report':out.relative_to(ROOT).as_posix()},indent=2))
if __name__=='__main__':main()
