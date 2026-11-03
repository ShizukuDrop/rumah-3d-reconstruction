"""Select alignment anchors and appearance views with separate, audited rules."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import json
import time
import cv2
from .capture import load_capture, sha256
from .motion import MotionConfig, compare_pair
from .quality import QualityConfig, evaluate_pair
from .training_views import TrainingViewConfig, select_training_views


@dataclass(frozen=True)
class SelectionConfig:
    min_interval_seconds: float = .066
    max_interval_seconds: float = .5
    parallax_degrees: float = 3.0
    rotation_degrees: float = 12.0
    minimum_track_survival: float = .55
    reference_neighbors_each_side: int = 4
    training_interval_seconds: float = .1
    include_eval_for_alignment: bool = False
    allow_unknown_quality_for_experiment: bool = False


def motion_reasons(comparison, elapsed, config):
    reasons=[]
    for lens in ('cam0','cam1'):
        evidence=comparison['lenses'][lens]
        if evidence['status']!='measured':
            reasons.append(f'{lens}:unknown_motion')
        else:
            if evidence['parallax_deg_p75']>=config.parallax_degrees:reasons.append(f'{lens}:parallax')
            if evidence['rotation_deg']>=config.rotation_degrees:reasons.append(f'{lens}:rotation_coverage')
            if evidence['track_survival']<config.minimum_track_survival:reasons.append(f'{lens}:lost_track_coverage')
    if elapsed>=config.max_interval_seconds:reasons.append('maximum_gap')
    return reasons


def apply_manual_review(decision, labels, frame_id):
    """A recorded human review can resolve uncertainty, never erase measured blur."""
    for lens in ('cam0','cam1'):
        label=labels.get(f'{frame_id}:{lens}')
        if not label:continue
        if not label.get('reason') or not label.get('evidence'):
            raise ValueError('Manual quality labels require a reason and inspected evidence')
        current=decision['views'][lens]
        if label['verdict']=='blur':
            current.update(verdict='blur',confirmed=True,training_eligible=False,manual_review=label)
        elif label['verdict']=='sharp' and not(current['verdict']=='blur' and current['confirmed']):
            current.update(verdict='sharp',confirmed=True,training_eligible=True,manual_review=label)
    if any(v['verdict']=='blur' and v['confirmed'] for v in decision['views'].values()):
        decision.update(action='reject',reason='confirmed_blurry_lens')
    elif all(v['verdict']=='sharp' and v['confirmed'] for v in decision['views'].values()):
        decision.update(action='keep',reason='both_lenses_pass_quality')
    decision['training_eligible']={k:v['training_eligible'] for k,v in decision['views'].items()}
    return decision


def choose_frames(capture, quality, compare, config=SelectionConfig(), regions=()):
    """compare(reference,current) supplies prospective two-lens motion evidence."""
    frames=[];anchor=None;last_training={'cam0':None,'cam1':None};comparisons=[]
    for source in capture['frames']:
        row=dict(source);q=quality[source['id']];reasons=[];selected=False
        eval_excluded=source['split']=='eval' and not config.include_eval_for_alignment
        eligible=q['action']=='keep' or (q['action']=='review' and config.allow_unknown_quality_for_experiment)
        if eval_excluded:reasons.append('held_out_from_alignment')
        elif q['action']=='reject':reasons.append('confirmed_blur_rejected')
        elif not eligible:reasons.append('quality_review_required')
        elif anchor is None:selected=True;reasons.append('first_eligible_pair')
        elif source['time_seconds']-anchor['time_seconds']<config.min_interval_seconds:
            reasons.append('below_minimum_interval')
        else:
            comparison=compare(anchor,source);comparisons.append(comparison)
            reasons=motion_reasons(comparison,source['time_seconds']-anchor['time_seconds'],config)
            if reasons:selected=True
            else:reasons=['redundant_in_both_lenses']
        if selected:anchor=source
        training={}
        for lens in ('cam0','cam1'):
            last=last_training[lens]
            allowed=source['split']=='train' and q['training_eligible'][lens]
            # Appearance selection is independent of alignment anchor membership.
            allowed=allowed and (last is None or source['time_seconds']-last>=config.training_interval_seconds-1e-9)
            training[lens]=bool(allowed)
            if allowed:last_training[lens]=source['time_seconds']
        row.update(selected=selected,alignment_reasons=reasons,quality_action=q['action'],
                   training=training,training_reason='independent clear-view cadence; pose must subsequently pass localization',
                   requires_quality_review=selected and q['action']=='review')
        frames.append(row)
    # Coverage is an acceptance gate. Do not restore a blurred pair to meet it.
    coverage=[]
    for region in regions:
        available=[r for r in frames if region['source_frame_min']<=r['id']<=region['source_frame_max']]
        chosen=[r for r in available if r['selected']]
        minimum=region.get('minimum_complete_pairs',3)
        for row in chosen:row['room']=region['name'];row['protected']=True
        coverage.append({'name':region['name'],'source_pairs':len(available),'anchor_pairs':len(chosen),
                         'minimum_anchor_pairs':minimum,'passed':len(chosen)>=minimum,
                         'selected_frame_ids':[r['id'] for r in chosen]})
    selected=[r for r in frames if r['selected']]
    gaps=[{'from':a['id'],'to':b['id'],'seconds':b['time_seconds']-a['time_seconds']}
          for a,b in zip(selected,selected[1:]) if b['time_seconds']-a['time_seconds']>config.max_interval_seconds+1/capture['fps']]
    if selected:
        for label,a,b in [('start',frames[0],selected[0]),('end',selected[-1],frames[-1])]:
            duration=b['time_seconds']-a['time_seconds']
            if duration>config.max_interval_seconds+1/capture['fps']:
                gaps.append({'from':a['id'],'to':b['id'],'seconds':duration,'boundary':label})
    return {'schema_version':1,'source_selection_sha256':capture['source_selection_sha256'],
            'configuration':asdict(config),'frames':frames,'comparisons':comparisons,'coverage':coverage,
            'unresolved_gaps':gaps,'source_pair_count':len(frames),'alignment_pair_count':len(selected),
            'training_view_count':sum(sum(r['training'].values()) for r in frames),
            'selected_unknown_quality_count':sum(r['requires_quality_review'] for r in frames),
            'acceptance_passed':bool(selected) and all(c['passed'] for c in coverage) and not gaps
                                 and not any(r['requires_quality_review'] for r in frames),
            'baseline_geometry_used_for_selection':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--measurements',type=Path,required=True)
    parser.add_argument('--quality-config',type=Path,required=True)
    parser.add_argument('--selection-config',type=Path)
    parser.add_argument('--review-labels',type=Path)
    parser.add_argument('--quality-decisions',type=Path,help='Reuse separately audited classification from this exact scan/config')
    parser.add_argument('--coverage',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cv2.setNumThreads(1)
    if args.output.exists():raise FileExistsError(args.output)
    capture=load_capture(args.dataset)
    config=SelectionConfig(**json.loads(args.selection_config.read_text())) if args.selection_config else SelectionConfig()
    qconfig=QualityConfig(**json.loads(args.quality_config.read_text()))
    labels=json.loads(args.review_labels.read_text()) if args.review_labels else {}
    scan=json.loads((args.measurements/'status.json').read_text())
    if scan['state']!='complete' or scan['identity']['selection']!=capture['source_selection_sha256']:
        raise ValueError('Quality scan incomplete or from a different capture')
    data={row['id']:json.loads((args.measurements/'frames'/f'{row["id"]:06d}.json').read_text()) for row in capture['frames']}
    frames=capture['frames'];quality={};started=time.perf_counter()
    if args.quality_decisions:
        prior=json.loads(args.quality_decisions.read_text())
        if prior['quality_scan_signature']!=scan['signature'] or prior['configuration']!=asdict(qconfig):
            raise ValueError('Reused quality decisions differ from the measurement/configuration identity')
        quality={int(key):apply_manual_review(value,labels,int(key)) for key,value in prior['decisions'].items()}
    else:
        for i,frame in enumerate(frames):
            nearby=frames[max(0,i-config.reference_neighbors_each_side):i]+frames[i+1:i+1+config.reference_neighbors_each_side]
            nearby=[row for row in nearby if row['split']=='train']
            references={lens:[data[r['id']]['views'][lens] for r in nearby] for lens in ('cam0','cam1')}
            quality[frame['id']]=apply_manual_review(evaluate_pair(data[frame['id']]['views'],references,qconfig),labels,frame['id'])
    regions=json.loads(args.coverage.read_text()) if args.coverage else []
    cache={};motion_config=MotionConfig()
    def compare(first,second):
        # Retain only two timestamp pairs, so full-clip selection has bounded memory.
        for key in list(cache):
            if key[0] not in (first['id'],second['id']):del cache[key]
        return compare_pair(capture,first,second,motion_config,cache)
    result=choose_frames(capture,quality,compare,config,regions)
    training=select_training_views(capture,quality,data,TrainingViewConfig(),regions)
    eligible={(row['frame_id'],row['lens']) for row in training['views']
              if row['selected'] and row['status']=='eligible_pending_pose'}
    for row in result['frames']:
        row['training']={lens:(row['id'],lens) in eligible for lens in ('cam0','cam1')}
        row['training_reason']='Independent appearance selection; see training-views.json; pose validation still required.'
    result['training_view_count']=training['eligible_view_count']
    result['training_review_view_count']=training['review_view_count']
    result['acceptance_scope']='Anchor quality/temporal/region coverage only; this does not certify reconstruction or rendering.'
    result.update(elapsed_seconds=time.perf_counter()-started,quality_scan_signature=scan['signature'],
                  quality_configuration=asdict(qconfig),motion_configuration=asdict(motion_config),
                  review_labels_sha256=sha256(args.review_labels) if args.review_labels else None)
    args.output.mkdir(parents=True)
    (args.output/'selection.json').write_text(json.dumps(result,indent=2))
    (args.output/'quality-decisions.json').write_text(json.dumps(quality,indent=2))
    (args.output/'training-views.json').write_text(json.dumps(training,indent=2))
    print(json.dumps({k:result[k] for k in ('alignment_pair_count','training_view_count','selected_unknown_quality_count','acceptance_passed','elapsed_seconds')}))


if __name__=='__main__':main()
