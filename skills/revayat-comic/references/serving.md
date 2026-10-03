# Driving the pipeline without a shell

The CLI is the recommended path and nothing here replaces it. This is for the
case where a host cannot run a subprocess at all — a hosted agent, a sandboxed
one, a machine that is not the one holding the pages.

```bash
revayat-comic serve mcp                   # JSON-RPC 2.0 over stdio
revayat-comic serve http --port 8765      # loopback, token in a header
```

## It is a transport, not a layer

Every tool is one stage's own `main(argv)`, called with the arguments the CLI
takes, with stdout captured and parsed back into JSON:

```json
{"name": "revayat_detect", "arguments": {"args": ["--doc", "work/comic.json"]}}
```

There is no path through the server that can do something the CLI cannot, and no
stage changed in order to be reachable. The arguments stay a pass-through list
on purpose: `--help` on each stage is the authority on them, and a hand-copied
JSON schema for every stage would be wrong within a month.

One tool per stage, plus `revayat_doctor`. Their descriptions are read
from each stage module's own docstring, so a tool description cannot drift from
what the stage does.

## What a result looks like

```json
{"ok": true, "stage": "detect", "exit": 0, "report": { ... }}
```

`report` is exactly what the CLI would have printed. Failure is a value, not an
exception: a missing dependency, a bad path, an unknown flag and a non-zero exit
all come back with `ok: false` and a reason. Over MCP the same object is the
text of the tool result and `isError` mirrors `ok`.

**Stdout is captured for two reasons at once.** It is how a stage returns its
report, and on the stdio transport it is also the JSON-RPC channel — a stage
printing into it would derail the conversation from the first real call.

## Step 5 is still yours

Exposing the stages does not make the pipeline autonomous. Step 5 is a reading
model looking at the crop sheets, and that model is the one driving this server,
not something the server can call. What these tools give it is the other fifteen
stages without a shell.

## One stage at a time

**Stage runs are serialised inside the server, so concurrent tool calls queue
rather than overlap.** That is not a performance choice waiting to be undone: a
stage returns its report by printing to stdout, the capture replaces the
process-global `sys.stdout`, and the HTTP transport is a `ThreadingHTTPServer`.
Two stages capturing at once each restore the other's stdout, and the caller
receives someone else's report with nothing raising — a wrong answer that parses
is the worst shape a transport can fail in.

In practice the queue costs little: these stages are CPU-bound image work that
would contend anyway. If you ever need real parallelism, the fix is to stop
using process-global stdout as the return channel, not to remove the lock.

## Security

Both transports run pipeline stages with the server process's file access.
Arguments go straight to `argparse` and never near a shell, so there is nothing
to inject into — but a caller can name any path the process can reach.

The HTTP transport therefore:

- **binds loopback only.** `--host` takes `127.0.0.1`, `::1` or `localhost`;
  anything else is refused rather than warned about. A file-writing service
  reachable from the network is not a configuration choice.
- **bounds what it will read.** A request body over 1 MiB is refused, and a
  connection that stops sending is dropped after 30 seconds. A stage's arguments
  are a few hundred bytes; reading 64 MiB of them to refuse them afterwards is a
  denial of service written as politeness.
- **requires a token**, printed to stderr at startup and sent as
  `X-Revayat-Token`. A page in a browser can POST to `localhost`; it cannot read
  a token from the terminal, and it cannot set that header cross-origin without
  a preflight this server never answers.
- **ends the connection when it rejects a request before reading the body.**
  The body is still in the socket, and on a keep-alive connection the next read
  would start in the middle of it — so a rejected call could be followed by a
  nonsense one the client never sent.

Both transports:

- **bound one message.** A stdio line over 1 MiB is refused unparsed, for the
  same reason the HTTP body is. Native MCP reads physical LF-delimited byte frames
  before strict UTF-8 decoding, including when stdin has a text wrapper. Bad bytes
  produce `-32700`, null ID and fixed `invalid JSON`, without stage dispatch or
  request echo; the next healthy frame in the same session still works. LF, CRLF,
  final EOF without LF, Persian and astral text remain supported. The transport
  borrows a fresh unread exclusive buffer and never closes it; mixing another
  reader with it is unsupported. Oversize discard stops after at most four limits
  plus one byte on binary streams. Decoded-only library streams keep character
  caps and can overshoot that byte budget by one capped chunk. An unfinished huge
  frame requires reconnecting; arbitrary stdin gains no inactivity deadline.
  Fixed warning kinds go to the shared run log, never protocol stdout.
- **bound decoded structure and numbers.** The shared decoder permits at most
  128 container levels and 1024 integer digits, and refuses nonfinite numbers
  (including overflowing exponents). Invalid JSON gets a protocol error while
  the next valid request remains usable; interpreter-wide settings are unchanged.
  Every decoded string and object key must also strictly encode UTF-8: isolated
  surrogate escapes are refused before stage invocation, with no lossy replacement
  or raw request echo. Valid paired escapes, astral characters, Persian and literal
  backslash-u text remain unchanged. This is an interoperability restriction,
  not a claim that RFC 8259's grammar forbids every unpaired escape.
  Discovery still lists healthy tools when one stage cannot import, marking that
  stage unavailable. Invocation reports its failure normally.
- **answer a malformed envelope instead of dropping it.** A `jsonrpc` that is
  not `"2.0"`, a `method` that is not a string, an `id` that is an object, and
  an explicit `"id": null` all come back as JSON-RPC errors. Only a message
  with no `id` at all is a notification, which the protocol forbids answering —
  treating a null id as one left clients waiting for a reply that was never
  coming.
- **treat a stage's failure as an answer.** A corrupt archive, a path the
  process cannot read, a full disk: all of them come back as
  `{"ok": false, "kind": "stage-failed"}`. Only a shutdown you asked for ends
  the loop.

```bash
curl -s -H "X-Revayat-Token: $TOKEN" http://127.0.0.1:8765/tools
curl -s -H "X-Revayat-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"args":["--doc","work/comic.json"]}' \
     http://127.0.0.1:8765/tools/revayat_detect
```

`--port 0` picks a free port and prints it with the token.

## Registering the MCP server

The command is a plain stdio server, so any MCP client takes it the same way:

```json
{
  "mcpServers": {
    "revayat-comic": {
      "command": "python",
      "args": ["<skill>/scripts/revayat-comic.py", "serve", "mcp"]
    }
  }
}
```

Run `revayat_doctor` first. It reports whether this machine can shape and draw
Persian, which is the difference between output that is correct and output that
merely exists — see `persian-typesetting.md`.
