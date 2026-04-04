// tree-sitter bridge for q/kdb+ via 2:
// Exposes tree-sitter parsing of q code as q-callable functions
#define KXVER 3
#include "k.h"
#include <tree_sitter/api.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

extern const TSLanguage *tree_sitter_q(void);

static TSParser *parser = NULL;

// Extract long from int(-6h), long(-7h), or float(-9h) atom
static J toJ(K x) {
  switch(x->t) {
    case -KI: return (J)x->i;
    case -KE: return (J)x->e;
    case -KF: return (J)x->f;
    default: return x->j;
  }
}

// ── Stdin byte reading (LSP needs exact byte counts) ────────
// stdin_read[n] — read exactly n bytes from stdin
K stdin_read(K x) {
  if (x->t != -KJ && x->t != -KI && x->t != -KF) return krr("stdin_read: expected number");
  J n = toJ(x);
  if (n <= 0) return ktn(KC, 0);
  K result = ktn(KC, n);
  J total = 0;
  while (total < n) {
    size_t got = fread(kC(result) + total, 1, n - total, stdin);
    if (got == 0) { r0(result); return krr("stdin_read: eof"); }
    total += got;
  }
  return result;
}

// stdin_line[] — read one line from stdin (strips \r\n)
K stdin_line(K x) {
  (void)x;
  char buf[4096];
  if (!fgets(buf, sizeof(buf), stdin)) return krr("stdin_line: eof");
  J len = strlen(buf);
  while (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r')) len--;
  K result = ktn(KC, len);
  memcpy(kC(result), buf, len);
  return result;
}

// ── Init ────────────────────────────────────────────────────
// ts_init[] — initialize parser, returns 1b on success
// Also disables stdout buffering (needed for LSP over pipe)
K ts_init(K x) {
  (void)x;
  setvbuf(stdout, NULL, _IONBF, 0);
  if (parser) return kb(1);
  parser = ts_parser_new();
  if (!parser) return kb(0);
  ts_parser_set_language(parser, tree_sitter_q());
  return kb(1);
}

// ── Parse ───────────────────────────────────────────────────
// ts_parse[text] — parse string, return opaque tree handle (long)
K ts_parse(K x) {
  if (!parser) return krr("ts: not initialized");
  if (x->t != KC) return krr("ts_parse: expected string");
  TSTree *tree = ts_parser_parse_string(parser, NULL, (char*)kC(x), x->n);
  if (!tree) return krr("ts_parse: parse failed");
  return kj((J)tree);
}

// ts_free[handle] — free a parse tree
K ts_free(K x) {
  if (x->t != -KJ && x->t != -KI && x->t != -KF) return krr("ts_free: expected number");
  TSTree *tree = (TSTree*)toJ(x);
  if (tree) ts_tree_delete(tree);
  return kb(1);
}

// ── Node info helpers ───────────────────────────────────────
// Pack node info as a dict: `type`named`srow`scol`erow`ecol`text`field
static K node_dict(TSNode node, const char *src, const char *field_name) {
  TSPoint sp = ts_node_start_point(node);
  TSPoint ep = ts_node_end_point(node);
  uint32_t sb = ts_node_start_byte(node);
  uint32_t eb = ts_node_end_byte(node);

  K keys = ktn(KS, 8);
  kS(keys)[0] = ss("type");
  kS(keys)[1] = ss("named");
  kS(keys)[2] = ss("srow");
  kS(keys)[3] = ss("scol");
  kS(keys)[4] = ss("erow");
  kS(keys)[5] = ss("ecol");
  kS(keys)[6] = ss("text");
  kS(keys)[7] = ss("field");

  K vals = ktn(0, 8);
  kK(vals)[0] = ks((S)ts_node_type(node));
  kK(vals)[1] = kb(ts_node_is_named(node));
  kK(vals)[2] = kj(sp.row);
  kK(vals)[3] = kj(sp.column);
  kK(vals)[4] = kj(ep.row);
  kK(vals)[5] = kj(ep.column);
  // text slice
  uint32_t len = eb - sb;
  K txt = ktn(KC, len);
  memcpy(kC(txt), src + sb, len);
  kK(vals)[6] = txt;
  // field name (may be null)
  kK(vals)[7] = field_name ? ks((S)field_name) : ks("");

  return xD(keys, vals);
}

// ── Children ────────────────────────────────────────────────
// ts_children[handle;text] — return list of dicts for root's children
K ts_children(K h, K text) {
  if (h->t != -KJ) return krr("ts_children: expected long handle");
  if (text->t != KC) return krr("ts_children: expected string text");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("ts_children: null tree");

  TSNode root = ts_tree_root_node(tree);
  uint32_t n = ts_node_child_count(root);
  K result = ktn(0, n);
  const char *src = (const char*)kC(text);
  for (uint32_t i = 0; i < n; i++) {
    TSNode child = ts_node_child(root, i);
    const char *fname = ts_node_field_name_for_child(root, i);
    kK(result)[i] = node_dict(child, src, fname);
  }
  return result;
}

// ts_node_children[handle;text;row;col] — children of node at position
K ts_node_children(K h, K text, K row, K col) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSPoint pt = {(uint32_t)toJ(row), (uint32_t)toJ(col)};
  TSNode node = ts_node_named_descendant_for_point_range(
    ts_tree_root_node(tree), pt, pt);
  if (ts_node_is_null(node)) return ktn(0, 0);

  uint32_t n = ts_node_child_count(node);
  K result = ktn(0, n);
  const char *src = (const char*)kC(text);
  for (uint32_t i = 0; i < n; i++) {
    TSNode child = ts_node_child(node, i);
    const char *fname = ts_node_field_name_for_child(node, i);
    kK(result)[i] = node_dict(child, src, fname);
  }
  return result;
}

