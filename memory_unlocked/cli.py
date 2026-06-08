"""Command-line interface: ``python -m memory_unlocked`` / ``memory-unlocked``.

A thin, scriptable shell over the service layer in :mod:`memory_unlocked.ops`,
backed by the durable :class:`~memory_unlocked.persistence.JsonlStore`. Every
command resolves a store path, every write requires a source, and every recall
or list requires an explicit namespace — the same guarantees the library makes.

Exit codes:
    0  success
    2  usage error (argparse)
    3  a write was rejected by the policy gate
    1  any other runtime error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from . import __version__, evaluation, ops
from .models import Namespace
from .persistence import atomic_write_text
from .store import MemoryStore

DEFAULT_PATH = "./.memory_unlocked"
ENV_PATH = "MEMORY_UNLOCKED_HOME"
ENV_BACKEND = "MEMORY_UNLOCKED_BACKEND"
DEFAULT_BACKEND = "jsonl"
EXIT_OK = 0
EXIT_REJECTED = 3
EXIT_ERROR = 1


def _utc_clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_path(args: argparse.Namespace) -> str:
    return args.path or os.environ.get(ENV_PATH) or DEFAULT_PATH


def _resolve_backend(args: argparse.Namespace) -> str:
    return getattr(args, "backend", None) or os.environ.get(ENV_BACKEND) or DEFAULT_BACKEND


def _open_store(args: argparse.Namespace) -> MemoryStore:
    return MemoryStore.open(_resolve_path(args), backend=_resolve_backend(args), clock=_utc_clock)


def _namespace(args: argparse.Namespace) -> Namespace:
    return Namespace(tenant=args.tenant, project=args.project)


def _optional_namespace(args: argparse.Namespace) -> Optional[Namespace]:
    if args.tenant and args.project:
        return Namespace(tenant=args.tenant, project=args.project)
    if args.tenant or args.project:
        raise SystemExit("error: --tenant and --project must be given together")
    return None


def _read_body(body: str) -> str:
    """Allow ``--body -`` to read the body from stdin (handy for piping)."""
    if body == "-":
        return sys.stdin.read().strip()
    return body


# --- Command handlers --------------------------------------------------------

def _cmd_init(args: argparse.Namespace) -> int:
    store = _open_store(args)
    backend = _resolve_backend(args)
    print(f"Initialized {backend} memory store at {store.path}")
    if backend == "sqlite":
        print(f"  database: {store.db_file}")
    else:
        print(f"  memories: {store.path / 'memories.jsonl'}")
        print(f"  events:   {store.path / 'events.jsonl'}")
    return EXIT_OK


def _cmd_write(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.write_memory(
        store,
        namespace=_namespace(args),
        title=args.title,
        body=_read_body(args.body),
        source=args.source,
        source_kind=args.source_kind,
        source_note=args.source_note,
        kind=args.kind,
        tags=args.tags,
        confidence=args.confidence,
        status=getattr(args, "status", "active"),
    )
    if args.json:
        print(json.dumps(result))
    elif result["ok"]:
        print(f"stored {result['id']} ({result['status']})")
    else:
        detail = f" ({result['detail']})" if result.get("detail") else ""
        print(f"rejected: {result['rejected']}{detail}", file=sys.stderr)
    return EXIT_OK if result["ok"] else EXIT_REJECTED


def _cmd_recall(args: argparse.Namespace) -> int:
    store = _open_store(args)
    token_budget = getattr(args, "token_budget", None)
    if token_budget:
        result = ops.build_context(
            store, _namespace(args), query=args.query,
            token_budget=token_budget, max_memories=args.max,
        )
    else:
        result = ops.recall(store, _namespace(args), query=args.query, max_memories=args.max)
    if args.json:
        print(json.dumps(result))
    elif result["context"]:
        print(result["context"])
    else:
        print("(no matching memories)")
    return EXIT_OK


def _cmd_list(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.list_memories(store, _namespace(args))
    if args.json:
        print(json.dumps(result))
    elif not result["memories"]:
        print("(no memories in scope)")
    else:
        for m in result["memories"]:
            tags = f" [{', '.join(m['tags'])}]" if m["tags"] else ""
            src = f"{m['source']['kind']}:{m['source']['ref']}"
            print(f"- {m['id']}  {m['title']}{tags}  (source: {src})")
    return EXIT_OK


def _cmd_stats(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.compute_stats(store, _optional_namespace(args))
    if args.json:
        print(json.dumps(result))
    else:
        print(f"memories: {result['total']}")
        if result["namespaces"]:
            print("by namespace:")
            for key, count in sorted(result["namespaces"].items()):
                print(f"  {key}: {count}")
        if result["events"]:
            print("events:")
            for key, count in sorted(result["events"].items()):
                print(f"  {key}: {count}")
    return EXIT_OK


def _cmd_export(args: argparse.Namespace) -> int:
    store = _open_store(args)
    data = ops.export_store(store, _optional_namespace(args))
    text = json.dumps(data, indent=2, sort_keys=True)
    if args.out:
        atomic_write_text(args.out, text + "\n")
        print(f"exported {len(data['memories'])} memories to {args.out}", file=sys.stderr)
    else:
        print(text)
    return EXIT_OK


def _cmd_import(args: argparse.Namespace) -> int:
    store = _open_store(args)
    with open(args.in_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    result = ops.import_into(store, data)
    if args.json:
        print(json.dumps(result))
    else:
        print(f"imported {result['imported']}, rejected {result['rejected']}")
    return EXIT_OK



def _cmd_status(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.set_memory_status(store, args.id, args.status)
    print(json.dumps(result) if args.json else (f"{args.id}: {result.get('status', result.get('error'))}"))
    return EXIT_OK if result.get("ok") else EXIT_ERROR


def _cmd_forget(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.forget_memory(store, args.id)
    print(json.dumps(result) if args.json else ("forgotten" if result["forgotten"] else "not found"))
    return EXIT_OK if result["forgotten"] else EXIT_ERROR


def _cmd_audit(args: argparse.Namespace) -> int:
    store = _open_store(args)
    cutoff = None
    if args.stale_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.stale_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = ops.audit(
        store,
        namespace=_optional_namespace(args),
        min_confidence=args.min_confidence,
        stale_before=cutoff,
    )
    if args.json:
        print(json.dumps(result))
    else:
        print(f"memories audited: {result['total']}")
        print(f"candidates: {len(result['candidates'])}")
        print(f"low confidence: {len(result['low_confidence'])}")
        print(f"stale: {len(result['stale'])}")
        print(f"duplicate groups: {len(result['duplicates'])}")
    return EXIT_OK


def _cmd_review(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.audit(store, namespace=_optional_namespace(args), min_confidence=args.min_confidence)
    candidates = result["candidates"]
    if args.json:
        print(json.dumps({"candidates": candidates}))
    elif not candidates:
        print("No candidate memories pending review.")
    else:
        print("Candidate memories pending review:")
        for item in candidates:
            print(f"- {item['id']} [{item['namespace']}] {item['title']} (confidence={item['confidence']})")
        print("\nPromote one with: memory-unlocked status --id <id> --status active")
        print("Archive one with: memory-unlocked status --id <id> --status archived")
    return EXIT_OK


def _cmd_graph(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.graph_report(store, _namespace(args), query=args.query)
    if args.json:
        print(json.dumps(result))
    else:
        print(f"semantic graph — {result['namespace']}")
        print(f"entities: {result['counts']['entities']}")
        print(f"relations: {result['counts']['relations']}")
        print(f"co_occurs: {result['counts']['co_occurs']}")
        for rel, views in result["semantic_relations"].items():
            print(f"  {rel}:")
            for v in views:
                print(f"    {v['subject']} -> {v['object']}")
        if result["warnings"]:
            print("warnings:")
            for w in result["warnings"]:
                print(f"  - {w}")
    return EXIT_OK


def _cmd_graph_context(args: argparse.Namespace) -> int:
    store = _open_store(args)
    result = ops.graph_context(
        store, _namespace(args), query=args.query, token_budget=args.token_budget,
    )
    if args.json:
        print(json.dumps(result))
    elif result["context"]:
        print(result["context"])
    else:
        print("(no semantic relations in scope)")
    return EXIT_OK


def _cmd_eval(args: argparse.Namespace) -> int:
    data = evaluation.load_evalset(args.evalset)
    result = evaluation.run_evalset(data)
    if args.json:
        print(json.dumps(result))
    else:
        print(f"eval: {result['name']}")
        print(f"recall hit rate: {result['recall_hit_rate']:.2f}")
        print(f"isolation pass rate: {result['isolation_pass_rate']:.2f}")
        print(f"token budget pass rate: {result['token_budget_pass_rate']:.2f}")
    return EXIT_OK if result.get("passed") else EXIT_ERROR

# --- Argument parsing --------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-unlocked",
        description="Privacy-first, scope-isolated local memory for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"memory-unlocked {__version__}")
    parser.add_argument(
        "--path",
        help=f"store directory (default: ${ENV_PATH} or {DEFAULT_PATH})",
    )
    parser.add_argument(
        "--backend", choices=("jsonl", "sqlite"),
        help=f"storage backend (default: ${ENV_BACKEND} or {DEFAULT_BACKEND})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_ns(p: argparse.ArgumentParser, required: bool = True) -> None:
        p.add_argument("--tenant", required=required, help="tenant scope")
        p.add_argument("--project", required=required, help="project scope")

    p_init = sub.add_parser("init", help="create a store directory")
    p_init.set_defaults(func=_cmd_init)

    p_write = sub.add_parser("write", help="store a durable fact")
    add_ns(p_write)
    p_write.add_argument("--title", required=True)
    p_write.add_argument("--body", required=True, help="fact body, or '-' to read stdin")
    p_write.add_argument("--source", required=True, help="provenance ref (path, url, id)")
    p_write.add_argument("--source-kind", default="doc",
                         help="doc|url|ticket|commit|run|message (default: doc)")
    p_write.add_argument("--source-note", default=None)
    p_write.add_argument("--kind", default="fact",
                         help="fact|decision|convention|reference (default: fact)")
    p_write.add_argument("--tags", default=None, help="comma-separated tags")
    p_write.add_argument("--confidence", type=float, default=1.0)
    p_write.add_argument("--status", default="active",
                         help="candidate|active|archived|rejected (default: active)")
    p_write.add_argument("--json", action="store_true")
    p_write.set_defaults(func=_cmd_write)

    for name in ("recall", "context"):
        p_recall = sub.add_parser(name, help="assemble scope-filtered context")
        add_ns(p_recall)
        p_recall.add_argument("--query", default="")
        p_recall.add_argument("--max", type=int, default=None, help="max memories")
        p_recall.add_argument("--token-budget", type=int, default=None,
                              help="estimated token budget for context assembly")
        p_recall.add_argument("--json", action="store_true")
        p_recall.set_defaults(func=_cmd_recall)

    p_list = sub.add_parser("list", help="list memories in a scope")
    add_ns(p_list)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_stats = sub.add_parser("stats", help="counts of memories and events")
    add_ns(p_stats, required=False)
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=_cmd_stats)

    p_export = sub.add_parser("export", help="export memories as JSON")
    add_ns(p_export, required=False)
    p_export.add_argument("--out", default=None, help="write to a file instead of stdout")
    p_export.set_defaults(func=_cmd_export)

    p_import = sub.add_parser("import", help="import an export document (re-gated)")
    p_import.add_argument("--in", dest="in_file", required=True, help="export JSON file")
    p_import.add_argument("--json", action="store_true")
    p_import.set_defaults(func=_cmd_import)

    p_status = sub.add_parser("status", help="set lifecycle status for one memory")
    p_status.add_argument("--id", required=True)
    p_status.add_argument("--status", required=True, help="candidate|active|archived|rejected")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=_cmd_status)

    p_forget = sub.add_parser("forget", help="permanently remove one memory")
    p_forget.add_argument("--id", required=True)
    p_forget.add_argument("--json", action="store_true")
    p_forget.set_defaults(func=_cmd_forget)

    p_audit = sub.add_parser("audit", help="governance scan without printing memory bodies")
    add_ns(p_audit, required=False)
    p_audit.add_argument("--min-confidence", type=float, default=0.5)
    p_audit.add_argument("--stale-days", type=int, default=None)
    p_audit.add_argument("--json", action="store_true")
    p_audit.set_defaults(func=_cmd_audit)

    p_review = sub.add_parser("review", help="text UI for candidate memory review")
    add_ns(p_review, required=False)
    p_review.add_argument("--min-confidence", type=float, default=0.5)
    p_review.add_argument("--json", action="store_true")
    p_review.set_defaults(func=_cmd_review)

    p_graph = sub.add_parser("graph", help="extract a public-safe semantic graph for a scope")
    add_ns(p_graph)
    p_graph.add_argument("--query", default="", help="narrow the graph to matching memories")
    p_graph.add_argument("--json", action="store_true")
    p_graph.set_defaults(func=_cmd_graph)

    p_graph_ctx = sub.add_parser(
        "graph-context", help="render a compact, token-budgeted semantic-graph block")
    add_ns(p_graph_ctx)
    p_graph_ctx.add_argument("--query", default="")
    p_graph_ctx.add_argument("--token-budget", type=int, default=None,
                             help="estimated token budget for the graph block")
    p_graph_ctx.add_argument("--json", action="store_true")
    p_graph_ctx.set_defaults(func=_cmd_graph_context)

    p_eval = sub.add_parser("eval", help="run an offline recall/privacy evalset")
    p_eval.add_argument("evalset")
    p_eval.add_argument("--json", action="store_true")
    p_eval.set_defaults(func=_cmd_eval)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return args.func(args)
    except BrokenPipeError:  # pragma: no cover - piping into head etc.
        return EXIT_OK
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level guard for a CLI
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
