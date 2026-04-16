use vesta_tests::SERVER;

#[test]
fn name_normalization() {
    let c = SERVER.client();
    let name = c.create_agent("My Test Agent", false).unwrap();
    assert_eq!(name, "my-test-agent");
    let _ = c.destroy_agent(&name);
}

#[test]
fn empty_name_fails() {
    assert!(SERVER.client().create_agent("", false).is_err());
}

#[test]
fn special_chars_name_normalized() {
    assert!(SERVER.client().create_agent("!!!", false).is_err(), "name normalizing to empty should fail");
}