// ts_node_at[handle;text;row;col] — get node info at position
K ts_node_at(K h, K text, K row, K col) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSPoint pt = {(uint32_t)toJ(row), (uint32_t)toJ(col)};
  TSNode node = ts_node_named_descendant_for_point_range(
    ts_tree_root_node(tree), pt, pt);
  if (ts_node_is_null(node)) return knk(0);

  const char *src = (const char*)kC(text);
  // Walk up to find field name
  TSNode parent = ts_node_parent(node);
  const char *fname = NULL;
  if (!ts_node_is_null(parent)) {
    uint32_t n = ts_node_child_count(parent);
    for (uint32_t i = 0; i < n; i++) {
      TSNode sib = ts_node_child(parent, i);
      if (ts_node_start_byte(sib) == ts_node_start_byte(node) &&
          ts_node_end_byte(sib) == ts_node_end_byte(node)) {
        fname = ts_node_field_name_for_child(parent, i);
        break;
      }
    }
  }
  return node_dict(node, src, fname);
}

// ts_parent[handle;text;row;col] — get parent node info at position
K ts_parent(K h, K text, K row, K col) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSPoint pt = {(uint32_t)toJ(row), (uint32_t)toJ(col)};
  TSNode node = ts_node_named_descendant_for_point_range(
    ts_tree_root_node(tree), pt, pt);
  if (ts_node_is_null(node)) return knk(0);
  TSNode parent = ts_node_parent(node);
  if (ts_node_is_null(parent)) return knk(0);

  const char *src = (const char*)kC(text);
  return node_dict(parent, src, NULL);
}

