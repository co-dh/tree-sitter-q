# tree-sitter-q

Tree-sitter grammar for the q/kdb+ programming language. Provides syntax highlighting and an LSP server with
go-to-definition, hover, completion, and document symbols.

## Helix

Add to `~/.config/helix/languages.toml`:

```toml
[[language]]
name = "q"
scope = "source.q"
file-types = ["q", "k"]
comment-token = "/"
indent = { tab-width = 2, unit = "  " }

[[grammar]]
name = "q"
source = { git = "https://github.com/co-dh/tree-sitter-q", rev = "main" }
```

Then fetch and build:

```sh
helix --grammar fetch
helix --grammar build
```

Verify with `helix --health q` — should show parser and highlights as green.

## LSP (optional, requires q)

The LSP server is written in q and uses tree-sitter via a C bridge (`2:` FFI). It provides hover (shows function bodies
and k implementations for builtins), go-to-definition, completion, and document symbols.

### Prerequisites

- q/kdb+ runtime
- `k.h` header (from kx — set `KDB_INC` to its directory)
- `libtree-sitter` shared library

### Build and test

```sh
KDB_INC=/path/to/kdb make test
```

### Configure in Helix

Add to `~/.config/helix/languages.toml`:

```toml
[language-server.q-lsp]
command = "q"
args = ["/path/to/tree-sitter-q/lsp/lsp.q", "-q"]

[[language]]
name = "q"
language-servers = ["q-lsp"]
```

## Development

Edit `grammar.js`, then regenerate and rebuild:

```sh
tree-sitter generate          # regenerates src/parser.c
tree-sitter parse test.q      # verify parse tree
tree-sitter highlight test.q  # verify highlighting
make                          # rebuild LSP bridge
```

See [doc/how-it-works.md](doc/how-it-works.md) for a detailed explanation of the build pipeline and architecture.
