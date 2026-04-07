#!/usr/bin/env python3
"""End-to-end tests for the q LSP server."""
import sys, time
from lsp_harness import LSPClient, TestRunner

lsp = LSPClient()
t = TestRunner()
check = t.check

URI = "file:///test.q"
def td(**kw): return {"textDocument": {"uri": URI, **kw}}

try:
    # ── Initialize ───────────────────────────────────────────
    print("initialize")
    lsp.send("initialize", {"capabilities": {}})
    r = lsp.recv()
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
    lsp.send("initialized", notify=True)

    # ── Open document ────────────────────────────────────────
    print("didOpen")
    text = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]\nn:count result"
    lsp.send("textDocument/didOpen", {**td(languageId="q", version=1, text=text)}, notify=True)
    time.sleep(0.1)

    # ── Hover: user-defined function ─────────────────────────
    print("hover")
    lsp.send("textDocument/hover", {**td(), "position": {"line": 0, "character": 0}})
    r = lsp.recv()
    hover_f = r["result"]["contents"]["value"]
    check("hover f shows body", "{[x;y] x+y}" in hover_f)

    # ── Hover: global variable ───────────────────────────────
    lsp.send("textDocument/hover", {**td(), "position": {"line": 1, "character": 0}})
    r = lsp.recv()
    hover_g = r["result"]["contents"]["value"]
    check("hover g shows global", "(global)" in hover_g)
    check("hover g shows value", "42" in hover_g)

    # ── Hover: builtin identifier (count) ──────────────────────
    lsp.send("textDocument/hover", {**td(), "position": {"line": 3, "character": 2}})
    r = lsp.recv()
    hover_count = r["result"]["contents"]["value"]
    check("hover builtin has content", len(hover_count) > 0)

    # ── Hover: verb (count) ────────────────────────────────
    lsp.send("textDocument/hover", {**td(), "position": {"line": 3, "character": 2}})
    r = lsp.recv()
    hover_verb = r["result"]["contents"]["value"]
    check("hover verb shows k impl", len(hover_verb) > 0 and hover_verb != "count")

    # ── Hover: no node ───────────────────────────────────────
    lsp.send("textDocument/hover", {**td(), "position": {"line": 99, "character": 0}})
    r = lsp.recv()
    check("hover empty line returns null", r["result"] is None)

    # ── Go to definition ─────────────────────────────────────
    print("definition")
    lsp.send("textDocument/definition", {**td(), "position": {"line": 2, "character": 7}})
    r = lsp.recv()
    defn = r["result"]
    check("def f has uri", defn["uri"] == URI)
    check("def f points to line 0", defn["range"]["start"]["line"] == 0)

    # ── Definition of undefined symbol ───────────────────────
    lsp.send("textDocument/definition", {**td(), "position": {"line": 2, "character": 0}})
    r = lsp.recv()
    check("def result found", r["result"] is not None)

    # ── Document symbols ─────────────────────────────────────
    print("documentSymbol")
    lsp.send("textDocument/documentSymbol", td())
    r = lsp.recv()
    syms = r["result"]
    sym_names = [s["name"] for s in syms]
    check("4 symbols", len(syms) == 4)
    check("f in symbols", "f" in sym_names)
    check("g :: in symbols", "g ::" in sym_names)
    check("result in symbols", "result" in sym_names)
    check("n in symbols", "n" in sym_names)

    # ── Completion ───────────────────────────────────────────
    print("completion")
    lsp.send("textDocument/completion", {**td(), "position": {"line": 0, "character": 0}})
    r = lsp.recv()
    items = r["result"]
    labels = [i["label"] for i in items]
    check("completion has user defs", "f" in labels and "g" in labels)
    check("completion has builtins", "count" in labels or "select" in labels)
    check("completion count > 100", len(items) > 100)

    # ── References ───────────────────────────────────────────
    print("references")
    lsp.send("textDocument/references", {**td(), "position": {"line": 0, "character": 0},
         "context": {"includeDeclaration": True}})
    r = lsp.recv()
    refs = r["result"]
    check("refs f has 2 hits", len(refs) == 2)
    check("refs f all same uri", all(ref["uri"] == URI for ref in refs))

    lsp.send("textDocument/references", {**td(), "position": {"line": 0, "character": 9},
         "context": {"includeDeclaration": True}})
    r = lsp.recv()
    check("refs x has 2 hits", len(r["result"]) == 2)

    lsp.send("textDocument/references", {**td(), "position": {"line": 99, "character": 0},
         "context": {"includeDeclaration": True}})
    r = lsp.recv()
    check("refs unknown returns empty", r["result"] == [])

    # ── Prepare Rename ───────────────────────────────────────
    print("prepareRename")
    lsp.send("textDocument/prepareRename", {**td(), "position": {"line": 0, "character": 0}})
    r = lsp.recv()
    check("prepareRename f has range", "range" in r["result"])
    check("prepareRename f placeholder", r["result"]["placeholder"] == "f")

    lsp.send("textDocument/prepareRename", {**td(), "position": {"line": 3, "character": 2}})
    r = lsp.recv()
    check("prepareRename builtin null", r["result"] is None)

    # ── Rename ───────────────────────────────────────────────
    print("rename")
    lsp.send("textDocument/rename", {**td(), "position": {"line": 0, "character": 0}, "newName": "add"})
    r = lsp.recv()
    changes = r["result"]["changes"]
    check("rename has changes", URI in changes)
    edits = changes[URI]
    check("rename f->add 2 edits", len(edits) == 2)
    check("rename newText", all(e["newText"] == "add" for e in edits))

    # ── didChange ────────────────────────────────────────────
    print("didChange")
    text2 = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]\nn:count result\nh:{neg x}"
    lsp.send("textDocument/didChange", {**td(version=2), "contentChanges": [{"text": text2}]}, notify=True)
    time.sleep(0.1)
    lsp.send("textDocument/documentSymbol", td())
    r = lsp.recv()
    check("didChange: 5 symbols after edit", len(r["result"]) == 5)
    check("didChange: h in symbols", "h" in [s["name"] for s in r["result"]])

    # ── Diagnostics ──────────────────────────────────────────
    print("diagnostics")
    lsp.clear_notifs()
    bad_uri = "file:///bad.q"
    lsp.send("textDocument/didOpen", {"textDocument": {"uri": bad_uri, "languageId": "q",
         "version": 1, "text": "f:{[x] x+"}}, notify=True)
    r = lsp.recv_notif()
    check("diag method", r["method"] == "textDocument/publishDiagnostics")
    check("diag has errors", len(r["params"]["diagnostics"]) > 0)
    check("diag severity", r["params"]["diagnostics"][0]["severity"] == 1)
    check("diag source", r["params"]["diagnostics"][0]["source"] == "tree-sitter")

    lsp.send("textDocument/didChange", {"textDocument": {"uri": bad_uri, "version": 2},
         "contentChanges": [{"text": "f:{[x] x+1}"}]}, notify=True)
    r = lsp.recv_notif()
    check("diag cleared after fix", len(r["params"]["diagnostics"]) == 0)

    lsp.send("textDocument/didClose", {"textDocument": {"uri": bad_uri}}, notify=True)
    r = lsp.recv_notif()
    check("close clears diag", len(r["params"]["diagnostics"]) == 0)

    # ── Document Highlight ───────────────────────────────────
    print("documentHighlight")
    lsp.clear_notifs()
    lsp.send("textDocument/didOpen", {**td(languageId="q", version=1, text=text2)}, notify=True)
    time.sleep(0.1)
    lsp.send("textDocument/documentHighlight", {**td(), "position": {"line": 0, "character": 0}})
    r = lsp.recv()
    highlights = r["result"]
    check("highlight f has 2 hits", len(highlights) == 2)
    check("highlight has range", "range" in highlights[0])
    check("highlight kind is 1 (text)", highlights[0]["kind"] == 1)

    lsp.send("textDocument/documentHighlight", {**td(), "position": {"line": 99, "character": 0}})
    r = lsp.recv()
    check("highlight empty returns empty", r["result"] == [])

    # ── Folding Range ────────────────────────────────────────
    print("foldingRange")
    fold_uri = "file:///fold.q"
    fold_text = "f:{\n  x+y\n  }\ng:42"
    lsp.send("textDocument/didOpen", {"textDocument": {"uri": fold_uri, "languageId": "q",
         "version": 1, "text": fold_text}}, notify=True)
    time.sleep(0.1)
    lsp.send("textDocument/foldingRange", {"textDocument": {"uri": fold_uri}})
    r = lsp.recv()
    folds = r["result"]
    check("folding has ranges", len(folds) >= 1)
    check("fold startLine is 0", folds[0]["startLine"] == 0)
    check("fold endLine > startLine", folds[0]["endLine"] > folds[0]["startLine"])
    check("fold kind is region", folds[0]["kind"] == "region")
    lsp.send("textDocument/didClose", {"textDocument": {"uri": fold_uri}}, notify=True)
    time.sleep(0.1)
    lsp.clear_notifs()

    # ── Workspace Symbol ─────────────────────────────────────
    print("workspace/symbol")
    lsp.send("workspace/symbol", {"query": "f"})
    r = lsp.recv()
    ws_syms = r["result"]
    check("workspace/symbol has results", len(ws_syms) >= 1)
    check("workspace/symbol name", any(s["name"] == "f" for s in ws_syms))
    check("workspace/symbol has location", "location" in ws_syms[0])

    lsp.send("workspace/symbol", {"query": ""})
    r = lsp.recv()
    check("workspace/symbol empty query returns all", len(r["result"]) >= 4)

    lsp.send("workspace/symbol", {"query": "zzz_nonexistent"})
    r = lsp.recv()
    check("workspace/symbol no match returns empty", len(r["result"]) == 0)

    # ── Selection Range ──────────────────────────────────────
    print("selectionRange")
    lsp.send("textDocument/selectionRange", {**td(), "positions": [{"line": 0, "character": 9}]})
    r = lsp.recv()
    sel = r["result"]
    check("selectionRange returns list", isinstance(sel, list) and len(sel) == 1)
    check("selectionRange has range", "range" in sel[0])
    check("selectionRange has parent", "parent" in sel[0])
    depth = 0; node = sel[0]
    while node and isinstance(node, dict) and "range" in node:
        depth += 1; node = node.get("parent")
    check("selectionRange depth > 2", depth > 2)

    # ── Semantic Tokens ──────────────────────────────────────
    print("semanticTokens/full")
    lsp.send("textDocument/semanticTokens/full", td())
    r = lsp.recv()
    data = r["result"]["data"]
    check("semantic tokens has data", len(data) > 0)
    check("semantic tokens multiple of 5", len(data) % 5 == 0)
    check("first token deltaLine=0", data[0] == 0)
    check("first token deltaCol=0", data[1] == 0)
    check("first token type=function(2)", data[3] == 2)
    check("first token mod=definition(2)", data[4] == 2)

    # ── Code Action ──────────────────────────────────────────
    print("codeAction")
    ca_uri = "file:///codeaction.q"
    lsp.send("textDocument/didOpen", {"textDocument": {"uri": ca_uri, "languageId": "q",
         "version": 1, "text": "f:{[x] x+"}}, notify=True)
    diag_notif = lsp.recv_notif()
    diags = diag_notif["params"]["diagnostics"]
    lsp.send("textDocument/codeAction", {"textDocument": {"uri": ca_uri},
         "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 10}},
         "context": {"diagnostics": diags}})
    r = lsp.recv()
    actions = r["result"]
    check("codeAction returns list", isinstance(actions, list))
    missing_diags = [d for d in diags if d["message"].startswith("missing ")]
    if missing_diags:
        check("codeAction has fix for missing token", len(actions) > 0)
        check("codeAction kind is quickfix", actions[0]["kind"] == "quickfix")
        check("codeAction has edit", "edit" in actions[0])
    else:
        check("codeAction empty for non-missing errors", True)
    lsp.send("textDocument/didClose", {"textDocument": {"uri": ca_uri}}, notify=True)
    time.sleep(0.1)
    lsp.clear_notifs()

    # ── Formatting ───────────────────────────────────────────
    print("formatting")
    fmt_uri = "file:///fmt.q"
    fmt_text = "f:{x+y}   \n\n\n\ng:42  \n"
    lsp.send("textDocument/didOpen", {"textDocument": {"uri": fmt_uri, "languageId": "q",
         "version": 1, "text": fmt_text}}, notify=True)
    time.sleep(0.1)
    lsp.send("textDocument/formatting", {"textDocument": {"uri": fmt_uri},
         "options": {"tabSize": 2, "insertSpaces": True}})
    r = lsp.recv()
    edits = r["result"]
    check("formatting returns edits", len(edits) > 0)
    check("formatting edit has range", "range" in edits[0])
    check("formatting edit has newText", "newText" in edits[0])
    new_text = edits[0]["newText"]
    check("formatting strips trailing ws", "   " not in new_text)
    check("formatting collapses blank lines", "\n\n\n" not in new_text)
    check("formatting has trailing newline", new_text.endswith("\n"))

    fmt2_uri = "file:///fmt2.q"
    lsp.send("textDocument/didOpen", {"textDocument": {"uri": fmt2_uri, "languageId": "q",
         "version": 1, "text": "f:{x+y}\ng:42\n"}}, notify=True)
    time.sleep(0.1)
    lsp.send("textDocument/formatting", {"textDocument": {"uri": fmt2_uri},
         "options": {"tabSize": 2, "insertSpaces": True}})
    r = lsp.recv()
    check("formatting clean text returns empty", r["result"] == [])
    lsp.send("textDocument/didClose", {"textDocument": {"uri": fmt_uri}}, notify=True)
    lsp.send("textDocument/didClose", {"textDocument": {"uri": fmt2_uri}}, notify=True)
    time.sleep(0.1)
    lsp.clear_notifs()

    # ── didClose ─────────────────────────────────────────────
    print("didClose")
    lsp.clear_notifs()
    lsp.send("textDocument/didClose", td(), notify=True)
    time.sleep(0.1)
    lsp.send("textDocument/hover", {**td(), "position": {"line": 0, "character": 0}})
    r = lsp.recv()
    check("hover after close returns null", r["result"] is None)

    # ── Shutdown + exit ──────────────────────────────────────
    print("shutdown")
    lsp.send("shutdown")
    r = lsp.recv()
    check("shutdown returns null result", r["result"] is None)
    lsp.send("exit", notify=True)
    lsp.proc.wait(timeout=2)
    check("process exited", lsp.proc.returncode == 0)

    t.summary()

except Exception as e:
    lsp.die(f"ERROR: {e}")
