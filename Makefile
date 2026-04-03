KDB_INC ?= /home/dh/repo/nouse/Tc-rust-ffi/c/kdb
CFLAGS  := -shared -fPIC -O2 -I $(KDB_INC) -I src

ts_q.so: ts_q.c src/parser.c src/scanner.c
	cc $(CFLAGS) -o $@ $^ -ltree-sitter

test: ts_q.so test-ts test-lsp

test-ts: ts_q.so
	q test_ts.q -q

test-lsp: ts_q.so
	python3 test_lsp.py

clean:
	rm -f ts_q.so

.PHONY: test test-ts test-lsp clean
