# How tree-sitter-q Works

A tree-sitter grammar that parses q/kdb+ code into a syntax tree. Used for syntax highlighting (Helix) and the LSP
(go-to-def, hover, completion).

## What tree-sitter does

Tree-sitter is a parser generator. You write a grammar in JavaScript (`grammar.js`), and tree-sitter generates a C
parser from it. The generated parser is fast (incremental, runs on every keystroke) and produces a concrete syntax tree
(CST) — every token has a typed node with byte positions.

```
grammar.js  ──[tree-sitter generate]──>  src/parser.c + src/node-types.json
```

The generated C code is ~22k lines — you never edit it. You edit `grammar.js` and regenerate.

## Files and what they do

```
grammar.js              You write this. Defines q's syntax rules.
src/parser.c            Generated. The actual parser (state machine tables).
src/scanner.c           You write this. Handles context-sensitive tokens
                        that can't be expressed in grammar.js (comments, whitespace).
src/node-types.json     Generated. Lists all node types the parser can produce.
                        Used by editors to validate highlight queries.
queries/highlights.scm  You write this. Maps node types → highlight groups.
                        Written in S-expression query syntax.
tree-sitter.json        Metadata for the tree-sitter CLI (name, file-types, paths).
ts_q.c                  You write this. C bridge exposing tree-sitter to q via 2: FFI.
lsp.q                   You write this. LSP server in q, calls ts_q.so for parsing.
```

## Build flow

### Step 1: Generate the parser

```sh
tree-sitter generate
```

Reads `grammar.js`, produces `src/parser.c` and `src/node-types.json`. This is a **build-time** step — you only re-run
it when you change the grammar. The generated files are checked into git so consumers don't need the tree-sitter CLI.

### Step 2: Build the shared library for q

```sh
make          # builds ts_q.so
```

This compiles three C files together into one `.so`:

```
ts_q.c  +  src/parser.c  +  src/scanner.c  ──[cc -shared]──>  ts_q.so
```

- `parser.c` = the generated parser (state tables + tree-sitter runtime calls)
- `scanner.c` = custom scanner for q's context-sensitive `/` comments
- `ts_q.c` = glue code that wraps tree-sitter's C API into q-callable functions via k.h

The result `ts_q.so` is loaded by q at runtime: `` `ts_q 2: (`ts_parse;1) `` gives q a function that parses a string
into a syntax tree.

### Step 3: Build the shared library for Helix

```sh
cc -shared -fPIC -o q.so src/parser.c src/scanner.c -I src -O2
cp q.so ~/.config/helix/runtime/grammars/q.so
cp queries/highlights.scm ~/.config/helix/runtime/queries/q/highlights.scm
```

Same parser + scanner, but **without** `ts_q.c` — Helix links directly against tree-sitter and calls the parser itself.
Helix just needs the raw grammar `.so` and the highlight queries.

## How the grammar works

`grammar.js` defines q's syntax as a set of rules. Each rule produces a **named node** in the parse tree. For example:

```javascript
assignment: $ => seq(
  field('name', $._name),     // left side
  ':',                        // literal colon
  field('value', $._expr),    // right side
),
```

When tree-sitter parses `f:{x+1}`, it produces:

```
(assignment
  name: (identifier)          "f"       bytes 0-1
  value: (lambda              "{x+1}"   bytes 2-7
    (binary_expr
      left: (identifier)      "x"
      op: (operator)          "+"
      right: (integer)        "1")))
```

Every node has: type name, start/end byte positions, start/end row/column, and optional field names (`name:`,
`value:`). The `field()` wrappers in the grammar let you access children by name instead of index.

### Precedence and conflicts

q evaluates right-to-left with no operator precedence (`2*3+4 = 14`). The grammar uses `prec.right()` to encode this.
The `conflicts` array lists ambiguities tree-sitter resolves via GLR parsing — for example, `f x` could be function
application or a binary expression depending on what `f` is.

### The external scanner (`scanner.c`)

Some tokens in q depend on context that a regular grammar can't express:

- `/` is a **comment** if preceded by whitespace or at column 0, but an **adverb** (iterator) otherwise:
  `x/y` = over, `x  / comment` = comment
- `\d .ns` at column 0 is a **system command**, but `\` elsewhere is an adverb

The external scanner (`scanner.c`) runs C code to make these decisions. It's declared in `grammar.js` as:

```javascript
externals: $ => [$.line_comment, $.block_comment, $.backslash_cmd, $._whitespace],
```

Tree-sitter calls the scanner whenever it needs one of these tokens. The scanner checks column position and surrounding
characters to decide.

## How highlighting works

`queries/highlights.scm` maps parse tree patterns to highlight groups using S-expression queries:

```scheme
(verb) @function.builtin                                    ; count, first, etc.
(operator) @operator                                        ; + - * %
(assignment name: (identifier) @function.macro value: (lambda))  ; f:{...} = purple
((verb) @keyword (#any-of? @keyword "select" "exec" ...))   ; select = keyword color
```

The editor walks the tree, matches these patterns, and applies colors. **Last match wins** — so specific patterns
(function definitions) override general ones (identifiers).

## How the LSP uses the tree

`lsp.q` loads `ts_q.so` and calls:

| q function                 | Does what                                                          |
| -------------------------- | ------------------------------------------------------------------ |
| `ts_parse[text]`           | Parse string → opaque tree handle (long)                           |
| `ts_defs[handle;text]`     | Walk root children, extract assignments → table of definitions     |
| `ts_node_at[h;text;r;c]`  | Find the named node at row/col → dict with type, text, positions   |
| `ts_free[handle]`          | Free a parse tree                                                  |

On every `didOpen`/`didChange`, the LSP parses the full file and extracts definitions. On hover/goto-def/completion, it
queries the tree for the node at the cursor position, then looks up definitions across all open documents.

The tree handle is a raw pointer cast to a q long (via `kj((J)tree)`). The q side never dereferences it — just passes
it back to C functions. This is the standard pattern for opaque handles in q's `2:` FFI.

## How to modify the grammar

1. Edit `grammar.js` (add/change rules)
2. If you need context-sensitive tokenization, edit `src/scanner.c`
3. Run `tree-sitter generate` to regenerate `src/parser.c`
4. Test: `tree-sitter parse test.q` to see the tree, `tree-sitter highlight test.q` to test colors
5. Rebuild: `make` (for q), copy `.so` + `highlights.scm` to Helix runtime (for editor)
6. Update `queries/highlights.scm` if you added new node types
