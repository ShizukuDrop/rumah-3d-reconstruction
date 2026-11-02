"""Audit candidate files or staged blobs without printing credential values.

Before git init, ripgrep applies .gitignore with --no-require-git. After staging,
--staged reads actual index blobs so ignored-file assumptions cannot hide leaks.
No GitHub authentication tokens are read or printed by this tool.
"""
from pathlib import Path
import argparse,hashlib,io,ipaddress,json,os,re,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/repo-audit-2026-11-01'
MAX_FILE=25_000_000
FORBIDDEN={'.glb','.gltf','.ply','.sog','.spz','.splat','.ksplat','.rad','.osv','.lrf','.insv','.nev','.mp4','.mov','.npz','.npy','.bin','.gz','.tar','.zip','.exe','.dll','.pyd','.so','.pem','.key','.pfx','.p12'}
DENIED_DIRS={'node_modules','.venv','pydeps','qa-deps','tsdfdeps','site-packages','runtime','private-source-backup','.local','public','deployment','__pycache__'}
PATTERNS={
 'private-key':re.compile(r'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----'),
 'github-token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
 'google-api-key':re.compile(r'\bAIza[0-9A-Za-z_-]{30,}\b'),
 'huggingface-token':re.compile(r'\bhf_[A-Za-z0-9]{30,}\b'),
 'openai-api-key':re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{30,}\b'),
 'google-client-secret':re.compile(r'\bGOCSPX-[A-Za-z0-9_-]{20,}\b'),
 'slack-token':re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
 'credential-in-url':re.compile(r'(?i)(?:https?|ssh)://[^/\s:@]+:([^@\s/]+)@'),
 'aws-access-key':re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
 'jwt':re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b'),
 'literal-secret-assignment':re.compile(r'''(?i)["']?(?:password|passwd|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|tunnel[_-]?secret|cf[_-]?token|token)["']?\s*[:=]\s*["']([^"'\r\n]{6,})["']'''),
 'literal-authorization':re.compile(r'(?i)(?:Bearer\s+|CF-Access-Client-Secret:\s*)([A-Za-z0-9_/.+=-]{20,})'),
}
PLACEHOLDERS=re.compile(r'(?i)^(?:[<$]|REDACTED|YOUR_|EXAMPLE|PLACEHOLDER|os\.environ|os\.getenv|process\.env|https?://|application/|not-|fixture|fake|dummy|test)')
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def candidates(staged):
    raw=git('ls-files','-z') if staged else subprocess.check_output(['rg','--files','--hidden','--no-require-git','--null'],cwd=ROOT)
    return sorted(set(s.replace('\\','/') for s in raw.decode('utf-8').split('\0') if s and not s.startswith('.git/')))
def blobs(paths,staged):
    if not staged:
        for rel in paths:yield rel,(ROOT/rel).read_bytes(),'100644'
        return
    entries={}
    for row in git('ls-files','--stage','-z').decode('utf-8').split('\0'):
        if not row:continue
        header,rel=row.split('\t',1);mode,digest,stage=header.split();entries[rel]=(mode,digest)
    process=subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for rel in paths:
            mode,digest=entries[rel];process.stdin.write((digest+'\n').encode());process.stdin.flush();header=process.stdout.readline().split()
            if len(header)!=3 or header[1]!=b'blob':raise ValueError('Staged object unavailable')
            data=process.stdout.read(int(header[2]));assert process.stdout.read(1)==b'\n'
            yield rel,data,mode
    finally:
        process.stdin.close();process.wait(timeout=10)
def secret_hits(text,path):
    hits=[]
    for label,pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            value=match.group(1) if match.lastindex else match.group(0)
            if label in {'literal-secret-assignment','literal-authorization'} and (PLACEHOLDERS.match(value) or any(x in value for x in ['${','{token','{secret','{password','[A-Za-z','\\s','--'])):continue
            hits.append({'path':path,'line':text.count('\n',0,match.start())+1,'category':label,'valuePrinted':False})
    networks=[ipaddress.ip_network(n) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10']]
    for match in re.finditer(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',text):
        try:address=ipaddress.ip_address(match.group(0))
        except ValueError:continue
        if any(address==network.network_address and text[match.end():].startswith('/'+str(network.prefixlen)) for network in networks):continue
        if any(address in network for network in networks):hits.append({'path':path,'line':text.count('\n',0,match.start())+1,'category':'private-infrastructure-address','valuePrinted':False})
    return hits
def main():
    p=argparse.ArgumentParser();p.add_argument('--staged',action='store_true');p.add_argument('--report-only',action='store_true');a=p.parse_args();rows=[];problems=[];secrets=[]
    for rel,data,mode in blobs(candidates(a.staged),a.staged):
        path=Path(rel);row={'path':rel,'bytes':len(data)};rows.append(row)
        if mode not in {'100644','100755'}:problems.append({**row,'reason':'Unapproved index mode / linked file'})
        if len(data)>MAX_FILE:problems.append({**row,'reason':'File exceeds 25 decimal MB'})
        if path.suffix.lower() in FORBIDDEN or set(path.parts)&DENIED_DIRS or any(n.startswith('.venv-') for n in path.parts):problems.append({**row,'reason':'Binary/environment/private path staged'})
        if 'credential' in path.name.lower() and rel.startswith('work/hosting/'):problems.append({**row,'reason':'Credential helper/trace selected'})
        if path.suffix.lower()=='.pdf':
            from pypdf import PdfReader
            text='\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(data)).pages)
        else:
            try:text=data.decode('utf-8-sig')
            except UnicodeDecodeError:
                problems.append({**row,'reason':'Unapproved non-text binary'});continue
            if b'\x00' in data:problems.append({**row,'reason':'Binary NUL in source candidate'})
        secrets.extend(secret_hits(text,rel))
    result={'passed':not problems and not secrets,'scope':'actual staged blobs' if a.staged else 'ripgrep Git-ignore-aware candidates before init','files':len(rows),'totalBytes':sum(r['bytes'] for r in rows),'largestFiles':sorted(rows,key=lambda r:r['bytes'],reverse=True)[:12],'limitPerFile':MAX_FILE,'fileProblems':problems,'secretFindings':secrets,'secretValuesPrinted':False,'note':'Pattern scanning is supplemented by review of hosting/access/deployment sources; it is not proof that arbitrary secrets cannot exist.'}
    name='staged-git-hygiene' if a.staged else 'preinit-git-hygiene'
    # Keep the dated Windows receipt; other platforms write a platform-suffixed copy.
    OUT.mkdir(parents=True,exist_ok=True);dest=OUT/(name+'.json' if os.name=='nt' else f'{name}-{sys.platform}.json');dest.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
    if not result['passed'] and not a.report_only:raise SystemExit(1)
if __name__=='__main__':main()
