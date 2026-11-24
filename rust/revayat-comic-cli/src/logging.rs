use std::{
    fs::{DirBuilder, File, OpenOptions},
    io::{self, Write},
    time::Duration,
};

use time::OffsetDateTime;

use crate::{VERSION, diagnostic};

pub struct RunLog {
    file: Option<File>,
    id: String,
    command: &'static str,
}

impl RunLog {
    pub fn start(command: &'static str) -> Self {
        let now = OffsetDateTime::now_utc();
        let mut log = Self {
            file: None,
            id: String::new(),
            command,
        };
        match open_log(now) {
            Ok((file, id)) => {
                log.file = Some(file);
                log.id = id;
                log.record(
                    now,
                    "INFO",
                    "Start",
                    format_args!(
                        "state=start os={} pid={}",
                        std::env::consts::OS,
                        std::process::id()
                    ),
                );
            }
            Err(_) => diagnostic("file logging unavailable; diagnostics use stderr"),
        }
        log
    }

    pub fn finish(&mut self, code: u8, reason: &'static str, elapsed: Duration) {
        self.record(
            OffsetDateTime::now_utc(),
            if code == 0 { "INFO" } else { "ERROR" },
            "Finish",
            format_args!(
                "state=finish exit={code} duration_ms={} result={reason:?}",
                elapsed.as_millis()
            ),
        );
    }

    fn record(
        &mut self,
        now: OffsetDateTime,
        level: &str,
        message: &str,
        context: std::fmt::Arguments<'_>,
    ) {
        // Only fixed command labels and internal metadata reach this writer.
        if let Some(file) = &mut self.file
            && writeln!(
                file,
                "[{} {:02}:{:02}:{:02} UTC] [{level}] [revayat-comic] {message}, command={} version={VERSION} run_id={} {context}",
                now.date(), now.hour(), now.minute(), now.second(), self.command, self.id
            )
            .and_then(|()| file.flush())
            .is_err()
        {
            self.file = None;
            diagnostic("file logging failed; diagnostics use stderr");
        }
    }
}

fn open_log(now: OffsetDateTime) -> io::Result<(File, String)> {
    let exe = std::env::current_exe()?;
    let dir = exe
        .parent()
        .ok_or_else(|| io::Error::other("no executable directory"))?;
    let base = if dir.file_name().is_some_and(|name| name == "bin") {
        dir.parent()
            .ok_or_else(|| io::Error::other("no installation directory"))?
    } else {
        dir
    };
    let logs = base.join("logs");
    let mut directories = DirBuilder::new();
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
        directories.mode(0o700);
        options.mode(0o600);
    }
    directories.recursive(true).create(&logs)?;
    options.write(true).create_new(true);

    let timestamp = format!(
        "{}_{:02}-{:02}-{:02}_UTC",
        now.date(),
        now.hour(),
        now.minute(),
        now.second()
    );
    for suffix in 0_u64.. {
        let id = if suffix == 0 {
            timestamp.clone()
        } else {
            format!("{timestamp}_{suffix:02}")
        };
        match options.open(logs.join(format!("revayat-comic_{id}.log"))) {
            Ok(file) => return Ok((file, id)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => (),
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::other("no available log name"))
}
