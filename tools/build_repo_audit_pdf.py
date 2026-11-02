"""Build the repository map, source explanations and complete per-file register.

The PDF contains a readable architectural guide followed by every inventoried
path. Long appendices are searchable and bookmarked. No reconstruction or
network action runs here. Only this audit's PDF and QA sidecars are written.
"""
from pathlib import Path
from collections import Counter,defaultdict
from xml.sax.saxutils import escape
import csv,hashlib,io,json,math,re,sys,textwrap
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from pypdf import PdfReader,PdfWriter
from PIL import Image
import repo_audit as a

ROOT=a.ROOT;D=a.AUDIT;OUTPUT=ROOT/'output/pdf/Rumah_Repository_Map_and_Cleanup_Audit_2026-11-01.pdf'
# ponytail: off Windows the same names alias reportlab's built-in Type 1 fonts (WinAnsi only; metrics differ slightly).
for name,file,builtin in [('Arial','arial.ttf','Helvetica'),('Arial-Bold','arialbd.ttf','Helvetica-Bold'),('Arial-Italic','ariali.ttf','Helvetica-Oblique'),('Consolas','consola.ttf','Courier')]:pdfmetrics.registerFont(TTFont(name,'C:/Windows/Fonts/'+file) if Path('C:/Windows/Fonts/'+file).is_file() else pdfmetrics.Font(name,builtin,'WinAnsiEncoding'))
pdfmetrics.registerFontFamily('Arial',normal='Arial',bold='Arial-Bold',italic='Arial-Italic',boldItalic='Arial-Bold');pdfmetrics.registerFontFamily('Consolas')
INK=colors.HexColor('#19313e');MUTED=colors.HexColor('#58707e');TEAL=colors.HexColor('#117c80');PALE=colors.HexColor('#edf3f5');LINE=colors.HexColor('#d1dde2')
PW,PH=841.89,595.28;M=34;W=PW-2*M
S=ParagraphStyle('body',fontName='Arial',fontSize=10.2,leading=14,textColor=INK)
SM=ParagraphStyle('small',parent=S,fontSize=8.4,leading=11.2)
CELL=ParagraphStyle('cell',parent=S,fontSize=8.2,leading=10.8)

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def size(n):
    if n>=1e9:return f'{n/1e9:.3f} GB'
    if n>=1e6:return f'{n/1e6:.2f} MB'
    if n>=1e3:return f'{n/1e3:.1f} kB'
    return f'{n} B'

def fitted_lines(text,font,size,width):
    """Wrap even long hashes/filenames within their measured column width."""
    lines=[];line=''
    for char in text:
        if line and pdfmetrics.stringWidth(line+char,font,size)>width:
            lines.append(line);line=''
        line+=char
    return lines+[line] if line else lines or ['']

