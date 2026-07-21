You are the **permissions** command. Manages approval prompts for the current project.

All changes go to `.claude/settings.local.json` — automatically gitignored, local only, never committed.

## Subcommands

### `allow all`
1. Read `.claude/settings.local.json` if it exists (preserve any other keys).
2. Add or overwrite the `permissions` key:
   ```json
   "permissions": {
     "allow": ["Bash(*)", "Read(*)", "Edit(*)", "Write(*)", "Glob(*)", "Grep(*)"]
   }
   ```
3. Write the file.
4. Output:
```
══════════════════════════════════════════
🔓 ALL PERMISSIONS ALLOWED
File:   .claude/settings.local.json
Effect: No approval prompts for Bash, Read, Edit, Write, Glob, Grep
Scope:  This project only — not committed, not pushed
Undo:   /permissions reset to restore prompts
⚠️  Restart Claude Code for the change to take effect.
══════════════════════════════════════════
```

---

### `reset`
1. If `.claude/settings.local.json` does not exist → output ALREADY CLEAN and stop.
2. Read the file. Remove the `permissions` key entirely.
3. If the result is `{}` → delete the file. Otherwise → write the updated file.
4. Output:
```
══════════════════════════════════════════
🔒 PERMISSIONS RESET
File:   .claude/settings.local.json
Effect: Approval prompts restored
⚠️  Restart Claude Code for the change to take effect.
══════════════════════════════════════════
```

**Already clean:**
```
══════════════════════════════════════════
🔒 PERMISSIONS ALREADY AT DEFAULT
No permissions block found — nothing to reset.
══════════════════════════════════════════
```

---

If called with no subcommand or an unrecognised argument, output:
```
Usage: /permissions allow all   — disable all approval prompts (local only)
       /permissions reset       — restore approval prompts
```
