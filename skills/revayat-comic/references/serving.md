# Run the pipeline over MCP or loopback HTTP

Use the CLI directly when the host can run a subprocess. Both server transports run the same stages with the same arguments. Paths refer to files on the machine running `revayat-comic`.

## MCP over stdio

```bash
revayat-comic serve --stdio
```

Register the server in a client that supports MCP stdio:

```json
{
  "mcpServers": {
    "revayat-comic": {
      "command": "revayat-comic",
      "args": ["serve", "--stdio"]
    }
  }
}
```

Call `tools/list` to see available tools. Each tool takes the stage's CLI arguments as an `args` array. For example, the `revayat_worksheet` tool accepts:

```json
{"args":["build","--doc","/path/to/work/comic.json","--worksheets","/path/to/work/worksheets"]}
```

Run `revayat-comic doctor --json` directly on the server machine and check `ok` before starting. The doctor command is not a pipeline tool.

## Loopback HTTP

Set `REVAYAT_HTTP_TOKEN` in the server environment before starting. Keep it out of command history and logs. Send it in the `X-Revayat-Token` header on every request.

```bash
revayat-comic serve --http 127.0.0.1:8765
```

`GET /tools` lists the tools. `POST /tools/{stage}` runs one stage, using the same JSON body as the MCP call. Use `127.0.0.1:0` to choose a free port; the server writes the bound address to stderr. It accepts loopback addresses only.

Treat the listener as local file access. Only trusted clients should receive the token. In particular, avoid running the server for untrusted callers or forwarding the port to other machines.

## Read the result before proceeding

A completed stage returns `ok`, `exit`, and `report`. Check the report's findings as you would at the CLI. A request or dispatch failure returns `ok: false` and an `error`. MCP marks failed tool results with `isError`.

Keep one writer per workspace and wait for the current stage to finish before starting its dependent stage. Rendering crops over either transport still leaves the visual reading to the agent. Open the overview and sheets before writing a worksheet.
