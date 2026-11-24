#![forbid(unsafe_code)]

mod commands;
mod logging;

use std::{
    io::{self, Read, Write},
    process::ExitCode,
    time::Instant,
};

use commands::{Command, Failure};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const INPUT_LIMIT: u64 = 1 << 20;

fn main() -> ExitCode {
    let started = Instant::now();
    let command = Command::parse(std::env::args_os().skip(1));
    let name = command.as_ref().map_or("invalid", |cmd| cmd.name());
    let mut log = logging::RunLog::start(name);
    let result = command.and_then(execute);
    let (code, reason) = match result {
        Ok(0) => (0, "complete"),
        Ok(code) if name == "check-geometry" => (code, "invalid_pages"),
        Ok(code) => (code, "kernel_self_check_failed"),
        Err(failure) => {
            diagnostic(failure.message());
            (failure.code(), failure.message())
        }
    };
    log.finish(code, reason, started.elapsed());
    ExitCode::from(code)
}

fn execute(command: Command) -> Result<u8, Failure> {
    let input = if command.reads_input() {
        read_input(io::stdin().lock())?
    } else {
        String::new()
    };
    let (output, code) = command.run(input)?;
    let mut stdout = io::stdout().lock();
    stdout
        .write_all(output.as_bytes())
        .and_then(|()| stdout.flush())
        .map_err(|_| Failure::Runtime("could not write stdout"))?;
    Ok(code)
}

fn read_input(input: impl Read) -> Result<String, Failure> {
    let mut bytes = Vec::new();
    input
        .take(INPUT_LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| Failure::Runtime("could not read stdin"))?;
    if bytes.len() as u64 > INPUT_LIMIT {
        return Err(Failure::Usage("stdin exceeds 1 MiB"));
    }
    String::from_utf8(bytes).map_err(|_| Failure::Usage("stdin is not valid UTF-8"))
}

fn diagnostic(message: &str) {
    let _ = writeln!(io::stderr().lock(), "revayat-comic: {message}");
}
