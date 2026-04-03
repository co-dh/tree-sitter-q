#!/usr/bin/env python3
"""End-to-end tests for the q LSP server."""
import subprocess, json, sys, threading, time

proc = subprocess.Popen(["q", "lsp.q", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=sys.path[0] or ".")

stderr_lines = []
def read_stderr():
    for line in proc.stderr:
        stderr_lines.append(line.decode().rstrip())
threading.Thread(target=read_stderr, daemon=True).start()

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

def recv(timeout=5):
    headers = {}
    deadline = time.time() + timeout
    buf = b""
    while True:
        if time.time() > deadline:
            print("TIMEOUT", file=sys.stderr)
            print("stderr:", stderr_lines, file=sys.stderr)
            proc.kill(); sys.exit(1)
        c = proc.stdout.read(1)
        if not c:
            print("EOF", file=sys.stderr)
            print("stderr:", stderr_lines, file=sys.stderr)
            proc.kill(); sys.exit(1)
        if c == b"\n":
            line = buf.rstrip(b"\r")
            buf = b""
            if not line: break
            if line.startswith(b"Content-Length:"):
                headers["cl"] = int(line.split(b":")[1].strip())
        else:
            buf += c
    return json.loads(proc.stdout.read(headers["cl"]))

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
    check("serverInfo name", r["result"]["serverInfo"]["name"] == "q-lsp")
    send("initialized", notify=True)

    # ── Open document ────────────────────────────────────────
    print("didOpen")
    text = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]"
    send("textDocument/didOpen", {"textDocument": {"uri": "file:///test.q", "languageId": "q", "version": 1, "text": text}}, notify=True)
    time.sleep(0.1)  # let server process

    # ── Hover: user-defined function ─────────────────────────
    print("hover")
    send("textDocument/hover", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 0, "character": 0}})
    r = recv()
    hover_f = r["result"]["contents"]["value"]
    check("hover f shows body", "{[x;y] x+y}" in hover_f)

    # ── Hover: global variable ───────────────────────────────
    send("textDocument/hover", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 1, "character": 0}})
    r = recv()
    hover_g = r["result"]["contents"]["value"]
    check("hover g shows global", "(global)" in hover_g)
    check("hover g shows value", "42" in hover_g)

    # ── Hover: no node ───────────────────────────────────────
    send("textDocument/hover", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 99, "character": 0}})
    r = recv()
    check("hover empty line returns null", r["result"] is None)

    # ── Go to definition ─────────────────────────────────────
    print("definition")
    send("textDocument/definition", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 2, "character": 7}})
    r = recv()
    defn = r["result"]
    check("def f has uri", defn["uri"] == "file:///test.q")
    check("def f points to line 0", defn["range"]["start"]["line"] == 0)

    # ── Definition of undefined symbol ───────────────────────
    send("textDocument/definition", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 2, "character": 0}})
    r = recv()
    defn_result = r["result"]
    # "result" is the assignment target — should find it
    check("def result found", defn_result is not None)

    # ── Document symbols ─────────────────────────────────────
    print("documentSymbol")
    send("textDocument/documentSymbol", {"textDocument": {"uri": "file:///test.q"}})
    r = recv()
    syms = r["result"]
    sym_names = [s["name"] for s in syms]
    check("3 symbols", len(syms) == 3)
    check("f in symbols", "f" in sym_names)
    check("g :: in symbols", "g ::" in sym_names)
    check("result in symbols", "result" in sym_names)

    # ── Completion ───────────────────────────────────────────
    print("completion")
    send("textDocument/completion", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 0, "character": 0}})
    r = recv()
    items = r["result"]
    labels = [i["label"] for i in items]
    check("completion has user defs", "f" in labels and "g" in labels)
    check("completion has builtins", "count" in labels or "select" in labels)
    check("completion count > 100", len(items) > 100)  # builtins + user defs

    # ── didChange ────────────────────────────────────────────
    print("didChange")
    text2 = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]\nh:{neg x}"
    send("textDocument/didChange", {"textDocument": {"uri": "file:///test.q", "version": 2},
         "contentChanges": [{"text": text2}]}, notify=True)
    time.sleep(0.1)
    send("textDocument/documentSymbol", {"textDocument": {"uri": "file:///test.q"}})
    r = recv()
    check("didChange: 4 symbols after edit", len(r["result"]) == 4)
    check("didChange: h in symbols", "h" in [s["name"] for s in r["result"]])

    # ── didClose ─────────────────────────────────────────────
    print("didClose")
    send("textDocument/didClose", {"textDocument": {"uri": "file:///test.q"}}, notify=True)
    time.sleep(0.1)
    send("textDocument/hover", {"textDocument": {"uri": "file:///test.q"}, "position": {"line": 0, "character": 0}})
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
    print(f"ERROR: {e}", file=sys.stderr)
    print("stderr:", stderr_lines, file=sys.stderr)
    proc.kill(); sys.exit(1)
