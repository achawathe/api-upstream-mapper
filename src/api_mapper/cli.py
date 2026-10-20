"""Command line entry point: map specs to a report, grade against an answer key, or start the GUI."""

import argparse
import json
import sys
from pathlib import Path

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import grade
from api_mapper.loaders import SpecLoadError
from api_mapper.matching.semantic import LocalNlpError, NlpSettings
from api_mapper.models import ProgressEvent, StageState
from api_mapper.normalize.lexicon import DEFAULT_LEXICON, Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline
from api_mapper.pipeline.overrides import load_overrides
from api_mapper.reporting.excel_report import write_excel_report
from api_mapper.reporting.serialize import run_to_dict


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("api_mapper.api.app:app", host=args.host, port=args.port)
        return 0
    try:
        return _map(args)
    except (SpecLoadError, LocalNlpError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _map(args: argparse.Namespace) -> int:
    lexicon = Lexicon.load(DEFAULT_LEXICON, *args.lexicon)
    pipeline = MappingPipeline(
        lexicon,
        listener=None if args.quiet else _print_event,
        nlp=NlpSettings(model_path=str(args.nlp_model) if args.nlp_model else ""),
    )
    overrides = tuple(load_overrides(args.overrides)) if args.overrides else ()
    inputs = pipeline.load(args.upstream, args.downstream, args.errors, overrides)
    run = pipeline.run(inputs).run

    args.out.mkdir(parents=True, exist_ok=True)
    excel = write_excel_report(run, args.out / "mapping-report.xlsx")
    json_path = args.out / "mapping-report.json"
    json_path.write_text(json.dumps(run_to_dict(run), indent=2, default=str), encoding="utf-8")
    print(f"wrote {excel} and {json_path}")
    for warning in run.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.answer_key:
        report = grade(run.mappings, load_answer_key(args.answer_key, run.upstream.name))
        print(report.summary())
        for key, failure in sorted(report.failures().items()):
            print(f"  {failure}  [{key}]")
    return 0


def _print_event(event: ProgressEvent) -> None:
    if event.state is StageState.STARTED:
        return
    counts = ", ".join(f"{k}={v}" for k, v in event.counts.items())
    timing = f" ({event.elapsed_ms:.0f} ms)" if event.elapsed_ms else ""
    print(f"[{event.stage}] {event.state.value}: {event.message}{timing} {counts}".rstrip())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="api-mapper", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("map", help="map downstream APIs to an upstream spec and write reports")
    run.add_argument("--upstream", type=Path, required=True, help="upstream OpenAPI/Swagger spec or schema fragment")
    run.add_argument("--downstream", type=Path, nargs="+", required=True, help="downstream specs or sample manifests")
    run.add_argument("--errors", type=Path, help="upstream error catalog (YAML)")
    run.add_argument("--overrides", type=Path, help="saved manual decisions (JSON)")
    run.add_argument("--lexicon", type=Path, nargs="*", default=[], help="extra lexicon files merged over the default")
    run.add_argument("--answer-key", type=Path, help="grade the run against this answer key")
    run.add_argument("--out", type=Path, default=Path("output"))
    run.add_argument("--quiet", action="store_true")
    run.add_argument(
        "--nlp-model", type=Path, help="enable offline NLP using a local Sentence Transformers model folder"
    )

    serve = commands.add_parser("serve", help="start the web GUI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
