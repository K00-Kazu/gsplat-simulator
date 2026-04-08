use std::{env, error::Error, time::Duration};

use tokio::time::sleep;
use zenoh::bytes::Encoding;

const DEFAULT_KEY_EXPR: &str = "simulation/core/gaze_vector";
const DEFAULT_CONNECT_ENDPOINT: &str = "tcp/127.0.0.1:7447";
const DEFAULT_INTERVAL_MS: u64 = 1_000;
const DEFAULT_STARTUP_DELAY_MS: u64 = 1_000;
const DEFAULT_VECTOR: [f32; 3] = [0.0, 0.0, 1.0];
type DynError = Box<dyn Error + Send + Sync>;

#[derive(Debug, Clone)]
struct CliOptions {
    key_expr: String,
    connect_endpoint: String,
    interval_ms: u64,
    startup_delay_ms: u64,
    max_messages: Option<usize>,
}

impl CliOptions {
    fn parse() -> Result<Self, DynError> {
        let mut key_expr = DEFAULT_KEY_EXPR.to_string();
        let mut connect_endpoint = DEFAULT_CONNECT_ENDPOINT.to_string();
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
                    let value = args
                        .next()
                        .ok_or("`--connect-endpoint` には値が必要です。")?;
                    connect_endpoint = value;
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
            connect_endpoint,
            interval_ms,
            startup_delay_ms,
            max_messages,
        })
    }
}

fn print_usage() {
    println!("Zenoh gaze vector publisher");
    println!("Usage:");
    println!(
        "  cargo run -- [--key-expr <expr>] [--connect-endpoint <endpoint>] [--interval-ms <ms>] [--startup-delay-ms <ms>] [--count <n>]"
    );
    println!();
    println!("Examples:");
    println!("  cargo run --");
    println!("  cargo run -- --count 3");
    println!("  cargo run -- --connect-endpoint tcp/127.0.0.1:7447 --interval-ms 500");
}

fn build_payload(sequence: usize) -> String {
    format!(
        r#"{{"sequence":{sequence},"vector":[{:.3},{:.3},{:.3}]}}"#,
        DEFAULT_VECTOR[0], DEFAULT_VECTOR[1], DEFAULT_VECTOR[2]
    )
}

fn build_config(connect_endpoint: &str) -> Result<zenoh::Config, DynError> {
    let mut config = zenoh::Config::default();
    let endpoints_json = format!(r#"["{connect_endpoint}"]"#);

    config.insert_json5("scouting/multicast/enabled", "false")?;
    config.insert_json5("connect/endpoints", endpoints_json.as_str())?;

    Ok(config)
}

#[tokio::main]
async fn main() -> Result<(), DynError> {
    let options = CliOptions::parse()?;
    let config = build_config(options.connect_endpoint.as_str())?;

    println!("Opening Zenoh session...");
    let session = zenoh::open(config).await?;
    println!(
        "Publishing gaze vectors on `{}` via `{}` (interval={}ms, startup_delay={}ms, count={})",
        options.key_expr,
        options.connect_endpoint,
        options.interval_ms,
        options.startup_delay_ms,
        options
            .max_messages
            .map(|count| count.to_string())
            .unwrap_or_else(|| "infinite".to_string())
    );

    if options.startup_delay_ms > 0 {
        println!(
            "Waiting {}ms for subscriber setup...",
            options.startup_delay_ms
        );
        sleep(Duration::from_millis(options.startup_delay_ms)).await;
    }

    let mut sequence = 0usize;

    loop {
        sequence += 1;
        let payload = build_payload(sequence);

        session
            .put(options.key_expr.as_str(), payload.as_str())
            .encoding(Encoding::APPLICATION_JSON)
            .await?;

        println!("Published: {payload}");

        if let Some(max_messages) = options.max_messages {
            if sequence >= max_messages {
                break;
            }
        }

        tokio::select! {
            _ = sleep(Duration::from_millis(options.interval_ms)) => {}
            _ = tokio::signal::ctrl_c() => {
                println!("Stopping publisher.");
                break;
            }
        }
    }

    session.close().await?;
    println!("Zenoh session closed.");
    Ok(())
}
