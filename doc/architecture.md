# LSP Architecture

```
                          ┌─────────────────────────────────────────┐
                          │              Helix Editor               │
                          │                                         │
                          │  .q file → tree-sitter q.so (highlight) │
                          │  cursor  → LSP client (hover/def/comp)  │
                          └────────────────┬────────────────────────┘
                                           │ stdin/stdout
                                           │ Content-Length framing
                          ┌────────────────┴────────────────────────┐
                          │           lsp.q  (main loop)            │
                          │                                         │
                          │  readMsg ◄── stdin_line[] + stdin_read[]│
                          │     │         (C helpers in ts_q.so)    │
                          │     ▼                                   │
                          │  handle ──► dispatch by method name     │
                          │     │                                   │
                          │     ▼                                   │
                          │  respond ──► writeMsg ──► stdout        │
                          └────────────────┬────────────────────────┘
                                           │
              ┌────────────────────────────┬┴───────────────────────────┐
              │                            │                            │
    ┌─────────┴──────────┐   ┌─────────────┴───────────┐  ┌────────────┴──────────┐
    │   Document State   │   │      Handlers           │  │    Builtins           │
    │                    │   │                          │  │                       │
    │ .lsp.docs:         │   │ hInit     → capabilities │  │ .Q.res → reserved    │
    │   uri → (text      │   │ hDef      → go-to-def    │  │ key `.q → stdlib     │
    │          tree_h    │   │ hHover    → hover info   │  │                       │
    │          defs_tbl) │   │ hCompletion → items      │  │ builtinDoc:           │
    │                    │   │ hSymbols  → symbol list  │  │   .Q.s1 .q w         │
    │ updateDoc: parse   │   │                          │  │   (k implementation)  │
    │   + extract defs   │   │                          │  │                       │
    │ closeDoc: free     │   │                          │  │                       │
    └─────────┬──────────┘   └──────────┬───────────────┘  └───────────────────────┘
              │                         │
              │    ┌────────────────────┘
              │    │  queries
              ▼    ▼
    ┌─────────────────────────────┐
    │    ts_q.so  (C bridge)      │
    │                             │
    │  ts_parse[text] → tree_h    │
    │  ts_defs[h;text] → table   │
    │  ts_node_at[h;t;r;c] → dict│
    │  ts_free[h]                 │
    │  stdin_read[n] → bytes     │
    │  stdin_line[] → string     │
    └──────────────┬──────────────┘
                   │ links
                   ▼
    ┌─────────────────────────────┐
    │   libtree-sitter            │
    │                             │
    │  TSParser + TSTree + TSNode │
    │  Generated from grammar.js  │
    │  via src/parser.c           │
    │      src/scanner.c          │
    └─────────────────────────────┘
```

## Example: hover on `count`

1. Helix sends `textDocument/hover` with position → `readMsg` parses JSON-RPC
2. `handle` dispatches to `hHover`
3. `nodeAt` calls `ts_node_at` in C → returns `` {type:`verb; text:"count"; ...} ``
4. `verb` type → look up `` .Q.s1 .q `count `` → returns k implementation `#:`
5. `respond` sends `mkHover` result back via `writeMsg`
