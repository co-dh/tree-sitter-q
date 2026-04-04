/ q/kdb+ Language Server — powered by tree-sitter
/ Features: go-to-definition, completion, document symbols, hover, references, rename, diagnostics
/ Protocol: LSP JSON-RPC over stdio (Content-Length framing)
/ Usage: q lsp.q -q
/ Configure in editor to launch this as a language server.
/ Requires ts_q.so in the same directory (built via make).

/ ── Load tree-sitter bridge ──────────────────────────────────
/ ts_q.so provides: ts_init, ts_parse, ts_free, ts_defs, ts_node_at, ts_parent
/ plus stdin_read/stdin_line for byte-level stdio (q's read0 only does lines)
tsdir:      first ` vs hsym .z.f       / directory of this script
tso:        ` sv (tsdir;`ts_q)
ts_init:    tso 2: (`ts_init;1)
ts_parse:   tso 2: (`ts_parse;1)
ts_free:    tso 2: (`ts_free;1)
ts_defs:    tso 2: (`ts_defs;2)
ts_node_at: tso 2: (`ts_node_at;4)
ts_parent:  tso 2: (`ts_parent;4)
ts_refs:    tso 2: (`ts_refs;3)
ts_errors:  tso 2: (`ts_errors;2)
ts_children:tso 2: (`ts_children;2)
ts_ancestors:tso 2: (`ts_ancestors;4)
ts_tokens:  tso 2: (`ts_tokens;2)
stdin_read: tso 2: (`stdin_read;1)
stdin_line: tso 2: (`stdin_line;1)
ts_init[];

/ ── Built-in docs from q itself ──────────────────────────────
/ Builtins derived at runtime from q itself, not hardcoded.
/ .Q.res = reserved words (select, exec, etc.)
/ key `.q = stdlib functions (count, first, each, etc.)
/ builtinDoc uses .Q.s1 to show k implementation (same as typing name in console)
builtins:(.Q.res,1_ key `.q) except `;
builtinDoc:{[w]
    ; if[w in 1_ key `.q; :.Q.s1 .q w]
    ; if[w in .Q.res; :"(reserved) ",string w]
    ; ""}

/ ── Document state ───────────────────────────────────────────
/ Maps URI (as symbol) → (source_text; tree_handle; defs_table)
/ tree_handle is an opaque long (pointer to TSTree, passed back to C)
/ defs_table has columns: name, srow, scol, erow, ecol, global, lambda, detail
.lsp.docs:(`symbol$())!();

/ Parse text with tree-sitter, extract top-level definitions, store in .lsp.docs
updateDoc:{[uri;text]
    ; su:`$uri
    ; if[su in key .lsp.docs; ts_free .lsp.docs[su] 1]  / free old tree
    ; h:ts_parse text
    ; d:ts_defs[h;text]
    ; .lsp.docs[su]:(text;h;d)
    ; publishDiag[uri]}

closeDoc:{[uri]
    ; su:`$uri
    ; notify["textDocument/publishDiagnostics";`uri`diagnostics!(uri;())]
    ; if[su in key .lsp.docs; ts_free .lsp.docs[su] 1]
    ; .lsp.docs _:su}

/ ── Helpers ──────────────────────────────────────────────────
/ Build LSP Range object from row/col pairs
mkRange:{[sr;sc;er;ec]
  `start`end!(`line`character!(sr;sc);`line`character!(er;ec))}

/ Get the text of the symbol at a position (identifiers, verbs, keywords)
wordAt:{[uri;line;col]
    ; su:`$uri
    ; if[not su in key .lsp.docs; :""]
    ; doc:.lsp.docs su
    ; nd:ts_node_at[doc 1;doc 0;line;col]
    ; if[99h<>type nd; :""]           / not a dict = no node found
    ; tp:nd`type
    ; if[tp in `identifier`dotted_name`verb`keyword_op; :nd`text]
    ; ""}

/ Get full node dict at a position, or (::) if none
nodeAt:{[uri;line;col]
    ; su:`$uri
    ; if[not su in key .lsp.docs; :(::)]
    ; doc:.lsp.docs su
    ; nd:ts_node_at[doc 1;doc 0;line;col]
    ; $[99h=type nd;nd;(::)]}

/ ── LSP I/O ──────────────────────────────────────────────────
/ LSP uses Content-Length framing over stdio.
/ stdin_line reads headers, stdin_read reads exact byte count for body.
/ q's built-in read0 can't do exact byte reads, hence the C helpers.
readMsg:{
    ; cl:0
    ; line:stdin_line[]
    ; while[0<count line;
        if[line like "Content-Length:*"; cl:"J"$ltrim 15_ line]
        ; line:stdin_line[]]
    ; if[cl=0; :(::)]
    ; .j.k stdin_read cl}

writeMsg:{[msg]
    ; body:.j.j msg
    ; 1 "Content-Length: ",(string count body),"\r\n\r\n",body}

respond:{[id;result] writeMsg `jsonrpc`id`result!("2.0";id;result)}
notify:{[method;params] writeMsg `jsonrpc`method`params!("2.0";method;params)}
mkHover:{[txt] (enlist`contents)!enlist `kind`value!("plaintext";txt)}

