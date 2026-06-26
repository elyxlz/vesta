use vesta_tests::exec_in_container;

use super::common::lock_live_agent_a;

/// First-start regression: the agent must call `mark_setup_done` as the REAL MCP tool, not
/// by reverse-engineering the bridge socket because the tool never reached the model.
///
/// This is the failure that bit production: with the MCP server registered via the live
/// in-process bridge, claude's startup tools/list didn't make the control tools callable, so
/// the agent limped through first-start by driving the unix socket from a Bash/python one-liner.
/// The fully-qualified name `mcp__vesta__mark_setup_done` appears in a transcript ONLY on a
/// genuine tool_use/tool_result; the socket hack uses the bare name inside a Bash command. So
/// finding it proves the model actually had, and called, the MCP control tool during first-start.
#[test]
fn agent_called_mark_setup_done_as_real_mcp_tool() {
    let Some((_shared, container)) = lock_live_agent_a() else {
        return;
    };

    let hits = exec_in_container(
        &container,
        "grep -l 'mcp__vesta__mark_setup_done' /root/.claude/projects/*/*.jsonl 2>/dev/null || true",
    )
    .unwrap_or_default();

    assert!(
        !hits.trim().is_empty(),
        "no mcp__vesta__mark_setup_done tool_use found in any claude transcript — the agent could \
         not call its MCP control tools and worked around them (e.g. driving the bridge socket \
         directly); MCP tools are not reaching the model during first-start"
    );
}