class Report:
    def __init__(self):
        OUTPUT.parent.mkdir(parents=True,exist_ok=True);self.c=canvas.Canvas(str(OUTPUT),pagesize=(PW,PH),pageCompression=1);self.c.setTitle('Rumah repository map, cleanup and asset backup audit - 2026-11-01');self.c.setAuthor('Codex - project audit handoff');self.pg=0;self.y=0;self.section='';self.anchors=[];self.record_pages={};self.source_count=0;self.registry_count=0;self.layout_errors=[]
    def page(self,title,subtitle='',bookmark=True,level=0):
        if self.pg:self.c.showPage()
        self.pg+=1
        if bookmark:self.section=title
        c=self.c;c.setFillColor(TEAL);c.rect(0,PH-7,PW,7,fill=1,stroke=0);c.setFillColor(MUTED);c.setFont('Arial',8);c.drawString(M,PH-26,'RUMAH / REPOSITORY MAP AND CLEANUP AUDIT / 01 NOV 2026')
        fs=min(18,18*W/max(W,pdfmetrics.stringWidth(title,'Arial-Bold',18)));c.setFont('Arial-Bold',fs);c.setFillColor(INK);c.drawString(M,PH-51,title)
        c.setFont('Arial',7.2);c.setFillColor(MUTED);c.drawString(M,20,'Local audit. Public release unchanged. Sizes are decimal unless marked MiB; hardlinks can share storage.');c.drawRightString(PW-M,20,str(self.pg));self.y=PH-68
        if bookmark:
            dest='section-'+str(len(self.anchors));c.bookmarkPage(dest);c.addOutlineEntry(title,dest,level=level,closed=level>0);self.anchors.append({'title':title,'page':self.pg,'destination':dest})
        if subtitle:self.para(subtitle,SM)
    def need(self,h):
        if self.y-h<40:self.page(self.section+' (continued)',bookmark=False)
    def para(self,text,style=S):
        p=Paragraph(text,style);_,h=p.wrap(W,1000);self.need(h+8);p.drawOn(self.c,M,self.y-h);self.y-=h+8
    def heading(self,text):
        self.need(35);self.c.setFont('Arial-Bold',11);self.c.setFillColor(TEAL);self.c.drawString(M,self.y-13,text);self.y-=23
    def table(self,headers,rows,widths,style=CELL):
        def row(data,header=False):
            cells=[Paragraph(escape(str(t)),style) for t in data];heights=[p.wrap(w-12,1000)[1] for p,w in zip(cells,widths)];h=max(heights)+10
            if self.y-h<40:
                self.page(self.section+' (continued)',bookmark=False)
                if not header:row(headers,True)
            c=self.c
            if header:c.setFillColor(PALE);c.rect(M,self.y-h,W,h,fill=1,stroke=0)
            x=M
            for p,w,hh in zip(cells,widths,heights):p.drawOn(c,x+6,self.y-5-hh);x+=w
            c.setStrokeColor(LINE);c.setLineWidth(.35);c.line(M,self.y-h,PW-M,self.y-h);self.y-=h
        row(headers,True)
        for data in rows:row(data)
        self.y-=9
    def mono(self,text,fs=9):
        lines=[]
        for line in text.splitlines():lines.extend(textwrap.wrap(line,width=126,break_long_words=True,replace_whitespace=False,drop_whitespace=False) or [''])
        self.need(len(lines)*(fs+3)+8);self.c.setFont('Consolas',fs);self.c.setFillColor(INK)
        for line in lines:self.c.drawString(M,self.y-fs,line);self.y-=fs+3
        self.y-=8
    def box(self,x,y,w,h,title,body,fill=PALE):
        c=self.c;c.setFillColor(fill);c.roundRect(x,y-h,w,h,7,fill=1,stroke=0);c.setFillColor(INK);c.setFont('Arial-Bold',10);c.drawString(x+10,y-20,title);p=Paragraph(body,SM);_,hh=p.wrap(w-20,h-30);p.drawOn(c,x+10,y-29-hh)
    def arrow(self,x1,y1,x2,y2):
        c=self.c;c.setStrokeColor(TEAL);c.setLineWidth(1.3);c.line(x1,y1,x2,y2);ang=math.atan2(y2-y1,x2-x1)
        for d in [-.45,.45]:c.line(x2,y2,x2-7*math.cos(ang+d),y2-7*math.sin(ang+d))