// ── Assignments ─────────────────────────────────────────────
// ts_defs[handle;text] — extract top-level assignments as table
// Returns table: (name;srow;scol;erow;ecol;global;lambda;detail)
K ts_defs(K h, K text) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSNode root = ts_tree_root_node(tree);
  uint32_t n = ts_node_named_child_count(root);
  const char *src = (const char*)kC(text);

  // Preallocate columns
  K names = ktn(KS, 0), srows = ktn(KJ, 0), scols = ktn(KJ, 0);
  K erows = ktn(KJ, 0), ecols = ktn(KJ, 0);
  K globals = ktn(KB, 0), lambdas = ktn(KB, 0), details = ktn(0, 0);

  for (uint32_t i = 0; i < n; i++) {
    TSNode child = ts_node_named_child(root, i);
    const char *type = ts_node_type(child);
    int is_assign = strcmp(type, "assignment") == 0;
    int is_global = strcmp(type, "global_assignment") == 0;
    if (!is_assign && !is_global) continue;

    // Get name field
    TSNode name_node = ts_node_child_by_field_name(child, "name", 4);
    if (ts_node_is_null(name_node)) continue;
    uint32_t nsb = ts_node_start_byte(name_node);
    uint32_t neb = ts_node_end_byte(name_node);
    uint32_t nlen = neb - nsb;
    char nbuf[256];
    if (nlen >= sizeof(nbuf)) nlen = sizeof(nbuf) - 1;
    memcpy(nbuf, src + nsb, nlen);
    nbuf[nlen] = 0;

    // Get value field — check if lambda, extract full value text
    TSNode val_node = ts_node_child_by_field_name(child, "value", 5);
    int is_lambda = 0;
    uint32_t vsb = 0, veb = 0;
    if (!ts_node_is_null(val_node)) {
      is_lambda = strcmp(ts_node_type(val_node), "lambda") == 0;
      vsb = ts_node_start_byte(val_node);
      veb = ts_node_end_byte(val_node);
    }

    TSPoint sp = ts_node_start_point(name_node);
    TSPoint ep = ts_node_end_point(name_node);

    js(&names, ss(nbuf));
    J sr=sp.row, sc=sp.column, er=ep.row, ec=ep.column;
    ja(&srows, &sr); ja(&scols, &sc);
    ja(&erows, &er); ja(&ecols, &ec);
    G gl=(G)is_global, lm=(G)is_lambda;
    ja(&globals, &gl); ja(&lambdas, &lm);
    uint32_t vlen = veb - vsb;
    K dtl = ktn(KC, vlen);
    if (vlen) memcpy(kC(dtl), src + vsb, vlen);
    jk(&details, dtl);
  }

  K colnames = ktn(KS, 8);
  kS(colnames)[0] = ss("name");
  kS(colnames)[1] = ss("srow");
  kS(colnames)[2] = ss("scol");
  kS(colnames)[3] = ss("erow");
  kS(colnames)[4] = ss("ecol");
  kS(colnames)[5] = ss("global");
  kS(colnames)[6] = ss("lambda");
  kS(colnames)[7] = ss("detail");

  K vals = ktn(0, 8);
  kK(vals)[0] = names; kK(vals)[1] = srows; kK(vals)[2] = scols;
  kK(vals)[3] = erows; kK(vals)[4] = ecols;
  kK(vals)[5] = globals; kK(vals)[6] = lambdas; kK(vals)[7] = details;

  return xT(xD(colnames, vals));
}

// ── References ──────────────────────────────────────────────
// ts_refs[handle;text;name] — find all identifier/dotted_name nodes matching name
// Returns table: (srow;scol;erow;ecol)
K ts_refs(K h, K text, K name) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  if (name->t != KC && name->t != -KC) return krr("ts_refs: expected string name");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSNode root = ts_tree_root_node(tree);
  const char *src = (const char*)kC(text);
  const char *tgt; J tgt_len;
  if (name->t == KC) { tgt = (const char*)kC(name); tgt_len = name->n; }
  else { tgt = (const char*)&name->g; tgt_len = 1; }

  K srows = ktn(KJ, 0), scols = ktn(KJ, 0);
  K erows = ktn(KJ, 0), ecols = ktn(KJ, 0);

  TSTreeCursor cursor = ts_tree_cursor_new(root);
  int done = 0;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    if (ts_node_is_named(node)) {
      const char *type = ts_node_type(node);
      if (strcmp(type, "identifier") == 0 || strcmp(type, "dotted_name") == 0) {
        uint32_t sb = ts_node_start_byte(node);
        uint32_t eb = ts_node_end_byte(node);
        if ((J)(eb - sb) == tgt_len && memcmp(src + sb, tgt, tgt_len) == 0) {
          TSPoint sp = ts_node_start_point(node);
          TSPoint ep = ts_node_end_point(node);
          J sr = sp.row, sc = sp.column, er = ep.row, ec = ep.column;
          ja(&srows, &sr); ja(&scols, &sc);
          ja(&erows, &er); ja(&ecols, &ec);
        }
      }
    }
    if (ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor)) {
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = 1; break; }
    }
  }
  ts_tree_cursor_delete(&cursor);

  K colnames = ktn(KS, 4);
  kS(colnames)[0] = ss("srow"); kS(colnames)[1] = ss("scol");
  kS(colnames)[2] = ss("erow"); kS(colnames)[3] = ss("ecol");
  K vals = ktn(0, 4);
  kK(vals)[0] = srows; kK(vals)[1] = scols;
  kK(vals)[2] = erows; kK(vals)[3] = ecols;
  return xT(xD(colnames, vals));
}