/ Publish parse errors as diagnostics (called after every document update)
publishDiag:{[uri]
    ; su:`$uri
    ; if[not su in key .lsp.docs; :(::)]
    ; doc:.lsp.docs su
    ; errs:ts_errors[doc 1;doc 0]
    ; diags:{`range`severity`message`source!(
        mkRange[x`srow;x`scol;x`erow;x`ecol];1;x`msg;"tree-sitter")} each errs
    ; notify["textDocument/publishDiagnostics";`uri`diagnostics!(uri;diags)]}

/ ── Handlers ─────────────────────────────────────────────────
/ Dispatch incoming LSP message by method name.
/ Notifications (no id) are fire-and-forget; requests get a respond[] call.
handle:{[msg]
    ; m:msg`method; id:msg`id; p:msg`params
    ; $[m~"initialize";           hInit[id]
        ; m~"initialized";          (::)
        ; m~"shutdown";              respond[id;(::)]
        ; m~"exit";                  exit 0
        ; m~"textDocument/didOpen";  updateDoc[p[`textDocument]`uri;p[`textDocument]`text]
        ; m~"textDocument/didChange";
            [ch:p`contentChanges
             ; if[0<count ch; updateDoc[p[`textDocument]`uri;last[ch]`text]]]
        ; m~"textDocument/didClose"; closeDoc p[`textDocument]`uri
        ; m~"textDocument/definition"; hDef[id;p]
        ; m~"textDocument/hover";      hHover[id;p]
        ; m~"textDocument/completion"; hCompletion[id;p]
        ; m~"textDocument/documentSymbol"; hSymbols[id;p]
        ; m~"textDocument/references";     hRefs[id;p]
        ; m~"textDocument/rename";             hRename[id;p]
        ; m~"textDocument/prepareRename";    hPrepareRename[id;p]
        ; m~"textDocument/documentHighlight";hHighlight[id;p]
        ; m~"textDocument/foldingRange";     hFoldingRange[id;p]
        ; m~"workspace/symbol";              hWorkspaceSymbol[id;p]
        ; m~"textDocument/selectionRange";   hSelectionRange[id;p]
        ; m~"textDocument/semanticTokens/full";hSemanticTokensFull[id;p]
        ; m~"textDocument/codeAction";       hCodeAction[id;p]
        ; not null id;               respond[id;(::)]  / unknown request → null
        ; (::)]}

/ textDocumentSync=1 means full document sync (client sends entire text on change)
hInit:{[id]
  respond[id;`capabilities`serverInfo!(
    `textDocumentSync`completionProvider`definitionProvider`documentSymbolProvider`hoverProvider`referencesProvider`renameProvider`documentHighlightProvider`foldingRangeProvider`workspaceSymbolProvider`selectionRangeProvider`semanticTokensProvider`codeActionProvider!
      (1;`triggerCharacters`resolveProvider!((".";"\\`");0b);1b;1b;1b;1b;enlist[`prepareProvider]!enlist 1b;1b;1b;1b;1b;`full`legend!(1b;semanticLegend);1b);
    `name`version!("q-lsp";"0.5.0"))]}

/ Go-to-definition: search all open documents for a matching assignment
hDef:{[id;p]
    ; uri:p[`textDocument]`uri
    ; line:p[`position]`line; col:p[`position]`character
    ; w:wordAt[uri;line;col]
    ; if[0=count w; :respond[id;(::)]]
    ; r:raze {[w;uri]
        doc:.lsp.docs uri
        ; if[(::)~doc; :()]
        ; d:doc 2
        ; hits:select from d where name=`$w
        ; if[0=count hits; :()]
        ; {[uri;h] `uri`range!(string uri;mkRange[h`srow;h`scol;h`erow;h`ecol])}[uri] each hits
      }[w] each key .lsp.docs
    ; respond[id;$[1=count r;first r;r]]}

/ Search all docs for first definition of symbol w
findDef:{[w]
    ; hits:raze {[w;su] select from (.lsp.docs[su] 2) where name=w}[w] each key .lsp.docs
    ; $[0<count hits;first hits;(::)]}

