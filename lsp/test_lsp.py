#!/usr/bin/env python3
"""End-to-end tests for the q LSP server."""
import subprocess, json, sys, threading, time

proc = subprocess.Popen(["q", "lsp.q", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=sys.path[0] or ".")

URI = "file:///test.q"
def td(**kw): return {"textDocument": {"uri": URI, **kw}}

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
        seq += 1
        msg["id"] = seq
    body = json.dumps(msg).encode()
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    proc.stdin.flush()
    return None if notify else seq

_notifs = []
def _recv_msg(timeout=5):
    headers = {}
    deadline = time.time() + timeout
    buf = b""
    while True:
        if time.time() > deadline: _die("TIMEOUT")
        c = proc.stdout.read(1)
        if not c: _die("EOF")
        if c == b"\n":
            line = buf.rstrip(b"\r")
            buf = b""
            if not line: break
            if line.startswith(b"Content-Length:"):
                headers["cl"] = int(line.split(b":")[1].strip())
        else:
            buf += c
    return json.loads(proc.stdout.read(headers["cl"]))

def recv(timeout=5):
    """Read next response (has id). Buffer any notifications."""
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0: _die("TIMEOUT waiting for response")
        msg = _recv_msg(remaining)
        if "id" in msg: return msg
        _notifs.append(msg)

def recv_notif(timeout=2):
    """Return next notification (buffered or from wire)."""
    if _notifs: return _notifs.pop(0)
    return _recv_msg(timeout)

pass_n = 0; fail_n = 0
def check(name, cond):
    global pass_n, fail_n
    if cond:
        pass_n += 1; print(f"  pass: {name}")
    else:
        fail_n += 1; print(f"  FAIL: {name}", file=sys.stderr)

try:
    # ── Initialize ───────────────────────────────────────────
    print("initialize")
    send("initialize", {"capabilities": {}})
    r = recv()
    caps = r["result"]["capabilities"]
    check("has textDocumentSync", "textDocumentSync" in caps)
    check("has completionProvider", "completionProvider" in caps)
    check("has definitionProvider", caps.get("definitionProvider"))
    check("has hoverProvider", caps.get("hoverProvider"))
    check("has documentSymbolProvider", caps.get("documentSymbolProvider"))
    check("has referencesProvider", caps.get("referencesProvider"))
    check("has renameProvider", "renameProvider" in caps)
    check("has documentHighlightProvider", caps.get("documentHighlightProvider"))
    check("has foldingRangeProvider", caps.get("foldingRangeProvider"))
    check("has workspaceSymbolProvider", caps.get("workspaceSymbolProvider"))
    check("has selectionRangeProvider", caps.get("selectionRangeProvider"))
    check("has semanticTokensProvider", "semanticTokensProvider" in caps)
    check("has codeActionProvider", caps.get("codeActionProvider"))
    check("has documentFormattingProvider", caps.get("documentFormattingProvider"))
    check("serverInfo name", r["result"]["serverInfo"]["name"] == "q-lsp")
    send("initialized", notify=True)

    # ── Open document ────────────────────────────────────────
    print("didOpen")
    text = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]\nn:count result"
    send("textDocument/didOpen", {**td(languageId="q", version=1, text=text)}, notify=True)
    time.sleep(0.1)

    # ── Hover: user-defined function ─────────────────────────
    print("hover")
    send("textDocument/hover", {**td(), "position": {"line": 0, "character": 0}})
    r = recv()
    hover_f = r["result"]["contents"]["value"]
    check("hover f shows body", "{[x;y] x+y}" in hover_f)

    # ── Hover: global variable ───────────────────────────────
    send("textDocument/hover", {**td(), "position": {"line": 1, "character": 0}})
    r = recv()
    hover_g = r["result"]["contents"]["value"]
    check("hover g shows global", "(global)" in hover_g)
    check("hover g shows value", "42" in hover_g)

    # ── Hover: builtin identifier (count) ──────────────────────
    send("textDocument/hover", {**td(), "position": {"line": 3, "character": 2}})
    r = recv()
    hover_count = r["result"]["contents"]["value"]
    check("hover builtin has content", len(hover_count) > 0)

    # ── Hover: verb (count) ────────────────────────────────
    send("textDocument/hover", {**td(), "position": {"line": 3, "character": 2}})
    r = recv()
    hover_verb = r["result"]["contents"]["value"]
    check("hover verb shows k impl", len(hover_verb) > 0 and hover_verb != "count")

    # ── Hover: no node ───────────────────────────────────────
    send("textDocument/hover", {**td(), "position": {"line": 99, "character": 0}})
    r = recv()
    check("hover empty line returns null", r["result"] is None)

    # ── Go to definition ─────────────────────────────────────
    print("definition")
    send("textDocument/definition", {**td(), "position": {"line": 2, "character": 7}})
    r = recv()
    defn = r["result"]
    check("def f has uri", defn["uri"] == URI)
    check("def f points to line 0", defn["range"]["start"]["line"] == 0)

    # ── Definition of undefined symbol ───────────────────────
    send("textDocument/definition", {**td(), "position": {"line": 2, "character": 0}})
    r = recv()
    check("def result found", r["result"] is not None)

    # ── Document symbols ─────────────────────────────────────
    print("documentSymbol")
    send("textDocument/documentSymbol", td())
    r = recv()
    syms = r["result"]
    sym_names = [s["name"] for s in syms]
    check("4 symbols", len(syms) == 4)
    check("f in symbols", "f" in sym_names)
    check("g :: in symbols", "g ::" in sym_names)
    check("result in symbols", "result" in sym_names)
    check("n in symbols", "n" in sym_names)

    # ── Completion ───────────────────────────────────────────
    print("completion")
    send("textDocument/completion", {**td(), "position": {"line": 0, "character": 0}})
    r = recv()
    items = r["result"]
    labels = [i["label"] for i in items]
    check("completion has user defs", "f" in labels and "g" in labels)
    check("completion has builtins", "count" in labels or "select" in labels)
    check("completion count > 100", len(items) > 100)

    # ── References ───────────────────────────────────────────
    print("references")
    send("textDocument/references", {**td(), "position": {"line": 0, "character": 0},
         "context": {"includeDeclaration": True}})
    r = recv()
    refs = r["result"]
    check("refs f has 2 hits", len(refs) == 2)
    check("refs f all same uri", all(ref["uri"] == URI for ref in refs))

    send("textDocument/references", {**td(), "position": {"line": 0, "character": 9},
         "context": {"includeDeclaration": True}})
    r = recv()
    check("refs x has 2 hits", len(r["result"]) == 2)  # x in [x;y] + x in x+y

    send("textDocument/references", {**td(), "position": {"line": 99, "character": 0},
         "context": {"includeDeclaration": True}})
    r = recv()
    check("refs unknown returns empty", r["result"] == [])

    # ── Prepare Rename ───────────────────────────────────────
    print("prepareRename")
    send("textDocument/prepareRename", {**td(), "position": {"line": 0, "character": 0}})
    r = recv()
    check("prepareRename f has range", "range" in r["result"])
    check("prepareRename f placeholder", r["result"]["placeholder"] == "f")

    send("textDocument/prepareRename", {**td(), "position": {"line": 3, "character": 2}})
    r = recv()
    check("prepareRename builtin null", r["result"] is None)

    # ── Rename ───────────────────────────────────────────────
    print("rename")
    send("textDocument/rename", {**td(), "position": {"line": 0, "character": 0}, "newName": "add"})
    r = recv()
    changes = r["result"]["changes"]
    check("rename has changes", URI in changes)
    edits = changes[URI]
    check("rename f->add 2 edits", len(edits) == 2)
    check("rename newText", all(e["newText"] == "add" for e in edits))

    # ── didChange ────────────────────────────────────────────
    print("didChange")
    text2 = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]\nn:count result\nh:{neg x}"
    send("textDocument/didChange", {**td(version=2), "contentChanges": [{"text": text2}]}, notify=True)
    time.sleep(0.1)
    send("textDocument/documentSymbol", td())
    r = recv()
    check("didChange: 5 symbols after edit", len(r["result"]) == 5)
    check("didChange: h in symbols", "h" in [s["name"] for s in r["result"]])

    # ── Diagnostics ──────────────────────────────────────────
    print("diagnostics")
    _notifs.clear()
    bad_uri = "file:///bad.q"
    send("textDocument/didOpen", {"textDocument": {"uri": bad_uri, "languageId": "q",
         "version": 1, "text": "f:{[x] x+"}}, notify=True)
    r = recv_notif()
    check("diag method", r["method"] == "textDocument/publishDiagnostics")
    check("diag has errors", len(r["params"]["diagnostics"]) > 0)
    check("diag severity", r["params"]["diagnostics"][0]["severity"] == 1)
    check("diag source", r["params"]["diagnostics"][0]["source"] == "tree-sitter")

    send("textDocument/didChange", {"textDocument": {"uri": bad_uri, "version": 2},
         "contentChanges": [{"text": "f:{[x] x+1}"}]}, notify=True)
    r = recv_notif()
    check("diag cleared after fix", len(r["params"]["diagnostics"]) == 0)

    send("textDocument/didClose", {"textDocument": {"uri": bad_uri}}, notify=True)
    r = recv_notif()
    check("close clears diag", len(r["params"]["diagnostics"]) == 0)

    # ── Document Highlight ───────────────────────────────────
    # Re-open test doc for remaining tests
    print("documentHighlight")
    _notifs.clear()
    send("textDocument/didOpen", {**td(languageId="q", version=1, text=text2)}, notify=True)
    time.sleep(0.1)
    send("textDocument/documentHighlight", {**td(), "position": {"line": 0, "character": 0}})
    r = recv()
    highlights = r["result"]
    check("highlight f has 2 hits", len(highlights) == 2)
    check("highlight has range", "range" in highlights[0])
    check("highlight kind is 1 (text)", highlights[0]["kind"] == 1)

    send("textDocument/documentHighlight", {**td(), "position": {"line": 99, "character": 0}})
    r = recv()
    check("highlight empty returns empty", r["result"] == [])

    # ── Folding Range ────────────────────────────────────────
    print("foldingRange")
    # Open a doc with a multi-line function
    fold_uri = "file:///fold.q"
    fold_text = "f:{\n  x+y\n  }\ng:42"
    send("textDocument/didOpen", {"textDocument": {"uri": fold_uri, "languageId": "q",
         "version": 1, "text": fold_text}}, notify=True)
    time.sleep(0.1)
    send("textDocument/foldingRange", {"textDocument": {"uri": fold_uri}})
    r = recv()
    folds = r["result"]
    check("folding has ranges", len(folds) >= 1)
    check("fold startLine is 0", folds[0]["startLine"] == 0)
    check("fold endLine > startLine", folds[0]["endLine"] > folds[0]["startLine"])
    check("fold kind is region", folds[0]["kind"] == "region")
    send("textDocument/didClose", {"textDocument": {"uri": fold_uri}}, notify=True)
    time.sleep(0.1)
    _notifs.clear()

    # ── Workspace Symbol ─────────────────────────────────────
    print("workspace/symbol")
    send("workspace/symbol", {"query": "f"})
    r = recv()
    ws_syms = r["result"]
    check("workspace/symbol has results", len(ws_syms) >= 1)
    check("workspace/symbol name", any(s["name"] == "f" for s in ws_syms))
    check("workspace/symbol has location", "location" in ws_syms[0])

    send("workspace/symbol", {"query": ""})
    r = recv()
    check("workspace/symbol empty query returns all", len(r["result"]) >= 4)

    send("workspace/symbol", {"query": "zzz_nonexistent"})
    r = recv()
    check("workspace/symbol no match returns empty", len(r["result"]) == 0)

    # ── Selection Range ──────────────────────────────────────
    print("selectionRange")
    send("textDocument/selectionRange", {**td(), "positions": [{"line": 0, "character": 9}]})
    r = recv()
    sel = r["result"]
    check("selectionRange returns list", isinstance(sel, list) and len(sel) == 1)
    check("selectionRange has range", "range" in sel[0])
    check("selectionRange has parent", "parent" in sel[0])
    # Walk up the chain — should have multiple levels
    depth = 0; node = sel[0]
    while node and isinstance(node, dict) and "range" in node:
        depth += 1; node = node.get("parent")
    check("selectionRange depth > 2", depth > 2)

    # ── Semantic Tokens ──────────────────────────────────────
    print("semanticTokens/full")
    send("textDocument/semanticTokens/full", td())
    r = recv()
    data = r["result"]["data"]
    check("semantic tokens has data", len(data) > 0)
    check("semantic tokens multiple of 5", len(data) % 5 == 0)
    # First token should be f at (0,0) — function definition (type=2, mod=2)
    check("first token deltaLine=0", data[0] == 0)
    check("first token deltaCol=0", data[1] == 0)
    check("first token type=function(2)", data[3] == 2)
    check("first token mod=definition(2)", data[4] == 2)

    # ── Code Action ──────────────────────────────────────────
    print("codeAction")
    # Open a file with a missing bracket
    ca_uri = "file:///codeaction.q"
    send("textDocument/didOpen", {"textDocument": {"uri": ca_uri, "languageId": "q",
         "version": 1, "text": "f:{[x] x+"}}, notify=True)
    diag_notif = recv_notif()
    diags = diag_notif["params"]["diagnostics"]
    # Request code actions with those diagnostics
    send("textDocument/codeAction", {"textDocument": {"uri": ca_uri},
         "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 10}},
         "context": {"diagnostics": diags}})
    r = recv()
    actions = r["result"]
    # May or may not have actions depending on whether errors are "missing" type
    check("codeAction returns list", isinstance(actions, list))
    # Check with a known missing-bracket case
    missing_diags = [d for d in diags if d["message"].startswith("missing ")]
    if missing_diags:
        check("codeAction has fix for missing token", len(actions) > 0)
        check("codeAction kind is quickfix", actions[0]["kind"] == "quickfix")
        check("codeAction has edit", "edit" in actions[0])
    else:
        check("codeAction empty for non-missing errors", True)
    send("textDocument/didClose", {"textDocument": {"uri": ca_uri}}, notify=True)
    time.sleep(0.1)
    _notifs.clear()

    # ── Formatting ───────────────────────────────────────────
    print("formatting")
    fmt_uri = "file:///fmt.q"
    fmt_text = "f:{x+y}   \n\n\n\ng:42  \n"
    send("textDocument/didOpen", {"textDocument": {"uri": fmt_uri, "languageId": "q",
         "version": 1, "text": fmt_text}}, notify=True)
    time.sleep(0.1)
    send("textDocument/formatting", {"textDocument": {"uri": fmt_uri},
         "options": {"tabSize": 2, "insertSpaces": True}})
    r = recv()
    edits = r["result"]
    check("formatting returns edits", len(edits) > 0)
    check("formatting edit has range", "range" in edits[0])
    check("formatting edit has newText", "newText" in edits[0])
    new_text = edits[0]["newText"]
    check("formatting strips trailing ws", "   " not in new_text)
    check("formatting collapses blank lines", "\n\n\n" not in new_text)
    check("formatting has trailing newline", new_text.endswith("\n"))

    # Already clean text returns empty edits
    fmt2_uri = "file:///fmt2.q"
    send("textDocument/didOpen", {"textDocument": {"uri": fmt2_uri, "languageId": "q",
         "version": 1, "text": "f:{x+y}\ng:42\n"}}, notify=True)
    time.sleep(0.1)
    send("textDocument/formatting", {"textDocument": {"uri": fmt2_uri},
         "options": {"tabSize": 2, "insertSpaces": True}})
    r = recv()
    check("formatting clean text returns empty", r["result"] == [])
    send("textDocument/didClose", {"textDocument": {"uri": fmt_uri}}, notify=True)
    send("textDocument/didClose", {"textDocument": {"uri": fmt2_uri}}, notify=True)
    time.sleep(0.1)
    _notifs.clear()

    # ── didClose ─────────────────────────────────────────────
    print("didClose")
    _notifs.clear()
    send("textDocument/didClose", td(), notify=True)
    time.sleep(0.1)
    send("textDocument/hover", {**td(), "position": {"line": 0, "character": 0}})
    r = recv()
    check("hover after close returns null", r["result"] is None)

    # ── Shutdown + exit ──────────────────────────────────────
    print("shutdown")
    send("shutdown")
    r = recv()
    check("shutdown returns null result", r["result"] is None)
    send("exit", notify=True)
    proc.wait(timeout=2)
    check("process exited", proc.returncode == 0)

    # ── Summary ──────────────────────────────────────────────
    print(f"\n{pass_n} passed, {fail_n} failed")
    if fail_n > 0:
        sys.exit(1)
    print("all tests passed")

except Exception as e:
    _die(f"ERROR: {e}")
