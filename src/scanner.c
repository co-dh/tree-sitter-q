// External scanner for q/kdb+ context-sensitive comments and whitespace
//
// From code.kx.com/q/basics/syntax/:
// "If a `/` is meant to denote the left end of a comment then it must be
// preceded by a blank (or newline); otherwise it will be taken to be part
// of an iterator."
//
// Whitespace (spaces/tabs) is handled here instead of as a regex extra,
// so we can detect "/ preceded by blank" reliably. Newlines stay as
// regex extras since they don't affect comment detection.

#include "tree_sitter/parser.h"

enum TokenType {
  LINE_COMMENT,
  BLOCK_COMMENT,
  BACKSLASH_CMD,
  WHITESPACE,
};

static void advance(TSLexer *lexer) {
  lexer->advance(lexer, false);
}

static void skip(TSLexer *lexer) {
  lexer->advance(lexer, true);
}

static void consume_line(TSLexer *lexer) {
  while (lexer->lookahead != '\n' && lexer->lookahead != '\r'
         && lexer->lookahead != 0) {
    advance(lexer);
  }
}

static bool is_ws(int32_t c) {
  return c == ' ' || c == '\t';
}

void *tree_sitter_q_external_scanner_create(void) { return NULL; }
void tree_sitter_q_external_scanner_destroy(void *p) { (void)p; }
unsigned tree_sitter_q_external_scanner_serialize(void *p, char *b) {
  (void)p; (void)b; return 0;
}
void tree_sitter_q_external_scanner_deserialize(
    void *p, const char *b, unsigned n) { (void)p; (void)b; (void)n; }

bool tree_sitter_q_external_scanner_scan(
    void *payload, TSLexer *lexer, const bool *valid_symbols) {
  (void)payload;

  // ── Handle \ at column 0: system command (\d, \l, \p, etc.) ──
  if (lexer->lookahead == '\\' && lexer->get_column(lexer) == 0) {
    if (valid_symbols[BACKSLASH_CMD]) {
      lexer->mark_end(lexer);
      advance(lexer);
      if ((lexer->lookahead >= 'a' && lexer->lookahead <= 'z')
          || (lexer->lookahead >= 'A' && lexer->lookahead <= 'Z')
          || lexer->lookahead == '\n' || lexer->lookahead == '\r'
          || lexer->lookahead == 0) {
        consume_line(lexer);
        lexer->mark_end(lexer);
        lexer->result_symbol = BACKSLASH_CMD;
        return true;
      }
    }
    return false;
  }

  // ── Handle whitespace: consume spaces/tabs, check for following / ──
  if (is_ws(lexer->lookahead)) {
    // Consume all spaces/tabs
    while (is_ws(lexer->lookahead)) {
      skip(lexer);
    }

    // After whitespace, check if / follows → comment
    if (lexer->lookahead == '/' && valid_symbols[LINE_COMMENT]) {
      lexer->mark_end(lexer);
      advance(lexer); // consume /

      // // after whitespace = always comment
      if (lexer->lookahead == '/') {
        consume_line(lexer);
        lexer->mark_end(lexer);
        lexer->result_symbol = LINE_COMMENT;
        return true;
      }

      // Single / after whitespace = inline comment
      consume_line(lexer);
      lexer->mark_end(lexer);
      lexer->result_symbol = LINE_COMMENT;
      return true;
    }

    // Just whitespace, no comment
    if (valid_symbols[WHITESPACE]) {
      lexer->mark_end(lexer);
      lexer->result_symbol = WHITESPACE;
      return true;
    }
    return false;
  }

  // ── Handle / at current position (no preceding whitespace) ──
  if (lexer->lookahead != '/') return false;

  uint32_t slash_col = lexer->get_column(lexer);

  lexer->mark_end(lexer);
  advance(lexer); // consume /

  // Case 1: // — always a line comment
  if (lexer->lookahead == '/') {
    if (valid_symbols[LINE_COMMENT]) {
      consume_line(lexer);
      lexer->mark_end(lexer);
      lexer->result_symbol = LINE_COMMENT;
      return true;
    }
    return false;
  }

  // Case 2: / at column 0 (start of line, no preceding whitespace)
  if (slash_col == 0) {
    // / followed by newline or EOF = block comment start
    if (lexer->lookahead == '\n' || lexer->lookahead == '\r'
        || lexer->lookahead == 0) {
      if (valid_symbols[BLOCK_COMMENT]) {
        if (lexer->lookahead == '\r') advance(lexer);
        if (lexer->lookahead == '\n') advance(lexer);
        while (lexer->lookahead != 0) {
          if (lexer->get_column(lexer) == 0 && lexer->lookahead == '\\') {
            advance(lexer);
            if (lexer->lookahead == '\n' || lexer->lookahead == '\r'
                || lexer->lookahead == 0) {
              lexer->mark_end(lexer);
              lexer->result_symbol = BLOCK_COMMENT;
              return true;
            }
          }
          advance(lexer);
        }
        lexer->mark_end(lexer);
        lexer->result_symbol = BLOCK_COMMENT;
        return true;
      }
    }
    // / at col 0 followed by anything = line comment
    // Consume consecutive / comments to avoid parser error recovery
    // skipping the second / (tree-sitter GLR bug with extras)
    if (valid_symbols[LINE_COMMENT]) {
      consume_line(lexer);
      while (lexer->lookahead == '\n' || lexer->lookahead == '\r') {
        advance(lexer);  // consume newline
        if (lexer->lookahead == '/') {
          advance(lexer);  // consume /
          // // or / at col 0 followed by non-newline → another comment line
          if (lexer->lookahead == '/' || (lexer->lookahead != '\n'
              && lexer->lookahead != '\r' && lexer->lookahead != 0)) {
            consume_line(lexer);
            continue;
          }
          // / followed by newline = block comment start, stop merging
          break;
        }
        break;  // next line doesn't start with / → stop
      }
      lexer->mark_end(lexer);
      lexer->result_symbol = LINE_COMMENT;
      return true;
    }
    return false;
  }

  // Case 3: / NOT at col 0, NOT preceded by whitespace → adverb, not comment
  return false;
}
