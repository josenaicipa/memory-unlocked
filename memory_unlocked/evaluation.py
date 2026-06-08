"""Local, offline evaluation harness for a memory store.

``memory-unlocked eval <evalset.json>`` loads a self-contained fixture file,
builds a throwaway in-memory store, replays the writes, and scores recall,
namespace isolation, and token-budget behavior. Everything is deterministic,
in-process, and network-free.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Dict, List

from . import ops
from .models import Namespace
from .store import MemoryStore


def _ns(d: Dict[str, Any]) -> Namespace:
    """Accept either {namespace:{tenant,project}} or flat tenant/project."""
    if "namespace" in d:
        d = d["namespace"]
    return Namespace(tenant=d["tenant"], project=d["project"])


def _source(record: Dict[str, Any]) -> Dict[str, Any]:
    source = record.get("source")
    if isinstance(source, dict):
        return source
    return {"kind": record.get("source_kind", "doc"), "ref": source or record.get("source_ref")}


def _build_store(evalset: Dict[str, Any]) -> MemoryStore:
    """Load all fixture memories into a fresh, deterministic in-memory store."""
    counter = itertools.count(0)
    store = MemoryStore(clock=lambda: f"2026-01-01T00:00:{next(counter):02d}Z")
    for record in evalset.get("memories", []):
        source = _source(record)
        result = ops.write_memory(
            store,
            namespace=_ns(record),
            title=record["title"],
            body=record["body"],
            source=source["ref"],
            source_kind=source.get("kind", "doc"),
            source_note=source.get("note"),
            kind=record.get("kind", "fact"),
            tags=record.get("tags"),
            confidence=record.get("confidence", 1.0),
            status=record.get("status", "active"),
        )
        if not result["ok"]:
            raise ValueError(f"eval memory rejected: {result['rejected']}")
    return store


def run_evalset(evalset: Dict[str, Any]) -> Dict[str, Any]:
    """Run an evalset dict and return a structured metrics report."""
    store = _build_store(evalset)

    recall_results: List[Dict[str, Any]] = []
    for case in evalset.get("recall_cases", []):
        namespace = _ns(case)
        result = ops.build_context(
            store, namespace, query=case.get("query", ""),
            token_budget=case.get("token_budget"),
        )
        found_titles = {m["title"] for m in result["matches"]}
        expected = case.get("expect_titles", case.get("expected_titles", case.get("expected_ids", [])))
        missing = [t for t in expected if t not in found_titles]
        budget = case.get("token_budget")
        within_budget = True if budget is None else result["estimated_tokens"] <= budget
        recall_results.append({
            "query": case.get("query", ""),
            "namespace": namespace.as_key(),
            "hit": not missing,
            "missing": missing,
            "estimated_tokens": result["estimated_tokens"],
            "token_budget": budget,
            "within_budget": within_budget,
        })

    isolation_results: List[Dict[str, Any]] = []
    for case in evalset.get("isolation_cases", []):
        namespace = _ns(case)
        result = ops.build_context(store, namespace, query=case.get("query", ""))
        forbidden = case.get("forbidden_substrings", case.get("forbidden_titles", []))
        leaked = [s for s in forbidden if s in result["context"]]
        isolation_results.append({
            "query": case.get("query", ""),
            "namespace": namespace.as_key(),
            "isolated": not leaked,
            "leaked": leaked,
        })

    n_recall = len(recall_results)
    n_iso = len(isolation_results)
    budget_cases = [r for r in recall_results if r["token_budget"] is not None]
    recall_hit_rate = (sum(1 for r in recall_results if r["hit"]) / n_recall) if n_recall else 1.0
    isolation_pass_rate = (sum(1 for r in isolation_results if r["isolated"]) / n_iso) if n_iso else 1.0
    token_budget_pass_rate = (sum(1 for r in budget_cases if r["within_budget"]) / len(budget_cases)) if budget_cases else 1.0

    report = {
        "name": evalset.get("name", "evalset"),
        "memories_loaded": len(list(store.all())),
        "recall": {
            "total": n_recall,
            "hits": sum(1 for r in recall_results if r["hit"]),
            "hit_rate": recall_hit_rate,
            "cases": recall_results,
        },
        "isolation": {
            "total": n_iso,
            "isolated": sum(1 for r in isolation_results if r["isolated"]),
            "isolation_rate": isolation_pass_rate,
            "cases": isolation_results,
        },
        "token_budget": {
            "total": len(budget_cases),
            "within": sum(1 for r in budget_cases if r["within_budget"]),
            "pass_rate": token_budget_pass_rate,
        },
        "recall_hit_rate": recall_hit_rate,
        "isolation_pass_rate": isolation_pass_rate,
        "token_budget_pass_rate": token_budget_pass_rate,
    }
    report["passed"] = passed(report)
    return report


def load_evalset(path: str) -> Dict[str, Any]:
    """Read an evalset JSON file from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def passed(report: Dict[str, Any]) -> bool:
    """A run passes when recall, isolation, and budget are all perfect."""
    return (
        report["recall"]["hit_rate"] >= 1.0
        and report["isolation"]["isolation_rate"] >= 1.0
        and report["token_budget"]["pass_rate"] >= 1.0
    )
