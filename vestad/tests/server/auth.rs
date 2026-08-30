use vesta_tests::{
    mark_first_start_done, unique_agent, ProxyAuth, TestAgent, SERVER,
};

#[test]
fn provider_setup_and_catalogs_are_owned_by_the_named_agent() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("provider-relay")).expect("create agent");
    c.wait_until_running(&agent.name, 180)
        .expect("agent API running");

    let start_path = format!("/agents/{}/providers/claude/oauth/start", agent.name);
    assert_eq!(
        c.proxy_post_json(&start_path, ProxyAuth::None, &serde_json::json!({}))
            .expect("unauthenticated request reaches gateway")
            .0,
        401,
        "provider setup remains client-authenticated at the gateway"
    );
    let (start_status, start_body) = c
        .proxy_post_json(&start_path, ProxyAuth::ApiKey, &serde_json::json!({}))
        .expect("start Claude auth through relay");
    assert_eq!(start_status, 200);
    let start: serde_json::Value =
        serde_json::from_str(&start_body).expect("Claude auth start JSON");
    assert!(start["auth_url"].as_str().is_some_and(|url| url.contains("oauth")));
    assert!(start["session_id"].as_str().is_some_and(|id| !id.is_empty()));

    let complete_path = format!("/agents/{}/providers/claude/oauth/complete", agent.name);
    let (bad_status, bad_body) = c
        .proxy_post_json(
            &complete_path,
            ProxyAuth::ApiKey,
            &serde_json::json!({"session_id": "bogus-session", "code": "bogus-code"}),
        )
        .expect("bad completion still relays its upstream response");
    assert_eq!(bad_status, 400);
    let bad: serde_json::Value =
        serde_json::from_str(&bad_body).expect("Claude auth error JSON");
    assert_eq!(bad["error"], "invalid or expired auth session");

    let personalities_path = format!("/agents/{}/personalities", agent.name);
    let (personalities_status, personalities_body) = c
        .proxy_get(&personalities_path, ProxyAuth::ApiKey)
        .expect("personality catalog through relay");
    assert_eq!(personalities_status, 200);
    let personalities: serde_json::Value =
        serde_json::from_str(&personalities_body).expect("personality catalog JSON");
    assert_eq!(personalities["default"], "dry");
    assert!(personalities["presets"].as_array().is_some_and(|presets| {
        presets.iter().any(|preset| preset["name"] == "dry")
    }));

    let provider_path = format!("/agents/{}/provider", agent.name);
    let (provider_status, provider_body) = c
        .proxy_get(&provider_path, ProxyAuth::ApiKey)
        .expect("provider resource through relay");
    assert_eq!(provider_status, 200);
    let provider: serde_json::Value =
        serde_json::from_str(&provider_body).expect("provider resource JSON");
    assert_eq!(provider["catalog"]["default_provider"], "claude");
    assert!(provider["catalog"].get("default_personality").is_none());

    for reserved in ["providers", "personalities"] {
        let error = c
            .register_service(&agent.name, reserved)
            .expect_err("catalog and setup routes cannot be shadowed by services");
        assert!(error.contains("reserved name"), "{error}");
    }

    assert_eq!(
        c.proxy_post_json(
            "/providers/claude/oauth/start",
            ProxyAuth::ApiKey,
            &serde_json::json!({}),
        )
        .expect("removed global provider route")
        .0,
        404
    );
    assert_eq!(
        c.proxy_get("/manifest", ProxyAuth::None)
            .expect("removed manifest route")
            .0,
        404
    );
}

#[test]
fn agent_without_credentials_is_not_authenticated() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("no-creds")).unwrap();

    // No provider is configured, so the agent re-derives provider state on restart
    // and settles at unprovisioned. A fake token can't reach `authenticated` (the
    // agent's first turn 401s upstream and flips it back), so the authenticated path
    // is covered by the live tests with real credentials, not here.
    mark_first_start_done(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    let status = c.wait_until_running(&agent.name, 180).unwrap();
    assert_eq!(status, "unprovisioned");
}
