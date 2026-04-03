/ q/kdb+ Language Server — powered by tree-sitter
/ Features: go-to-definition, completion, document symbols, hover
/ Protocol: LSP JSON-RPC over stdio (Content-Length framing)

/ ── Load tree-sitter bridge ──────────────────────────────────
tsdir:first ` vs hsym .z.f;                     / directory of this script
tso:` sv (tsdir;`ts_q);
ts_init:tso 2: (`ts_init;1);
ts_parse:tso 2: (`ts_parse;1);
ts_free:tso 2: (`ts_free;1);
ts_defs:tso 2: (`ts_defs;2);
ts_node_at:tso 2: (`ts_node_at;4);
ts_parent:tso 2: (`ts_parent;4);
stdin_read:tso 2: (`stdin_read;1);
stdin_line:tso 2: (`stdin_line;1);
ts_init[];

/ ── Built-in docs from q itself ──────────────────────────────
/ .Q.res = reserved words, key `.q = stdlib functions
builtins:(.Q.res,1_ key `.q) except `;
builtin_doc:{[w]
  if[w in 1_ key `.q; :.Q.s1 .q w];
  if[w in .Q.res; :"(reserved) ",string w];
  ""}

/ ── Document state ───────────────────────────────────────────
/ uri -> (text;tree_handle;defs_table)
.lsp.docs:(`symbol$())!();

updatedoc:{[uri;text]
  su:`$uri;
  if[su in key .lsp.docs; ts_free .lsp.docs[su] 1];  / free old tree
  h:ts_parse text;
  d:ts_defs[h;text];
  .lsp.docs[su]:(text;h;d);}

closedoc:{[uri]
  su:`$uri;
  if[su in key .lsp.docs; ts_free .lsp.docs[su] 1];
  .lsp.docs _:su;}

/ ── Helpers ──────────────────────────────────────────────────
mkrange:{[sr;sc;er;ec]
  `start`end!(`line`character!(sr;sc);`line`character!(er;ec))}

wordat:{[uri;line;col]
  su:`$uri;
  if[not su in key .lsp.docs; :""];
  doc:.lsp.docs su;
  nd:ts_node_at[doc 1;doc 0;line;col];
  if[99h<>type nd; :""];           / not a dict = no node found
  tp:nd`type;
  if[tp in `identifier`dotted_name`verb`keyword_op; :nd`text];
  ""}

nodeat:{[uri;line;col]
  su:`$uri;
  if[not su in key .lsp.docs; :(::)];
  doc:.lsp.docs su;
  nd:ts_node_at[doc 1;doc 0;line;col];
  $[99h=type nd;nd;(::)]}

parentat:{[uri;line;col]
  doc:.lsp.docs `$uri;
  if[(::)~doc; :(::)];
  ts_parent[doc 1;doc 0;line;col]}

/ ── LSP I/O ──────────────────────────────────────────────────
/ Read Content-Length header, then exact byte body
readmsg:{
  cl:0;
  line:stdin_line[];
  while[0<count line;
    if[line like "Content-Length:*"; cl:"J"$ltrim 15_ line];
    line:stdin_line[]];
  if[cl=0; :(::)];
  .j.k stdin_read cl}

writemsg:{[msg]
  body:.j.j msg;
  1 "Content-Length: ",(string count body),"\r\n\r\n",body;}

respond:{[id;result] writemsg `jsonrpc`id`result!("2.0";id;result)}
mkhover:{[txt] (enlist`contents)!enlist `kind`value!("plaintext";txt)}

/ ── Handlers ─────────────────────────────────────────────────
handle:{[msg]
  m:msg`method; id:msg`id; p:msg`params;
  $[m~"initialize";           hInit[id];
    m~"initialized";          (::);
    m~"shutdown";              respond[id;(::)];
    m~"exit";                  exit 0;
    m~"textDocument/didOpen";  updatedoc[p[`textDocument]`uri;p[`textDocument]`text];
    m~"textDocument/didChange";
      [ch:p`contentChanges;
       if[0<count ch; updatedoc[p[`textDocument]`uri;last[ch]`text]]];
    m~"textDocument/didClose"; closedoc p[`textDocument]`uri;
    m~"textDocument/definition"; hDef[id;p];
    m~"textDocument/hover";      hHover[id;p];
    m~"textDocument/completion"; hCompletion[id;p];
    m~"textDocument/documentSymbol"; hSymbols[id;p];
    not null id;               respond[id;(::)];
    (::)]}

hInit:{[id]
  respond[id;`capabilities`serverInfo!(
    `textDocumentSync`completionProvider`definitionProvider`documentSymbolProvider`hoverProvider!
      (1;`triggerCharacters`resolveProvider!((".";"\\`");0b);1b;1b;1b);
    `name`version!("q-lsp";"0.2.0"))]}

hDef:{[id;p]
  uri:p[`textDocument]`uri;
  line:p[`position]`line; col:p[`position]`character;
  w:wordat[uri;line;col];
  if[0=count w; :respond[id;(::)]];
  / search all docs
  r:raze {[w;uri]
    doc:.lsp.docs uri;
    if[(::)~doc; :()];
    d:doc 2;
    hits:select from d where name=`$w;
    if[0=count hits; :()];
    {[uri;h] `uri`range!(string uri;mkrange[h`srow;h`scol;h`erow;h`ecol])}[uri] each hits
  }[w] each key .lsp.docs;
  respond[id;$[1=count r;first r;r]]}

finddef:{[w]
  / search all docs for definition of symbol w
  hits:raze {[w;su] select from (.lsp.docs[su] 2) where name=w}[w] each key .lsp.docs;
  $[0<count hits;first hits;(::)]}

hHover:{[id;p]
  uri:p[`textDocument]`uri;
  line:p[`position]`line; col:p[`position]`character;
  nd:nodeat[uri;line;col];
  if[(::)~nd; :respond[id;(::)]];
  tp:nd`type; txt:nd`text;
  if[tp in `verb`keyword_op;
    ws:`$txt;
    :respond[id;mkhover $[ws in 1_ key `.q;.Q.s1 .q ws;txt]]];
  if[tp in `identifier`dotted_name;
    ws:`$txt;
    if[ws in builtins;
      :respond[id;mkhover builtin_doc ws]];
    h:finddef ws;
    if[not (::)~h;
      pfx:$[h`global;"(global) ";""];
      sig:pfx,(string h`name),":",$[0<count h`detail;h`detail;string h`name];
      :respond[id;mkhover sig]]];
  respond[id;(::)]}

hCompletion:{[id;p]
  / collect all user defs
  alldefs:raze {doc:.lsp.docs x; doc 2} each key .lsp.docs;
  names:exec distinct name from alldefs;
  items:{[alldefs;n]
    row:first select from alldefs where name=n;
    `label`kind`detail!(string n;$[row`lambda;3;6];row`detail)
  }[alldefs] each names;
  / add builtins not already defined
  blt:builtins except names;
  items,:{ `label`kind`detail!(string x;3;builtin_doc x)} each blt;
  respond[id;items]}

hSymbols:{[id;p]
  uri:p[`textDocument]`uri;
  doc:.lsp.docs `$uri;
  if[(::)~doc; :respond[id;()]];
  d:doc 2;
  respond[id;{[d]
    `name`kind`range`selectionRange`detail!(
      (string d`name),$[d`global;" ::";""];
      $[d`lambda;12;13];
      mkrange[d`srow;d`scol;d`erow;d`ecol];
      mkrange[d`srow;d`scol;d`erow;d`ecol];
      d`detail)
  } each d]}

/ ── Main loop ────────────────────────────────────────────────
main:{[]
  while[1b;
    msg:@[readmsg;::;{[e] -2 "lsp error: ",e; `eof}];
    if[`eof~msg; :exit 0];
    if[not (::)~msg; @[handle;msg;{[e] -2 "lsp handle error: ",e}]]]}

main[]
