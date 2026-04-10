# Live File Watching

CodeGraphContext can automatically monitor your codebase for changes and update the code graph in real-time as you develop.

## Quick Start

Start watching your project directory:

```bash
cgc watch .
```

You'll see:
```
🔍 Watching /path/to/your/project for changes...
✓ Already indexed (no initial scan needed)
👀 Monitoring for file changes... (Press Ctrl+C to stop)

💡 Tip: Open a new terminal window to continue working
```

## How It Works

The watcher uses file system events to detect when you:

- Create new files
- Modify existing files
- Delete files
- Move/rename files

When changes are detected, CodeGraphContext automatically:

1. Re-parses the affected files
2. Updates the code graph
3. Maintains all relationships and dependencies

## Commands

### `cgc watch [path]`

Start watching a directory for changes.

**Examples:**
```bash
cgc watch .                    # Watch current directory
cgc watch /path/to/project     # Watch specific directory
cgc w .                        # Shortcut alias
```

**Behavior:**
- Runs in the foreground (blocking mode)
- Performs initial scan if directory is not yet indexed
- Monitors for all file system changes
- Uses 2-second debouncing to batch rapid changes
- Press `Ctrl+C` to stop

### `cgc watching`

List all directories currently being watched.

```bash
cgc watching
```

**Note:** This command is a CLI workflow. MCP is query-only and does not expose watcher control tools.

### `cgc unwatch <path>`

Stop watching a directory.

```bash
cgc unwatch /path/to/project
```

**Note:** This command is a CLI workflow. For active foreground sessions, you can also stop watching with `Ctrl+C`.

## Best Practices

### Development Workflow

1. Start watching at the beginning of your coding session
2. Open a new terminal tab/window for your actual work
3. Code normally - changes are automatically tracked
4. Stop watching (Ctrl+C) when you're done

### Performance Tips

- The watcher uses debouncing (2-second delay) to avoid excessive re-indexing
- Only modified files and their dependencies are re-processed
- Large projects may take a moment to process changes

### When to Use Watch Mode

✅ **Good for:**

- Active development sessions
- Refactoring work
- Keeping AI assistants up-to-date with latest code
- Live code analysis during development

❌ **Not needed for:**

- One-time indexing
- CI/CD pipelines
- Read-only code analysis
- Batch processing

## Example Workflow

Here's a typical development session using watch mode:

```bash
# Terminal 1: Start the watcher
$ cd ~/my-project
$ cgc watch .
🔍 Watching /home/user/my-project for changes...
✓ Already indexed (no initial scan needed)
👀 Monitoring for file changes... (Press Ctrl+C to stop)

💡 Tip: Open a new terminal window to continue working

# ... watcher runs and shows updates as you code ...
[21:15:32] 📝 Modified: src/utils.py (re-indexing...)
[21:15:32] ✓ Updated graph (3 nodes, 2 relationships)
[21:16:45] 📝 Created: src/new_feature.py (re-indexing...)
[21:16:45] ✓ Updated graph (8 nodes, 5 relationships)
```

```bash
# Terminal 2: Do your development work
$ cd ~/my-project
$ code .                       # Open your editor
$ git checkout -b new-feature  # Work normally
$ # ... make changes, save files ...
$ # The watcher in Terminal 1 automatically picks up changes!
```

## Troubleshooting

### Watcher not detecting changes

- Ensure the path is correct and accessible
- Check file permissions
- Some editors use atomic writes which may not trigger events
- Try restarting the watcher

### High CPU usage

- The watcher may be processing too many files
- Consider watching a smaller directory
- Check for file loops or symlinks
- Verify you're not watching `node_modules` or similar large directories

### Changes not appearing

- Wait for the debounce interval (2 seconds)
- Check the watcher output for errors
- Verify the file type is supported (Python, JavaScript, TypeScript, etc.)
- Ensure the file is within the watched directory

### "Already watching" message

If you see this message, it means the directory is already being watched. This can happen if:

- You're running multiple watch commands
- A previous watch session didn't terminate cleanly

**Solution:** Stop all watch processes and start fresh.

## CLI Watch Mode vs MCP Query Mode

CodeGraphContext supports CLI watch mode and MCP query mode:

### CLI Watch Mode (This Guide)

- **Command:** `cgc watch .`
- **Runs:** In foreground (blocking)
- **Use case:** Active development sessions
- **Control:** Press `Ctrl+C` to stop
- **Best for:** Single project, focused development

### MCP Server Mode

- **Command:** `cgc mcp start --readonly`
- **Runs:** As an MCP query server
- **Use case:** IDE/agent queries against indexed data
- **Control:** MCP query tools only
- **Best for:** Read-only analysis

## Technical Details

- **Library**: Uses `watchdog` for cross-platform file monitoring
- **Debouncing**: 2-second delay to batch rapid changes
- **Scope**: Watches recursively, respects `.gitignore`
- **Performance**: Only re-indexes changed files and affected relationships
- **Thread-safe**: Uses background threads for file monitoring
- **Graceful shutdown**: Properly cleans up on `Ctrl+C`

## Integration with AI Assistants

Watch mode is particularly powerful when combined with AI coding assistants:

1. **Start watching your project:**
   ```bash
   cgc watch .
   ```

2. **Configure your AI assistant** to use the CodeGraphContext MCP server

3. **Code normally** - your AI assistant always has the latest code context

4. **Ask questions** about your code, and the AI will have up-to-date information

This creates a seamless development experience where your AI assistant stays synchronized with your codebase in real-time!

## See Also

- [CLI Reference](reference/cli_master.md) - Complete list of CLI commands
- [MCP Tools](reference/mcp_master.md) - MCP query tools
- [Installation](getting-started/installation.md) - Getting started with CodeGraphContext
