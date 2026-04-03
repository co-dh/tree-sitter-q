/ Test the tree-sitter q bridge (ts_q.so)
/ Exit 1 on first failure
ts_init:`ts_q 2: (`ts_init;1);
ts_parse:`ts_q 2: (`ts_parse;1);
ts_free:`ts_q 2: (`ts_free;1);
ts_defs:`ts_q 2: (`ts_defs;2);
ts_children:`ts_q 2: (`ts_children;2);
ts_node_at:`ts_q 2: (`ts_node_at;4);
ts_parent:`ts_q 2: (`ts_parent;4);

npass:0; nfail:0;
assert:{[msg;cond] $[cond;[npass+:1;-1 "  pass: ",msg];[nfail+:1;-2 "  FAIL: ",msg]]}

/ ── ts_init ──────────────────────────────────────────────────
-1 "ts_init";
assert["returns true";ts_init[]];

/ ── ts_parse + ts_defs ───────────────────────────────────────
-1 "ts_parse + ts_defs";
code:"f:{[x;y] x+y}\ng::42\nresult:f[1;2]";
h:ts_parse code;
assert["returns long handle";-7h=type h];

d:ts_defs[h;code];
assert["defs is a table";98h=type d];
assert["3 defs found";3=count d];
assert["columns correct";`name`srow`scol`erow`ecol`global`lambda`detail~cols d];
assert["names are f,g,result";`f`g`result~d`name];
assert["f is lambda";d[0]`lambda];
assert["g is global";d[1]`global];
assert["result is local";not d[2]`global];
assert["f detail has body";0<count d[0]`detail];
assert["g detail is 42";"42"~d[1]`detail];

/ ── ts_children ──────────────────────────────────────────────
-1 "ts_children";
ch:ts_children[h;code];
assert["root has 3 children";3=count ch];

/ ── ts_node_at ───────────────────────────────────────────────
-1 "ts_node_at";
nd:ts_node_at[h;code;0j;0j];
assert["node at 0,0 is dict";99h=type nd];
assert["node at 0,0 is identifier";`identifier=nd`type];
assert["node text is f";(enlist"f")~nd`text];

nd2:ts_node_at[h;code;1j;0j];
assert["node at 1,0 text is g";(enlist"g")~nd2`text];

/ node inside lambda body — col 9 is x in "x+y"
nd3:ts_node_at[h;code;0j;9j];
assert["node at 0,9 is identifier";`identifier=nd3`type];
assert["node at 0,9 text is x";(enlist"x")~nd3`text];

/ ── ts_parent ────────────────────────────────────────────────
-1 "ts_parent";
p:ts_parent[h;code;0j;0j];
assert["parent is dict";99h=type p];
assert["parent of f is assignment";`assignment=p`type];

p2:ts_parent[h;code;1j;0j];
assert["parent of g is global_assignment";`global_assignment=p2`type];

/ ── ts_free ──────────────────────────────────────────────────
-1 "ts_free";
assert["free returns true";ts_free h];

/ ── Edge cases ───────────────────────────────────────────────
-1 "edge cases";
h2:ts_parse "";
d2:ts_defs[h2;""];
assert["empty code has 0 defs";0=count d2];
ts_free h2;

h3:ts_parse "/ just a comment\n";
d3:ts_defs[h3;"/ just a comment\n"];
assert["comment-only has 0 defs";0=count d3];
ts_free h3;

/ ── Summary ──────────────────────────────────────────────────
-1 "";
-1 (string npass)," passed, ",(string nfail)," failed";
if[nfail>0; exit 1];
-1 "all tests passed";
\\