def guide(r,inv,before,cleanup,manifest,deps):
    files=inv['files'];stats=inv['summary'];bk=manifest['summary']
    r.page('Repository audit: start here')
    r.para(f'This handoff maps <b>{len(files):,} retained files</b> and documents the cleanup of <b>{cleanup["filesDeleted"]:,} named generated/redundant files</b> ({size(cleanup["logicalBytesRemoved"])}). Original reconstruction/viewer code, unique models, source footage, masks/calibration and completed reports were preserved. No public-server change or new training run was made.')
    r.table(['Measure','Result / interpretation'],[
        ['Workspace',str(ROOT)],['Git state','No .git metadata in this workspace or its parent chain. No repository was initialized, committed or pushed.'],['Before cleanup',f'{before["summary"]["files"]:,} files; {size(before["summary"]["logical_bytes"])} logical file bytes.'],['After cleanup',f'{len(files):,} files; {size(stats["logical_bytes"])} logical bytes; {size(stats["unique_local_file_identity_bytes"])} across distinct local file identities.'],['Cloud assets',f'{bk["verified_assets"]}/{bk["asset_count"]} verified: {bk["models"]} unique 3D exports/seed models plus original OSV and matching LRF; {size(bk["unique_bytes"])}.'],['Current public release','20261031-osmo-clean-v1. Latest local 20261101-osmo-parity-review failed visual acceptance and was not deployed.'],
    ],[145,W-145])
    r.para('<b>How to use this PDF:</b> read the map, workflow and retention guidance first. The authored-file section explains each source/test file. The full register then lists every retained path, purpose class, importance and byte count, including vendor and evidence files. Use PDF bookmarks and search for a filename. An embedded CSV provides the same complete register for sorting.')

    r.page('Workspace map: current, shared and historical branches')
    r.box(M,510,245,105,'Public release sources','work/osmo-clean-20261031/<br/>review/production/<br/><b>Current live baseline and rollback identity.</b>')
    r.box(M+264,510,245,105,'Latest local review','work/osmo-parity-20261101/<br/>review/production/<br/><b>Controls fixed; model quality gates failed.</b>')
    r.box(M+528,510,245,105,'Read-first records','README.md<br/>assets-manifest.json<br/>docs/repo-audit-2026-11-01/<br/><b>Map, asset identities and deletion receipts.</b>')
    r.box(M,375,245,130,'Shared reconstruction foundation','osmo-clean: geometry/ and masking/<br/>osmo-reconstruct: seed_fisheye.py<br/>osmo-improve: photo_bake_agent.py<br/><b>Later scripts import these across folders.</b>')
    r.box(M+264,375,245,130,'Shared local tool environment','mobile-20261029/package-lock.json<br/>node_modules; pydeps; tsdfdeps<br/>osmo-clean/runtime/spirula-2026.10.30/<br/><b>Keep versions and restore paths together.</b>')
    r.box(M+528,375,245,130,'Historical / review material','osmo-web-20261031, -v2, -v3<br/>hosting; fullheight; reports<br/>outputs; reference_pack snapshots<br/><b>Archive/review before removing.</b>')
    r.box(M,215,W,90,'External capture data and cloud assets','The capture datasets are outside this workspace under the OneDrive roomscan data directory. Models/video have a separate Drive identity map. The local working folder layout is intentionally retained because older scripts use direct cross-folder and absolute paths.')
    r.arrow(M+122,405,M+122,375);r.arrow(M+386,405,M+386,375);r.arrow(M+122,245,M+190,215);r.arrow(M+386,245,M+400,215)
    r.y=100;r.para('This is a dependency map of the project workspace, not the website navigation tree. Green/teal boxes identify code roles; they are not a model-quality sign-off.',SM)

    r.page('Video-to-model-to-website: file responsibilities')
    steps=[
      ('1. Capture and transfer','External originals/*.OSV and *.LRF; work/import-osmo-20261031/transfer-receipt.json','OSV is the high-quality DJI Osmo 360 capture. LRF is its low-resolution preview. The receipt records the original card transfer and hashes.'),
      ('2. Decode and calibrate','work/osmo-format-20261031/; work/osmo-clean-20261031/select_frames.py; geometry/','Native lens frames, calibration interpretation, adaptive timestamps, one coherent SfM component and one +Y-up normalization.'),
      ('3. Exclude operator and mirrors','work/osmo-clean-20261031/masking/ and external dataset/masks/','Reviewed per-frame masks and annotations are input evidence, not disposable screenshot clutter.'),
      ('4. Materialize pinholes / guidance','build_explicit_pinhole.py; fit_explicit_depth.py; validate_explicit_depth.py','Calibrated virtual RGB/masks, cross-time-validated ray-depth maps and the train-only dense seed. Shared poses and scale must remain consistent.'),
      ('5. Train and review','run_logged_job.py; pilot-runs.py; start-full.py; external training directories','Commands, configurations, logs, raw PLY, evaluation and acceptance records. The new 50k run is complete but rejected visually.'),
      ('6. Pack, build, gate, deploy','pack-sog.py; production/build.mjs; candidate.json; prepare-deploy.py','The packed asset and source cameras feed the viewer. Quota and quality gates identify the exact release. Deployment templates are operational actions, not normal audit commands.'),
    ]
    r.table(['Stage','Files / locations','Why they matter'],steps,[130,285,W-415])

    r.page('Local-only data and the external dataset map')
    base='C:/Users/bombe/OneDrive/Documents/ChatGPT/Ruang Kamare/roomscan-reconstruction/data/'
    r.para('External capture root: <b>'+escape(base)+'</b>. These datasets are not part of the '+f'{len(files):,}'+'-file workspace register. A directory being under OneDrive is a location statement; this audit does not certify its sync state.')
    r.table(['Relative external location','Contents / importance','Retention'],[
      ['20261027_IPHONE_WIDE/','iPhone source/reconstruction data. Protected Fast/Full exports are separately identified.','Keep if rebuilding iPhone.'],
      ['20261031_OSMO360/originals/','CAM_20261031005909_0004_D.OSV and its LRF proxy. Both uploaded as complete original files.','Original capture: keep.'],
      ['20261031_OSMO360/clean-v3/dataset/','Native 3840px fisheye RGB, masks and calibrated SfM.','Foundation; not covered by export-only backup.'],
      ['20261031_OSMO360/clean-v3/explicit-full-v1/','Pinhole dataset, 439 trusted maps, dense seed and current-release training.','Preserve calibration/masks/guidance and needed training state.'],
      ['20261031_OSMO360/parity-20261101/','1600px dataset, matched pilots, diagnostics and latest 50k run.','Latest rejected experiment and reproducibility inputs.'],
      ['20261019_095800/','Legacy capture/runtime location referenced by older helpers.','Inspect actual shared runtimes before deleting by date/name.'],
    ],[270,355,W-625])
    r.para('<b>Backup scope:</b> exported 3D files and original OSV/LRF are backed up. Full optimizer checkpoints, every extracted RGB frame, mask set, COLMAP database and external environment are not all included in that export backup. Keep the corresponding external inputs when reconstruction or exact training resumption matters.',SM)

    r.page('Directory guide and removal priorities')
    phase_rows=[]
    for phase,info in stats['phases'].items():phase_rows.append([phase,a.PHASES.get(phase,''),f'{info["files"]:,}',size(info['logical_bytes'])])
    r.table(['Area under work/ unless root','Purpose / importance','Files','Logical bytes'],phase_rows,[165,440,60,W-665])
    r.para('The byte column is a logical total, including aliases. It is not a promise of recoverable disk space. Many public model copies are hardlinks to the same file identity.',SM)

    r.page('Canonical files: what to preserve first')
    r.table(['Path / group','Role and importance'],[
      ['work/osmo-clean-20261031/review/production/','Live baseline: viewer source, candidate, manifests, approval record and exact build closure. Preserve for maintenance/rollback.'],
      ['work/osmo-parity-20261101/EXECUTION-STATE.json and acceptance-gates.json','Latest state and mandatory failed release gates. Do not replace them with a generic successful-load statement.'],
      ['work/osmo-parity-20261101/review/production/','Latest authored controls and local build. release-approval.json is false.'],
      ['work/osmo-clean-20261031/geometry/ and masking/','Actual calibration, normalization, continuity and source-mask evidence.'],
      ['work/osmo-reconstruct-20261031/seed_fisheye.py','Shared COLMAP and fisheye utility; later scripts import it directly.'],
      ['work/osmo-improve-20261031/photo_bake_agent.py','Shared photographic visibility/baking logic and source of copied pilot implementations.'],
      ['work/mobile-20261029/package.json and package-lock.json','Pinned common Three.js, Spark-adjacent build/packing dependencies. Other stages resolve packages from this installation.'],
      ['assets-manifest.json and this audit records','Restore identities, local aliases, cloud links, removal journal and confidence labels.'],
    ],[330,W-330])

    r.page('Cleanup performed: exact boundaries and receipts')
    reasons=Counter()
    plan=read(D/'cleanup-plan.json')
    for row in plan['targets']:reasons[row['reason']]+=1
    r.table(['Removed family / reason','Files'],[[reason,n] for reason,n in reasons.items()],[W-65,65])
    r.para(f'Total: <b>{cleanup["filesDeleted"]:,} exact file deletions</b>, <b>{cleanup["logicalBytesRemoved"]:,} bytes</b> ({cleanup["logicalBytesRemoved"]/1024/1024:.2f} MiB). No recursive deletion was used. Every target was checked for workspace containment, kind, size, file identity and SHA before deletion. The duplicate verification download was checked against the retained canonical iPhone Full hash.')
    r.para(f'<b>{cleanup["authoredCodeFilesVerifiedUnchanged"]} catalogued source/test files matched their saved hashes immediately after cleanup.</b> A separate final check preserves all pre-existing reconstruction/viewer code; the new audit helpers and start-here files are explicit additions. No unique model, video, external capture file, completed report or source calibration/mask was removed.')
    r.para('Receipts: docs/repo-audit-2026-11-01/cleanup-plan.json, cleanup-journal.jsonl, cleanup-result.json and source-preservation-check.json. Each removed path retains its reason, hash and regeneration source in the journal.',SM)
    preserved=read(D/'model-preservation-check.json')
    r.para(f'After cleanup and completed uploads, all <b>{preserved["assetsChecked"]} original asset sources</b> were read again in full and matched their saved SHA-256, MD5 and byte counts. Local model-preservation-check.json records the results.',SM)

    r.page('Why hardlinks change the storage calculation')
    r.para(f'Before cleanup the folder reported {size(before["summary"]["logical_bytes"])} when every path was added. Distinct local file identities accounted for {size(before["summary"]["unique_local_file_identity_bytes"])}. Multiple filenames can refer to the same bytes. A hardlink is different from a separate byte-identical copy.')
    r.table(['Case','Practical effect','Audit rule'],[
      ['Same device/file ID, several paths','Hardlinked aliases share one underlying file. Removing one alias usually frees no payload bytes while another link remains.','Preserve required paths or update references; do not sum alias sizes as recoverable space.'],
      ['Same SHA, different file IDs','Independent byte-identical copies consume separate storage. One verified download copy was removed in this cleanup.','Keep a canonical copy and identity/restore record before dropping duplicates.'],
      ['Links outside the workspace','A file may remain allocated after all local aliases are removed. External training checkpoints often share links with local QA copies.','The catalog includes link count and file ID; inspect external ownership before estimating savings.'],
      ['Temporary browser-upload aliases','Large uploads used hardlinks in a named Windows Temp staging folder to supply clear filenames, without duplicating payloads.','Remove only staging aliases after Drive completion/readback; keep every original.'],
    ],[190,315,W-505])
    r.para('The cleanup estimate is based on complete selected link sets. The measured volume free-space delta can differ slightly because other applications write to the same drive.',SM)

    r.page('Cloud archive: identity, verification and scope')
    r.para('Destination: <link href="'+manifest['drive_folder_url']+'" color="#117c80">Rumah - 2026-11-01 - Models and 360 Source</link>. The existing parent-folder ZIP was preserved. Subfolders separate Models, 360 Source Video and Audit Documents. No permission/ownership change was made; the new files follow the destination folder organization.')
    r.table(['Measure','Value'],[['Unique assets',bk['asset_count']],['3D exports / seed models',bk['models']],['Original video and proxy',bk['source_files']],['Verified files',bk['verified_assets']],['Total unique payload',f'{bk["unique_bytes"]:,} bytes ({size(bk["unique_bytes"])})'],['Deduplication','Every complete SHA-256 identity uploaded once; all original local aliases retained in assets-manifest.json.'],['Verification','Drive exact filename, byte count and target parent checked after upload. Browser uploads also reached a complete state. Local full SHA-256/MD5 are provided.'],['Checksum limit','The connector normalizes away remote checksum fields. Local hashes are not falsely presented as remote checksum readback.'],['Large-file transport','Connector limits were encountered; normal Chrome file upload was used after the user enabled the extension file-access setting. Original files were not split.']],[180,W-180])
    r.para('Live iPhone Fast/Full and Osmo have explicit names. The newer packed Osmo candidate is named REVIEW-REJECTED. Historical and diagnostic raw/packed variants remain identifiable; backing up an export does not approve it for deployment.',SM)
    proof=D/'drive-model-upload-complete.jpg'
    if proof.is_file():
        r.page('Drive proof: large-model batch completed')
        image=Image.open(proof);height=W*image.height/image.width;r.c.drawImage(str(proof),M,r.y-height,width=W,height=height);r.y-=height+7
        r.para('Chrome shows the completed 23-file large-model batch. The 31 smaller models and original/proxy files are additionally checked by exact Drive metadata readback; the final manifest records all 56 identities.',SM)

    r.page('What the next auditor can reduce')
    r.table(['Candidate family','Conditions before removal','Expected consequence'],[
      ['Retired public/ bundles and transport archives','Keep the current live/review source, exact manifest, original model mapping and necessary historical receipts. Verify restoration from Drive and build inputs.','Can remove generated copies, but hardlinks may provide little immediate disk saving.'],
      ['Old intermediate PLY/GLB variants','Use the asset register and cloud links; choose which diagnostic stages are no longer needed locally. Retain the agreed canonical model and useful raw source.','Large possible reduction; changes which historical experiments can be opened immediately.'],
      ['Historical code snapshots / old viewer releases','Check cross-folder imports and preserve documentation/provenance. Date or a matching filename alone does not prove a file is unused.','Simplifies navigation; may break old reproducibility paths unless references are migrated.'],
      ['Local dependency folders','Keep lockfiles, installed versions, native/platform requirements and a tested restore path. These were retained today.','Frees reinstallable packages; current builds may need environment restoration.'],
      ['Remaining tmp/ photos / metadata','Only PDF page renders/contact montages were pruned. Remaining files may be unique report inputs or diagnostic photographs.','Inspect actual provenance before extending the cleanup to all tmp/.'],
      ['External capture datasets','They are outside this local-repo cleanup and not fully covered by the export/video backup.','Do not infer that an exported model preserves masks, calibration, source frames or optimizer state.'],
    ],[190,380,W-570])

    r.page('Importance and confidence legend')
    r.table(['Importance label','Interpretation'],[
      ['START HERE','Root navigation, exclusions and cloud asset identity map.'],['LIVE BASELINE','Recorded public-release code/metadata needed for maintenance and rollback.'],['CURRENT REVIEW','Latest local experiment and acceptance evidence; not an approved public model.'],['FOUNDATION','Geometry, source masks, calibration and normalization inputs/tools.'],['SHARED CORE','Helpers or dependency anchors reused across stage directories.'],['LOCAL DEPENDENCY','Third-party/pinned local software. Excluded from Git; restore requirements matter.'],['BACKED-UP ASSET','3D payload mapped to the cloud archive; retain canonical identity before deleting local copies.'],['USER EXPORT','Delivered report, offline viewer or other requested artifact.'],['REBUILDABLE','Compiled web asset or similar generated output. Check build/source closure.'],['HISTORY / EVIDENCE or SHARED / HISTORY','Historical methods, copies and records. They can still be imported or required to reproduce older results.'],['REVIEW','Unresolved or intermediate file. Inspect before removing.'],
    ],[200,W-200])
    r.para('Purpose confidence is explicit in the detailed source section and CSV: reviewed filename/source context, module docstring, package/path classification, or name/path inference. Filename-reference candidates are hints; constructed paths can be missed and duplicate basenames can be ambiguous. The historical 212-node Graphify graph covers only an earlier subset. It is not an unused-file detector.',SM)

    r.page('Installed dependencies and restore anchors')
    r.para('The shared Node installation is anchored by work/mobile-20261029/package.json and package-lock.json. Direct versions recorded there: Three.js 0.180.0, glTF-Transform 4.5.1, meshoptimizer 0.25.0 and esbuild 0.25.11. Browser Spark is vendored separately. Keep the package metadata with the source that resolves into this shared installation.')
    for env in deps:
        r.heading(env['path']);text=', '.join(p['name']+' '+p['version'] for p in env['packages']) or 'No distribution metadata was found here; inspect pinned binary/source provenance.';r.para(escape(text),SM)
    r.para('The Windows CPython 3.12 and 3.14 tools are used for different tasks in this project. Compiled Python modules are platform/ABI-specific; package lists from separate directories are not one interchangeable environment. The pinned Spirula executable under osmo-clean/runtime is the known working trainer/mesh tool and was retained.',SM)

    r.page('Audit outputs and reproducible entry points')
    r.table(['File','Purpose'],[
      ['README.md','Short root map, current-release state and external-data locations.'],['.gitignore','Excludes binary models/media, installed tool environments and generated outputs from future Git adds. No files are deleted by ignore rules.'],['assets-manifest.json','Small root identity/restore map with local aliases and observed Drive links.'],['tools/repo_audit.py','Read-only inventory and model/video hashing; writes audit metadata.'],['tools/cleanup_repo.py','Dated exact-file cleanup planner/apply helper, with containment and hash checks. Execution journal blocks blind repeat.'],['tools/finalize_repo_audit.py','Merges verified upload receipts, creates enriched per-file catalog and dependency version evidence.'],['tools/build_repo_audit_pdf.py','Creates this PDF, full file appendix and embedded catalog.'],['docs/repo-audit-2026-11-01/','Generated before/after inventories, complete CSV, deletion receipts and Drive verification records. Excluded from its own inventory to prevent recursion.'],
    ],[295,W-295])
    r.para('Read-only inventory command: <font face="Consolas">python -B tools/repo_audit.py --label audit</font>. The optional --assets flag hashes full model/video bytes. These tools do not train, deploy or change the public server. Rebuild source environments and assets before running old stage scripts.',SM)
    git=read(D/'git-ignore-audit.json')
    r.para(f'The explicit ignore-pattern estimate excludes all {git["modelPathsChecked"]} model paths from a future source checkout. It leaves approximately {git["candidateFiles"]:,} file candidates ({size(git["candidateLogicalBytes"])}), before a dedicated source/security review. This is an estimate, not a Git status result: there is no initialized repository.',SM)
    r.page('Generated audit pack: supporting file map')
    notes={'inventory-before.json':'Full pre-cleanup snapshot; includes the removed-file identities.','inventory-after.json':'Enriched retained-file register used to author this PDF.','file-catalog-before.csv':'Spreadsheet-friendly pre-cleanup snapshot.','file-catalog-after.csv':'Complete retained per-file CSV, also embedded in this PDF.','cleanup-plan.json':'Reviewed target list, reason, regeneration source and hashes.','cleanup-journal.jsonl':'Exact completed per-file deletion record.','cleanup-result.json':'Cleanup totals and preservation boundaries.','source-preservation-check.json':'Hash check of pre-existing reconstruction/viewer source and tests.','asset-upload-queue.json':'Unique full-content model/video hashes and all original aliases.','drive-upload-journal.jsonl':'Upload attempts and later verified receipts; verified SHA identities supersede failed connector attempts.','drive-destination.json':'Observed destination folder IDs.','backup-summary.json':'Count/bytes of complete verified asset uploads.','browser-upload-models.json':'Temporary hardlink staging list used for large single-file browser uploads.','browser-staging-cleanup.json':'Proof that only staging aliases were removed after completed uploads.','drive-model-upload-complete.jpg':'Browser screenshot of completed large-model batch.','local-dependency-versions.json':'Installed package/version evidence from separate local environments.','pdf-audit.json':'PDF hash, page count, bookmarks and file-ID-to-page index.','pdf-text-verification.json':'Independent extraction/count/attachment verification.','pdf-visual-verification.json':'Rendered-page layout review record.','model-preservation-check.json':'Post-cleanup local full-content SHA check of every upload source.','git-ignore-audit.json':'File-pattern estimate of source candidates and excluded binary assets.'}
    notes['audit-document-upload-journal.jsonl']='Verified Drive receipts for the final PDF, complete CSV, identity manifest and supporting cleanup/preservation records.'
    listed=sorted(set(p.name for p in D.iterdir() if p.is_file())|{'pdf-text-verification.json','pdf-visual-verification.json','model-preservation-check.json','git-ignore-audit.json','audit-document-upload-journal.jsonl'})
    r.table(['File under docs/repo-audit-2026-11-01/','Purpose / importance'],[[name,notes.get(name,'Generated supporting audit evidence; retain with this handoff until review completes.')] for name in listed],[310,W-310])

