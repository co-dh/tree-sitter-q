/ Test the tree-sitter q bridge
ts_init:`ts_q 2: (`ts_init;1);
ts_parse:`ts_q 2: (`ts_parse;1);
ts_free:`ts_q 2: (`ts_free;1);
ts_defs:`ts_q 2: (`ts_defs;2);
ts_children:`ts_q 2: (`ts_children;2);
ts_node_at:`ts_q 2: (`ts_node_at;4);
ts_parent:`ts_q 2: (`ts_parent;4);

-1 "init: ",string ts_init[];

code:"f:{[x;y] x+y}\ng::42\nresult:f[1;2]";
h:ts_parse code;
-1 "tree handle: ",string h;

-1 "\ndefs:";
show ts_defs[h;code];

-1 "\nroot children:";
show ts_children[h;code];

-1 "\nnode at 0,0:";
show ts_node_at[h;code;0j;0j];

-1 "\nnode at 1,0 (g):";
show ts_node_at[h;code;1j;0j];

-1 "\nparent of node at 0,2 (inside lambda):";
show ts_parent[h;code;0j;2j];

ts_free h;
-1 "\nall tests passed";
\\
