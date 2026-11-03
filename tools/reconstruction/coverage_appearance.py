"""Conservative appearance-only selection with fixed reference geometry.

Keep every quality-passed view in protected bathroom/doorway intervals. Elsewhere
retain per-lens temporal bins, the earlier eligible subset, and explicit gap
fillers. Unknown quality never becomes an eligible training view automatically.
This module selects names only: it never estimates poses, warps pixels or trains.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .capture import load_capture, sha256
from .localize_batch import write_json
from .training_views import _quality_status


@dataclass(frozen=True)
class CoverageAppearanceConfig:
    regular_bin_seconds: float = 0.10
    regular_max_gap_seconds: float = 0.15
    protected_max_gap_seconds: float = 0.10
    protected_regions: tuple[str, ...] = ("entry", "bathroom", "exit_first",
        "entry_second", "bathroom_second", "exit_second")
    min_reference_fraction: float = 1 / 3
    max_reference_fraction: float = 1 / 2
    review_spacing_seconds: float = 0.5
    max_review_candidates: int = 48

    def __post_init__(self):
        if not (0 < self.regular_bin_seconds <= self.regular_max_gap_seconds
                and self.protected_max_gap_seconds > 0 and self.review_spacing_seconds > 0):
            raise ValueError("Positive temporal floors and bin <= maximum gap required")
        if not 0 < self.min_reference_fraction <= self.max_reference_fraction <= 1:
            raise ValueError("Invalid reference fraction interval")
        if self.max_review_candidates < 1:
            raise ValueError("A positive bounded review budget is required")


def _gaps(rows, retained, maximum):
    if not rows:
        return []
    start, end = min(v['time_seconds'] for v in rows), max(v['time_seconds'] for v in rows)
    times = sorted({start, end, *(v['time_seconds'] for v in retained)})
    return [{'from_seconds': a, 'to_seconds': b, 'seconds': b-a}
            for a,b in zip(times,times[1:]) if b-a > maximum + 1e-8]


def _maximum_gap(rows, retained):
    if not rows:
        return None
    gaps = _gaps(rows, retained, -1)
    return max((g['seconds'] for g in gaps),default=0.)


def apply_scoped_reviews(quality, dataset, review, evidence_index, *, index_sha256):
    """Apply only root-approved individual views, bound to inspected source bytes.

    This changes an in-memory copy, never the original quality classification.
    Confirmed blur, heldout views, whole-lens approvals, changed pixels or missing
    mask review are rejected. A review is not geometry/publication acceptance.
    """
    if review.get('reviewer')!='root' or review.get('scope')!='single_native_view':
        raise ValueError('Explicit root per-view review is required')
    if review.get('evidence_index_sha256')!=index_sha256:
        raise ValueError('Scoped review evidence identity mismatch')
    evidence={row['image']:row for row in evidence_index['views']}
    approved=review.get('approved_views',[])
    if not approved:
        raise ValueError('At least one explicit per-view approval is required')
    if len({row['image'] for row in approved})!=len(approved):
        raise ValueError('Duplicate per-view review')
    excluded=review.get('excluded_views',[])
    if {row['image'] for row in approved}&{row['image'] for row in excluded}:
        raise ValueError('A view cannot be both approved and excluded')
    result=copy.deepcopy(quality);decisions=result.get('decisions',result);dataset=Path(dataset).resolve()
    for row in approved:
        name=row['image'];source=evidence.get(name)
        if (source is None or row.get('verdict')!='sharp' or row.get('mask_reviewed') is not True
                or row.get('approved_for_isolated_appearance_experiment') is not True
                or not str(row.get('observation','')).strip()):
            raise ValueError('Missing specific native-detail/mask review approval')
        if source['quality_status']!='review_required' or not name.endswith('_train.jpg'):
            raise ValueError('Only unknown training views may be explicitly promoted')
        frame=source['frame_id'];lens=source['lens']
        if name!=f'{lens}/frame_{frame:06d}_train.jpg' or lens not in ('cam0','cam1'):
            raise ValueError('Scoped image identity changed')
        for kind,relative,key in (('images',name,'source_image_sha256'),
                ('masks',str(Path(name).with_suffix('.png')),'source_mask_sha256')):
            path=(dataset/kind/relative).resolve()
            if not path.is_relative_to(dataset/kind) or sha256(path)!=source[key]:
                raise ValueError('Inspected source pixels or mask changed')
        decision=decisions.get(str(frame),decisions.get(frame))
        current=decision['views'][lens]
        if _quality_status(current)[0]!='review_required':
            raise ValueError('Only unknown quality can use this scoped promotion path')
        decision['views'][lens]={**current,'verdict':'sharp','confirmed':True,'training_eligible':True,
            'manual_review':{'reviewer':'root','scope':'single_native_view','observation':row['observation'],
                'source_image_sha256':source['source_image_sha256'],'source_mask_sha256':source['source_mask_sha256'],
                'evidence_index_sha256':index_sha256,'geometry_acceptance':False,'publication_acceptance':False}}
    for row in excluded:
        source=evidence.get(row['image'])
        if source is None or not str(row.get('reason','')).strip():
            raise ValueError('Explicit excluded view and mask reason required')
        decision=decisions.get(str(source['frame_id']),decisions.get(source['frame_id']))
        decision['views'][source['lens']]['appearance_blocked']={
            'reason':row['reason'],'kind':'mask_rejection','reviewer':'root','evidence_index_sha256':index_sha256}
    return result


def select_coverage_appearance(capture, quality, reference_audit, baseline,
                               regions, config=CoverageAppearanceConfig()):
    quality = quality.get('decisions', quality)
    reference = {}
    for face in reference_audit['views']:
        identity=(int(face['sourceFrame']),face['sourceSplit'])
        prior=reference.setdefault(face['sourceName'],identity)
        if prior!=identity:
            raise ValueError('Reference native name has inconsistent timestamp/split')
    baseline_names={v['image'] for v in baseline['views'] if v['split']=='train'
                    and v.get('selected') and v['status']=='eligible_pending_pose'}
    seen=set();views=[]
    for frame in sorted(capture['frames'],key=lambda f:f['id']):
        if frame['id'] in seen or not math.isfinite(frame['time_seconds']):
            raise ValueError('Capture requires unique IDs and finite timestamps')
        seen.add(frame['id'])
        if frame['split'] not in ('train','eval'):
            raise ValueError('Invalid train/eval ownership')
        memberships=[r['name'] for r in regions if r['source_frame_min']<=frame['id']<=r['source_frame_max']]
        protected=bool(set(memberships)&set(config.protected_regions))
        decision=quality.get(str(frame['id']),quality.get(frame['id']))
        if decision is None:
            raise ValueError('Every captured frame needs an explicit quality decision')
        for lens in ('cam0','cam1'):
            name=frame['images'][lens];status,reason=_quality_status(decision['views'][lens])
            available=name in reference
            if available and reference[name]!=(frame['id'],frame['split']):
                raise ValueError('Reference pose identity disagrees with original capture')
            row={'frame_id':frame['id'],'time_seconds':frame['time_seconds'],'lens':lens,
                 'image':name,'mask':frame.get('masks',{}).get(lens),'split':frame['split'],
                 'regions':memberships,'protected_coverage':protected,'selected':False,
                 'status':status,'quality_status':status,'reasons':[reason],
                 'reference_pose_available':available,'pose_source':'fixed_reference' if available else None,
                 'ready_for_training':False,'visual_acceptance_required':True}
            blocked=decision['views'][lens].get('appearance_blocked')
            if blocked:
                row['appearance_blocked']=blocked
            if decision['views'][lens].get('manual_review'):
                row['manual_quality_review']=decision['views'][lens]['manual_review']
            if frame['split']=='eval':
                row.update(status='excluded',reasons=['held_out_timestamp'])
            elif blocked:
                row.update(status='excluded',reasons=['explicit_mask_rejection'])
            elif not available:
                row['reasons'].append('missing_fixed_reference_pose')
            elif status=='eligible_pending_pose':
                if name in baseline_names:
                    row['selected']=True;row['reasons'].append('preserve_previous_quality_passed_subset')
                if protected:
                    row['selected']=True;row['reasons'].append('retain_all_passed_protected_coverage')
            views.append(row)
    train=[v for v in views if v['split']=='train']
    eligible=[v for v in train if v['quality_status']=='eligible_pending_pose' and v['reference_pose_available'] and not v.get('appearance_blocked')]
    bins=defaultdict(list)
    for view in eligible:
        if not view['protected_coverage']:
            key=(view['lens'],tuple(view['regions']),math.floor((view['time_seconds']+1e-9)/config.regular_bin_seconds))
            bins[key].append(view)
    for key,items in bins.items():
        center=(key[-1]+.5)*config.regular_bin_seconds
        choice=min(items,key=lambda v:(abs(v['time_seconds']-center),v['frame_id']))
        choice['selected']=True;choice['reasons'].append('per_lens_temporal_bin')
    # Fill intervals only with already quality-passed, reference-posed views.
    # If there is no such view, leave an explicit gap instead of rescuing blur.
    for lens in ('cam0','cam1'):
        pool=[v for v in eligible if v['lens']==lens]
        if not pool:
            continue
        for endpoint in (pool[0],pool[-1]):
            endpoint['selected']=True;endpoint['reasons'].append('capture_endpoint')
        while True:
            retained=[v for v in pool if v['selected']]
            added=False
            for a,b in zip(retained,retained[1:]):
                if b['time_seconds']-a['time_seconds']<=config.regular_max_gap_seconds+1e-8:
                    continue
                available=[v for v in pool if not v['selected'] and a['time_seconds']<v['time_seconds']<b['time_seconds']]
                if available:
                    mid=(a['time_seconds']+b['time_seconds'])/2
                    choice=min(available,key=lambda v:(abs(v['time_seconds']-mid),v['frame_id']))
                    choice['selected']=True;choice['reasons'].append('per_lens_gap_fill');added=True
            if not added:
                break
    scope_specs=[{'name':'capture','source_frame_min':min(seen),'source_frame_max':max(seen)},*regions]
    coverage=[];unresolved=[];review_by_name={}
    for region in scope_specs:
        protected=region['name'] in config.protected_regions
        maximum=config.protected_max_gap_seconds if protected else config.regular_max_gap_seconds
        for lens in ('cam0','cam1'):
            rows=[v for v in train if v['lens']==lens and region['source_frame_min']<=v['frame_id']<=region['source_frame_max']]
            posed=[v for v in rows if v['reference_pose_available']]
            selected=[v for v in rows if v['selected']]
            old=[v for v in posed if v['image'] in baseline_names]
            gaps=_gaps(rows,selected,maximum)
            coverage.append({'region':region['name'],'lens':lens,'source_train_views':len(rows),
                'reference_views':len(posed),'passed_available':sum(v['quality_status']=='eligible_pending_pose' for v in posed),
                'unknown_available':sum(v['quality_status']=='review_required' for v in posed),
                'confirmed_blur_available':sum(v['quality_status']=='excluded' for v in posed),
                'mask_rejected_available':sum(bool(v.get('appearance_blocked')) for v in posed),
                'old_selected_views':len(old),'new_selected_views':len(selected),
                'reference_max_gap_seconds':_maximum_gap(rows,posed),'old_max_gap_seconds':_maximum_gap(rows,old),
                'new_max_gap_seconds':_maximum_gap(rows,selected),'maximum_requested_gap_seconds':maximum,
                'unresolved_gap_count':len(gaps)})
            for gap in gaps:
                inner=[v for v in rows if gap['from_seconds']<v['time_seconds']<gap['to_seconds']]
                unknown=[v for v in inner if v['quality_status']=='review_required' and v['reference_pose_available'] and not v.get('appearance_blocked')]
                unresolved.append({'region':region['name'],'lens':lens,**gap,'unknown_posed_candidates':len(unknown),
                    'reason':'no_quality_passed_reference_view_can_fill_interval'})
                if region['name']=='capture':
                    continue # More useful room-specific review queue, no duplicate global proposals.
                slots=max(1,math.ceil(gap['seconds']/config.review_spacing_seconds))
                for index in range(slots):
                    if not unknown:break
                    target=gap['from_seconds']+(index+.5)*gap['seconds']/slots
                    candidate=min(unknown,key=lambda v:(abs(v['time_seconds']-target),v['frame_id']))
                    review_by_name.setdefault(candidate['image'],{'image':candidate['image'],'frame_id':candidate['frame_id'],
                        'time_seconds':candidate['time_seconds'],'lens':lens,'region':region['name'],
                        'status':'review_required','selected_for_training':False,'reference_pose_available':True,
                        'gap_seconds':gap['seconds'],'priority':0 if region['name'] in ('bathroom','bathroom_second') else (1 if protected else 2),
                        'reason':'Scoped native-detail and mask review required; no automatic promotion'})
    candidates=sorted(review_by_name.values(),key=lambda v:(v['priority'],-v['gap_seconds'],v['time_seconds'],v['lens']))
    selected=[v for v in train if v['selected']]
    full=sum(v['reference_pose_available'] for v in train);fraction=len(selected)/max(full,1)
    if any(v['status']!='eligible_pending_pose' or not v['reference_pose_available'] for v in selected):
        raise AssertionError('An unapproved/missing-pose view entered the training subset')
    return {'schema_version':1,'experiment':'coverage-aware-fixed-reference-v2',
        'source_selection_sha256':capture.get('source_selection_sha256'),'configuration':asdict(config),
        'views':views,'coverage':coverage,'unresolved_gaps':unresolved,
        'review_queue':candidates[:config.max_review_candidates],'review_candidate_count':len(candidates),
        'review_queue_truncated':len(candidates)>config.max_review_candidates,
        'eligible_view_count':len(selected),'selected_native_fraction_of_reference':fraction,
        'reference_native_training_views':full,'target_fraction_met':config.min_reference_fraction<=fraction<=config.max_reference_fraction,
        'selected_unknown_views':0,'selected_confirmed_blur_views':0,'selected_eval_views':0,
        'existing_subset_preserved':baseline_names&set(reference)<=set(v['image'] for v in selected),
        'training_ready':False,'appearance_acceptance_passed':False,'pose_validation_required':False,
        'remaining_gate':'Root scoped visual review of selected coverage and any proposed unknown promotions; controlled appearance comparison.',
        'quality_threshold_status':'Existing experimental per-view classifier, not proof of capture-wide blur recall.',
        'source_images_modified':False,'reference_poses_modified':False,'reference_seed_modified':False,
        'alignment_anchor_membership_used':False,'unknown_quality_promoted':False,
        'evaluation_policy':'Preserve complete fixed-reference heldout face set; exclude every eval timestamp from training.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','reference','quality','baseline','regions','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--scoped-reviews',type=Path,help='Explicit root per-view approvals; never inferred from review candidates')
    parser.add_argument('--evidence-index',type=Path,help='Hash-bound native detail/mask review index')
    args=parser.parse_args();output=args.output.resolve()
    if output.exists():raise FileExistsError(output)
    capture=load_capture(args.dataset);audit_path=args.reference/'explicit-pinhole-audit.json'
    quality=json.loads(args.quality.read_text());baseline=json.loads(args.baseline.read_text());regions=json.loads(args.regions.read_text())
    audit=json.loads(audit_path.read_text());config=CoverageAppearanceConfig(**json.loads(args.config.read_text())) if args.config else CoverageAppearanceConfig()
    if Path(audit['sourceDataset']).resolve()!=Path(capture['dataset']).resolve():
        raise ValueError('Fixed reference is not from this source capture')
    if baseline.get('source_selection_sha256')!=capture['source_selection_sha256']:
        raise ValueError('Baseline appearance manifest belongs to a different capture')
    if bool(args.scoped_reviews)!=bool(args.evidence_index):
        raise ValueError('Scoped approvals and their inspected evidence index are both required')
    if args.scoped_reviews:
        quality=apply_scoped_reviews(quality,args.dataset,json.loads(args.scoped_reviews.read_text()),
            json.loads(args.evidence_index.read_text()),index_sha256=sha256(args.evidence_index))
    result=select_coverage_appearance(capture,quality,audit,baseline,regions,config)
    result['inputs']={name:{'path':str(path.resolve()),'sha256':sha256(path)} for name,path in
        [('quality',args.quality),('baseline',args.baseline),('regions',args.regions),('reference_audit',audit_path)]}
    if args.scoped_reviews:
        result['inputs'].update({name:{'path':str(path.resolve()),'sha256':sha256(path)} for name,path in
            [('scoped_reviews',args.scoped_reviews),('evidence_index',args.evidence_index)]})
        result['unknown_quality_promoted']=True
        result['explicitly_root_reviewed_views']=sum(bool(v.get('manual_quality_review')) for v in result['views'])
    result['reference_dataset']=str(args.reference.resolve());result['selection_code_sha256']=sha256(__file__)
    output.mkdir(parents=True);write_json(output/'training-views.json',result)
    write_json(output/'coverage-comparison.json',{k:v for k,v in result.items() if k!='views'})
    write_json(output/'review-queue.json',{'training_ready':False,'automatic_promotions':0,'views':result['review_queue'],
        'total_candidates':result['review_candidate_count'],'truncated':result['review_queue_truncated']})
    print(json.dumps({key:result[key] for key in ('eligible_view_count','reference_native_training_views',
        'selected_native_fraction_of_reference','target_fraction_met','review_candidate_count','existing_subset_preserved')}))


if __name__=='__main__':main()
