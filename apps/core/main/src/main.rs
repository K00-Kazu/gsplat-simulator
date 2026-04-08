mod zenoh;

use std::{any::Any, error::Error, io, thread};

type DynError = Box<dyn Error + Send + Sync>;

#[tokio::main]
async fn main() -> Result<(), DynError> {
    run_program().await
}

async fn run_program() -> Result<(), DynError> {
    let render_loop_handle = thread::Builder::new()
        .name("run_render_loop".to_string())
        .spawn(|| -> Result<(), DynError> {
            let runtime = build_render_loop_runtime()?;
            runtime.block_on(run_render_loop())
        })?;

    match render_loop_handle.join() {
        Ok(result) => result,
        Err(panic) => Err(thread_panic_error(panic)),
    }
}

async fn run_render_loop() -> Result<(), DynError> {
    zenoh::publish_gaze_vector_loop().await
}

fn build_render_loop_runtime() -> io::Result<tokio::runtime::Runtime> {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()
}

fn thread_panic_error(panic: Box<dyn Any + Send + 'static>) -> DynError {
    let message = if let Some(message) = panic.downcast_ref::<&str>() {
        format!("run_render_loop thread panicked: {message}")
    } else if let Some(message) = panic.downcast_ref::<String>() {
        format!("run_render_loop thread panicked: {message}")
    } else {
        "run_render_loop thread panicked".to_string()
    };

    Box::new(io::Error::other(message))
}

#[cfg(test)]
mod tests {
    use super::build_render_loop_runtime;

    #[test]
    fn render_loop_runtime_uses_multi_thread_scheduler() {
        let runtime = build_render_loop_runtime().expect("runtime should build");

        runtime.block_on(async {
            assert_eq!(
                tokio::runtime::Handle::current().runtime_flavor(),
                tokio::runtime::RuntimeFlavor::MultiThread
            );
        });
    }
}
