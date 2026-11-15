"""Paired component removals on the native pilot's frozen data and receivers."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from dataset import atomic_text, sha256, verify_dataset
from retention.diagnostics import event_characteristics, summarize_strata
from retention.native_metrics import build_event_cases, evaluate_stream
from retention.native_model import causal_capture_scores
from retention.native_source import open_native_source
from retention.recorder import RecorderConfig
from run_retention_pilot import replay
from run_retention_randomized import load_frozen_model, validate_reference

ABLATIONS = {
    "full": {},
    "no_pre": {"pre_trigger_samples": 0},
    "no_post": {"post_trigger_samples": 0},
    "no_background": {"background_fraction": 0.0},
}


def ablation_configs(config):
    """Remove one component at a time, reallocating its unused quota as usual."""
    return {name: replace(config, **changes) for name, changes in ABLATIONS.items()}


def write_latex(report, path):
    rows = [
        "% Generated paired development ablations; caps are not equal expenditures.",
        r"\begin{tabular}{rlrrr}",
        r"\toprule",
        r"Cap & Variant & MiB & PCA events & Pre-context (\%) \\",
        r"\midrule",
    ]
    for name, metrics in report["arms"].items():
        budget, variant = name.split("-", 1)
        label = variant.replace("_", " ").capitalize()
        coverage = metrics["macro_pre_context_coverage"]
        context = "--" if coverage is None else f"{100 * coverage:.1f}"
        rows.append(
            f"{budget} & {label} & {metrics['serialized_bytes'] / 2**20:.2f} & "
            f"{metrics['receivers']['pca']['detected_events']}/"
            f"{metrics['source_eligible_events']} & {context} " + r"\\"
        )
    atomic_text(path, "\n".join(rows + [r"\bottomrule", r"\end{tabular}"]) + "\n")


def run_study(source, dataset, cache, baseline, output):
    header, annotations = verify_dataset(dataset)
    reference = json.loads((baseline / "report.json").read_text())
    timestamps, values, _ = open_native_source(source, dataset, cache, header)
    validate_reference(reference, baseline, dataset, cache, header)
    if output.resolve() in {p.resolve() for p in (source, dataset, cache, baseline)}:
        raise ValueError("Output must be separate from study inputs")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    prior = reference["provenance"]
    model = load_frozen_model(reference["model"])
    configs = {}
    for budget in prior["budgets"]:
        original = RecorderConfig(**reference["arms"][f"{budget}-adaptive"]["config"])
        configs.update(
            {
                f"{budget}-{name}": ("adaptive", config)
                for name, config in ablation_configs(original).items()
            }
        )
    provenance = dict(
        protocol="native-component-ablations-v1",
        phase="validation development, not held-out",
        reference_report_sha256=sha256(baseline / "report.json"),
        frozen_model_sha256=sha256(baseline / "model.json"),
        native_manifest_sha256=sha256(cache / "manifest.json"),
        scripts={
            p.name: sha256(p)
            for p in [
                Path(__file__),
                Path(__file__).parent / "run_retention_pilot.py",
                *sorted((Path(__file__).parent / "retention").glob("*.py")),
            ]
        },
        configs={name: asdict(config) for name, (_, config) in configs.items()},
        start_us=prior["start_us"],
        end_us=prior["end_us"],
        interpretation="Single removals under common caps; no-background releases reserved capacity to triggers. Not a factorial interaction estimate.",
    )
    atomic_text(output / "protocol.json", json.dumps(provenance, indent=2) + "\n")
    left, right = np.searchsorted(timestamps, [prior["start_us"], prior["end_us"]])
    timestamps, values = timestamps[left:right], values[left:right]
    scores = causal_capture_scores(timestamps, values, model.sigma)
    replay(timestamps, values, scores, configs, output)
    # A full-arm byte-for-byte check catches accidental drift before interpreting removals.
    for budget in prior["budgets"]:
        if (
            sha256(output / f"{budget}-full.taers")
            != reference["arms"][f"{budget}-adaptive"]["packet_stream_sha256"]
        ):
            raise ValueError("Full recorder differs from frozen reference")
    cases, _, normal = build_event_cases(
        timestamps, annotations, prior["start_us"], prior["end_us"], prior["context_us"]
    )
    arms = {}
    for name, (_, config) in configs.items():
        print(f"Evaluating {name}", flush=True)
        path = output / f"{name}.taers"
        metrics = evaluate_stream(
            path,
            timestamps,
            values,
            model,
            cases,
            normal,
            config,
            prior["start_us"],
            prior["end_us"],
        )
        if metrics["packets"] != reference["active_epochs"]:
            raise ValueError("Ablation omitted an active epoch")
        metrics.update(config=asdict(config), packet_stream_sha256=sha256(path))
        arms[name] = metrics
    characteristics = event_characteristics(timestamps, cases)
    for metrics in arms.values():
        metrics["strata"] = summarize_strata(metrics, characteristics)
    report = dict(
        provenance=provenance,
        model=model.to_dict(),
        arms=arms,
        source_observations=len(timestamps),
        event_characteristics=characteristics,
    )
    atomic_text(
        output / "report.json", json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/ESA-Mission1"))
    parser.add_argument("--dataset", type=Path, default=Path("data/processed"))
    parser.add_argument("--cache", type=Path, default=Path("data/native"))
    parser.add_argument(
        "--baseline", type=Path, default=Path("data/results/retention-native")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/results/retention-ablations")
    )
    parser.add_argument("--latex", type=Path)
    args = parser.parse_args()
    report = run_study(
        args.source, args.dataset, args.cache, args.baseline, args.output
    )
    if args.latex:
        write_latex(report, args.latex)


if __name__ == "__main__":
    main()
