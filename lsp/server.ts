#!/usr/bin/env node
// q/kdb+ Language Server
// Features: go-to-definition, completion, document symbols, hover

import {
  createConnection, TextDocuments, ProposedFeatures,
  InitializeResult, TextDocumentSyncKind, CompletionItemKind,
  SymbolKind, Position, Range,
  type CompletionItem, type DocumentSymbol,
  type Location, type Hover,
} from 'vscode-languageserver/node';
import { TextDocument } from 'vscode-languageserver-textdocument';

// ── q built-in verbs and keywords ───────────────────────────
const VERBS: Record<string, string> = {
  neg: 'Negate', abs: 'Absolute value', sqrt: 'Square root',
  floor: 'Round down', ceiling: 'Round up', reciprocal: '1%x',
  signum: 'Sign (-1, 0, 1)', not: 'Logical not', null: 'Is null',
  type: 'Type number', count: 'Count items', first: 'First item',
  last: 'Last item', enlist: 'Wrap in list', distinct: 'Unique items',
  raze: 'Flatten', reverse: 'Reverse', asc: 'Sort ascending',
  desc: 'Sort descending', flip: 'Transpose', key: 'Keys / key table',
  value: 'Values', where: 'Indices of 1s / filter', group: 'Group indices',
  til: 'Integers 0..n-1', sum: 'Sum', prd: 'Product',
  avg: 'Average', min: 'Minimum', max: 'Maximum', med: 'Median',
  sums: 'Running sum', prds: 'Running product', mins: 'Running min',
  maxs: 'Running max', avgs: 'Running avg',
  string: 'Convert to string', lower: 'Lowercase', upper: 'Uppercase',
  trim: 'Trim whitespace', ltrim: 'Trim left', rtrim: 'Trim right',
  show: 'Display', rand: 'Random', differ: 'Items differ from prior',
  fills: 'Forward-fill nulls', get: 'Read / evaluate',
  set: 'Write / assign', hopen: 'Open handle', hclose: 'Close handle',
  hdel: 'Delete file', hsym: 'File symbol', read0: 'Read lines',
  read1: 'Read bytes', parse: 'Parse string', eval: 'Evaluate parse tree',
  cols: 'Column names', tables: 'List tables', views: 'List views',
  meta: 'Table metadata', fkeys: 'Foreign keys',
  delete: 'Delete rows/cols', exec: 'Execute query',
  select: 'Select query', update: 'Update query',
};

const KEYWORD_OPS: Record<string, string> = {
  within: 'x within (lo;hi)', like: 'Pattern match', in: 'Membership',
  except: 'Set difference', inter: 'Set intersection', union: 'Set union',
  sv: 'Scalar from vector', vs: 'Vector from scalar',
  bin: 'Binary search', binr: 'Binary search (right)',
  cor: 'Correlation', cov: 'Covariance',
  each: 'Apply each', peach: 'Parallel each',
  ij: 'Inner join', lj: 'Left join', uj: 'Union join',
  pj: 'Plus join', aj: 'As-of join', wj: 'Window join', asof: 'As-of',
  xkey: 'Set key columns', xcol: 'Rename columns',
  xcols: 'Reorder columns', xasc: 'Sort asc by', xdesc: 'Sort desc by',
  xgroup: 'Group by', ss: 'String search', ssr: 'String search-replace',
  xexp: 'Power', xlog: 'Log base x', xbar: 'Round down to multiple',
  mod: 'Modulo', div: 'Integer divide', mmu: 'Matrix multiply',
  wavg: 'Weighted avg', wsum: 'Weighted sum', cross: 'Cross product',
  rotate: 'Rotate', sublist: 'Sublist', cut: 'Cut', ema: 'Exp moving avg',
  prior: 'Apply with prior', scan: 'Scan', over: 'Over/fold',
};

// ── Types ───────────────────────────────────────────────────
interface Def {
  name: string;
  range: Range;
  nameRange: Range;
  uri: string;
  kind: SymbolKind;
  detail?: string;
  isGlobal: boolean;
}

// ── Server setup ────────────────────────────────────────────
const conn = createConnection(ProposedFeatures.all);
const docs = new TextDocuments(TextDocument);
const defsByUri = new Map<string, Def[]>();

conn.onInitialize((): InitializeResult => ({
  capabilities: {
    textDocumentSync: TextDocumentSyncKind.Full,
    completionProvider: { triggerCharacters: ['.', '`'] },
    definitionProvider: true,
    documentSymbolProvider: true,
    hoverProvider: true,
  },
}));

