use std::sync::Once;

use tracing_subscriber::EnvFilter;

static TRACING_INIT: Once = Once::new();

/// 初始化全局 tracing 日志，仅第一次调用生效。
/// 默认输出到 stdout，可通过 RUST_LOG 调整日志级别过滤。
pub fn init_tracing(node_name: &str) {
    TRACING_INIT.call_once(|| {
        let env_filter =
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
        let _ = tracing_subscriber::fmt()
            .with_env_filter(env_filter)
            .with_writer(std::io::stdout)
            .with_target(false)
            .try_init();
    });

    tracing::info!(node = node_name, "tracing logger initialized");
}