def source_appendix(r,files):
    source=[f for f in files if f['role'] in {'CORE','TEST'}]
    r.page('Authored source and tests: file-by-file explanations')
    r.para(f'This section explains all {len(source):,} source/configuration/test files classified as first-party. The complete register later includes compiled builds, every metadata/evidence file and every third-party file as well. Phase context matters: a familiar filename in an old snapshot is not the current implementation.')
    previous=None
    for f in source:
        if f['phase']!=previous:
            previous=f['phase'];r.page('Source files: '+previous,escape(a.PHASES.get(previous,'')),level=1)
        refs=f.get('reference_candidates',[])
        note=f'Importance: <b>{escape(f["importance"])}</b>. Purpose basis: {escape(f["basis"])}.'
        if refs:note+=f' {len(refs)} textual filename-reference candidates; inspect exact imports/constructed paths before deletion.'
        r.need(80);r.para('<font face="Consolas" size="8.5">'+escape(f['path'])+'</font>',SM);r.para(escape(f['purpose']),S);r.para(note,SM);r.source_count+=1

def asset_appendix(r,manifest):
    r.page('3D model and original-video archive register')
    r.para('Each asset ID denotes one complete SHA-256 identity, not one local filename. The local aliases remain in assets-manifest.json and the CSV. Click a verified Drive name to open its archived file. Native/uncompressed and packed variants are distinct identities; backup status does not imply visual acceptance.')
    for asset in manifest['assets']:
        r.need(92)
        title=escape(asset['asset_id']+' - '+asset['drive_name'])
        if asset.get('drive_url'):title='<link href="'+asset['drive_url']+'" color="#117c80">'+title+'</link>'
        r.para('<b>'+title+'</b>',SM)
        r.para(escape(asset['status'])+f'; {asset["bytes"]:,} bytes; '+asset['upload_status']+'. '+str(len(asset['local_paths']))+' original local path(s).',SM)
        r.para('<font face="Consolas" size="8">SHA256 '+asset['sha256']+'</font>',SM)
        r.para('Local location: '+escape(asset['local_paths'][0]['path']),SM)

