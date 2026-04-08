use std::{
    env,
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};

use serde_json::Value;
use tokio::time::sleep;
use zenoh::bytes::Encoding;

const DEFAULT_KEY_EXPR: &str = "simulation/core/gaze_vector";
const DEFAULT_RENDER_STATE_KEY_EXPR: &str = "simulation/render/response/state";
const DEFAULT_INTERVAL_MS: u64 = 1_000;
const DEFAULT_STARTUP_DELAY_MS: u64 = 1_000;
const DEFAULT_TRANSPORT_CONFIG_RELATIVE_PATH: &str = "../../../config/transport.dev.json";
const DEFAULT_VECTOR: [f32; 3] = [0.0, 0.0, 1.0];

type DynError = Box<dyn Error + Send + Sync>;

#[derive(Debug, Clone)]
struct CliOptions {
    key_expr: String,
    transport_config_path: PathBuf,
    interval_ms: u64,
    startup_delay_ms: u64,
    max_messages: Option<usize>,
}

impl CliOptions {
    fn parse() -> Result<Self, DynError> {
        let mut key_expr = DEFAULT_KEY_EXPR.to_string();
        let mut transport_config_path = default_transport_config_path();
        let mut interval_ms = DEFAULT_INTERVAL_MS;
        let mut startup_delay_ms = DEFAULT_STARTUP_DELAY_MS;
        let mut max_messages = None;

        let mut args = env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--key-expr" => {
                    let value = args.next().ok_or("`--key-expr` には値が必要です。")?;
                    key_expr = value;
                }
                "--connect-endpoint" => {
                    return Err(
                        "`--connect-endpoint` は廃止されました。`--transport-config` を使ってください。"
                            .into(),
                    );
                }
                "--transport-config" => {
                    let value = args
                        .next()
                        .ok_or("`--transport-config` には値が必要です。")?;
                    transport_config_path = PathBuf::from(value);
                }
                "--interval-ms" => {
                    let value = args.next().ok_or("`--interval-ms` には値が必要です。")?;
                    interval_ms = value.parse()?;
                }
                "--startup-delay-ms" => {
                    let value = args
                        .next()
                        .ok_or("`--startup-delay-ms` には値が必要です。")?;
                    startup_delay_ms = value.parse()?;
                }
                "--count" => {
                    let value = args.next().ok_or("`--count` には値が必要です。")?;
                    max_messages = Some(value.parse()?);
                }
                "--help" | "-h" => {
                    print_usage();
                    std::process::exit(0);
                }
                other => {
                    return Err(format!("未知の引数です: {other}").into());
                }
            }
        }

        Ok(Self {
            key_expr,
            transport_config_path,
            interval_ms,
            startup_delay_ms,
            max_messages,
        })
    }
}

pub async fn publish_gaze_vector_loop() -> Result<(), DynError> {
    let options = CliOptions::parse()?;
    publish_gaze_vector_loop_with_options(options).await
}

async fn publish_gaze_vector_loop_with_options(options: CliOptions) -> Result<(), DynError> {
    let config = build_config(options.transport_config_path.as_path())?;
    let session = zenoh::open(config).await?;
    declare_render_state_debug_subscriber(&session).await?;
    let publisher = session.declare_publisher(options.key_expr.as_str()).await?;
    let interval = Duration::from_millis(options.interval_ms);

    if options.startup_delay_ms > 0 {
        sleep(Duration::from_millis(options.startup_delay_ms)).await;
    }

    let mut published_count = 0usize;
    loop {
        if reached_publish_limit(published_count, options.max_messages) {
            break;
        }

        let payload = build_payload(DEFAULT_VECTOR);
        publisher
            .put(payload)
            .encoding(Encoding::APPLICATION_JSON)
            .await?;

        published_count += 1;

        if reached_publish_limit(published_count, options.max_messages) {
            break;
        }

        sleep(interval).await;
    }

    Ok(())
}

async fn declare_render_state_debug_subscriber(session: &zenoh::Session) -> Result<(), DynError> {
    session
        .declare_subscriber(DEFAULT_RENDER_STATE_KEY_EXPR)
        .callback(|sample| {
            let payload = sample
                .payload()
                .try_to_string()
                .map(|value| value.into_owned())
                .unwrap_or_else(|_| format!("<non-utf8:{} bytes>", sample.payload().len()));
            let key_expr = sample.key_expr().to_string();

            println!(
                "{}",
                build_render_state_debug_line(key_expr.as_str(), payload.as_str())
            );
        })
        .background()
        .await?;

    println!("Subscribed to render state updates on `{DEFAULT_RENDER_STATE_KEY_EXPR}`",);

    Ok(())
}

fn print_usage() {
    println!("Zenoh gaze vector publisher");
    println!("Usage:");
    println!(
        "  cargo run -- [--key-expr <expr>] [--transport-config <path>] [--interval-ms <ms>] [--startup-delay-ms <ms>] [--count <n>]"
    );
    println!();
    println!("Examples:");
    println!("  cargo run --");
    println!("  cargo run -- --count 3");
    println!("  cargo run -- --transport-config config/transport.dev.json --interval-ms 500");
}

pub fn build_payload(vector: [f32; 3]) -> String {
    format!(r#"[{:.3},{:.3},{:.3}]"#, vector[0], vector[1], vector[2])
}

pub fn build_render_state_debug_line(key_expr: &str, payload: &str) -> String {
    format!("[render-state] key_expr={key_expr} payload={payload}")
}

pub fn reached_publish_limit(published_count: usize, max_messages: Option<usize>) -> bool {
    max_messages.is_some_and(|limit| published_count >= limit)
}

pub fn default_transport_config_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(DEFAULT_TRANSPORT_CONFIG_RELATIVE_PATH)
}

fn build_config(transport_config_path: &Path) -> Result<zenoh::Config, DynError> {
    let text = fs::read_to_string(transport_config_path)?;
    let root: Value = serde_json::from_str(&text)?;

    let zenoh_section = root
        .get("zenoh")
        .ok_or("transport config に `zenoh` セクションがありません。")?;

    let zenoh_text = serde_json::to_string(zenoh_section)?;
    Ok(zenoh::Config::from_json5(&zenoh_text)?)
}
