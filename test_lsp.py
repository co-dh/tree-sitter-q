#!/usr/bin/env python3
"""Test the q LSP server end-to-end."""
import subprocess, json, sys, threading, time

proc = subprocess.Popen(["q", "lsp.q", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Capture stderr in background
stderr_lines = []
def read_stderr():
    for line in proc.stderr:
        stderr_lines.append(line.decode().rstrip())
t = threading.Thread(target=read_stderr, daemon=True)
t.start()

def send(msg):
    body = json.dumps(msg).encode()
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    proc.stdin.write(header + body)
    proc.stdin.flush()
    print(f"  -> sent {msg.get('method', msg.get('id','?'))}", file=sys.stderr)

def recv(timeout=5):
    import select
    headers = {}
    deadline = time.time() + timeout
    while True:
        if time.time() > deadline:
            print("TIMEOUT waiting for response", file=sys.stderr)
            print("stderr:", stderr_lines, file=sys.stderr)
            proc.kill()
            sys.exit(1)
        c = proc.stdout.read(1)
        if not c:
            print("EOF on stdout", file=sys.stderr)
            print("stderr:", stderr_lines, file=sys.stderr)
            proc.kill()
            sys.exit(1)
        # Build lines
        if not hasattr(recv, '_buf'): recv._buf = b""
        if c == b"\n":
            line = recv._buf.rstrip(b"\r")
            recv._buf = b""
            if not line:
                break
            if line.startswith(b"Content-Length:"):
                headers["cl"] = int(line.split(b":")[1].strip())
        else:
            recv._buf += c
    body = proc.stdout.read(headers["cl"])
    r = json.loads(body)
    print(f"  <- got response id={r.get('id','?')}", file=sys.stderr)
    return r

try:
    send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}})
    r = recv()
    print("init:", r.get("result",{}).get("serverInfo"))

    send({"jsonrpc":"2.0","method":"initialized","params":{}})

    text = "f:{[x;y] x+y}\ng::42\nresult:f[1;2]"
    send({"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{"uri":"file:///test.q","languageId":"q","version":1,"text":text}}})

    send({"jsonrpc":"2.0","id":2,"method":"textDocument/hover","params":{"textDocument":{"uri":"file:///test.q"},"position":{"line":0,"character":0}}})
    r = recv()
    print("hover f:", r.get("result",{}).get("contents",{}).get("value","null"))

    send({"jsonrpc":"2.0","id":3,"method":"textDocument/hover","params":{"textDocument":{"uri":"file:///test.q"},"position":{"line":1,"character":0}}})
    r = recv()
    print("hover g:", r.get("result",{}).get("contents",{}).get("value","null"))

    send({"jsonrpc":"2.0","id":4,"method":"textDocument/definition","params":{"textDocument":{"uri":"file:///test.q"},"position":{"line":2,"character":7}}})
    r = recv()
    print("def f:", r.get("result"))

    send({"jsonrpc":"2.0","id":5,"method":"textDocument/documentSymbol","params":{"textDocument":{"uri":"file:///test.q"}}})
    r = recv()
    print("symbols:", [s["name"] for s in r.get("result",[])])

    send({"jsonrpc":"2.0","id":6,"method":"textDocument/completion","params":{"textDocument":{"uri":"file:///test.q"},"position":{"line":0,"character":0}}})
    r = recv()
    items = r.get("result",[])
    print("completion count:", len(items))

    send({"jsonrpc":"2.0","id":7,"method":"shutdown","params":{}})
    recv()
    send({"jsonrpc":"2.0","method":"exit","params":{}})
    proc.wait(timeout=2)
    print("all tests passed")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    print("stderr:", stderr_lines, file=sys.stderr)
    proc.kill()
    sys.exit(1)
