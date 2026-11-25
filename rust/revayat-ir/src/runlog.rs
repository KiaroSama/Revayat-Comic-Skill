use crate::{IrError, matcher};
use regex::Regex;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use time::{OffsetDateTime, macros::format_description};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum Level {
    Debug,
    Info,
    Warning,
    Error,
    Critical,
}
impl Level {
    fn name(self) -> &'static str {
        match self {
            Self::Debug => "DEBUG",
            Self::Info => "INFO",
            Self::Warning => "WARNING",
            Self::Error => "ERROR",
            Self::Critical => "CRITICAL",
        }
    }
}

pub struct RunLog {
    path: PathBuf,
    file: Mutex<File>,
    minimum: Level,
}
static URL: LazyLock<Regex> = LazyLock::new(|| matcher(r#"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>"']+"#));
static SECRET: LazyLock<Regex> = LazyLock::new(|| {
    matcher(
        r#"(?i)\b([\w-]*(?:key|token|secret|password|passwd|cookie|authorization|credential|session)[\w-]*["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|(?:bearer|basic)\s+[^\s,;]+|[^\s,;]+)"#,
    )
});
static BEARER: LazyLock<Regex> = LazyLock::new(|| matcher(r"(?i)\bbearer\s+[^\s,;]+"));

pub fn redact(text: &str) -> String {
    let text = URL.replace_all(text, "[REDACTED]");
    let text = SECRET.replace_all(&text, "${1}[REDACTED]");
    BEARER
        .replace_all(&text, "[REDACTED]")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
}
impl RunLog {
    pub fn open(workspace: impl AsRef<Path>, name: &str) -> Result<Self, IrError> {
        let minimum = match std::env::var("REVAYAT_LOG_LEVEL")
            .unwrap_or_default()
            .to_ascii_uppercase()
            .as_str()
        {
            "DEBUG" => Level::Debug,
            "WARNING" => Level::Warning,
            "ERROR" => Level::Error,
            "CRITICAL" => Level::Critical,
            _ => Level::Info,
        };
        Self::open_at(workspace.as_ref(), name, minimum, OffsetDateTime::now_utc())
    }
    pub fn open_at(
        workspace: &Path,
        name: &str,
        minimum: Level,
        now: OffsetDateTime,
    ) -> Result<Self, IrError> {
        if name.is_empty()
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
        {
            return Err(IrError::refused(
                "invalid_log_name",
                "log names must be ASCII letters, digits, hyphens or underscores",
            ));
        }
        let folder = workspace.join("logs");
        fs::create_dir_all(&folder)?;
        let stamp = now
            .to_utc()
            .format(format_description!(
                "[year]-[month]-[day]_[hour]-[minute]-[second]_UTC"
            ))
            .map_err(|e| IrError::refused("log_time", e.to_string()))?;
        for collision in 0u32.. {
            let suffix = if collision == 0 {
                String::new()
            } else {
                format!("_{collision:03}")
            };
            let path = folder.join(format!("{name}_{stamp}{suffix}.log"));
            let mut options = OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            match options.open(&path) {
                Ok(file) => {
                    return Ok(Self {
                        path,
                        file: Mutex::new(file),
                        minimum,
                    });
                }
                Err(err) if err.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(err) => return Err(err.into()),
            }
        }
        Err(IrError::refused(
            "log_collision",
            "too many log names in one second",
        ))
    }
    pub fn path(&self) -> &Path {
        &self.path
    }
    pub fn event(&self, level: Level, component: &str, message: &str) -> Result<(), IrError> {
        if level < self.minimum {
            return Ok(());
        }
        let stamp = OffsetDateTime::now_utc()
            .format(format_description!(
                "[year]-[month]-[day] [hour]:[minute]:[second]"
            ))
            .map_err(|e| IrError::refused("log_time", e.to_string()))?;
        let mut file = self
            .file
            .lock()
            .map_err(|_| IrError::refused("log_lock", "run log lock is poisoned"))?;
        writeln!(
            file,
            "[{stamp} UTC] [{}] [{}] {}",
            level.name(),
            redact(component),
            redact(message)
        )?;
        file.flush()?;
        Ok(())
    }
}
