# Using with AI (MCP Guide)

The Model Context Protocol (MCP) allows AI coding assistants to talk directly to tools like CodeGraphContext.

## 1. Run the MCP Setup Wizard

We provide an interactive tool to configure your editors automatically.

```bash
cgc mcp setup
```

**What happens here:**

1.  The tool looks for configuration files (e.g., `~/Library/Application Support/Cursor/User/globalStorage/mcp.json`).
2.  It injects the `CodeGraphContext` server details.
3.  It ensures the server knows how to find your database.

## 2. Supported Clients

| Client | Setup Method | Notes |
| :--- | :--- | :--- |
| **Cursor** | Automatic | Requires "MCP" feature enabled in settings. |
| **Claude Desktop** | Automatic | Works with the Claude 3.5 Sonnet model. |
| **VS Code** | Semi-Automatic | Requires the **"Continue"** extension or similar MCP client. |

## 3. How to Use It (Once Connected)

Open your AI Chat and talk naturally. The AI now has a "tool" it can call.

MCP is query-only. For indexing, watching, deleting, and bundle load/import, use CLI terminal commands.

**Example Prompts:**

*   "Who calls the `process_payment` function?" -> *AI calls `analyze_code_relationships`*
*   "Find all dead code in `utils.py`." -> *AI calls `find_dead_code`*

**CLI write examples (outside MCP):**

```bash
cgc index .
cgc watch .
cgc bundle load flask
```

## 4. Troubleshooting

*   **"Component not found":** This usually means the MCP server didn't start. Check the logs in your AI editor.
*   **"Database error":** Ensure your Neo4j container is running (`docker ps`) or that your Python environment is active.