// ── Errors ──────────────────────────────────────────────────
// ts_errors[handle;text] — find ERROR and MISSING nodes in parse tree
// Returns table: (srow;scol;erow;ecol;msg)
K ts_errors(K h, K text) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSNode root = ts_tree_root_node(tree);
  const char *src = (const char*)kC(text);
  J src_len = text->n;

  K srows = ktn(KJ, 0), scols = ktn(KJ, 0);
  K erows = ktn(KJ, 0), ecols = ktn(KJ, 0);
  K msgs = ktn(0, 0);

  TSTreeCursor cursor = ts_tree_cursor_new(root);
  int done = 0;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    int is_err = ts_node_is_error(node);
    int is_miss = ts_node_is_missing(node);
    int skip_children = 0;

    if (is_err || is_miss) {
      TSPoint sp = ts_node_start_point(node);
      TSPoint ep = ts_node_end_point(node);
      J sr = sp.row, sc = sp.column, er = ep.row, ec = ep.column;
      ja(&srows, &sr); ja(&scols, &sc);
      ja(&erows, &er); ja(&ecols, &ec);

      if (is_miss) {
        const char *type = ts_node_type(node);
        char buf[128];
        snprintf(buf, sizeof(buf), "missing %s", type);
        J mlen = strlen(buf);
        K msg = ktn(KC, mlen);
        memcpy(kC(msg), buf, mlen);
        jk(&msgs, msg);
      } else {
        uint32_t sb = ts_node_start_byte(node);
        uint32_t eb = ts_node_end_byte(node);
        uint32_t len = eb - sb;
        if (len > 60) len = 60;
        if (sb + len > (uint32_t)src_len) len = (uint32_t)src_len - sb;
        const char *pfx = "unexpected: ";
        J plen = strlen(pfx);
        K msg = ktn(KC, plen + len);
        memcpy(kC(msg), pfx, plen);
        if (len) memcpy(kC(msg) + plen, src + sb, len);
        jk(&msgs, msg);
      }
      if (is_err) skip_children = 1;
    }

    if (!skip_children && ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor)) {
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = 1; break; }
    }
  }
  ts_tree_cursor_delete(&cursor);

  K colnames = ktn(KS, 5);
  kS(colnames)[0] = ss("srow"); kS(colnames)[1] = ss("scol");
  kS(colnames)[2] = ss("erow"); kS(colnames)[3] = ss("ecol");
  kS(colnames)[4] = ss("msg");
  K vals = ktn(0, 5);
  kK(vals)[0] = srows; kK(vals)[1] = scols;
  kK(vals)[2] = erows; kK(vals)[3] = ecols;
  kK(vals)[4] = msgs;
  return xT(xD(colnames, vals));
}

// ── Ancestors ──────────────────────────────────────────────
// ts_ancestors[handle;text;row;col] — chain of nodes from leaf to root
// Returns list of dicts (innermost first)
K ts_ancestors(K h, K text, K row, K col) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSPoint pt = {(uint32_t)toJ(row), (uint32_t)toJ(col)};
  TSNode node = ts_node_named_descendant_for_point_range(
    ts_tree_root_node(tree), pt, pt);
  if (ts_node_is_null(node)) return ktn(0, 0);

  const char *src = (const char*)kC(text);
  K result = ktn(0, 0);
  while (!ts_node_is_null(node)) {
    jk(&result, node_dict(node, src, NULL));
    node = ts_node_parent(node);
  }
  return result;
}