// ── Analysis: extract definitions ───────────────────────────
// Matches: name:{...}, name:expr, name::expr
const ASSIGN_RE = /^(\s*)(\.?[a-zA-Z][a-zA-Z0-9_.]*)\s*(::?)\s*(.*)/;
const LAMBDA_START = /^\{/;
const PARAM_RE = /^\{\[([^\]]*)\]/;

function analyze(uri: string, doc: TextDocument): Def[] {
  const defs: Def[] = [];
  const lines = doc.getText().split('\n');

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Skip comments
    if (/^\s*\//.test(line) || /^\s*$/.test(line)) continue;

    const m = ASSIGN_RE.exec(line);
    if (!m) continue;
    const [, indent, name, colons, rest] = m;
    const col = indent.length;
    const isGlobal = colons === '::';
    const isLambda = LAMBDA_START.test(rest.trim());

    let detail: string | undefined;
    if (isLambda) {
      const pm = PARAM_RE.exec(rest.trim());
      detail = pm ? `[${pm[1]}]` : '{...}';
    }

    defs.push({
      name,
      range: Range.create(i, col, i, line.length),
      nameRange: Range.create(i, col, i, col + name.length),
      uri,
      kind: isLambda ? SymbolKind.Function : SymbolKind.Variable,
      detail,
      isGlobal,
    });
  }
  return defs;
}

// ── Document change handler ─────────────────────────────────
docs.onDidChangeContent(change => {
  const defs = analyze(change.document.uri, change.document);
  defsByUri.set(change.document.uri, defs);
});

docs.onDidClose(change => {
  defsByUri.delete(change.document.uri);
});

// ── Go to definition ────────────────────────────────────────
conn.onDefinition(params => {
  const doc = docs.get(params.textDocument.uri);
  if (!doc) return null;
  const word = getWordAt(doc, params.position);
  if (!word) return null;

  const results: Location[] = [];
  // Search current file first, then others
  const uris = [params.textDocument.uri, ...[...defsByUri.keys()].filter(u => u !== params.textDocument.uri)];
  for (const uri of uris) {
    const defs = defsByUri.get(uri);
    if (!defs) continue;
    for (const d of defs) {
      if (d.name === word) results.push({ uri, range: d.nameRange });
    }
  }
  return results.length === 1 ? results[0] : results;
});

// ── Document symbols ────────────────────────────────────────
conn.onDocumentSymbol(params => {
  const defs = defsByUri.get(params.textDocument.uri);
  if (!defs) return [];
  return defs.map((d): DocumentSymbol => ({
    name: d.name + (d.isGlobal ? ' ::' : ''),
    kind: d.kind,
    range: d.range,
    selectionRange: d.nameRange,
    detail: d.detail,
  }));
});

// ── Hover ───────────────────────────────────────────────────
conn.onHover(params => {
  const doc = docs.get(params.textDocument.uri);
  if (!doc) return null;
  const word = getWordAt(doc, params.position);
  if (!word) return null;

  if (word in VERBS) return mkHover(`(verb) ${word} — ${VERBS[word]}`);
  if (word in KEYWORD_OPS) return mkHover(`(keyword) ${word} — ${KEYWORD_OPS[word]}`);

  for (const [, defs] of defsByUri) {
    for (const d of defs) {
      if (d.name !== word) continue;
      const prefix = d.isGlobal ? '(global) ' : '';
      const sig = d.kind === SymbolKind.Function
        ? `${prefix}${d.name}:${d.detail || '{...}'}`
        : `${prefix}${d.name}`;
      return mkHover(sig);
    }
  }
  return null;
});

function mkHover(text: string): Hover {
  return { contents: { kind: 'plaintext', value: text } };
}

// ── Completion ──────────────────────────────────────────────
conn.onCompletion(() => {
  const items: CompletionItem[] = [];
  const seen = new Set<string>();

  for (const [, defs] of defsByUri) {
    for (const d of defs) {
      if (seen.has(d.name)) continue;
      seen.add(d.name);
      items.push({
        label: d.name,
        kind: d.kind === SymbolKind.Function ? CompletionItemKind.Function : CompletionItemKind.Variable,
        detail: d.detail,
      });
    }
  }

  for (const [v, doc] of Object.entries(VERBS)) {
    if (!seen.has(v)) items.push({ label: v, kind: CompletionItemKind.Function, detail: doc });
  }
  for (const [k, doc] of Object.entries(KEYWORD_OPS)) {
    if (!seen.has(k)) items.push({ label: k, kind: CompletionItemKind.Keyword, detail: doc });
  }

  return items;
});

// ── Utility ─────────────────────────────────────────────────
function getWordAt(doc: TextDocument, pos: Position): string | null {
  const line = doc.getText(Range.create(pos.line, 0, pos.line + 1, 0));
  const re = /\.?[a-zA-Z][a-zA-Z0-9_.]*/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) {
    if (m.index <= pos.character && pos.character <= m.index + m[0].length) return m[0];
  }
  return null;
}

// ── Start ───────────────────────────────────────────────────
docs.listen(conn);
conn.listen();
