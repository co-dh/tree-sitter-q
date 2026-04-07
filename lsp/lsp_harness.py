"""Shared LSP test harness — JSON-RPC over stdio with Content-Length framing."""
import subprocess, json, sys, threading, time

class LSPClient:
    def __init__(self, cwd=None):
        self.proc = subprocess.Popen(
            ["q", "lsp.q", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd or (sys.path[0] or "."))
        self.seq = 0
        self._notifs = []
        self.stderr_lines = []
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stderr(self):
        for line in self.proc.stderr:
            self.stderr_lines.append(line.decode().rstrip())

    def die(self, reason):
        print(reason, file=sys.stderr)
        print("stderr:", self.stderr_lines, file=sys.stderr)
        self.proc.kill(); sys.exit(1)

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.seq += 1; msg["id"] = self.seq
        body = json.dumps(msg).encode()
        self.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.proc.stdin.flush()
        return None if notify else self.seq

    def _recv_msg(self, timeout=5):
        headers = {}
        deadline = time.time() + timeout
        buf = b""
        while True:
            if time.time() > deadline: self.die("TIMEOUT")
            c = self.proc.stdout.read(1)
            if not c: self.die("EOF")
            if c == b"\n":
                line = buf.rstrip(b"\r"); buf = b""
                if not line: break
                if line.startswith(b"Content-Length:"):
                    headers["cl"] = int(line.split(b":")[1].strip())
            else:
                buf += c
        return json.loads(self.proc.stdout.read(headers["cl"]))

    def recv(self, timeout=5):
        """Read next response (has id). Buffer any notifications."""
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0: self.die("TIMEOUT waiting for response")
            msg = self._recv_msg(remaining)
            if "id" in msg: return msg
            self._notifs.append(msg)

    def recv_notif(self, timeout=2):
        """Return next notification (buffered or from wire)."""
        if self._notifs: return self._notifs.pop(0)
        return self._recv_msg(timeout)

    def clear_notifs(self):
        self._notifs.clear()

    @property
    def notifs(self):
        return self._notifs


class TestRunner:
    def __init__(self):
        self.pass_n = 0; self.fail_n = 0

    def check(self, name, cond):
        if cond:
            self.pass_n += 1; print(f"  pass: {name}")
        else:
            self.fail_n += 1; print(f"  FAIL: {name}", file=sys.stderr)

    def summary(self):
        print(f"\n{self.pass_n} passed, {self.fail_n} failed")
        if self.fail_n > 0:
            sys.exit(1)
        print("all tests passed")
