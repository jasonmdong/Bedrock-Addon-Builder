# Independent user plans (subscription POC)

This document describes the **demo / proof-of-concept** for tiered plans (Free, Creator, Pro) aimed at **hobbyists and independent creators**—not schools or enterprise. **No payment** is integrated; prices shown in the UI are illustrative.

---

## Goals

- Let new users **pick a plan at signup** to simulate future paid tiers.
- **Enforce usage limits** that scale with tier (variable AI cost later).
- Allow **changing the demo plan** without creating a new account.

---

## Already implemented (POC)

| Area | Behavior |
|------|----------|
| Signup UI | Tier cards (Free / Creator / Pro), “demo, no payment” copy. |
| Change plan | **Change demo plan** in sidebar → modal to switch tier; calls `setUserTier()` + backend sync. |
| Storage | `user_<username>_tier` in `localStorage`; workspace in `user_<username>_data`. |
| Daily AI quota | Counts **LLM assistant** runs only (`user_<user>_ai_actions_<YYYY-MM-DD>`). **+ New** creates a blank mob from `/api/spec` and does not use AI. Resets at midnight local time. |
| Usage panel | Under **LLM History**: for each line (AI prompts, mobs, history) shows **Included · Used · Left**. Sidebar has a one-line summary. |
| Mob limits | `canAddMob()` / `getTierMobLimit()` — enforced when opening **+ New** and when creating from template or AI. |
| LLM history cap | `getTierHistoryLimit()` wired in `llm.js` — stack trimmed to tier; extra entries dropped on downgrade. |
| Sidebar | Username + plan badge. |
| Backend sync | `POST /api/users`, `GET /api/users/{username}` — when DB is configured (`backend/api/routes.py`). |
| User list | Tier badge per user in the account switcher modal. |

---

## Features to implement (backlog)

### Tier enforcement & metering

1. **Server-side limits** — Mirror mob / AI / history limits in API routes when you add real auth (browser-only limits are bypassable today).
2. **Downgrade rules** — If mob count exceeds a newly selected tier’s cap: read-only extra mobs, export-only, or force delete — **not** implemented; user must delete mobs manually.
3. **Smarter AI accounting** — Optional: weight “Smart plan mode” or MCP-heavy calls higher than a simple spec edit.

### Product & UX

4. **Plan comparison** — Single page or panel summarizing limits (already partly on tier cards).
5. **Onboarding** — Short post-signup tooltip explaining demo vs future billing.
6. **Toasts** — Replace some `alert()`s with non-blocking status for limit hits.

### Optional: QA add-on

7. **Pro-only QA / golden tests** — If you productize the evaluation pipeline; keep off lower tiers to control cost.

### Explicitly out of scope (this README)

- **Institutional / student licensing** — Track separately.
- **Payment providers** — Add when you are ready for production billing; data model (`subscription_tier`) is already synced server-side.

---

## Key files

| File | Role |
|------|------|
| `frontend/js/core/user.js` | `TIER_LIMITS`, `createUser`, `getUserTier`, `setUserTier`, `canRunAiAction`, `recordAiAction`, `getTierHistoryLimit`, `updateTierUsagePanel`, mob helpers |
| `frontend/js/build/llm.js` | History stack size, `requestLlm` quota check, `recordAiAction` after success |
| `frontend/js/ui/modals.js` | Mob + AI checks before AI mob generation |
| `frontend/js/core/app.js` | Mob limit before opening add-mob modal |
| `frontend/index.html` | Signup tier cards, change-plan modal, `ai-daily-usage` |
| `backend/api/routes.py` | `VALID_TIERS`, `upsert_user`, `get_user` |

---

## Tier limits (reference — edit in `user.js` only)

| Tier | Mobs | LLM history (per mob) | AI actions / day |
|------|------|----------------------|------------------|
| Free | 5 | 3 | 20 |
| Creator | 50 | 20 | 200 |
| Pro | Unlimited (`-1`) | 50 stored (POC cap) | Unlimited (`-1`) |

**Counts as one AI action:** successful **Ask LLM** on the assistant. **New blank mob**, template load, and manual editing do **not** increment the counter.
