#[allow(dead_code)]
#[path = "../src/zenoh.rs"]
mod zenoh;

use zenoh::FrameMetadata;
use zenoh::PreviewFrameRouter;
use zenoh::TransportTopicKeyExprs;
use zenoh::build_render_camera_request_debug_line;
use zenoh::build_render_frame_metadata_debug_line;
use zenoh::build_render_frame_payload_debug_line;
use zenoh::build_render_state_debug_line;
use zenoh::build_ui_camera_command_debug_line;
use zenoh::build_ui_preview_frame_metadata_debug_line;
use zenoh::build_ui_preview_frame_payload_debug_line;
use zenoh::parse_frame_metadata_payload;
use zenoh::parse_transport_topic_key_exprs;
use zenoh::{build_payload, default_transport_config_path, reached_publish_limit};

#[test]
fn build_payload_formats_gaze_vector_as_json_array() {
    assert_eq!(build_payload([0.0, 0.0, 1.0]), "[0.000,0.000,1.000]");
}

#[test]
fn reached_publish_limit_stops_once_count_is_met() {
    assert!(!reached_publish_limit(0, Some(1)));
    assert!(reached_publish_limit(1, Some(1)));
    assert!(!reached_publish_limit(3, None));
}

#[test]
fn build_render_state_debug_line_includes_key_expr_and_payload() {
    assert_eq!(
        build_render_state_debug_line("simulation/render/response/state", r#"{"state":"Idle"}"#,),
        r#"[render-state] key_expr=simulation/render/response/state payload={"state":"Idle"}"#,
    );
}

#[test]
fn build_ui_camera_command_debug_line_includes_payload_text() {
    assert_eq!(
        build_ui_camera_command_debug_line(
            "simulation/ui/cmd/camera",
            br#"{"offset_x":0.2,"offset_y":0.0,"offset_z":0.0}"#,
        ),
        r#"[ui-camera-command] key_expr=simulation/ui/cmd/camera payload={"offset_x":0.2,"offset_y":0.0,"offset_z":0.0}"#,
    );
}

#[test]
fn build_render_camera_request_debug_line_includes_payload_text() {
    assert_eq!(
        build_render_camera_request_debug_line(
            "simulation/render/request/camera",
            br#"{"offset_x":0.2,"offset_y":0.0,"offset_z":0.0}"#,
        ),
        r#"[render-camera-request] key_expr=simulation/render/request/camera payload={"offset_x":0.2,"offset_y":0.0,"offset_z":0.0}"#,
    );
}

#[test]
fn default_transport_config_path_points_to_shared_config_file() {
    let path = default_transport_config_path();

    assert!(path.is_file());
    assert!(path.ends_with("config/transport.dev.json"));
}

#[test]
fn parse_frame_metadata_payload_reads_expected_fields() {
    let metadata = parse_frame_metadata_payload(
        r#"{"frame_id":1,"timestamp":"2026-04-08T00:00:00Z","width":4,"height":2,"stride":12,"pixel_format":"rgb8"}"#,
    )
    .expect("frame metadata should parse");

    assert_eq!(
        metadata,
        FrameMetadata {
            frame_id: 1,
            timestamp: "2026-04-08T00:00:00Z".to_string(),
            width: 4,
            height: 2,
            stride: 12,
            pixel_format: "rgb8".to_string(),
        }
    );
}

#[test]
fn build_render_frame_metadata_debug_line_includes_metadata_fields() {
    let metadata = FrameMetadata {
        frame_id: 1,
        timestamp: "2026-04-08T00:00:00Z".to_string(),
        width: 4,
        height: 2,
        stride: 12,
        pixel_format: "rgb8".to_string(),
    };

    assert_eq!(
        build_render_frame_metadata_debug_line("simulation/core/frame_metadata", &metadata),
        "[render-frame-metadata-ipc] key_expr=simulation/core/frame_metadata frame_id=1 timestamp=2026-04-08T00:00:00Z width=4 height=2 stride=12 pixel_format=rgb8",
    );
}

#[test]
fn build_render_frame_payload_debug_line_includes_size_and_preview() {
    let payload = [
        0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00,
    ];

    assert_eq!(
        build_render_frame_payload_debug_line("simulation/core/frame_payload", &payload),
        "[render-frame-payload-ipc] key_expr=simulation/core/frame_payload bytes=12 preview=ff0000ff0000ff0000ff0000",
    );
}

#[test]
fn parse_frame_metadata_payload_rejects_missing_fields() {
    let error = parse_frame_metadata_payload(r#"{"frame_id":1}"#)
        .expect_err("missing metadata fields should fail");

    assert!(error.to_string().contains("timestamp"));
}

#[test]
fn parse_transport_topic_key_exprs_reads_explicit_preview_topics() {
    let root = serde_json::json!({
        "topics": {
            "core": {
                "frame_metadata": "simulation/core/frame_metadata",
                "frame_payload": "simulation/core/frame_payload"
            },
            "render": {
                "request": "simulation/render/request/**",
                "camera_request": "simulation/render/request/camera",
                "response": "simulation/render/response/**",
                "state": "simulation/render/response/state"
            },
            "ui": {
                "command": "simulation/ui/cmd/**",
                "camera_command": "simulation/ui/cmd/camera",
                "preview": "simulation/ui/preview/**",
                "preview_metadata": "simulation/ui/preview/frame_metadata",
                "preview_payload": "simulation/ui/preview/frame_payload"
            }
        }
    });

    let key_exprs = parse_transport_topic_key_exprs(&root).expect("topic config should parse");

    assert_eq!(
        key_exprs,
        TransportTopicKeyExprs {
            ui_camera_command: "simulation/ui/cmd/camera".to_string(),
            render_camera_request: "simulation/render/request/camera".to_string(),
            render_state: "simulation/render/response/state".to_string(),
            render_frame_metadata: "simulation/core/frame_metadata".to_string(),
            render_frame_payload: "simulation/core/frame_payload".to_string(),
            ui_preview_metadata: "simulation/ui/preview/frame_metadata".to_string(),
            ui_preview_payload: "simulation/ui/preview/frame_payload".to_string(),
        }
    );
}

#[test]
fn parse_transport_topic_key_exprs_can_derive_preview_topics_from_wildcard() {
    let root = serde_json::json!({
        "topics": {
            "core": {
                "frame_metadata": "simulation/core/frame_metadata",
                "frame_payload": "simulation/core/frame_payload"
            },
            "render": {
                "request": "simulation/render/request/**",
                "response": "simulation/render/response/**"
            },
            "ui": {
                "command": "simulation/ui/cmd/**",
                "preview": "simulation/ui/preview/**"
            }
        }
    });

    let key_exprs = parse_transport_topic_key_exprs(&root).expect("topic config should parse");

    assert_eq!(key_exprs.ui_camera_command, "simulation/ui/cmd/camera");
    assert_eq!(
        key_exprs.render_camera_request,
        "simulation/render/request/camera"
    );
    assert_eq!(key_exprs.render_state, "simulation/render/response/state");
    assert_eq!(
        key_exprs.ui_preview_metadata,
        "simulation/ui/preview/frame_metadata"
    );
    assert_eq!(
        key_exprs.ui_preview_payload,
        "simulation/ui/preview/frame_payload"
    );
}

#[test]
fn preview_frame_router_pairs_payload_with_latest_metadata() {
    let metadata = FrameMetadata {
        frame_id: 1,
        timestamp: "2026-04-08T00:00:00Z".to_string(),
        width: 4,
        height: 2,
        stride: 12,
        pixel_format: "rgb8".to_string(),
    };
    let payload = vec![
        0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00,
    ];
    let mut router = PreviewFrameRouter::default();

    assert!(router.build_preview_route(&payload).is_none());

    router.store_frame_metadata(metadata.clone());
    let route = router
        .build_preview_route(&payload)
        .expect("payload should route once metadata exists");

    assert_eq!(route.metadata, metadata);
    assert_eq!(route.payload, payload);
}

#[test]
fn build_ui_preview_frame_metadata_debug_line_includes_metadata_fields() {
    let metadata = FrameMetadata {
        frame_id: 1,
        timestamp: "2026-04-08T00:00:00Z".to_string(),
        width: 4,
        height: 2,
        stride: 12,
        pixel_format: "rgb8".to_string(),
    };

    assert_eq!(
        build_ui_preview_frame_metadata_debug_line(
            "simulation/ui/preview/frame_metadata",
            &metadata,
        ),
        "[ui-preview-metadata] key_expr=simulation/ui/preview/frame_metadata frame_id=1 timestamp=2026-04-08T00:00:00Z width=4 height=2 stride=12 pixel_format=rgb8",
    );
}

#[test]
fn build_ui_preview_frame_payload_debug_line_includes_size_and_preview() {
    let payload = [
        0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00,
    ];

    assert_eq!(
        build_ui_preview_frame_payload_debug_line("simulation/ui/preview/frame_payload", &payload,),
        "[ui-preview-payload] key_expr=simulation/ui/preview/frame_payload bytes=12 preview=ff0000ff0000ff0000ff0000",
    );
}