/ Hover: show k implementation for builtins/verbs, full body for user definitions
hHover:{[id;p]
    ; uri:p[`textDocument]`uri
    ; line:p[`position]`line; col:p[`position]`character
    ; nd:nodeAt[uri;line;col]
    ; if[(::)~nd; :respond[id;(::)]]
    ; tp:nd`type; txt:nd`text
    / Verbs and keyword operators: show k implementation via .Q.s1
    ; if[tp in `verb`keyword_op;
        ws:`$txt
        ; :respond[id;mkHover $[ws in 1_ key `.q;.Q.s1 .q ws;txt]]]
    / Identifiers: check builtins first, then user definitions
    ; if[tp in `identifier`dotted_name;
        ws:`$txt
        ; if[ws in builtins;
            :respond[id;mkHover builtinDoc ws]]
        ; h:findDef ws
        ; if[not (::)~h;
            pfx:$[h`global;"(global) ";""]
            ; sig:pfx,(string h`name),":",$[0<count h`detail;h`detail;string h`name]
            ; :respond[id;mkHover sig]]]
    ; respond[id;(::)]}

/ Completion: all user-defined symbols + builtins
/ kind 3 = Function, 6 = Variable (LSP CompletionItemKind)
hCompletion:{[id;p]
    ; alldefs:raze {doc:.lsp.docs x; doc 2} each key .lsp.docs
    ; names:exec distinct name from alldefs
    ; items:{[alldefs;n]
        row:first select from alldefs where name=n
        ; `label`kind`detail!(string n;$[row`lambda;3;6];row`detail)
      }[alldefs] each names
    / add builtins not already shadowed by user definitions
    ; blt:builtins except names
    ; items,:{ `label`kind`detail!(string x;3;builtinDoc x)} each blt
    ; respond[id;items]}

/ Document symbols: list all top-level definitions in the file
/ kind 12 = Function, 13 = Variable (LSP SymbolKind)
/ Global assignments show " ::" suffix in the name
hSymbols:{[id;p]
    ; uri:p[`textDocument]`uri
    ; doc:.lsp.docs `$uri
    ; if[(::)~doc; :respond[id;()]]
    ; d:doc 2
    ; respond[id;{[d]
        `name`kind`range`selectionRange`detail!(
            (string d`name),$[d`global;" ::";""]
            ; $[d`lambda;12;13]
            ; mkRange[d`srow;d`scol;d`erow;d`ecol]
            ; mkRange[d`srow;d`scol;d`erow;d`ecol]
            ; d`detail)
      } each d]}

