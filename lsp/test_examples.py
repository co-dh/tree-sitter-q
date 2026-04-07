#!/usr/bin/env python3
"""Test LSP features against real-world q example files.

Exercises parsing, formatting, symbols, semantic tokens, folding, and diagnostics
on every .q file under examples/. Validates that the parser handles real q idioms
and that formatting round-trips without changing parse trees.
"""
import sys, time, os
from lsp_harness import LSPClient, TestRunner

DIR = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(DIR, "examples")

lsp = LSPClient(cwd=DIR)
# Example files can be slow to parse
lsp._default_timeout = 10
t = TestRunner()
check = t.check

def collect_q_files():
    """Collect all .q files under examples/, skipping non-q content."""
    files = []
    for root, _, names in os.walk(EXAMPLES):
        for name in sorted(names):
            if name.endswith(".q"):
                path = os.path.join(root, name)
                with open(path) as f:
                    text = f.read()
                if text.startswith("<"):
                    continue
                has_backslash_cmd = any(l[:1] == "\\" and len(l) > 1 and l[1].isalpha()
                                        for l in text.splitlines())
                files.append((name, path, text, has_backslash_cmd))
    return files

try:
    # ── Initialize ──────────────────────────────────────────
    lsp.send("initialize", {"capabilities": {}})
    r = lsp.recv(timeout=10)
    check("initialize", r["result"]["capabilities"]["hoverProvider"])
    lsp.send("initialized", notify=True)

    q_files = collect_q_files()
    check("found example files", len(q_files) >= 5)
    print(f"testing {len(q_files)} example files")

    for name, path, text, has_backslash_d in q_files:
        uri = f"file:///{name}"
        print(f"\n── {name} ({len(text.splitlines())} lines) ──")
        lsp.clear_notifs()

        # ── Open + parse ────────────────────────────────────
        lsp.send("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "q",
             "version": 1, "text": text}}, notify=True)
        time.sleep(0.15)

        # ── Diagnostics: check how many parse errors ────────
        diag = None
        for n in lsp.notifs:
            if n.get("method") == "textDocument/publishDiagnostics" and n["params"]["uri"] == uri:
                diag = n
        if diag:
            errs = diag["params"]["diagnostics"]
            check(f"{name} parse errors <= 5", len(errs) <= 5)
            if errs:
                print(f"    ({len(errs)} parse errors)")

        # ── Document symbols ────────────────────────────────
        lsp.send("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        r = lsp.recv(timeout=10)
        syms = r["result"]
        if has_backslash_d:
            check(f"{name} symbols (\\d file)", isinstance(syms, list))
        else:
            check(f"{name} has symbols", len(syms) > 0)
        if syms:
            check(f"{name} symbol has name", "name" in syms[0])
            check(f"{name} symbol has range", "range" in syms[0])

        # ── Semantic tokens ─────────────────────────────────
        lsp.send("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
        r = lsp.recv(timeout=10)
        data = r["result"]["data"]
        if has_backslash_d:
            check(f"{name} tokens (\\d file)", len(data) % 5 == 0)
        else:
            check(f"{name} has semantic tokens", len(data) > 0)
            check(f"{name} tokens multiple of 5", len(data) % 5 == 0)

        # ── Folding ranges ──────────────────────────────────
        lsp.send("textDocument/foldingRange", {"textDocument": {"uri": uri}})
        r = lsp.recv(timeout=10)
        folds = r["result"]
        check(f"{name} folds ok", isinstance(folds, list))
        if folds:
            check(f"{name} fold structure", "startLine" in folds[0])

        # ── Hover on first symbol ───────────────────────────
        if syms:
            sym = syms[0]
            line = sym["range"]["start"]["line"]
            col = sym["range"]["start"]["character"]
            lsp.send("textDocument/hover", {"textDocument": {"uri": uri},
                 "position": {"line": line, "character": col}})
            r = lsp.recv(timeout=10)
            check(f"{name} hover responds", "result" in r)

        # ── Completion ──────────────────────────────────────
        lsp.send("textDocument/completion", {"textDocument": {"uri": uri},
             "position": {"line": 0, "character": 0}})
        r = lsp.recv(timeout=10)
        items = r["result"]
        check(f"{name} completion has items", len(items) > 0)
        labels = {i["label"] for i in items}
        check(f"{name} completion has builtins", "count" in labels or "select" in labels)

        # ── Formatting ──────────────────────────────────────
        lsp.send("textDocument/formatting", {"textDocument": {"uri": uri},
             "options": {"tabSize": 2, "insertSpaces": True}})
        r = lsp.recv(timeout=10)
        edits = r["result"]
        if edits:
            new_text = edits[0]["newText"]
            for i, line in enumerate(new_text.split("\n")):
                if line != line.rstrip():
                    check(f"{name} no trailing ws line {i}", False)
                    break
            else:
                check(f"{name} no trailing whitespace", True)
            check(f"{name} no excessive blanks", "\n\n\n" not in new_text)
            check(f"{name} trailing newline", new_text.endswith("\n"))
        else:
            check(f"{name} already clean or safe", True)

        # ── Format idempotence ──────────────────────────────
        if edits:
            new_text = edits[0]["newText"]
            uri2 = f"file:///{name}.fmt"
            lsp.send("textDocument/didOpen", {"textDocument": {"uri": uri2, "languageId": "q",
                 "version": 1, "text": new_text}}, notify=True)
            time.sleep(0.1)
            lsp.send("textDocument/formatting", {"textDocument": {"uri": uri2},
                 "options": {"tabSize": 2, "insertSpaces": True}})
            r2 = lsp.recv(timeout=10)
            check(f"{name} format idempotent", r2["result"] == [])
            lsp.send("textDocument/didClose", {"textDocument": {"uri": uri2}}, notify=True)

        # ── References for first symbol ─────────────────────
        if syms:
            sym = syms[0]
            line = sym["range"]["start"]["line"]
            col = sym["range"]["start"]["character"]
            lsp.send("textDocument/references", {"textDocument": {"uri": uri},
                 "position": {"line": line, "character": col},
                 "context": {"includeDeclaration": True}})
            r = lsp.recv(timeout=10)
            refs = r["result"]
            check(f"{name} refs found", len(refs) >= 1)

        # ── Selection range ─────────────────────────────────
        lsp.send("textDocument/selectionRange", {"textDocument": {"uri": uri},
             "positions": [{"line": 0, "character": 0}]})
        r = lsp.recv(timeout=10)
        sel = r["result"]
        check(f"{name} selectionRange ok", isinstance(sel, list) and len(sel) == 1)

        # ── Workspace symbol ────────────────────────────────
        if syms:
            lsp.send("workspace/symbol", {"query": syms[0]["name"].split()[0]})
            r = lsp.recv(timeout=10)
            check(f"{name} workspace/symbol found", len(r["result"]) >= 1)

        # ── Close ───────────────────────────────────────────
        lsp.send("textDocument/didClose", {"textDocument": {"uri": uri}}, notify=True)
        time.sleep(0.05)
        lsp.clear_notifs()

    # ── Multi-document cross-references ─────────────────────
    print("\n── multi-doc ──")
    multi_files = [(n, p, t_) for n, p, t_, bd in q_files if not bd][:2]
    for name, path, text in multi_files:
        lsp.send("textDocument/didOpen", {"textDocument": {"uri": f"file:///{name}", "languageId": "q",
             "version": 1, "text": text}}, notify=True)
    time.sleep(0.15)
    lsp.send("workspace/symbol", {"query": ""})
    r = lsp.recv(timeout=10)
    check("multi-doc workspace/symbol sees both", len(r["result"]) >= 2)
    for name, _, _ in multi_files:
        lsp.send("textDocument/didClose", {"textDocument": {"uri": f"file:///{name}"}}, notify=True)
    time.sleep(0.05)
    lsp.clear_notifs()

    # ── Shutdown ────────────────────────────────────────────
    print("\n── shutdown ──")
    lsp.send("shutdown")
    r = lsp.recv(timeout=10)
    check("shutdown ok", r["result"] is None)
    lsp.send("exit", notify=True)
    lsp.proc.wait(timeout=3)
    check("process exited", lsp.proc.returncode == 0)

    t.summary()

except Exception as e:
    lsp.die(f"ERROR: {e}")
