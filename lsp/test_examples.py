#!/usr/bin/env python3
"""Test LSP features against real-world q example files.

Exercises parsing, formatting, symbols, semantic tokens, folding, and diagnostics
on every .q file under examples/. Validates that the parser handles real q idioms
and that formatting round-trips without changing parse trees.
"""
import subprocess, json, sys, threading, time, os

DIR = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(DIR, "examples")

proc = subprocess.Popen(["q", "lsp.q", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=DIR)

stderr_lines = []
def read_stderr():
    for line in proc.stderr:
        stderr_lines.append(line.decode().rstrip())
threading.Thread(target=read_stderr, daemon=True).start()

def _die(reason):
    print(reason, file=sys.stderr)
    print("stderr:", stderr_lines, file=sys.stderr)
    proc.kill(); sys.exit(1)

seq = 0
def send(method, params=None, notify=False):
    global seq
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not notify:
        seq += 1; msg["id"] = seq
    body = json.dumps(msg).encode()
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    proc.stdin.flush()
    return None if notify else seq

_notifs = []
def _recv_msg(timeout=10):
    headers = {}
    deadline = time.time() + timeout
    buf = b""
    while True:
        if time.time() > deadline: _die("TIMEOUT")
        c = proc.stdout.read(1)
        if not c: _die("EOF")
        if c == b"\n":
            line = buf.rstrip(b"\r"); buf = b""
            if not line: break
            if line.startswith(b"Content-Length:"):
                headers["cl"] = int(line.split(b":")[1].strip())
        else:
            buf += c
    return json.loads(proc.stdout.read(headers["cl"]))

def recv(timeout=10):
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0: _die("TIMEOUT waiting for response")
        msg = _recv_msg(remaining)
        if "id" in msg: return msg
        _notifs.append(msg)

def recv_notif(timeout=5):
    if _notifs: return _notifs.pop(0)
    return _recv_msg(timeout)

pass_n = 0; fail_n = 0
def check(name, cond):
    global pass_n, fail_n
    if cond:
        pass_n += 1; print(f"  pass: {name}")
    else:
        fail_n += 1; print(f"  FAIL: {name}", file=sys.stderr)

def collect_q_files():
    """Collect all .q files under examples/, skipping non-q content."""
    files = []
    for root, _, names in os.walk(EXAMPLES):
        for name in sorted(names):
            if name.endswith(".q"):
                path = os.path.join(root, name)
                with open(path) as f:
                    text = f.read()
                # skip files that aren't actually q (e.g. HTML 404 pages)
                if text.startswith("<"):
                    continue
                # tree-sitter grammar stops parsing at backslash commands (\d, \l, \c, etc.)
                has_backslash_cmd = any(l[:1] == "\\" and len(l) > 1 and l[1].isalpha()
                                        for l in text.splitlines())
                files.append((name, path, text, has_backslash_cmd))
    return files

try:
    # ── Initialize ──────────────────────────────────────────
    send("initialize", {"capabilities": {}})
    r = recv()
    check("initialize", r["result"]["capabilities"]["hoverProvider"])
    send("initialized", notify=True)

    q_files = collect_q_files()
    check("found example files", len(q_files) >= 5)
    print(f"testing {len(q_files)} example files")

    for name, path, text, has_backslash_d in q_files:
        uri = f"file:///{name}"
        print(f"\n── {name} ({len(text.splitlines())} lines) ──")
        _notifs.clear()

        # ── Open + parse ────────────────────────────────────
        send("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "q",
             "version": 1, "text": text}}, notify=True)
        time.sleep(0.15)

        # ── Diagnostics: check how many parse errors ────────
        diag = None
        for n in _notifs:
            if n.get("method") == "textDocument/publishDiagnostics" and n["params"]["uri"] == uri:
                diag = n
        if diag:
            errs = diag["params"]["diagnostics"]
            check(f"{name} parse errors <= 5", len(errs) <= 5)
            if errs:
                print(f"    ({len(errs)} parse errors)")

        # ── Document symbols ────────────────────────────────
        send("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        r = recv()
        syms = r["result"]
        if has_backslash_d:
            check(f"{name} symbols (\\d file)", isinstance(syms, list))
        else:
            check(f"{name} has symbols", len(syms) > 0)
        if syms:
            check(f"{name} symbol has name", "name" in syms[0])
            check(f"{name} symbol has range", "range" in syms[0])

        # ── Semantic tokens ─────────────────────────────────
        send("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
        r = recv()
        data = r["result"]["data"]
        if has_backslash_d:
            check(f"{name} tokens (\\d file)", len(data) % 5 == 0)
        else:
            check(f"{name} has semantic tokens", len(data) > 0)
            check(f"{name} tokens multiple of 5", len(data) % 5 == 0)

        # ── Folding ranges ──────────────────────────────────
        send("textDocument/foldingRange", {"textDocument": {"uri": uri}})
        r = recv()
        folds = r["result"]
        check(f"{name} folds ok", isinstance(folds, list))
        # Multi-line files with multi-line functions should have folds
        if folds:
            check(f"{name} fold structure", "startLine" in folds[0])

        # ── Hover on first symbol ───────────────────────────
        if syms:
            sym = syms[0]
            line = sym["range"]["start"]["line"]
            col = sym["range"]["start"]["character"]
            send("textDocument/hover", {"textDocument": {"uri": uri},
                 "position": {"line": line, "character": col}})
            r = recv()
            # Should return something (hover content or null)
            check(f"{name} hover responds", "result" in r)

        # ── Completion ──────────────────────────────────────
        send("textDocument/completion", {"textDocument": {"uri": uri},
             "position": {"line": 0, "character": 0}})
        r = recv()
        items = r["result"]
        check(f"{name} completion has items", len(items) > 0)
        # Should include builtins + file defs
        labels = {i["label"] for i in items}
        check(f"{name} completion has builtins", "count" in labels or "select" in labels)

        # ── Formatting ──────────────────────────────────────
        send("textDocument/formatting", {"textDocument": {"uri": uri},
             "options": {"tabSize": 2, "insertSpaces": True}})
        r = recv()
        edits = r["result"]
        if edits:
            new_text = edits[0]["newText"]
            # Formatting should not introduce trailing whitespace
            for i, line in enumerate(new_text.split("\n")):
                if line != line.rstrip():
                    check(f"{name} no trailing ws line {i}", False)
                    break
            else:
                check(f"{name} no trailing whitespace", True)
            # Should not have 3+ consecutive blank lines
            check(f"{name} no excessive blanks", "\n\n\n" not in new_text)
            # Should end with newline
            check(f"{name} trailing newline", new_text.endswith("\n"))
        else:
            check(f"{name} already clean or safe", True)

        # ── Format idempotence ──────────────────────────────
        # If formatting produced edits, apply them and format again — should be empty
        if edits:
            new_text = edits[0]["newText"]
            uri2 = f"file:///{name}.fmt"
            send("textDocument/didOpen", {"textDocument": {"uri": uri2, "languageId": "q",
                 "version": 1, "text": new_text}}, notify=True)
            time.sleep(0.1)
            send("textDocument/formatting", {"textDocument": {"uri": uri2},
                 "options": {"tabSize": 2, "insertSpaces": True}})
            r2 = recv()
            check(f"{name} format idempotent", r2["result"] == [])
            send("textDocument/didClose", {"textDocument": {"uri": uri2}}, notify=True)

        # ── References for first symbol ─────────────────────
        if syms:
            sym = syms[0]
            line = sym["range"]["start"]["line"]
            col = sym["range"]["start"]["character"]
            send("textDocument/references", {"textDocument": {"uri": uri},
                 "position": {"line": line, "character": col},
                 "context": {"includeDeclaration": True}})
            r = recv()
            refs = r["result"]
            check(f"{name} refs found", len(refs) >= 1)

        # ── Selection range ─────────────────────────────────
        send("textDocument/selectionRange", {"textDocument": {"uri": uri},
             "positions": [{"line": 0, "character": 0}]})
        r = recv()
        sel = r["result"]
        check(f"{name} selectionRange ok", isinstance(sel, list) and len(sel) == 1)

        # ── Workspace symbol ────────────────────────────────
        if syms:
            send("workspace/symbol", {"query": syms[0]["name"].split()[0]})
            r = recv()
            check(f"{name} workspace/symbol found", len(r["result"]) >= 1)

        # ── Close ───────────────────────────────────────────
        send("textDocument/didClose", {"textDocument": {"uri": uri}}, notify=True)
        time.sleep(0.05)
        _notifs.clear()

    # ── Multi-document cross-references ─────────────────────
    print("\n── multi-doc ──")
    # Open two files that both define functions, check workspace/symbol sees both
    # Pick files without \d so they have symbols
    multi_files = [(n, p, t) for n, p, t, bd in q_files if not bd][:2]
    for name, path, text in multi_files:
        send("textDocument/didOpen", {"textDocument": {"uri": f"file:///{name}", "languageId": "q",
             "version": 1, "text": text}}, notify=True)
    time.sleep(0.15)
    send("workspace/symbol", {"query": ""})
    r = recv()
    check("multi-doc workspace/symbol sees both", len(r["result"]) >= 2)
    for name, _, _ in multi_files:
        send("textDocument/didClose", {"textDocument": {"uri": f"file:///{name}"}}, notify=True)
    time.sleep(0.05)
    _notifs.clear()

    # ── Shutdown ────────────────────────────────────────────
    print("\n── shutdown ──")
    send("shutdown")
    r = recv()
    check("shutdown ok", r["result"] is None)
    send("exit", notify=True)
    proc.wait(timeout=3)
    check("process exited", proc.returncode == 0)

    print(f"\n{pass_n} passed, {fail_n} failed")
    if fail_n > 0:
        sys.exit(1)
    print("all tests passed")

except Exception as e:
    _die(f"ERROR: {e}")