def brief(f):
    role=f['role'];p=Path(f['path']);name=p.name.lower();parts=p.parts
    if role in {'CORE','TEST'}:return 'Authored source' if role=='CORE' else 'Verification / regression'
    if role=='MODEL':return '3D model; '+f.get('asset_id','inspect manifest')
    if role=='VENDOR' or role=='RUNTIME':
        anchor=next((x for x in parts if x in a.DEPENDENCIES or x.startswith('source-v20')),None);index=parts.index(anchor) if anchor else -1;package=parts[index+1] if index>=0 and index+1<len(parts) else 'dependency'
        ext=p.suffix.lower();kind='Python module' if ext=='.py' else 'native module/tool' if ext in {'.pyd','.dll','.exe','.so'} else 'JS/TS module' if ext in {'.js','.mjs','.ts'} else 'package data/metadata'
        return (package+' / '+kind)[:90]
    if role=='MEDIA':
        if 'masking' in parts or 'masks' in parts:return 'Mask/source-review image'
        if 'qa' in parts or 'display-ablation' in parts:return 'Fixed-view QA / reference'
        if 'sources' in parts:return 'Viewer source photograph'
        return 'Reference/evidence image'
    if role=='AUDIT':
        if p.suffix in {'.npz','.npy'}:return 'Geometry / measurement arrays'
        if 'camera' in name or 'pose' in name:return 'Calibrated cameras / poses'
        if 'mask' in name:return 'Mask review / provenance'
        if 'approval' in name or 'acceptance' in name:return 'Release acceptance / refusal'
        if 'train' in name or 'request' in name or 'job' in name:return 'Pipeline command / status'
        if 'manifest' in name or 'build' in name:return 'Build / asset inventory'
        if 'eval' in name or 'score' in name:return 'Image-quality measurements'
        if 'photo' in name or 'bake' in name:return 'Photo-texture audit record'
        if 'config' in name:return 'Processing parameters'
        if any(x in name for x in ['verify','verification','audit','check','report']):return 'Validation / audit result'
        if '.log' in name or '.jsonl' in name:return 'Process / request log'
        return 'Stage metadata / provenance'
    return {'REPORT':'User-facing report / offline export','ARCHIVE':'Packaged archive / transport','BUILD':'Generated browser build','TEMP':'Temporary derivative; review','OTHER':'Binary format diagnostic; inspect'}.get(role,a.ROLES[role][0])

