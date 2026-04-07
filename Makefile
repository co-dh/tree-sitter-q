KDB_INC ?= /home/dh/repo/nouse/Tc-rust-ffi/c/kdb
CFLAGS  := -shared -fPIC -O2 -I $(KDB_INC) -I src

lsp/ts_q.so: lsp/ts_q.c src/parser.c src/scanner.c
	cc $(CFLAGS) -o $@ $^ -ltree-sitter

test: lsp/ts_q.so test-ts test-lsp test-examples

test-ts: lsp/ts_q.so
	cd lsp && q test_ts.q -q

test-lsp: lsp/ts_q.so
	cd lsp && python3 test_lsp.py

test-examples: lsp/ts_q.so
	cd lsp && python3 test_examples.py

errors:
	@for f in lsp/examples/*.q lsp/examples/ext/*.q; do \
		errs=$$(tree-sitter parse "$$f" 2>&1 | grep -c ERROR); \
		if [ "$$errs" -gt 0 ]; then echo "$$errs\t$$f"; fi; \
	done

clean:
	rm -f lsp/ts_q.so

.PHONY: test test-ts test-lsp test-examples errors clean
