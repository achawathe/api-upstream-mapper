"""Freeze current-app candidate packets before model evaluation, independently of answer labels."""

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from api_mapper.evaluation.contracts import grade_contract
from api_mapper.loaders.response_samples import attach_responses
from api_mapper.matching.semantic import NlpSettings
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline
from experiments.local_reranker.focus import write_focus
from experiments.local_reranker.runtime import offline, read_rows, write_json

ROOT = Path(__file__).resolve().parents[2]


def field(node) -> dict:
    return {
        key: value
        for key, value in {
            "path": node.path,
            "endpoint": node.endpoint,
            "type": node.type,
            "format": node.format,
            "description": node.description,
            "enum": node.enum,
            "condition": node.condition,
            "sample_values": node.observed,
            "sample_context": node.sample_context,
            "associated_definitions": [asdict(clue) for clue in node.context_clues],
            "documentation": [asdict(clue) for clue in node.documentation],
        }.items()
        if value is not None and value != "" and value != ()
    }


def prepare(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    offline()
    labels = json.loads((ROOT / "samples/real-contracts/answer-key.json").read_text())
    system = read_rows(ROOT / "experiments/local_reranker/data/valid.jsonl")[0]["messages"][0]
    rows, baseline, metadata = [], [], []
    for provider in ("plaid", "uk"):
        pipeline = MappingPipeline(Lexicon.load(), nlp=NlpSettings(model_path=str(ROOT / "models/all-MiniLM-L6-v2")))
        inputs = pipeline.load(
            ROOT / "samples/upstream/fdx/core-exchange-6.4.yaml",
            [ROOT / f"samples/real-contracts/{provider}/openapi.json"],
        )
        spec = inputs.downstreams[0]
        for endpoint in spec.endpoints:
            if endpoint.response_examples:
                examples = [
                    (f"{endpoint.operation_id}-{i}.json", body) for i, body in enumerate(endpoint.response_examples)
                ]
                spec = attach_responses(spec, endpoint.key, examples)
        result = pipeline.run(replace(inputs, downstreams=(spec,)))
        provider_labels = [label for label in labels if label["provider"] == provider]
        grade = grade_contract(result.run.mappings, provider_labels, set(result.prepared.sources))
        baseline.append({"provider": provider, "summary": grade.summary, "rows": grade.rows})
        mappings = {mapping.target.key.split("|", 1)[1]: mapping for mapping in result.run.mappings}
        for label in provider_labels:
            mapping = mappings[label["target"]]
            target = result.prepared.targets[mapping.target.key]
            candidates = [
                candidate
                for source in result.prepared.index.candidates_for(target)
                if (candidate := result.prepared.scorer.score(target, source)) is not None
            ]
            candidates.sort(
                key=lambda candidate: (candidate.vetoed_by is not None, -candidate.score, candidate.source.key)
            )
            candidates = candidates[:12]
            if mapping.chosen and all(candidate.source.key != mapping.chosen.source.key for candidate in candidates):
                candidates[-1:] = [mapping.chosen]
            candidates.sort(key=lambda candidate: candidate.source.key)
            options = [
                {
                    "candidate_id": f"C{i + 1}",
                    "source_key": candidate.source.key,
                    **field(candidate.source),
                    "prohibited": bool(candidate.vetoed_by),
                    "constraint": candidate.vetoed_by,
                }
                for i, candidate in enumerate(candidates)
            ]
            acceptable = [option["candidate_id"] for option in options if option["source_key"] in label["expected"]]
            expected = acceptable or (["NOT_RETRIEVED"] if label["expected"] else ["NONE"])
            payload = {"target": field(mapping.target), "candidates": options}
            rows.append(
                {
                    "messages": [
                        system,
                        {"role": "user", "content": json.dumps(payload)},
                        {"role": "assistant", "content": json.dumps({"candidate_id": expected[0]})},
                    ],
                    "expected": expected,
                }
            )
            metadata.append(
                {
                    **label,
                    "retrieved": bool(acceptable),
                    "case": len(rows) - 1,
                    "baseline": mapping.chosen.source.key if mapping.chosen else None,
                }
            )
    (output / "public.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    write_json(output / "baseline.json", baseline)
    write_json(output / "metadata.json", metadata)
    write_focus(output, rows, metadata)
    print("PUBLIC_INPUTS_FROZEN", len(rows), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args().output)
