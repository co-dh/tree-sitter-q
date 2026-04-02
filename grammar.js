/// <reference types="tree-sitter-cli/dsl" />

// Tree-sitter grammar for q/kdb+
//
// q's evaluation model: right-to-left, no operator precedence.
// 2*3+4 = 2*(3+4) = 14. All operators are right-associative.
//
// Juxtaposition: `f x` = `f[x]`. Verbs (keywords) are greedy:
// `neg 3+4` = `neg(3+4)`.

const PREC = {
  BINARY: 1,
  SIGNAL: 2,
  VERB: 3,
  APPLY: 4,     // juxtaposition f x
  BRACKET: 5,
  ASSIGN: 6,    // name:value — must beat application
  ADVERB: 7,
  UNARY: 8,
  LIST: 9,
};

module.exports = grammar({
  name: 'q',

  externals: $ => [
    $.line_comment,
    $.block_comment,
    $.backslash_cmd,
    $._whitespace,    // spaces/tabs — handled by scanner to detect / comments
  ],

  // Newlines stay as regex extra; spaces handled by scanner
  extras: $ => [/[\r\n]/, $._whitespace, $.line_comment, $.block_comment],

  word: $ => $.identifier,

  conflicts: $ => [
    [$.assignment, $._expr],
    [$.application, $.verb_expr],
    [$.application, $.binary_expr],
    [$.application, $.binary_expr, $.signal],
    [$.application, $.binary_expr, $.early_return],
    [$.application, $.signal],
    [$.application, $.early_return],
    [$.application, $.adverb_expr],
    [$.application, $.binary_expr, $.adverb_expr],
    [$.application, $.verb_expr, $.binary_expr],
  ],

  supertypes: $ => [$._expr],

  rules: {
    // Top level: semicolons and newlines both separate statements
    source_file: $ => optional($._statements),

    _statements: $ => seq(
      $._statement,
      repeat(seq(choice(';', /\n/), optional($._statement))),
    ),

    _statement: $ => choice(
      $.assignment,
      $.global_assignment,
      $._expr,
    ),

    // ── Literals ──────────────────────────────────────────────

    bool_lit: _ => token(/[01]+b/),
    short_lit: _ => token(/\-?[0-9]+h/),
    int_lit: _ => token(/\-?[0-9]+i/),
    long_suffix: _ => token(/\-?[0-9]+j/),
    real_lit: _ => token(/\-?[0-9]+\.?[0-9]*e/),
    float_suffix: _ => token(/\-?[0-9]+\.[0-9]*f/),
    null_lit: _ => token(/0[nN][hijefpmdznuvtgx]?/),
    inf_lit: _ => token(/0[wW][hijefpmdznuvt]?/),
    float_lit: _ => token(/\-?[0-9]+\.[0-9]*/),
    integer: _ => token(/\-?[0-9]+/),
    string_lit: _ => token(/"[^"]*"/),
    symbol_lit: _ => token(/`[a-zA-Z0-9_.:]*/),

    _number: $ => choice(
      $.bool_lit,
      $.short_lit, $.int_lit, $.long_suffix, $.real_lit, $.float_suffix,
      $.null_lit, $.inf_lit,
      $.float_lit, $.integer,
    ),

    _literal: $ => choice(
      $._number,
      $.string_lit,
      $.symbol_lit,
    ),

    // ── Names ─────────────────────────────────────────────────

    identifier: _ => /[a-zA-Z][a-zA-Z0-9_]*/,
    dotted_name: _ => /\.[a-zA-Z][a-zA-Z0-9_.]*(\.[a-zA-Z][a-zA-Z0-9_]*)*/,

    _name: $ => choice($.identifier, $.dotted_name),

    // ── Expressions ───────────────────────────────────────────

    _expr: $ => choice(
      $._literal,
      $._name,
      $.operator,       // operators as values: @[f;x;h], f[a;~;b]
      $.binary_expr,
      $.verb_expr,
      $.application,
      $.bracket_apply,
      $.lambda,
      $.paren_expr,
      $.list_literal,
      $.symbol_list,
      $.cond,
      $.if_stmt,
      $.do_stmt,
      $.while_stmt,
      $.adverb_expr,
      $.unary_expr,
      $.signal,
      $.early_return,
      $.generic_null,
      $.system_cmd,
    ),

    // Operator token
    operator: _ => token(choice(
      '+', '-', '*', '%',
      '=', '<>', '<=', '>=', '<', '>',
      '&', '|',
      ',', '#', '_', '~', '^',
      '!', '@', '.', '?',
    )),

    // Compound assignment: x+:y, x-:y, etc.
    compound_assign: _ => token(choice(
      '+:', '-:', '*:', '%:', ',:', '&:', '|:',
    )),

    keyword_op: _ => choice(
      'within', 'like', 'in', 'except', 'inter', 'union',
      'sv', 'vs', 'set', 'bin', 'binr', 'cor', 'cov',
      'each', 'peach',
      'ij', 'lj', 'uj', 'pj', 'aj', 'wj', 'asof',
      'xkey', 'xcol', 'xcols', 'xasc', 'xdesc', 'xgroup',
      'ss', 'ssr',
      'xexp', 'xlog', 'xbar', 'mod', 'div', 'mmu',
      'wavg', 'wsum', 'cross', 'rotate',
      'sublist', 'cut', 'ema',
      'prior', 'scan', 'over',
    ),

    // x op y — right-associative
    binary_expr: $ => prec.right(PREC.BINARY, seq(
      field('left', $._expr),
      field('op', choice($.operator, $.keyword_op, $.compound_assign, '$')),
      field('right', $._expr),
    )),

    // Monadic prefix: -x, #x, etc.
    unary_expr: $ => prec(PREC.UNARY, seq(
      field('op', $.operator),
      field('arg', $._expr),
    )),

    // verb arg — named unary keywords
    verb_expr: $ => prec.right(PREC.VERB, seq(
      field('verb', $.verb),
      field('arg', $._expr),
    )),

    verb: _ => choice(
      'neg', 'abs', 'sqrt', 'floor', 'ceiling', 'reciprocal', 'signum',
      'not', 'null', 'type', 'count',
      'first', 'last', 'enlist', 'distinct', 'raze',
      'reverse', 'asc', 'desc', 'flip', 'key', 'value',
      'where', 'group', 'til',
      'sum', 'prd', 'avg', 'min', 'max', 'med',
      'sums', 'prds', 'mins', 'maxs', 'avgs',
      'string', 'lower', 'upper', 'trim', 'ltrim', 'rtrim',
      'show', 'rand', 'differ', 'fills',
      'get', 'hopen', 'hclose', 'hdel', 'hsym',
      'read0', 'read1',
      'parse', 'eval', 'over', 'scan',
      'cols', 'tables', 'views', 'meta', 'fkeys',
      'delete', 'exec', 'select', 'update',
    ),

    // f x — juxtaposition application
    application: $ => prec.right(PREC.APPLY, seq(
      field('fn', $._expr),
      field('arg', $._expr),
    )),

    // f[x;y;z]
    bracket_apply: $ => prec(PREC.BRACKET, seq(
      field('fn', $._expr),
      '[',
      optional($._arg_list),
      ']',
    )),

    _arg_list: $ => choice(
      seq($._expr, repeat(seq(';', optional($._expr)))),
      seq(repeat1(seq(';', optional($._expr)))),
    ),

    // {body} or {[x;y] body}
    lambda: $ => seq(
      '{',
      optional($.params),
      optional($.lambda_body),
      '}',
    ),

    params: $ => seq(
      '[',
      optional(seq($.identifier, repeat(seq(';', $.identifier)))),
      ']',
    ),

    lambda_body: $ => seq(
      $._statement,
      repeat(seq(';', optional($._statement))),
    ),

    // (expr) or (e1;e2;...)
    paren_expr: $ => seq(
      '(',
      optional(seq(
        optional($._expr),
        repeat(seq(';', optional($._expr))),
      )),
      ')',
    ),

    // 1 2 3 — space-separated numeric list
    list_literal: $ => prec.right(PREC.LIST, seq(
      $._number, choice($.list_literal, $._number),
    )),

    // `a`b`c — symbol list
    symbol_list: $ => prec.right(PREC.LIST, seq(
      $.symbol_lit, choice($.symbol_list, $.symbol_lit),
    )),

    // $[c;t;f]
    cond: $ => seq('$', '[', $._expr, repeat1(seq(';', $._expr)), ']'),

    if_stmt: $ => seq('if', '[', $._expr, repeat(seq(';', $._expr)), ']'),
    do_stmt: $ => seq('do', '[', $._expr, repeat(seq(';', $._expr)), ']'),
    while_stmt: $ => seq(
      'while', '[', $._expr, repeat(seq(';', $._expr)), ']',
    ),

    // f/ f\ f' f/: f\: f':
    adverb_expr: $ => prec.left(PREC.ADVERB, seq(
      $._expr,
      alias(choice("'", '/', '\\', '/:', "\\:", "':"), $.adverb),
    )),

    // 'msg — signal
    signal: $ => prec.right(PREC.SIGNAL, seq("'", $._expr)),

    // :expr — early return
    early_return: $ => prec.right(PREC.SIGNAL, seq(':', $._expr)),

    // (::) or bare :: — generic null / identity
    generic_null: _ => choice(seq('(', '::', ')'), '::'),

    // system "cmd" or \d .ns (via external scanner)
    system_cmd: $ => choice(
      seq('system', $.string_lit),
      $.backslash_cmd,
    ),

    // name:expr
    assignment: $ => prec.right(PREC.ASSIGN, seq(
      field('name', $._name),
      ':',
      field('value', $._expr),
    )),

    // name::expr
    global_assignment: $ => prec.right(PREC.ASSIGN, seq(
      field('name', $._name),
      '::',
      field('value', $._expr),
    )),
  },
});
