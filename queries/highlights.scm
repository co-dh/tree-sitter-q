; tree-sitter-q highlight queries for Helix

; ── Comments ──────────────────────────────────────────────
(line_comment) @comment
(block_comment) @comment

; ── Punctuation ───────────────────────────────────────────
";" @punctuation.delimiter
(lambda "{" @punctuation.bracket "}" @punctuation.bracket)
(bracket_apply "[" @punctuation.bracket "]" @punctuation.bracket)
(paren_expr "(" @punctuation.bracket ")" @punctuation.bracket)
(params "[" @punctuation.bracket "]" @punctuation.bracket)

; ── Operators ─────────────────────────────────────────────
(operator) @operator
(adverb) @operator
(keyword_op) @keyword.operator

; ── Control flow ──────────────────────────────────────────
(if_stmt "if" @keyword.control.conditional)
(do_stmt "do" @keyword.control.repeat)
(while_stmt "while" @keyword.control.repeat)
(cond "$" @keyword.control.conditional)
(signal "'" @keyword.control.exception)
(early_return ":" @keyword.control.return)

; ── Functions / verbs ─────────────────────────────────────
(verb_expr verb: (verb) @function.builtin)
(application fn: (identifier) @function)
(system_cmd "system" @function.builtin)
(system_cmd) @keyword

; ── Parameters ────────────────────────────────────────────
(params (identifier) @variable.parameter)

; ── Assignment ────────────────────────────────────────────
(assignment name: (identifier) @variable)
(assignment name: (dotted_name) @variable)
(global_assignment name: (identifier) @variable)
(global_assignment name: (dotted_name) @variable)

; ── Strings ───────────────────────────────────────────────
(string_lit) @string
(symbol_lit) @string.special.symbol

; ── Numbers ───────────────────────────────────────────────
(integer) @constant.numeric.integer
(float_lit) @constant.numeric.float
(bool_lit) @constant.numeric
(short_lit) @constant.numeric.integer
(int_lit) @constant.numeric.integer
(long_suffix) @constant.numeric.integer
(real_lit) @constant.numeric.float
(float_suffix) @constant.numeric.float

; ── Special constants ─────────────────────────────────────
(null_lit) @constant.builtin
(inf_lit) @constant.builtin
(generic_null) @constant.builtin

; ── Names (general fallback) ──────────────────────────────
(identifier) @variable
(dotted_name) @variable
