// Mangaka Android shell. All state lives in the WebView (localStorage)
// and the host exposes one read-only command. There is no filesystem,
// network, shell or installer permission in Rust: the WebView fetches
// the public reader API directly (CSP connect-src). The app id comes
// from tauri.conf.json at build time (see build.rs).
#[tauri::command]
fn awai_host_info() -> serde_json::Value {
    serde_json::json!({"schema": "awai.shell.host.v1", "app": env!("ITONAMI_APP_ID")})
}
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .runtime(tauri_runtime_wry::Wry::default())
        .invoke_handler(tauri::generate_handler![awai_host_info])
        .run(tauri::generate_context!())
        .expect("mangaka app failed to start");
}
