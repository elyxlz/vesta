#[cfg(target_os = "macos")]
#[test]
fn test_zstd_tar_extraction() {
    let tmp = tempfile::tempdir().unwrap();

    // Create a test file to put in the archive
    let src_dir = tempfile::tempdir().unwrap();
    std::fs::write(src_dir.path().join("test-file"), b"hello vesta").unwrap();

    // Create tar.zst archive
    let archive_path = tmp.path().join("test.tar.zst");
    let file = std::fs::File::create(&archive_path).unwrap();
    let encoder = zstd::Encoder::new(file, 3).unwrap();
    let mut tar_builder = tar::Builder::new(encoder);
    tar_builder
        .append_path_with_name(src_dir.path().join("test-file"), "test-file")
        .unwrap();
    let encoder = tar_builder.into_inner().unwrap();
    encoder.finish().unwrap();

    // Extract using the same method as download_vm_image()
    let extract_dir = tempfile::tempdir().unwrap();
    let zst_file = std::fs::File::open(&archive_path).unwrap();
    let decoder = zstd::Decoder::new(zst_file).unwrap();
    let mut archive = tar::Archive::new(decoder);
    archive.unpack(extract_dir.path()).unwrap();

    // Verify
    let content = std::fs::read_to_string(extract_dir.path().join("test-file")).unwrap();
    assert_eq!(content, "hello vesta");
}