def register(r,files):
    r.page('Complete retained-file register')
    r.para(f'All {len(files):,} retained paths are listed below. A directory header supplies the parent path; each row supplies the complete basename, purpose and importance. Every F-number uniquely identifies a full path in the embedded CSV. Exact byte counts are logical; use file ID/link count in the CSV to distinguish hardlinks.')
    r.para('The register includes dependency libraries and every evidence image, not only hand-picked source files. The generated audit pack, its own PDF and render scratch are excluded to prevent self-reference; the preceding evidence-map section names those outputs. A short role label is a file-purpose classification, not a finding that an individual dependency is unused.',SM)
    phase=None;parent=None;header_y=None
    widths=[350,225,96,69,W-740];xs=[M]
    for width in widths[:-1]:xs.append(xs[-1]+width)
    def columns():
        nonlocal header_y
        r.c.setFillColor(PALE);r.c.rect(M,r.y-18,W,18,fill=1,stroke=0);r.c.setFillColor(INK);r.c.setFont('Arial-Bold',7.5)
        for x,t in zip(xs,['Filename under current directory','Purpose / role','Importance','Bytes','ID']):r.c.drawString(x+3,r.y-12,t)
        r.y-=21;header_y=r.y
    def dir_header(path,continued=False):
        lines=textwrap.wrap(path+('/ (continued)' if continued else '/'),width=164,break_long_words=True,break_on_hyphens=False) or ['/']
        h=len(lines)*10+7
        r.c.setFillColor(TEAL);r.c.setFont('Consolas',7.5)
        for line in lines:r.c.drawString(M+2,r.y-9,line);r.y-=10
        r.y-=7
        return h
    for f in files:
        p=Path(f['path']);current=str(p.parent).replace('\\','/');current='.' if current=='.' else current
        if f['phase']!=phase:
            phase=f['phase'];parent=None;r.page('File register: '+phase,escape(a.PHASES.get(phase,'')),level=1);columns()
        name_lines=fitted_lines(p.name,'Consolas',7,widths[0]-8)
        role_lines=fitted_lines(brief(f),'Arial',7.1,widths[1]-8)
        imp_lines=fitted_lines(f['importance'],'Arial',7.1,widths[2]-8)
        h=max(len(name_lines),len(role_lines),len(imp_lines))*9.2+4
        extra=27 if current!=parent else 0
        if r.y-h-extra<42:
            r.page('File register: '+phase+' (continued)',bookmark=False);columns();dir_header(current,True);parent=current
        elif current!=parent:dir_header(current);parent=current
        if r.y-h<40:raise ValueError('Registry row does not fit '+f['path'])
        top=r.y;c=r.c;c.setFillColor(INK);c.setFont('Consolas',7)
        for i,line in enumerate(name_lines):c.drawString(xs[0]+3,top-8.5-i*9.2,line)
        c.setFont('Arial',7.1)
        for i,line in enumerate(role_lines):c.drawString(xs[1]+3,top-8.5-i*9.2,line)
        for i,line in enumerate(imp_lines):c.drawString(xs[2]+3,top-8.5-i*9.2,line)
        c.setFont('Consolas',7);c.drawRightString(xs[3]+widths[3]-4,top-8.5,f'{f["bytes"]:,}');c.drawString(xs[4]+2,top-8.5,f['catalog_id'])
        c.setStrokeColor(LINE);c.setLineWidth(.2);c.line(M,top-h,PW-M,top-h);r.y-=h;r.registry_count+=1;r.record_pages[f['catalog_id']]=r.pg

