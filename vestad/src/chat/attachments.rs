//! The attachment store: one directory per id under `<config_dir>/chat/attachments/`, a staging
//! session (`.session.json` plus `.part`) that finalizes into `.meta.json` plus the named blob.
//! Control files are dot-prefixed and `sanitize_filename` strips leading dots, so a user file can
//! never collide with the store's own records.

use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

pub(crate) const MAX_CHUNK_BYTES: usize = 8 * 1024 * 1024;
pub(crate) const MAX_ATTACHMENT_BYTES: u64 = 512 * 1024 * 1024;
pub(crate) const MAX_ATTACHMENTS_PER_MESSAGE: usize = 10;
pub(crate) const STALE_SESSION_MAX_AGE_SECS: u64 = 24 * 3600;
pub(crate) const FILENAME_MAX_CHARS: usize = 120;
pub(crate) const MIME_MAX_CHARS: usize = 200;
pub(crate) const ATTACHMENT_ID_BYTES: usize = 16;

const SESSION_FILE: &str = ".session.json";
const META_FILE: &str = ".meta.json";
const PART_FILE: &str = ".part";
const FALLBACK_NAME: &str = "file";

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub(crate) struct AttachmentMeta {
    pub id: String,
    pub name: String,
    pub mime: String,
    pub size: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub width: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub height: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_secs: Option<f64>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(crate) struct MetaExtra {
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub duration_secs: Option<f64>,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum AttachmentError {
    Unknown,
    Size(String),
    SizeMismatch { staged: u64, declared: u64 },
    Offset { received: u64 },
}

impl std::fmt::Display for AttachmentError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unknown => write!(formatter, "unknown attachment"),
            Self::Size(reason) => write!(formatter, "{reason}"),
            Self::SizeMismatch { staged, declared } => {
                write!(formatter, "staged {staged} of declared {declared} bytes")
            }
            Self::Offset { received } => write!(formatter, "offset mismatch, received {received}"),
        }
    }
}

impl std::error::Error for AttachmentError {}

pub(crate) fn sanitize_filename(name: &str) -> String {
    let base = name.rsplit(['/', '\\']).next().unwrap_or_default();
    let cleaned: String = base
        .chars()
        .map(|character| {
            if character.is_control() {
                '_'
            } else {
                character
            }
        })
        .collect();
    let trimmed = cleaned.trim_start_matches('.');
    let bounded: String = trimmed.chars().take(FILENAME_MAX_CHARS).collect();
    if bounded.is_empty() {
        FALLBACK_NAME.to_string()
    } else {
        bounded
    }
}

