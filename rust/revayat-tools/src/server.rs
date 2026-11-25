//! The CLI's stage registry behind MCP stdio and authenticated loopback REST.

use std::io::{self, BufRead, Write};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use axum::body::{Body, to_bytes};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::{get, post};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::Serialize;
use serde_json::{Value, json};
use subtle::ConstantTimeEq;
use tokio::net::TcpListener;

pub const PROTOCOL_VERSION: &str = "2025-03-26";
pub const MAX_BODY_BYTES: usize = 1 << 20;

#[derive(Clone, Debug, Serialize)]
pub struct StageDescriptor {
    pub name: String,
    pub description: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: Value,
}

impl StageDescriptor {
    pub fn new(name: impl Into<String>, description: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            input_schema: json!({"type":"object","properties":{"args":{"type":"array","items":{"type":"string"}}}}),
        }
    }
}

#[derive(Debug, thiserror::Error)]
#[error("{message}")]
pub struct StageError {
    pub kind: &'static str,
    pub message: String,
}

impl StageError {
    pub fn new(kind: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }
}

impl From<io::Error> for StageError {
    fn from(error: io::Error) -> Self {
        Self::new("stage-failed", error.to_string())
    }
}

pub trait StageDispatcher: Send + Sync {
    fn descriptors(&self) -> &[StageDescriptor];

    /// Write all command output to the provided writer, not process stdout.
    fn dispatch(
        &self,
        stage: &str,
        args: &[String],
        output: &mut dyn Write,
    ) -> Result<i32, StageError>;
}

fn descriptor(dispatcher: &dyn StageDispatcher, name: &str) -> bool {
    dispatcher
        .descriptors()
        .iter()
        .any(|stage| stage.name == name)
}

fn tools(dispatcher: &dyn StageDispatcher) -> Vec<StageDescriptor> {
    dispatcher
        .descriptors()
        .iter()
        .map(|stage| StageDescriptor {
            name: format!("revayat_{}", stage.name),
            ..stage.clone()
        })
        .collect()
}

pub fn run_stage(dispatcher: &dyn StageDispatcher, stage: &str, args: Option<&Value>) -> Value {
    let stage = stage.strip_prefix("revayat_").unwrap_or(stage);
    let failure =
        |kind: &str, error: &str| json!({"ok":false,"stage":stage,"kind":kind,"error":error});
    if !descriptor(dispatcher, stage) {
        return failure("invalid-arguments", "unknown tool name");
    }
    let args = match args {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(values)) => {
            let Some(args) = values
                .iter()
                .map(|v| match v {
                    Value::String(text) => Some(text.clone()),
                    Value::Number(number) => Some(number.to_string()),
                    _ => None,
                })
                .collect::<Option<Vec<_>>>()
            else {
                return failure(
                    "invalid-arguments",
                    "args must contain only strings or numbers",
                );
            };
            args
        }
        _ => return failure("invalid-arguments", "args must be an array of strings"),
    };
    let mut output = Vec::new();
    match dispatcher.dispatch(stage, &args, &mut output) {
        Ok(code) => {
            let Ok(text) = String::from_utf8(output) else {
                return failure("stage-failed", "stage output is not UTF-8");
            };
            let text = text.trim();
            let report = if text.is_empty() {
                Value::Null
            } else {
                serde_json::from_str(text).unwrap_or_else(|_| json!({"output":text}))
            };
            json!({"ok":code == 0,"stage":stage,"exit":code,"report":report})
        }
        Err(error) => failure(error.kind, &error.message),
    }
}

fn wire_json(bytes: &[u8]) -> Option<Value> {
    let (mut i, mut in_string) = (0, false);
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if in_string => i += 2,
            b'"' => {
                in_string = !in_string;
                i += 1;
            }
            b'-' | b'0'..=b'9' if !in_string => {
                let start = i;
                while i < bytes.len()
                    && matches!(bytes[i], b'0'..=b'9' | b'+' | b'-' | b'.' | b'e' | b'E')
                {
                    i += 1;
                }
                let token = &bytes[start..i];
                if token.iter().any(|b| matches!(b, b'.' | b'e' | b'E')) {
                    if !std::str::from_utf8(token)
                        .ok()?
                        .parse::<f64>()
                        .is_ok_and(f64::is_finite)
                    {
                        return None;
                    }
                } else if token.strip_prefix(b"-").unwrap_or(token).len() > 1024 {
                    return None;
                }
            }
            _ => i += 1,
        }
    }
    serde_json::from_slice(bytes).ok()
}

