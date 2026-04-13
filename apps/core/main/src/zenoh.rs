use std::{
    env,
    error::Error,
    fs, io,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::Duration,
};

use serde_json::Value;
use tokio::time::sleep;
use zenoh::Wait;
use zenoh::bytes::Encoding;

const DEFAULT_KEY_EXPR: &str = "simulation/core/gaze_vector";
const DEFAULT_RENDER_STATE_KEY_EXPR: &str = "simulation/render/response/state";
const DEFAULT_RENDER_REQUEST_KEY_EXPR: &str = "simulation/render/request/camera";
const DEFAULT_FRAME_METADATA_KEY_EXPR: &str = "simulation/core/frame_metadata";
const DEFAULT_FRAME_PAYLOAD_KEY_EXPR: &str = "simulation/core/frame_payload";
const DEFAULT_UI_COMMAND_KEY_EXPR: &str = "simulation/ui/cmd/camera";
const DEFAULT_UI_PREVIEW_KEY_EXPR: &str = "simulation/ui/preview/**";
const DEFAULT_UI_PREVIEW_METADATA_KEY_EXPR: &str = "simulation/ui/preview/frame_metadata";
const DEFAULT_UI_PREVIEW_PAYLOAD_KEY_EXPR: &str = "simulation/ui/preview/frame_payload";
const DEFAULT_INTERVAL_MS: u64 = 1_000;
const DEFAULT_STARTUP_DELAY_MS: u64 = 1_000;
const DEFAULT_TRANSPORT_CONFIG_RELATIVE_PATH: &str = "../../../config/transport.dev.json";
const DEFAULT_VECTOR: [f32; 3] = [0.0, 0.0, 1.0];
const PAYLOAD_PREVIEW_BYTES: usize = 12;

type DynError = Box<dyn Error + Send + Sync>;

