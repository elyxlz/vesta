use std::time::{Duration, SystemTime, UNIX_EPOCH};

use vesta_tests::exec_in_container;

use super::common::{setup_live_agent, wait_for_file_contains, write_notification, E2E_FILES_DIR};

/// The agent must invoke one of its in-process MCP tools mid-conversation. This
/// exercises the full cc_sdk MCP path against real claude: claude -> _mcp_stdio.py
/// stdio proxy -> unix-socket bridge -> in-process handler (events.db search) -> result
/// back to claude. Container startup already requires one MCP call (mark_setup_done),
/// but this verifies tools keep working in the middle of a normal conversation turn.
#[test]
fn agent_uses_mcp_tool_in_conversation() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-mcp", true, true, None) else {
        return;
    };

    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let result_file = format!("{E2E_FILES_DIR}/mcp-{uid}.txt");

    write_notification(
        &container,
        &format!(
            "Use your search_conversation_history tool to search for the word \"pytest\". \
             After the tool call returns (regardless of what it found), create the file \
             \"{result_file}\" containing only the text: MCP_TOOL_OK"
        ),
        true,
    )
    .expect("write mcp notification");

    let content = wait_for_file_contains(&container, &result_file, "MCP_TOOL_OK", Duration::from_secs(180))
        .expect("wait for mcp result file");
    assert!(content.contains("MCP_TOOL_OK"));

    // The file write alone could be done without the tool; require evidence of the actual
    // MCP tool_use in the claude session transcript.
    exec_in_container(
        &container,
        "grep -q 'search_conversation_history' /root/.claude/projects/*/*.jsonl",
    )
    .expect("expected a search_conversation_history tool_use in the claude transcript");
}
