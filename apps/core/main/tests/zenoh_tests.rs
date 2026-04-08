#[allow(dead_code)]
#[path = "../src/zenoh.rs"]
mod zenoh;

use zenoh::build_render_state_debug_line;
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
fn default_transport_config_path_points_to_shared_config_file() {
    let path = default_transport_config_path();

    assert!(path.is_file());
    assert!(path.ends_with("config/transport.dev.json5"));
}