#[derive(Debug, Clone)]
struct CliOptions {
    key_expr: String,
    transport_config_path: PathBuf,
    interval_ms: u64,
    startup_delay_ms: u64,
    max_messages: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrameMetadata {
    pub frame_id: u64,
    pub timestamp: String,
    pub width: u64,
    pub height: u64,
    pub stride: u64,
    pub pixel_format: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransportTopicKeyExprs {
    pub ui_camera_command: String,
    pub render_camera_request: String,
    pub render_state: String,
    pub render_frame_metadata: String,
    pub render_frame_payload: String,
    pub ui_preview_metadata: String,
    pub ui_preview_payload: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreviewFrameRoute {
    pub metadata: FrameMetadata,
    pub payload: Vec<u8>,
}

#[derive(Debug, Default)]
pub struct PreviewFrameRouter {
    last_frame_metadata: Option<FrameMetadata>,
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

impl PreviewFrameRouter {
    pub fn store_frame_metadata(&mut self, metadata: FrameMetadata) {
        self.last_frame_metadata = Some(metadata);
    }

    pub fn build_preview_route(&self, payload: &[u8]) -> Option<PreviewFrameRoute> {
        // Payloads do not yet include a frame identifier, so routing uses the latest metadata.
        self.last_frame_metadata
            .clone()
            .map(|metadata| PreviewFrameRoute {
                metadata,
                payload: payload.to_vec(),
            })
    }
}

pub async fn publish_gaze_vector_loop() -> Result<(), DynError> {
    let options = CliOptions::parse()?;
    publish_gaze_vector_loop_with_options(options).await
}

async fn publish_gaze_vector_loop_with_options(options: CliOptions) -> Result<(), DynError> {
    let transport_config = load_transport_config(options.transport_config_path.as_path())?;
    let config = build_config_from_transport_config(&transport_config)?;
    let topic_key_exprs = parse_transport_topic_key_exprs(&transport_config)?;
    let session = zenoh::open(config).await?;
    declare_render_state_debug_subscriber(&session, topic_key_exprs.render_state.as_str()).await?;
    subscribe_preview_frame_ipc(&session, &topic_key_exprs).await?;
    subscribe_ui_camera_commands(&session, &topic_key_exprs).await?;
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

async fn subscribe_preview_frame_ipc(
    session: &zenoh::Session,
    topic_key_exprs: &TransportTopicKeyExprs,
) -> Result<(), DynError> {
    let preview_router = Arc::new(Mutex::new(PreviewFrameRouter::default()));
    declare_frame_metadata_ipc_subscriber(
        session,
        topic_key_exprs.render_frame_metadata.as_str(),
        preview_router.clone(),
    )
    .await?;
    declare_frame_payload_ipc_subscriber(
        session,
        topic_key_exprs.render_frame_payload.as_str(),
        preview_router,
        session.clone(),
        topic_key_exprs.clone(),
    )
    .await?;
    Ok(())
}

async fn subscribe_ui_camera_commands(
    session: &zenoh::Session,
    topic_key_exprs: &TransportTopicKeyExprs,
) -> Result<(), DynError> {
    let session_for_render_request = session.clone();
    let render_camera_request_key_expr = topic_key_exprs.render_camera_request.clone();
    let ui_camera_command_key_expr = topic_key_exprs.ui_camera_command.clone();

    session
        .declare_subscriber(ui_camera_command_key_expr.as_str())
        .callback(move |sample| {
            let key_expr = sample.key_expr().to_string();
            let payload_bytes = sample.payload().to_bytes();

            println!(
                "{}",
                build_ui_camera_command_debug_line(key_expr.as_str(), payload_bytes.as_ref())
            );

            if let Err(error) = publish_render_camera_request(
                &session_for_render_request,
                render_camera_request_key_expr.as_str(),
                payload_bytes.as_ref(),
            ) {
                eprintln!(
                    "[render-camera-request-route] key_expr={} error={error}",
                    render_camera_request_key_expr.as_str()
                );
                return;
            }

            println!(
                "{}",
                build_render_camera_request_debug_line(
                    render_camera_request_key_expr.as_str(),
                    payload_bytes.as_ref(),
                )
            );
        })
        .background()
        .await?;

    println!("Subscribed to UI camera commands on `{ui_camera_command_key_expr}`");

    Ok(())
}

async fn declare_render_state_debug_subscriber(
    session: &zenoh::Session,
    render_state_key_expr: &str,
) -> Result<(), DynError> {
    session
        .declare_subscriber(render_state_key_expr)
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

    println!("Subscribed to render state updates on `{render_state_key_expr}`");

    Ok(())
}

async fn declare_frame_metadata_ipc_subscriber(
    session: &zenoh::Session,
    render_frame_metadata_key_expr: &str,
    preview_router: Arc<Mutex<PreviewFrameRouter>>,
) -> Result<(), DynError> {
    session
        .declare_subscriber(render_frame_metadata_key_expr)
        .callback(move |sample| {
            let key_expr = sample.key_expr().to_string();
            let payload = sample.payload();
            let payload_text = match payload.try_to_string() {
                Ok(value) => value.into_owned(),
                Err(_) => {
                    eprintln!(
                        "[render-frame-metadata-ipc] key_expr={key_expr} error=payload is not valid UTF-8"
                    );
                    return;
                }
            };

            match parse_frame_metadata_payload(payload_text.as_str()) {
                Ok(metadata) => {
                    println!(
                        "{}",
                        build_render_frame_metadata_debug_line(key_expr.as_str(), &metadata)
                    );
                    preview_router
                        .lock()
                        .expect("preview router mutex should not be poisoned")
                        .store_frame_metadata(metadata);
                }
                Err(error) => eprintln!(
                    "[render-frame-metadata-ipc] key_expr={key_expr} error={error}"
                ),
            }
        })
        .background()
        .await?;

    println!("Subscribed to render frame metadata IPC on `{render_frame_metadata_key_expr}`");

    Ok(())
}

async fn declare_frame_payload_ipc_subscriber(
    session: &zenoh::Session,
    render_frame_payload_key_expr: &str,
    preview_router: Arc<Mutex<PreviewFrameRouter>>,
    session_for_preview_publish: zenoh::Session,
    topic_key_exprs: TransportTopicKeyExprs,
) -> Result<(), DynError> {
    session
        .declare_subscriber(render_frame_payload_key_expr)
        .callback(move |sample| {
            let key_expr = sample.key_expr().to_string();
            let payload_bytes = sample.payload().to_bytes();

            println!(
                "{}",
                build_render_frame_payload_debug_line(key_expr.as_str(), payload_bytes.as_ref())
            );

            let preview_route = preview_router
                .lock()
                .expect("preview router mutex should not be poisoned")
                .build_preview_route(payload_bytes.as_ref());

            let Some(preview_route) = preview_route else {
                eprintln!(
                    "[ui-preview-route] key_expr={} error=frame payload arrived before metadata",
                    topic_key_exprs.ui_preview_payload.as_str()
                );
                return;
            };

            if let Err(error) = publish_preview_frame(
                &session_for_preview_publish,
                &topic_key_exprs,
                &preview_route,
            ) {
                eprintln!(
                    "[ui-preview-route] key_expr={} error={error}",
                    topic_key_exprs.ui_preview_payload.as_str()
                );
                return;
            }

            println!(
                "{}",
                build_ui_preview_frame_metadata_debug_line(
                    topic_key_exprs.ui_preview_metadata.as_str(),
                    &preview_route.metadata,
                )
            );
            println!(
                "{}",
                build_ui_preview_frame_payload_debug_line(
                    topic_key_exprs.ui_preview_payload.as_str(),
                    preview_route.payload.as_slice(),
                )
            );
        })
        .background()
        .await?;

    println!("Subscribed to render frame payload IPC on `{render_frame_payload_key_expr}`");

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

pub fn build_ui_camera_command_debug_line(key_expr: &str, payload: &[u8]) -> String {
    format!(
        "[ui-camera-command] key_expr={key_expr} payload={}",
        String::from_utf8_lossy(payload)
    )
}

pub fn build_render_camera_request_debug_line(key_expr: &str, payload: &[u8]) -> String {
    format!(
        "[render-camera-request] key_expr={key_expr} payload={}",
        String::from_utf8_lossy(payload)
    )
}

pub fn parse_frame_metadata_payload(payload: &str) -> Result<FrameMetadata, DynError> {
    let root: Value = serde_json::from_str(payload)?;

    Ok(FrameMetadata {
        frame_id: required_u64_field(&root, "frame_id")?,
        timestamp: required_string_field(&root, "timestamp")?.to_string(),
        width: required_u64_field(&root, "width")?,
        height: required_u64_field(&root, "height")?,
        stride: required_u64_field(&root, "stride")?,
        pixel_format: required_string_field(&root, "pixel_format")?.to_string(),
    })
}

pub fn build_render_frame_metadata_debug_line(key_expr: &str, metadata: &FrameMetadata) -> String {
    format!(
        "[render-frame-metadata-ipc] key_expr={key_expr} frame_id={} timestamp={} width={} height={} stride={} pixel_format={}",
        metadata.frame_id,
        metadata.timestamp,
        metadata.width,
        metadata.height,
        metadata.stride,
        metadata.pixel_format,
    )
}

pub fn build_render_frame_payload_debug_line(key_expr: &str, payload: &[u8]) -> String {
    format!(
        "[render-frame-payload-ipc] key_expr={key_expr} bytes={} preview={}",
        payload.len(),
        build_payload_preview(payload),
    )
}

pub fn build_ui_preview_frame_metadata_debug_line(
    key_expr: &str,
    metadata: &FrameMetadata,
) -> String {
    format!(
        "[ui-preview-metadata] key_expr={key_expr} frame_id={} timestamp={} width={} height={} stride={} pixel_format={}",
        metadata.frame_id,
        metadata.timestamp,
        metadata.width,
        metadata.height,
        metadata.stride,
        metadata.pixel_format,
    )
}

pub fn build_ui_preview_frame_payload_debug_line(key_expr: &str, payload: &[u8]) -> String {
    format!(
        "[ui-preview-payload] key_expr={key_expr} bytes={} preview={}",
        payload.len(),
        build_payload_preview(payload),
    )
}

pub fn reached_publish_limit(published_count: usize, max_messages: Option<usize>) -> bool {
    max_messages.is_some_and(|limit| published_count >= limit)
}

pub fn default_transport_config_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(DEFAULT_TRANSPORT_CONFIG_RELATIVE_PATH)
}

fn load_transport_config(transport_config_path: &Path) -> Result<Value, DynError> {
    let text = fs::read_to_string(transport_config_path)?;
    Ok(serde_json::from_str(&text)?)
}

fn build_config_from_transport_config(root: &Value) -> Result<zenoh::Config, DynError> {
    let zenoh_section = root
        .get("zenoh")
        .ok_or("transport config に `zenoh` セクションがありません。")?;

    let zenoh_text = serde_json::to_string(zenoh_section)?;
    Ok(zenoh::Config::from_json5(&zenoh_text)?)
}

pub fn parse_transport_topic_key_exprs(root: &Value) -> Result<TransportTopicKeyExprs, DynError> {
    let topics = required_object_field(root, "topics")?;
    let core_topics = required_object_member(topics, "core", "topics.core")?;
    let render_topics = required_object_member(topics, "render", "topics.render")?;
    let ui_topics = required_object_member(topics, "ui", "topics.ui")?;

    Ok(TransportTopicKeyExprs {
        ui_camera_command: resolve_ui_command_key_expr(ui_topics)?,
        render_camera_request: resolve_render_request_key_expr(render_topics)?,
        render_state: resolve_render_state_key_expr(render_topics)?,
        render_frame_metadata: core_topics
            .get("frame_metadata")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .unwrap_or(DEFAULT_FRAME_METADATA_KEY_EXPR)
            .to_string(),
        render_frame_payload: core_topics
            .get("frame_payload")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .unwrap_or(DEFAULT_FRAME_PAYLOAD_KEY_EXPR)
            .to_string(),
        ui_preview_metadata: resolve_ui_preview_key_expr(
            ui_topics,
            "preview_metadata",
            DEFAULT_UI_PREVIEW_METADATA_KEY_EXPR,
            "frame_metadata",
        )?,
        ui_preview_payload: resolve_ui_preview_key_expr(
            ui_topics,
            "preview_payload",
            DEFAULT_UI_PREVIEW_PAYLOAD_KEY_EXPR,
            "frame_payload",
        )?,
    })
}

fn publish_render_camera_request(
    session: &zenoh::Session,
    render_camera_request_key_expr: &str,
    payload: &[u8],
) -> Result<(), DynError> {
    session
        .put(render_camera_request_key_expr, payload.to_vec())
        .encoding(Encoding::APPLICATION_JSON)
        .wait()?;

    Ok(())
}

fn publish_preview_frame(
    session: &zenoh::Session,
    topic_key_exprs: &TransportTopicKeyExprs,
    preview_route: &PreviewFrameRoute,
) -> Result<(), DynError> {
    session
        .put(
            topic_key_exprs.ui_preview_metadata.as_str(),
            serialize_frame_metadata(&preview_route.metadata),
        )
        .encoding(Encoding::APPLICATION_JSON)
        .wait()?;
    session
        .put(
            topic_key_exprs.ui_preview_payload.as_str(),
            preview_route.payload.clone(),
        )
        .encoding(Encoding::APPLICATION_OCTET_STREAM)
        .wait()?;

    Ok(())
}

fn serialize_frame_metadata(metadata: &FrameMetadata) -> String {
    serde_json::json!({
        "frame_id": metadata.frame_id,
        "timestamp": metadata.timestamp,
        "width": metadata.width,
        "height": metadata.height,
        "stride": metadata.stride,
        "pixel_format": metadata.pixel_format,
    })
    .to_string()
}

fn required_u64_field(root: &Value, field_name: &str) -> Result<u64, DynError> {
    root.get(field_name).and_then(Value::as_u64).ok_or_else(|| {
        invalid_data_error(format!(
            "frame metadata `{field_name}` must be a non-negative integer"
        ))
    })
}

fn required_object_field<'a>(
    root: &'a Value,
    field_name: &str,
) -> Result<&'a serde_json::Map<String, Value>, DynError> {
    root.get(field_name)
        .and_then(Value::as_object)
        .ok_or_else(|| {
            invalid_data_error(format!("transport config `{field_name}` must be an object"))
        })
}

fn required_object_member<'a>(
    root: &'a serde_json::Map<String, Value>,
    field_name: &str,
    path: &str,
) -> Result<&'a serde_json::Map<String, Value>, DynError> {
    root.get(field_name)
        .and_then(Value::as_object)
        .ok_or_else(|| invalid_data_error(format!("transport config `{path}` must be an object")))
}

fn resolve_render_state_key_expr(
    render_topics: &serde_json::Map<String, Value>,
) -> Result<String, DynError> {
    if let Some(value) = render_topics.get("state").and_then(Value::as_str) {
        if !value.is_empty() {
            return Ok(value.to_string());
        }
    }

    let Some(response_key_expr) = render_topics.get("response").and_then(Value::as_str) else {
        return Ok(DEFAULT_RENDER_STATE_KEY_EXPR.to_string());
    };
    if response_key_expr.is_empty() {
        return Ok(DEFAULT_RENDER_STATE_KEY_EXPR.to_string());
    }
    if !response_key_expr.ends_with("/**") {
        return Err(invalid_data_error(
            "transport config `topics.render.state` must be configured when `topics.render.response` is not a wildcard"
                .to_string(),
        ));
    }

    Ok(format!(
        "{}/state",
        &response_key_expr[..response_key_expr.len() - 3]
    ))
}

fn resolve_render_request_key_expr(
    render_topics: &serde_json::Map<String, Value>,
) -> Result<String, DynError> {
    if let Some(value) = render_topics.get("camera_request").and_then(Value::as_str) {
        if !value.is_empty() {
            return Ok(value.to_string());
        }
    }

    let request_key_expr = render_topics
        .get("request")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .unwrap_or("simulation/render/request/**");
    if !request_key_expr.ends_with("/**") {
        return Err(invalid_data_error(
            "transport config `topics.render.camera_request` must be configured when `topics.render.request` is not a wildcard"
                .to_string(),
        ));
    }

    if request_key_expr == "simulation/render/request/**" {
        return Ok(DEFAULT_RENDER_REQUEST_KEY_EXPR.to_string());
    }

    Ok(format!(
        "{}/camera",
        &request_key_expr[..request_key_expr.len() - 3]
    ))
}

fn resolve_ui_preview_key_expr(
    ui_topics: &serde_json::Map<String, Value>,
    exact_field_name: &str,
    default_key_expr: &str,
    suffix: &str,
) -> Result<String, DynError> {
    if let Some(value) = ui_topics.get(exact_field_name).and_then(Value::as_str) {
        if !value.is_empty() {
            return Ok(value.to_string());
        }
    }

    let preview_key_expr = ui_topics
        .get("preview")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .unwrap_or(DEFAULT_UI_PREVIEW_KEY_EXPR);
    if !preview_key_expr.ends_with("/**") {
        return Err(invalid_data_error(
            "transport config `topics.ui.preview` must be a wildcard when exact preview topics are omitted"
                .to_string(),
        ));
    }

    if preview_key_expr == DEFAULT_UI_PREVIEW_KEY_EXPR {
        return Ok(default_key_expr.to_string());
    }

    Ok(format!(
        "{}/{}",
        &preview_key_expr[..preview_key_expr.len() - 3],
        suffix
    ))
}

fn resolve_ui_command_key_expr(
    ui_topics: &serde_json::Map<String, Value>,
) -> Result<String, DynError> {
    if let Some(value) = ui_topics.get("camera_command").and_then(Value::as_str) {
        if !value.is_empty() {
            return Ok(value.to_string());
        }
    }

    let command_key_expr = ui_topics
        .get("command")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .unwrap_or("simulation/ui/cmd/**");
    if !command_key_expr.ends_with("/**") {
        return Err(invalid_data_error(
            "transport config `topics.ui.camera_command` must be configured when `topics.ui.command` is not a wildcard"
                .to_string(),
        ));
    }

    if command_key_expr == "simulation/ui/cmd/**" {
        return Ok(DEFAULT_UI_COMMAND_KEY_EXPR.to_string());
    }

    Ok(format!(
        "{}/camera",
        &command_key_expr[..command_key_expr.len() - 3]
    ))
}

fn required_string_field<'a>(root: &'a Value, field_name: &str) -> Result<&'a str, DynError> {
    let value = root
        .get(field_name)
        .and_then(Value::as_str)
        .ok_or_else(|| {
            invalid_data_error(format!("frame metadata `{field_name}` must be a string"))
        })?;

    if value.is_empty() {
        return Err(invalid_data_error(format!(
            "frame metadata `{field_name}` must not be empty"
        )));
    }

    Ok(value)
}

fn build_payload_preview(payload: &[u8]) -> String {
    if payload.is_empty() {
        return "<empty>".to_string();
    }

    payload
        .iter()
        .take(PAYLOAD_PREVIEW_BYTES)
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn invalid_data_error(message: String) -> DynError {
    Box::new(io::Error::new(io::ErrorKind::InvalidData, message))
}