def main():
    if (D/'deep-cleanup-result.json').exists():raise SystemExit('This finalized PDF preserves the first-cleanup snapshot. After deep cleanup use README.md and a current inventory; do not overwrite the historical handoff PDF.')
    inv=read(D/'inventory-after.json');before=read(D/'inventory-before.json');cleanup=read(D/'cleanup-result.json');manifest=read(ROOT/'assets-manifest.json');deps=read(D/'local-dependency-versions.json')
    if not manifest['summary']['all_verified']:raise ValueError('Finalize every model/video upload before authoring the final handoff PDF')
    r=Report();guide(r,inv,before,cleanup,manifest,deps);source_appendix(r,inv['files']);asset_appendix(r,manifest);register(r,inv['files']);r.c.save()
    assert r.registry_count==len(inv['files'])
    # The visible register is complete. CSV attachment additionally supports
    # sorting/filtering without copying hundreds of PDF pages into a spreadsheet.
    reader=PdfReader(OUTPUT);writer=PdfWriter();writer.clone_document_from_reader(reader);writer.add_attachment('Rumah_complete_file_catalog.csv',(D/'file-catalog-after.csv').read_bytes());raw=io.BytesIO();writer.write(raw);OUTPUT.write_bytes(raw.getvalue())
    audit={'file':str(OUTPUT),'pages':len(writer.pages),'bytes':OUTPUT.stat().st_size,'sha256':hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),'sourceFilesExplained':r.source_count,'registeredFiles':r.registry_count,'csvEmbedded':True,'bookmarks':r.anchors,'fileIdPageIndex':r.record_pages,'backupComplete':manifest['summary']['all_verified'],'visualQA':'pending'}
    (D/'pdf-audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps({k:v for k,v in audit.items() if k not in {'bookmarks','fileIdPageIndex'}},indent=2))

if __name__=='__main__':main()
