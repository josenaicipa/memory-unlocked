"""Product-level behavior introduced for v0.3."""

import json

from memory_unlocked import cli
from memory_unlocked.mcp_server import build_tools


def run(args, path):
    return cli.main(["--path", str(path), *args])


def test_sqlite_backend_roundtrip(tmp_path, capsys):
    store = tmp_path / "store"
    assert run([
        "--backend", "sqlite", "write",
        "--tenant", "acme", "--project", "ops",
        "--title", "SQLite works", "--body", "Local durable backend.",
        "--source", "docs/sqlite.md", "--json",
    ], store) == 0
    capsys.readouterr()

    assert run([
        "--backend", "sqlite", "recall",
        "--tenant", "acme", "--project", "ops", "--query", "backend", "--json",
    ], store) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["matches"][0]["title"] == "SQLite works"
    assert (store / "memory.db").exists()


def test_lifecycle_review_promote_archive_and_forget(tmp_path, capsys):
    store = tmp_path / "store"
    assert run([
        "write", "--tenant", "acme", "--project", "ops",
        "--title", "Needs review", "--body", "Candidate fact.",
        "--source", "notes/review.md", "--status", "candidate", "--json",
    ], store) == 0
    memory_id = json.loads(capsys.readouterr().out)["id"]

    assert run(["review", "--tenant", "acme", "--project", "ops", "--json"], store) == 0
    assert json.loads(capsys.readouterr().out)["candidates"][0]["id"] == memory_id

    assert run(["status", "--id", memory_id, "--status", "active", "--json"], store) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"

    assert run(["status", "--id", memory_id, "--status", "archived", "--json"], store) == 0
    capsys.readouterr()
    assert run(["recall", "--tenant", "acme", "--project", "ops", "--query", "Candidate", "--json"], store) == 0
    assert json.loads(capsys.readouterr().out)["matches"] == []

    assert run(["forget", "--id", memory_id, "--json"], store) == 0
    assert json.loads(capsys.readouterr().out)["forgotten"] is True


def test_context_token_budget_and_eval(tmp_path, capsys):
    store = tmp_path / "store"
    for title, body in [
        ("Refund routing", "Refunds are handled by the billing worker."),
        ("Shipping owner", "Warehouse handles labels and pickups."),
    ]:
        assert run([
            "write", "--tenant", "acme", "--project", "ops",
            "--title", title, "--body", body, "--source", "docs/public.md",
        ], store) == 0
    capsys.readouterr()

    assert run([
        "context", "--tenant", "acme", "--project", "ops",
        "--query", "refund worker", "--token-budget", "80", "--json",
    ], store) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["estimated_tokens"] <= 80
    assert "Refund routing" in payload["context"]

    evalset = tmp_path / "evalset.json"
    evalset.write_text(json.dumps({
        "name": "smoke",
        "memories": [{
            "tenant": "acme", "project": "ops", "title": "Refund routing",
            "body": "Refunds are handled by the billing worker.",
            "source": "docs/public.md", "tags": ["billing"]
        }],
        "recall_cases": [{
            "tenant": "acme", "project": "ops", "query": "refund worker",
            "expected_ids": ["Refund routing"], "token_budget": 80
        }],
        "isolation_cases": [{
            "tenant": "other", "project": "ops", "query": "refund",
            "forbidden_titles": ["Refund routing"]
        }]
    }))
    assert run(["eval", str(evalset), "--json"], tmp_path / "eval-store") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is True
    assert report["recall_hit_rate"] == 1.0


def test_mcp_exposes_memory_context_tool():
    names = {tool["name"] for tool in build_tools()}
    assert "memory_context" in names
    assert "memory_recall" in names