fn rpc_error(id: &Value, code: i32, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}

pub fn handle_rpc(dispatcher: &dyn StageDispatcher, request: Value) -> Option<Value> {
    let Some(request) = request.as_object() else {
        return Some(rpc_error(
            &Value::Null,
            -32600,
            "a JSON-RPC message must be an object",
        ));
    };
    let id = request.get("id").unwrap_or(&Value::Null);
    if !(id.is_null() || id.is_string() || id.is_number()) {
        return Some(rpc_error(
            &Value::Null,
            -32600,
            "a JSON-RPC id must be a string or number",
        ));
    }
    let fail = |code, text: &str| Some(rpc_error(id, code, text));
    if request.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return fail(-32600, "expected JSON-RPC 2.0");
    }
    let Some(method) = request
        .get("method")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
    else {
        return fail(-32600, "method must be a nonempty string");
    };
    if !request.contains_key("id") {
        return None;
    }
    if id.is_null() {
        return fail(-32600, "a request needs a non-null id");
    }
    let params = request.get("params").unwrap_or(&Value::Null);
    if !params.is_null() && !params.is_object() {
        return fail(-32602, "params must be an object");
    }
    let result = match method {
        "initialize" => {
            json!({"protocolVersion":PROTOCOL_VERSION,"capabilities":{"tools":{}},"serverInfo":{"name":"revayat-comic","version":env!("CARGO_PKG_VERSION")}})
        }
        "ping" => json!({}),
        "tools/list" => json!({"tools":tools(dispatcher)}),
        "tools/call" => {
            let arguments = &params["arguments"];
            if !arguments.is_null() && !arguments.is_object() {
                return fail(-32602, "arguments must be an object");
            }
            let Some(stage) = params["name"]
                .as_str()
                .and_then(|name| name.strip_prefix("revayat_"))
                .filter(|name| descriptor(dispatcher, name))
            else {
                return fail(-32602, "unknown tool name");
            };
            let outcome = run_stage(dispatcher, stage, arguments.get("args"));
            json!({"content":[{"type":"text","text":outcome.to_string()}],"isError":outcome["ok"] != true})
        }
        _ => return fail(-32601, "unknown method"),
    };
    Some(json!({"jsonrpc":"2.0","id":id,"result":result}))
}

/// Read one bounded physical line. Drain an oversized line without storing it.
fn frame(input: &mut impl BufRead, bytes: &mut Vec<u8>) -> io::Result<(bool, bool)> {
    bytes.clear();
    let mut consumed = 0;
    loop {
        let buf = input.fill_buf()?;
        if buf.is_empty() {
            return Ok((consumed != 0, false));
        }
        let buf = &buf[..buf.len().min(MAX_BODY_BYTES * 4 - consumed)];
        let newline = buf.iter().position(|&byte| byte == b'\n');
        let count = newline.map_or(buf.len(), |i| i + 1);
        let save = count.min(MAX_BODY_BYTES + 1 - bytes.len());
        bytes.extend_from_slice(&buf[..save]);
        input.consume(count);
        consumed += count;
        if newline.is_some() {
            return Ok((true, false));
        }
        if consumed == MAX_BODY_BYTES * 4 {
            return Ok((true, true));
        }
    }
}

pub fn run_stdio_server(
    dispatcher: &dyn StageDispatcher,
    mut input: impl BufRead,
    mut output: impl Write,
) -> io::Result<i32> {
    let mut bytes = Vec::new();
    loop {
        let (present, exhausted) = frame(&mut input, &mut bytes)?;
        if !present {
            return Ok(0);
        }
        let reply = if bytes.len() > MAX_BODY_BYTES {
            Some(rpc_error(
                &Value::Null,
                -32600,
                "a message may be at most 1048576 bytes",
            ))
        } else if bytes.iter().all(u8::is_ascii_whitespace) {
            None
        } else {
            match wire_json(&bytes) {
                Some(request) => handle_rpc(dispatcher, request),
                None => Some(rpc_error(&Value::Null, -32700, "invalid JSON")),
            }
        };
        if let Some(reply) = reply {
            serde_json::to_writer(&mut output, &reply)?;
            output.write_all(b"\n")?;
            output.flush()?;
        }
        if exhausted {
            return Ok(1);
        }
    }
}

