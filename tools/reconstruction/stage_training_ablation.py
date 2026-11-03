"""Stage selected appearance views with fixed reference poses for an ablation.

Use the same external seed as the full reference run. This isolates appearance
selection from changes in pose estimation or the initial point cloud.
"""
import argparse
import json
import os
from pathlib import Path
import shutil

from .capture import sha256


def stage(source, selection, output):
    if output.exists():
        raise FileExistsError(output)
    appearance = json.loads(selection.read_text())
    approved = {
        view["image"] for view in appearance["views"]
        if view["selected"] and view["status"] == "eligible_pending_pose"
        and view["split"] == "train"
    }
    audit_path = source / "explicit-pinhole-audit.json"
    audit = json.loads(audit_path.read_text())
    views = {
        view["name"]: view for view in audit["views"]
        if view["sourceSplit"] == "eval" or view["sourceName"] in approved
    }
    if any(Path(name).name != name for name in views):
        raise ValueError("Expected flat pinhole image names")
    records = {}
    sparse = source / "sparse/0"
    with (sparse / "images.txt").open() as stream:
        for line in stream:
            if not line.strip() or line.startswith("#"):
                continue
            name = line.split(maxsplit=9)[-1].strip()
            next(stream)  # The external seed supplies geometry, so omit tracks.
            if name in views:
                if name in records:
                    raise ValueError(f"Duplicate image record: {name}")
                records[name] = line.rstrip()
    if records.keys() != views.keys():
        raise ValueError("Reference poses and audited view list differ")
    counts = {split: sum(v["sourceSplit"] == split for v in views.values())
              for split in ("train", "eval")}
    if not all(counts.values()) or counts["eval"] != audit["evalViews"]:
        raise ValueError("Training or reference evaluation coverage is incomplete")
    assets = [relative for name in views for relative in
              (Path("images") / name, Path("masks") / Path(name).with_suffix(".png"))]
    for relative in assets:
        if not (source / relative).is_file():
            raise FileNotFoundError(source / relative)
    seed = source / "seed-sparse-train.ply"
    if sha256(seed) != audit["sha256"][seed.name]:
        raise ValueError("Reference seed identity changed")
    (output / "images").mkdir(parents=True)
    (output / "masks").mkdir()
    destination = output / "sparse/0"
    destination.mkdir(parents=True)
    for relative in assets:
        os.link(source / relative, output / relative)
    shutil.copyfile(sparse / "cameras.txt", destination / "cameras.txt")
    (destination / "images.txt").write_text(
        "".join(f"{record}\n\n" for record in records.values()), encoding="utf-8"
    )
    (destination / "points3D.txt").write_text("# External reference seed\n")
    report = {
        "reference_dataset": str(source.resolve()),
        "source_audit_sha256": sha256(audit_path),
        "appearance_selection_sha256": sha256(selection),
        "counts": counts,
        "selected_native_views_missing_reference_poses": sorted(
            approved - {view["sourceName"] for view in views.values()}
        ),
        "external_seed": str(seed.resolve()),
        "external_seed_sha256": audit["sha256"][seed.name],
        "poses": "Reference poses, unchanged. This is an appearance-only ablation.",
        "eval": "Same reference interpolation views as the original training run.",
    }
    (output / "ablation.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("source", "selection", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.selection, args.output), indent=2))
