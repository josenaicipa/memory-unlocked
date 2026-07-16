"""CLI tests: exercise `python -m memory_unlocked` command surface."""

import json

import pytest

from memory_unlocked import cli


def run(args, path):
    """Invoke the CLI with a store path injected, return (exit_code, stdout)."""
    return cli.main(["--path", str(path), *args])


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "store"


def test_init_creates_store(store_path, capsys):
    code = run(["init"], store_path)
    out = capsys.readouterr().out
    assert code == 0
    assert store_path.exists()
    assert "memories.jsonl" in out or str(store_path) in out


def test_write_and_recall_roundtrip(store_path, capsys):
    code = run([
        "write",
        "--tenant", "acme", "--project", "billing",
        "--title", "Refunds are async",
        "--body", "Processed by a worker, not inline.",
        "--source", "docs/refunds.md",
        "--tags", "billing,architecture",
    ], store_path)
    assert code == 0
    capsys.readouterr()

    code = run([
        "recall", "--tenant", "acme", "--project", "billing",
        "--query", "refunds",
    ], store_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "Refunds are async" in out


def test_write_requires_source(store_path):
    with pytest.raises(SystemExit):
        run([
            "write", "--tenant", "acme", "--project", "billing",
            "--title", "t", "--body", "b",
        ], store_path)


def test_write_rejects_secret_with_exit_code(store_path, capsys):
    code = run([
        "write", "--tenant", "acme", "--project", "billing",
        "--title", "leak",
        "--body", "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE",
        "--source", "notes.md",
    ], store_path)
    err = capsys.readouterr().err
    assert code == 3
    assert "secret_detected" in err
    # The offending value is never echoed back.
    assert "AKIAIOSFODNN7EXAMPLE" not in err


def test_write_json_output(store_path, capsys):
    code = run([
        "write", "--tenant", "acme", "--project", "billing",
        "--title", "t", "--body", "a stable fact",
        "--source", "docs/x.md", "--json",
    ], store_path)
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["id"].startswith("mem_")


def test_list_is_scope_filtered(store_path, capsys):
    run(["write", "--tenant", "acme", "--project", "billing",
         "--title", "acme fact", "--body", "x", "--source", "a"], store_path)
    run(["write", "--tenant", "globex", "--project", "docs",
         "--title", "globex fact", "--body", "y", "--source", "b"], store_path)
    capsys.readouterr()

    code = run(["list", "--tenant", "acme", "--project", "billing", "--json"], store_path)
    out = capsys.readouterr().out
    assert code == 0
    titles = [m["title"] for m in json.loads(out)["memories"]]
    assert titles == ["acme fact"]


def test_stats_reports_totals(store_path, capsys):
    run(["write", "--tenant", "acme", "--project", "billing",
         "--title", "a", "--body", "x", "--source", "s"], store_path)
    run(["write", "--tenant", "acme", "--project", "billing",
         "--title", "b", "--body", "y", "--source", "s"], store_path)
    capsys.readouterr()

    code = run(["stats", "--json"], store_path)
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["total"] == 2
    assert data["namespaces"]["acme/billing"] == 2


def test_doctor_reports_healthy_empty_local_store(store_path, capsys):
    code = run(["--backend", "sqlite", "doctor", "--json"], store_path)
    out = capsys.readouterr().out
    data = json.loads(out)

    assert code == 0
    assert data["ok"] is True
    assert data["backend"] == "sqlite"
    assert data["memories"] == 0
    assert data["writable"] is True
    assert data["version"] == "1.0.0"
    assert "memory_bodies" not in data


def test_export_outputs_json(store_path, capsys):
    run(["write", "--tenant", "acme", "--project", "billing",
         "--title", "exported", "--body", "x", "--source", "s"], store_path)
    capsys.readouterr()

    code = run(["export"], store_path)
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["memories"][0]["title"] == "exported"


def test_body_from_stdin(store_path, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("body piped via stdin"))
    code = run([
        "write", "--tenant", "acme", "--project", "billing",
        "--title", "piped", "--body", "-", "--source", "s", "--json",
    ], store_path)
    out = capsys.readouterr().out
    assert code == 0
    assert json.loads(out)["ok"] is True