// ── Semantic tokens ────────────────────────────────────────
// ts_tokens[handle;text] — classify all leaf nodes for semantic highlighting
// Legend: 0=variable, 1=parameter, 2=function, 3=keyword, 4=operator,
//         5=number, 6=string, 7=comment
// Returns table: (line;col;len;tokenType;tokenModifiers)
K ts_tokens(K h, K text) {
  if (h->t != -KJ && h->t != -KI && h->t != -KF) return krr("type");
  if (text->t != KC) return krr("type");
  TSTree *tree = (TSTree*)toJ(h);
  if (!tree) return krr("null tree");

  TSNode root = ts_tree_root_node(tree);
  K lines = ktn(KJ, 0), cols = ktn(KJ, 0), lens = ktn(KJ, 0);
  K types = ktn(KJ, 0), mods = ktn(KJ, 0);

  TSTreeCursor cursor = ts_tree_cursor_new(root);
  int done = 0;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);

    // Only process leaf nodes
    if (ts_node_child_count(node) == 0) {
      const char *type = ts_node_type(node);
      int is_named = ts_node_is_named(node);
      J tt = -1, tm = 0;

      if (is_named) {
        if (strcmp(type, "identifier") == 0 || strcmp(type, "dotted_name") == 0) {
          tt = 0; // variable by default
          TSNode parent = ts_node_parent(node);
          if (!ts_node_is_null(parent)) {
            const char *ptype = ts_node_type(parent);
            // Parameter?
            if (strcmp(ptype, "params") == 0) {
              tt = 1; tm = 2; // parameter + definition
            }
            // Function definition (assignment of lambda)?
            else if (strcmp(ptype, "assignment") == 0 || strcmp(ptype, "global_assignment") == 0) {
              TSNode name_n = ts_node_child_by_field_name(parent, "name", 4);
              if (!ts_node_is_null(name_n) &&
                  ts_node_start_byte(name_n) == ts_node_start_byte(node)) {
                tm = 2; // definition
                TSNode val_n = ts_node_child_by_field_name(parent, "value", 5);
                if (!ts_node_is_null(val_n) && strcmp(ts_node_type(val_n), "lambda") == 0)
                  tt = 2; // function
              }
            }
          }
        }
        else if (strcmp(type, "integer") == 0 || strcmp(type, "float_lit") == 0 ||
                 strcmp(type, "inf_lit") == 0)               tt = 5;
        else if (strcmp(type, "identifier") == 0)             {} // already handled
        else if (strcmp(type, "line_comment") == 0 ||
                 strcmp(type, "block_comment") == 0)           tt = 7;
        else if (strcmp(type, "verb") == 0 ||
                 strcmp(type, "operator") == 0 ||
                 strcmp(type, "adverb") == 0)                  tt = 4;
        else if (strcmp(type, "keyword_op") == 0)              tt = 3;
        else if (strcmp(type, "bool_lit") == 0 ||
                 strcmp(type, "null_lit") == 0)                 tt = 5;
      } else {
        // Anonymous keyword nodes
        if (strcmp(type, "if") == 0 || strcmp(type, "do") == 0 ||
            strcmp(type, "while") == 0 || strcmp(type, "$") == 0)
          tt = 3;
      }

      if (tt >= 0) {
        TSPoint sp = ts_node_start_point(node);
        uint32_t sb = ts_node_start_byte(node), eb = ts_node_end_byte(node);
        J l = sp.row, c = sp.column, ln = eb - sb;
        ja(&lines, &l); ja(&cols, &c); ja(&lens, &ln);
        ja(&types, &tt); ja(&mods, &tm);
      }
    }

    if (ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor)) {
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = 1; break; }
    }
  }
  ts_tree_cursor_delete(&cursor);

  K colnames = ktn(KS, 5);
  kS(colnames)[0] = ss("line"); kS(colnames)[1] = ss("col");
  kS(colnames)[2] = ss("len"); kS(colnames)[3] = ss("tokenType");
  kS(colnames)[4] = ss("tokenModifiers");
  K vals = ktn(0, 5);
  kK(vals)[0] = lines; kK(vals)[1] = cols; kK(vals)[2] = lens;
  kK(vals)[3] = types; kK(vals)[4] = mods;
  return xT(xD(colnames, vals));
}