#[derive(Clone)]
struct HttpState {
    dispatcher: Arc<dyn StageDispatcher>,
    token: Arc<str>,
}

type HttpReply = (StatusCode, axum::Json<Value>);

fn http_failure(status: StatusCode, error: &str) -> HttpReply {
    (status, axum::Json(json!({"ok":false,"error":error})))
}

impl HttpState {
    fn authorized(&self, headers: &HeaderMap) -> bool {
        headers
            .get("x-revayat-token")
            .is_some_and(|value| bool::from(self.token.as_bytes().ct_eq(value.as_bytes())))
    }
}

async fn list(State(state): State<HttpState>, headers: HeaderMap) -> HttpReply {
    if !state.authorized(&headers) {
        return http_failure(StatusCode::UNAUTHORIZED, "bad token");
    }
    (
        StatusCode::OK,
        axum::Json(json!({"tools":tools(state.dispatcher.as_ref())})),
    )
}

async fn call(
    State(state): State<HttpState>,
    Path(stage): Path<String>,
    headers: HeaderMap,
    body: Body,
) -> HttpReply {
    if !state.authorized(&headers) {
        return http_failure(StatusCode::UNAUTHORIZED, "bad token");
    }
    let parsed =
        match tokio::time::timeout(Duration::from_secs(30), to_bytes(body, MAX_BODY_BYTES)).await {
            Ok(Ok(bytes)) if bytes.is_empty() => Some(json!({})),
            Ok(Ok(bytes)) => wire_json(&bytes),
            Ok(Err(_)) => {
                return http_failure(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    "request body is too large or unreadable",
                );
            }
            Err(_) => return http_failure(StatusCode::REQUEST_TIMEOUT, "request body timed out"),
        };
    let Some(Value::Object(body)) = parsed else {
        return http_failure(StatusCode::BAD_REQUEST, "expected a JSON object");
    };
    let result = tokio::task::spawn_blocking(move || {
        run_stage(state.dispatcher.as_ref(), &stage, body.get("args"))
    })
    .await;
    match result {
        Ok(value) if value["ok"] == true => (StatusCode::OK, axum::Json(value)),
        Ok(value) => (StatusCode::BAD_REQUEST, axum::Json(value)),
        Err(_) => http_failure(StatusCode::INTERNAL_SERVER_ERROR, "stage execution stopped"),
    }
}

/// Authenticate every route using `X-Revayat-Token`. The callback receives the bound address and token.
pub async fn run_http_server(
    dispatcher: Arc<dyn StageDispatcher>,
    address: SocketAddr,
    token: Option<&str>,
    announce: impl FnOnce(SocketAddr, &str),
) -> io::Result<()> {
    if !address.ip().is_loopback() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "the REST server can only bind to loopback",
        ));
    }
    let token: Arc<str> = match token.filter(|token| !token.is_empty()) {
        Some(token) if token.bytes().all(|byte| byte.is_ascii_graphic()) => Arc::from(token),
        Some(_) => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "HTTP token must be printable ASCII without whitespace",
            ));
        }
        None => {
            let mut bytes = [0; 24];
            getrandom::fill(&mut bytes)
                .map_err(|_| io::Error::other("could not generate an HTTP token"))?;
            Arc::from(URL_SAFE_NO_PAD.encode(bytes))
        }
    };
    let listener = TcpListener::bind(address).await?;
    announce(listener.local_addr()?, &token);
    let router = Router::new()
        .route("/tools", get(list))
        .route("/tools/", get(list))
        .route("/tools/{stage}", post(call))
        .with_state(HttpState { dispatcher, token });
    axum::serve(listener, router).await
}
