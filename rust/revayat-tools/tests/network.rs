#![forbid(unsafe_code)]

use std::io::{self, Write};
use std::net::SocketAddr;
use std::sync::{Arc, mpsc};
use std::time::Duration;

use axum::Router;
use axum::http::{HeaderMap, StatusCode, header};
use axum::routing::post;
use revayat_tools::providers::{ProviderClient, ProviderError};
use revayat_tools::server::{self, StageDescriptor, StageDispatcher, StageError};
use serde_json::{Value, json};
use tokio::net::TcpListener;

const WAIT: Duration = Duration::from_secs(5);

type TestResult = Result<(), Box<dyn std::error::Error>>;

struct ConcurrentEcho {
    descriptors: Vec<StageDescriptor>,
    peer: Arc<tokio::sync::Barrier>,
    runtime: tokio::runtime::Handle,
}

impl StageDispatcher for ConcurrentEcho {
    fn descriptors(&self) -> &[StageDescriptor] {
        &self.descriptors
    }

    fn dispatch(&self, _: &str, args: &[String], out: &mut dyn Write) -> Result<i32, StageError> {
        write!(out, "{{\"arg\":")?;
        self.runtime
            .block_on(async { tokio::time::timeout(WAIT, self.peer.wait()).await })
            .map_err(|_| StageError::new("test", "requests never overlapped"))?;
        serde_json::to_writer(&mut *out, &args.first()).map_err(io::Error::other)?;
        write!(out, "}}")?;
        Ok(0)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rest_requires_token_and_concurrent_http_requests_have_private_output() -> TestResult {
    let stage = Arc::new(ConcurrentEcho {
        descriptors: vec![StageDescriptor::new("echo", "Echo one parameter")],
        peer: Arc::new(tokio::sync::Barrier::new(2)),
        runtime: tokio::runtime::Handle::current(),
    });
    let nonlocal = SocketAddr::from(([0, 0, 0, 0], 0));
    assert!(
        server::run_http_server(stage.clone(), nonlocal, Some("test"), |_, _| {})
            .await
            .is_err()
    );
    let (tx, rx) = tokio::sync::oneshot::channel();
    let listener = tokio::spawn(server::run_http_server(
        stage,
        SocketAddr::from(([127, 0, 0, 1], 0)),
        Some("test-token"),
        |addr, _| {
            let _ = tx.send(addr);
        },
    ));
    let addr = tokio::time::timeout(WAIT, rx).await??;
    let result = tokio::task::spawn_blocking(move || -> TestResultBlocking {
        let agent: ureq::Agent = ureq::config::Config::builder()
            .proxy(None)
            .timeout_global(Some(WAIT))
            .build()
            .into();
        let url = format!("http://{addr}/tools");
        let denied = agent.get(&url).call();
        assert!(matches!(denied, Err(ureq::Error::StatusCode(401))));
        let listed: Value = agent
            .get(&url)
            .header("X-Revayat-Token", "test-token")
            .call()?
            .body_mut()
            .read_json()?;
        assert_eq!(listed["tools"][0]["name"], "revayat_echo");
        let tasks: Vec<_> = ["اول", "دوم"]
            .into_iter()
            .map(|arg| {
                let url = format!("{url}/revayat_echo");
                let agent = agent.clone();
                std::thread::spawn(move || -> TestResultBlocking {
                    let reply: Value = agent
                        .post(&url)
                        .header("X-Revayat-Token", "test-token")
                        .send_json(json!({"args":[arg]}))?
                        .body_mut()
                        .read_json()?;
                    assert_eq!(reply["report"]["arg"], arg);
                    Ok(())
                })
            })
            .collect();
        for job in tasks {
            job.join().map_err(|_| "HTTP test worker panicked")??;
        }
        Ok(())
    })
    .await;
    listener.abort();
    let _ = listener.await;
    result?.map_err(|error| -> Box<dyn std::error::Error> { error })
}

type TestResultBlocking = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_sends_utf8_to_localhost_and_does_not_follow_redirects() -> TestResult {
    let (data_tx, data_rx) = mpsc::channel();
    let router = Router::new()
        .route("/v1/chat/completions", post(move |headers: HeaderMap, axum::Json(payload): axum::Json<Value>| {
            let data_tx = data_tx.clone();
            async move {
                let bearer = headers.get(header::AUTHORIZATION).and_then(|h| h.to_str().ok()).map(str::to_owned);
                let _ = data_tx.send((bearer, payload));
                axum::Json(json!({"choices":[{"finish_reason":"stop","message":{"content":"سلام دنیا"}}]}))
            }
        }))
        .route("/v1/redirect", post(|| async { (StatusCode::TEMPORARY_REDIRECT, [(header::LOCATION, "/v1/chat/completions")]) }));
    let socket = TcpListener::bind(("127.0.0.1", 0)).await?;
    let port = socket.local_addr()?.port();
    let listener = tokio::spawn(async { axum::serve(socket, router).await });
    let result = tokio::task::spawn_blocking(move || -> TestResultBlocking {
        let client = ProviderClient::new(
            &format!("http://localhost:{port}/v1"),
            Some("test-key"),
            WAIT,
        )?;
        let result = client.translate("synthetic-model", "今日は", &serde_json::Map::new())?;
        assert_eq!(result.as_deref(), Some("سلام دنیا"));
        let (bearer, payload) = data_rx.recv_timeout(WAIT)?;
        assert_eq!(bearer.as_deref(), Some("Bearer test-key"));
        let content = payload["messages"][1]["content"]
            .as_str()
            .ok_or("missing user data")?;
        assert_eq!(serde_json::from_str::<Value>(content)?["source"], "今日は");
        assert!(matches!(
            client.post_json("redirect", &json!({})),
            Err(ProviderError::Redirect)
        ));
        assert!(data_rx.try_recv().is_err());
        Ok(())
    })
    .await;
    listener.abort();
    let _ = listener.await;
    result?.map_err(|error| -> Box<dyn std::error::Error> { error })
}