pub(crate) fn is_valid_id(id: &str) -> bool {
    id.len() == ATTACHMENT_ID_BYTES * 2
        && id
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

/// The declared mime becomes a response header, so it must be printable ASCII with a slash.
pub(crate) fn valid_mime(mime: &str) -> bool {
    !mime.is_empty()
        && mime.len() <= MIME_MAX_CHARS
        && mime.contains('/')
        && mime.bytes().all(|byte| (b' '..=b'~').contains(&byte))
}

#[derive(Debug)]
pub(crate) struct AttachmentStore {
    root: PathBuf,
}

impl AttachmentStore {
    pub(crate) fn new(root: PathBuf) -> Self {
        Self { root }
    }

    pub(crate) fn root(&self) -> &Path {
        &self.root
    }

    fn dir(&self, id: &str) -> Result<PathBuf, AttachmentError> {
        if !is_valid_id(id) {
            return Err(AttachmentError::Unknown);
        }
        Ok(self.root.join(id))
    }

    fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|content| serde_json::from_str(&content).ok())
    }

    fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), AttachmentError> {
        let body = serde_json::to_vec(value).map_err(|_| AttachmentError::Unknown)?;
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, body)
            .and_then(|()| std::fs::rename(&tmp, path))
            .map_err(|_| AttachmentError::Unknown)
    }

    fn session(&self, id: &str) -> Result<(PathBuf, AttachmentMeta), AttachmentError> {
        let dir = self.dir(id)?;
        let session = Self::read_json::<AttachmentMeta>(&dir.join(SESSION_FILE))
            .ok_or(AttachmentError::Unknown)?;
        Ok((dir, session))
    }

    fn part_size(dir: &Path) -> u64 {
        std::fs::metadata(dir.join(PART_FILE)).map_or(0, |meta| meta.len())
    }

    pub(crate) fn create_session(
        &self,
        name: &str,
        mime: &str,
        size: u64,
        extra: MetaExtra,
    ) -> Result<String, AttachmentError> {
        if size > MAX_ATTACHMENT_BYTES {
            return Err(AttachmentError::Size(format!(
                "size {size} exceeds the {MAX_ATTACHMENT_BYTES} byte limit"
            )));
        }
        let id = hex::encode(rand::random::<[u8; ATTACHMENT_ID_BYTES]>());
        let dir = self.root.join(&id);
        std::fs::create_dir_all(&dir).map_err(|_| AttachmentError::Unknown)?;
        let session = AttachmentMeta {
            id: id.clone(),
            name: sanitize_filename(name),
            mime: mime.to_string(),
            size,
            width: extra.width,
            height: extra.height,
            duration_secs: extra.duration_secs,
        };
        Self::write_json(&dir.join(SESSION_FILE), &session)?;
        std::fs::write(dir.join(PART_FILE), b"").map_err(|_| AttachmentError::Unknown)?;
        Ok(id)
    }

    /// Append one chunk at exactly the staged size; a mismatch reports the truth to resync to.
    pub(crate) fn append_at(
        &self,
        id: &str,
        offset: u64,
        data: &[u8],
    ) -> Result<u64, AttachmentError> {
        let (dir, session) = self.session(id)?;
        let current = Self::part_size(&dir);
        if offset != current {
            return Err(AttachmentError::Offset { received: current });
        }
        let after = current + data.len() as u64;
        if after > session.size {
            return Err(AttachmentError::Size(format!(
                "append past the declared size {}",
                session.size
            )));
        }
        let mut part = std::fs::OpenOptions::new()
            .append(true)
            .open(dir.join(PART_FILE))
            .map_err(|_| AttachmentError::Unknown)?;
        part.write_all(data).map_err(|_| AttachmentError::Unknown)?;
        Ok(after)
    }

    pub(crate) fn upload_status(&self, id: &str) -> Result<(u64, u64, bool), AttachmentError> {
        if let Some(meta) = self.read_meta(id) {
            return Ok((meta.size, meta.size, true));
        }
        let (dir, session) = self.session(id)?;
        Ok((Self::part_size(&dir), session.size, false))
    }

    /// Promote the staged part to the named blob. Idempotent: a finalized id answers its meta.
    pub(crate) fn finalize(&self, id: &str) -> Result<AttachmentMeta, AttachmentError> {
        if let Some(meta) = self.read_meta(id) {
            return Ok(meta);
        }
        let (dir, session) = self.session(id)?;
        let staged = Self::part_size(&dir);
        if staged != session.size {
            return Err(AttachmentError::SizeMismatch {
                staged,
                declared: session.size,
            });
        }
        std::fs::rename(dir.join(PART_FILE), dir.join(&session.name))
            .map_err(|_| AttachmentError::Unknown)?;
        Self::write_json(&dir.join(META_FILE), &session)?;
        let _ = std::fs::remove_file(dir.join(SESSION_FILE));
        Ok(session)
    }

    pub(crate) fn read_meta(&self, id: &str) -> Option<AttachmentMeta> {
        let dir = self.dir(id).ok()?;
        Self::read_json(&dir.join(META_FILE))
    }

    pub(crate) fn blob_path(&self, id: &str) -> Result<PathBuf, AttachmentError> {
        let meta = self.read_meta(id).ok_or(AttachmentError::Unknown)?;
        Ok(self.root.join(id).join(meta.name))
    }

    pub(crate) fn is_removed(&self, id: &str) -> bool {
        self.blob_path(id).is_ok_and(|path| !path.exists())
    }

    /// Remove every stale directory: a staging session, or a finalized blob nothing references.
    /// Staleness is the newest mtime of the directory or any entry in it.
    pub(crate) fn sweep(&self, now_secs: u64, referenced: &dyn Fn(&str) -> bool) -> Vec<String> {
        let Ok(entries) = std::fs::read_dir(&self.root) else {
            return Vec::new();
        };
        let mut swept = Vec::new();
        for entry in entries.flatten() {
            let id = entry.file_name().to_string_lossy().to_string();
            if !is_valid_id(&id) {
                continue;
            }
            let dir = entry.path();
            let stale = Self::last_activity_secs(&dir)
                .is_some_and(|last| now_secs.saturating_sub(last) > STALE_SESSION_MAX_AGE_SECS);
            if !stale {
                continue;
            }
            let staging = dir.join(SESSION_FILE).exists();
            let orphan = dir.join(META_FILE).exists() && !referenced(&id) && !self.is_removed(&id);
            if (staging || orphan) && std::fs::remove_dir_all(&dir).is_ok() {
                swept.push(id);
            }
        }
        swept
    }

    fn last_activity_secs(dir: &Path) -> Option<u64> {
        let mut newest = Self::mtime_secs(dir)?;
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                if let Some(secs) = Self::mtime_secs(&entry.path()) {
                    newest = newest.max(secs);
                }
            }
        }
        Some(newest)
    }

    fn mtime_secs(path: &Path) -> Option<u64> {
        let modified = std::fs::metadata(path).ok()?.modified().ok()?;
        modified
            .duration_since(std::time::UNIX_EPOCH)
            .ok()
            .map(|duration| duration.as_secs())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> (tempfile::TempDir, AttachmentStore) {
        let tmp = tempfile::tempdir().expect("tempdir");
        let store = AttachmentStore::new(tmp.path().join("attachments"));
        (tmp, store)
    }

    fn extra() -> MetaExtra {
        MetaExtra {
            width: None,
            height: None,
            duration_secs: None,
        }
    }

    #[test]
    fn sanitize_filename_strips_paths_dots_and_control_chars_and_bounds_length() {
        assert_eq!(sanitize_filename("../../etc/passwd"), "passwd");
        assert_eq!(sanitize_filename(".hidden"), "hidden");
        assert_eq!(sanitize_filename("a\u{0}b\nc.txt"), "a_b_c.txt");
        assert_eq!(sanitize_filename(""), "file");
        assert_eq!(sanitize_filename("..."), "file");
        assert_eq!(
            sanitize_filename(&"x".repeat(200)).chars().count(),
            FILENAME_MAX_CHARS
        );
    }

    #[test]
    fn ids_are_32_lowercase_hex_and_mimes_are_printable_with_a_slash() {
        assert!(is_valid_id(&"a".repeat(32)));
        assert!(!is_valid_id(&"A".repeat(32)));
        assert!(!is_valid_id("../x"));
        assert!(valid_mime("image/png"));
        assert!(!valid_mime("png"));
        assert!(!valid_mime("image/\u{0}"));
        assert!(!valid_mime(&format!(
            "image/{}",
            "x".repeat(MIME_MAX_CHARS)
        )));
    }

    #[test]
    fn a_session_stages_chunks_at_exact_offsets_and_finalizes_once() {
        let (_tmp, store) = store();
        let id = store
            .create_session("photo.png", "image/png", 6, extra())
            .expect("session");
        assert!(is_valid_id(&id));
        assert_eq!(store.upload_status(&id).expect("status"), (0, 6, false));
        assert_eq!(store.append_at(&id, 0, b"abc").expect("first"), 3);
        let mismatch = store.append_at(&id, 1, b"zz").expect_err("offset");
        assert_eq!(mismatch, AttachmentError::Offset { received: 3 });
        assert_eq!(store.append_at(&id, 3, b"def").expect("second"), 6);
        let over = store.append_at(&id, 6, b"g").expect_err("past size");
        assert!(matches!(over, AttachmentError::Size(_)));
        let meta = store.finalize(&id).expect("finalize");
        assert_eq!(
            meta,
            AttachmentMeta {
                id: id.clone(),
                name: "photo.png".into(),
                mime: "image/png".into(),
                size: 6,
                width: None,
                height: None,
                duration_secs: None
            }
        );
        assert_eq!(store.finalize(&id).expect("idempotent"), meta);
        assert_eq!(store.upload_status(&id).expect("status"), (6, 6, true));
        assert_eq!(
            std::fs::read(store.blob_path(&id).expect("blob")).expect("bytes"),
            b"abcdef"
        );
        assert!(!store.root().join(&id).join(".session.json").exists());
        assert!(!store.root().join(&id).join(".part").exists());
        assert_eq!(store.read_meta(&id), Some(meta));
    }

    #[test]
    fn finalize_refuses_a_short_stage_and_rejects_an_oversized_declaration() {
        let (_tmp, store) = store();
        let id = store
            .create_session("a.bin", "application/octet-stream", 4, extra())
            .expect("session");
        store.append_at(&id, 0, b"ab").expect("chunk");
        assert_eq!(
            store.finalize(&id).expect_err("short"),
            AttachmentError::SizeMismatch {
                staged: 2,
                declared: 4
            }
        );
        let too_big = store
            .create_session(
                "b.bin",
                "application/octet-stream",
                MAX_ATTACHMENT_BYTES + 1,
                extra(),
            )
            .expect_err("size");
        assert!(matches!(too_big, AttachmentError::Size(_)));
        assert_eq!(
            store
                .append_at("0000000000000000000000000000dead", 0, b"x")
                .expect_err("unknown"),
            AttachmentError::Unknown
        );
        assert_eq!(store.read_meta("not-an-id"), None);
    }

    #[test]
    fn extra_metadata_rides_the_session_into_the_meta() {
        let (_tmp, store) = store();
        let id = store
            .create_session(
                "clip.mp4",
                "video/mp4",
                1,
                MetaExtra {
                    width: Some(1920),
                    height: Some(1080),
                    duration_secs: Some(2.5),
                },
            )
            .expect("session");
        store.append_at(&id, 0, b"x").expect("chunk");
        let meta = store.finalize(&id).expect("finalize");
        assert_eq!(
            (meta.width, meta.height, meta.duration_secs),
            (Some(1920), Some(1080), Some(2.5))
        );
        let json = serde_json::to_value(&meta).expect("json");
        assert_eq!(json["duration_secs"], 2.5);
        let plain = serde_json::to_value(store.read_meta(&id).expect("meta")).expect("json");
        assert!(plain.get("width").is_some());
    }

    #[test]
    fn sweep_removes_stale_staging_and_stale_unreferenced_blobs_only() {
        let (_tmp, store) = store();
        let staged = store
            .create_session("s.bin", "application/octet-stream", 1, extra())
            .expect("staged");
        let kept = store
            .create_session("k.bin", "application/octet-stream", 1, extra())
            .expect("kept");
        store.append_at(&kept, 0, b"x").expect("chunk");
        store.finalize(&kept).expect("finalize");
        let orphan = store
            .create_session("o.bin", "application/octet-stream", 1, extra())
            .expect("orphan");
        store.append_at(&orphan, 0, b"x").expect("chunk");
        store.finalize(&orphan).expect("finalize");
        let fresh = store
            .create_session("f.bin", "application/octet-stream", 1, extra())
            .expect("fresh");
        let old = crate::time_utils::now_epoch_secs() + STALE_SESSION_MAX_AGE_SECS + 1;
        let mut swept = store.sweep(old, &|id| id == kept);
        swept.sort();
        let mut expected = vec![staged.clone(), orphan.clone(), fresh.clone()];
        expected.sort();
        assert_eq!(swept, expected);
        assert!(store.read_meta(&kept).is_some());
        assert!(!store.root().join(&staged).exists());
        let recent = store.sweep(crate::time_utils::now_epoch_secs(), &|_| false);
        assert!(recent.is_empty());
    }
}
