use rand::RngCore;
use std::{
    fs,
    net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener},
    path::PathBuf,
    sync::Mutex,
    time::Duration,
};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

struct SidecarState(Mutex<Option<CommandChild>>);

fn reserve_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind(SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0))
        .map_err(|error| format!("Could not reserve a loopback port: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("Could not inspect the loopback port: {error}"))
}

fn random_token() -> String {
    let mut bytes = [0_u8; 32];
    rand::rng().fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn prepare_runtime_data(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Could not resolve application data directory: {error}"))?;
    for path in [
        root.join("uploads"),
        root.join("experiment-artifacts"),
        root.join("source-cache"),
        root.join("exports"),
        root.join("tmp"),
    ] {
        fs::create_dir_all(path)
            .map_err(|error| format!("Could not create application data directory: {error}"))?;
    }
    Ok(root)
}

async fn wait_until_ready(base_url: &str, token: &str) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_millis(400))
        .timeout(Duration::from_secs(1))
        .build()
        .map_err(|error| error.to_string())?;
    // Frozen scientific dependencies can initialize slowly on low-memory
    // Windows machines, so retain short probes with a bounded startup window.
    for _ in 0..480 {
        if let Ok(response) = client
            .get(format!("{base_url}/api/health"))
            .bearer_auth(token)
            .send()
            .await
        {
            if response.status().is_success() {
                return Ok(());
            }
        }
        tokio_sleep(Duration::from_millis(250)).await;
    }
    Err("The Python sidecar did not become ready within 120 seconds".into())
}

async fn tokio_sleep(duration: Duration) {
    // Tauri's async runtime re-exports a runtime-neutral sleep helper.
    tauri::async_runtime::spawn_blocking(move || std::thread::sleep(duration))
        .await
        .ok();
}

fn stop_sidecar(app: &tauri::AppHandle) {
    if let Some(child) = app
        .state::<SidecarState>()
        .0
        .lock()
        .ok()
        .and_then(|mut child| child.take())
    {
        let _ = child.kill();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            let port = reserve_loopback_port().map_err(std::io::Error::other)?;
            let token = random_token();
            let base_url = format!("http://127.0.0.1:{port}");
            let data_root =
                prepare_runtime_data(app.handle()).map_err(std::io::Error::other)?;
            let sidecar = app
                .shell()
                .sidecar("research-agent-python")?
                .args(vec![
                    "--host".to_string(),
                    "127.0.0.1".to_string(),
                    "--port".to_string(),
                    port.to_string(),
                ])
                .env("RESEARCH_AGENT_IPC_TOKEN", &token)
                .env("RESEARCH_AGENT_DESKTOP", "1")
                .env("DATABASE_PATH", data_root.join("research_agent.sqlite3"))
                .env("UPLOAD_PATH", data_root.join("uploads"))
                .env(
                    "EXPERIMENT_ARTIFACT_PATH",
                    data_root.join("experiment-artifacts"),
                )
                .env("LITERATURE_CACHE_PATH", data_root.join("source-cache"))
                .env("EXPORT_PATH", data_root.join("exports"))
                // Keep Python/native-library temporary work off a constrained
                // system drive and beside the persistent application data.
                .env("TMP", data_root.join("tmp"))
                .env("TEMP", data_root.join("tmp"));
            let (mut events, child) = sidecar.spawn()?;
            *app.state::<SidecarState>().0.lock().expect("sidecar state lock poisoned") = Some(child);

            let ipc_json = serde_json::json!({ "baseUrl": base_url, "token": token });
            let init_script = format!(
                "Object.defineProperty(window,'__RESEARCH_AGENT_IPC__',{{value:{ipc_json},writable:false,configurable:false}});"
            );
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Research Agent")
                .inner_size(1280.0, 820.0)
                .min_inner_size(900.0, 620.0)
                .visible(false)
                .initialization_script(&init_script)
                .build()?;

            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let ready = wait_until_ready(&base_url, &token).await;
                if ready.is_ok() {
                    let _ = window.show();
                    let _ = window.set_focus();
                } else {
                    stop_sidecar(&app_handle);
                    let message = ready.unwrap_err();
                    eprintln!("Sidecar startup failed: {message}");
                    let _ = window.show();
                    let _ = window.eval(&format!(
                        "window.dispatchEvent(new CustomEvent('sidecar-error',{{detail:{}}}))",
                        serde_json::to_string(&message).unwrap_or_else(|_| "\"Sidecar failed\"".into())
                    ));
                }
            });

            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stderr(bytes) => eprintln!("sidecar: {}", String::from_utf8_lossy(&bytes)),
                        CommandEvent::Error(error) => eprintln!("sidecar process error: {error}"),
                        CommandEvent::Terminated(status) => eprintln!("sidecar exited: {status:?}"),
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Research Agent desktop shell");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_sidecar(app_handle);
        }
    });
}
