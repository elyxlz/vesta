use vesta_tests::{TestAgent, SERVER, unique_agent};

#[test]
fn multi_agent_unique_ports() {
    let c = SERVER.client();
    let a1 = TestAgent::create(&c, &unique_agent("multi")).unwrap();
    let a2 = TestAgent::create(&c, &unique_agent("multi")).unwrap();
    let a3 = TestAgent::create(&c, &unique_agent("multi")).unwrap();

    let list = c.list_agents().unwrap();
    let ports: Vec<u16> = [&a1.name, &a2.name, &a3.name]
        .iter()
        .filter_map(|n| list.iter().find(|a| &a.name == *n))
        .map(|a| a.ws_port)
        .collect();

    assert_eq!(ports.len(), 3);
    assert_ne!(ports[0], ports[1]);
    assert_ne!(ports[0], ports[2]);
    assert_ne!(ports[1], ports[2]);
}

#[test]
fn stopped_agent_port_not_stolen() {
    let c = SERVER.client();
    let a1 = TestAgent::create(&c, &unique_agent("port-theft")).unwrap();
    c.start_agent(&a1.name).unwrap();
    let port1 = c.agent_status(&a1.name).unwrap().ws_port;
    assert!(port1 > 0, "agent should have a non-zero port");

    c.stop_agent(&a1.name).unwrap();

    let mut other_ports = Vec::new();
    let mut agents = Vec::new();
    for _ in 0..4 {
        let agent = TestAgent::create(&c, &unique_agent("port-theft")).unwrap();
        let port = c.agent_status(&agent.name).unwrap().ws_port;
        other_ports.push(port);
        agents.push(agent);
    }

    assert!(
        !other_ports.contains(&port1),
        "stopped agent's port {port1} was stolen by a new agent: {other_ports:?}"
    );
}

#[test]
fn agent_env_file_includes_vestad_port() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("env-port")).unwrap();

    let env_path = SERVER._tmpdir_path()
        .join(format!(".config/vesta/vestad/agents/{}.env", agent.name));
    let content = std::fs::read_to_string(&env_path)
        .expect("per-agent env file should exist");
    let expected = format!("export VESTAD_PORT={}", SERVER.port);
    assert!(content.contains(&expected), "agent env file should contain VESTAD_PORT: {content}");
}

#[test]
fn agent_has_env_file_with_token() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("token-env")).unwrap();

    let agents_dir = SERVER._tmpdir_path().join(".config/vesta/vestad/agents");
    let env_path = agents_dir.join(format!("{}.env", agent.name));
    assert!(env_path.exists(), "per-agent env file should exist at {:?}", env_path);

    let content = std::fs::read_to_string(&env_path).expect("should be able to read env file");
    let token_line = content.lines()
        .find(|l| l.contains("AGENT_TOKEN="))
        .expect("env file should contain AGENT_TOKEN");
    let token = token_line.strip_prefix("export AGENT_TOKEN=").expect("should have export prefix");
    assert_eq!(token.len(), 64, "token should be 32 bytes hex-encoded (64 chars)");

    let output = std::process::Command::new("docker")
        .args([
            "inspect", "--format",
            "{{index .Config.Labels \"vesta.agent_token\"}}",
            &format!("vesta-{}-{}", std::env::var("USER").unwrap_or_default(), agent.name),
        ])
        .output()
        .expect("docker inspect should work");
    let label = String::from_utf8_lossy(&output.stdout).trim().to_string();
    assert!(label.is_empty() || label == "<no value>", "token should NOT be in Docker labels");
}