/ References: find all occurrences of the symbol under cursor
hRefs:{[id;p]
    ; uri:p[`textDocument]`uri
    ; line:p[`position]`line; col:p[`position]`character
    ; w:wordAt[uri;line;col]
    ; if[0=count w; :respond[id;()]]
    ; r:raze {[w;uri]
        doc:.lsp.docs uri
        ; if[(::)~doc; :()]
        ; refs:ts_refs[doc 1;doc 0;w]
        ; if[0=count refs; :()]
        ; {[uri;r] `uri`range!(string uri;mkRange[r`srow;r`scol;r`erow;r`ecol])}[uri] each refs
      }[w] each key .lsp.docs
    ; respond[id;r]}

/ Prepare rename: validate position is a renamable identifier (not a builtin)
hPrepareRename:{[id;p]
    ; uri:p[`textDocument]`uri
    ; line:p[`position]`line; col:p[`position]`character
    ; nd:nodeAt[uri;line;col]
    ; if[(::)~nd; :respond[id;(::)]]
    ; if[not nd[`type] in `identifier`dotted_name; :respond[id;(::)]]
    ; if[(`$nd`text) in builtins; :respond[id;(::)]]
    ; respond[id;`range`placeholder!(mkRange[nd`srow;nd`scol;nd`erow;nd`ecol];nd`text)]}

/ Rename: replace all occurrences of a symbol across open documents
hRename:{[id;p]
    ; uri:p[`textDocument]`uri
    ; line:p[`position]`line; col:p[`position]`character
    ; newName:p`newName
    ; w:wordAt[uri;line;col]
    ; if[0=count w; :respond[id;(::)]]
    ; if[(`$w) in builtins; :respond[id;(::)]]
    ; pairs:raze {[w;newName;uri]
        doc:.lsp.docs uri
        ; if[(::)~doc; :()]
        ; refs:ts_refs[doc 1;doc 0;w]
        ; if[0=count refs; :()]
        ; edits:{[newName;r] `range`newText!(mkRange[r`srow;r`scol;r`erow;r`ecol];newName)}[newName] each refs
        ; enlist (uri;edits)
      }[w;newName] each key .lsp.docs
    ; if[0=count pairs; :respond[id;(::)]]
    ; changes:(first each pairs)!(last each pairs)
    ; respond[id;(enlist`changes)!enlist changes]}

/ Document highlight: all occurrences of symbol under cursor in same file
hHighlight:{[id;p]
    ; uri:p[`textDocument]`uri; su:`$uri
    ; line:p[`position]`line; col:p[`position]`character
    ; w:wordAt[uri;line;col]
    ; if[0=count w; :respond[id;()]]
    ; doc:.lsp.docs su
    ; if[(::)~doc; :respond[id;()]]
    ; refs:ts_refs[doc 1;doc 0;w]
    ; respond[id;{`range`kind!(mkRange[x`srow;x`scol;x`erow;x`ecol];1)} each refs]}

/ Folding ranges: top-level multi-line nodes
hFoldingRange:{[id;p]
    ; uri:p[`textDocument]`uri; su:`$uri
    ; doc:.lsp.docs su
    ; if[(::)~doc; :respond[id;()]]
    ; ch:ts_children[doc 1;doc 0]
    ; ml:{x where {x[`srow]<x`erow} each x} ch
    ; respond[id;{`startLine`startCharacter`endLine`endCharacter`kind!(
        x`srow;x`scol;x`erow;x`ecol;"region")} each ml]}

/ Workspace symbol: search definitions across all open documents
hWorkspaceSymbol:{[id;p]
    ; q:p`query
    ; r:raze {[q;su]
        doc:.lsp.docs su
        ; if[(::)~doc; :()]
        ; d:doc 2
        ; hits:$[0=count q;d;select from d where (string each name) like (q,"*")]
        ; if[0=count hits; :()]
        ; {[su;d] `name`kind`location!(
            string d`name
            ; $[d`lambda;12;13]
            ; `uri`range!(string su;mkRange[d`srow;d`scol;d`erow;d`ecol])
          )}[su] each hits
      }[q] each key .lsp.docs
    ; respond[id;r]}

/ Selection range: nested ranges from leaf to root for expand/shrink selection
hSelectionRange:{[id;p]
    ; uri:p[`textDocument]`uri; su:`$uri
    ; doc:.lsp.docs su
    ; if[(::)~doc; :respond[id;()]]
    ; respond[id;{[doc;pos]
        nodes:ts_ancestors[doc 1;doc 0;pos`line;pos`character]
        ; if[0=count nodes; :(::)]
        / Build nested SelectionRange from outermost to innermost
        ; r:(::); i:count[nodes]-1
        ; while[i>=0; nd:nodes i; r:`range`parent!(mkRange[nd`srow;nd`scol;nd`erow;nd`ecol];r); i-:1]
        ; r
      }[doc] each p`positions]}

/ Semantic tokens: full document token classification
/ Legend: variable(0) parameter(1) function(2) keyword(3) operator(4) number(5) string(6) comment(7)
/ Modifiers: declaration(0) definition(1) defaultLibrary(2)
semanticLegend:`tokenTypes`tokenModifiers!(
    ("variable";"parameter";"function";"keyword";"operator";"number";"string";"comment");
    ("declaration";"definition";"defaultLibrary"))
hSemanticTokensFull:{[id;p]
    ; uri:p[`textDocument]`uri; su:`$uri
    ; doc:.lsp.docs su
    ; if[(::)~doc; :respond[id;(enlist`data)!enlist `long$()]]
    ; toks:`line`col xasc ts_tokens[doc 1;doc 0]
    ; if[0=count toks; :respond[id;(enlist`data)!enlist `long$()]]
    / Delta-encode: deltaLine, deltaStartChar, length, tokenType, tokenModifiers
    ; dl:deltas toks`line
    ; dc:?[dl>0;toks`col;deltas toks`col]
    ; data:raze flip (dl;dc;toks`len;toks`tokenType;toks`tokenModifiers)
    ; respond[id;(enlist`data)!enlist data]}

/ Code actions: suggest fixes for parse errors (missing tokens)
hCodeAction:{[id;p]
    ; uri:p[`textDocument]`uri
    ; diags:p[`context]`diagnostics
    ; actions:raze {[uri;d]
        msg:d`message
        ; if[not msg like "missing *"; :()]
        ; token:8_ msg                                       / strip "missing " prefix
        ; if[not token in ("}";")";";";"[";"]"); :()]        / only fix simple tokens
        ; pos:d[`range]`start
        ; edit:`range`newText!(mkRange[pos`line;pos`character;pos`line;pos`character];token)
        ; enlist `title`kind`edit!(
            "Insert ",token; "quickfix";
            (enlist`changes)!enlist (enlist `$uri)!enlist enlist edit)
      }[uri] each diags
    ; respond[id;actions]}

/ ── Main loop ────────────────────────────────────────────────
/ Read messages forever. Errors in readMsg (EOF) cause clean exit.
/ Errors in handle are logged to stderr but don't crash the server.
main:{[]
    ; while[1b;
        msg:@[readMsg;::;{[e] -2 "lsp error: ",e; `eof}]
        ; if[`eof~msg; :exit 0]
        ; if[not (::)~msg; @[handle;msg;{[e] -2 "lsp handle error: ",e}]]]}

main[]
