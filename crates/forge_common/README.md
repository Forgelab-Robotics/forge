# forge_common

Shared Rust utilities for Forge crates.

This crate is intentionally lightweight. It currently provides tracing
initialization helpers and may grow to include other cross-crate utilities as
Forge evolves.

## Tracing Usage

```rust
use forge_common::logger::init_tracing;

fn main() {
    init_tracing("my-node");
}
```

`init_tracing` initializes global tracing once and uses `RUST_LOG` for log level
filtering when it is set.

## Testing

Run the crate tests from the workspace root:

```bash
cargo test -p forge_common
```
