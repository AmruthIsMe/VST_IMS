# AGENTS.md — Rules for AI Agents

## ⚠️ Build vs Production — MANDATORY

> **Every agent must follow these rules. No exceptions.**

### Environments

| Environment | Database | Safety |
|-------------|----------|--------|
| **Build** | `sqlite:///vst_ims.db` (local) | Safe to reset, seed, modify freely |
| **Production** | `postgresql://...supabase.com` (cloud) | LIVE data — never touch without explicit user approval |

### Rules

1. **Never run scripts against production without explicit user confirmation.**
2. **Always ask: "Is this Build or Production?"** before executing DB operations.
3. **Default to Build/local.** Production access only with `--cloud` flag AND user approval.
4. **Flag any change that could affect production data** before proceeding.
5. **Never run `DELETE FROM`, `DROP TABLE`, or bulk writes** against production without confirmation.
6. **When in doubt, ask.**

### Script Flags

| Script | Local (default) | Production |
|--------|-----------------|------------|
| `seed_cloud_db.py` | `python seed_cloud_db.py` | `python seed_cloud_db.py --cloud` (requires user approval) |

---

*Added: August 2026*
