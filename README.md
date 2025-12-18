ENABLE_EXPERIMENTAL_MCP_CLI=true (dynamically loaded mcps)
SKILLS

NO CUSTOM SUBAGENTS, just prompt claude to load a subagent for every task, and then the subagent can hot load skills or mcps as required for the task

have the memory agent work be able to update / make new skills
only use mcps for 2 way communication, where you need a persistent active server (to send notifications), potentially move the python mcps to in process mcps for simplicty


read docx skill
google docs skill
pdf operation skills 
email skills
calendar skills

in process mcps?
need solution for captchas
dbify microsoft?
dockerize
security (password + encrypt DBs)
