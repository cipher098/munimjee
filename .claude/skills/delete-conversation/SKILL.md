---
name: delete-conversation
description: Delete a conversation and ALL its dependent rows (llm_call_logs, orders, order_items, transactions, delivery_updates, seller_alerts, conversation_products) from the sellerbot Postgres DB, FK-safe and irreversibly. Use when the user asks to delete / remove / purge / wipe a conversation — by its UUID or by customer Instagram id.
---

# Delete a conversation from the DB

Removes a conversation and everything that references it. The conversation
foreign keys have **no `ON DELETE CASCADE`**, so children must be deleted
leaf-first; the script `backend/scripts/delete_conversation.py` does this in the
correct order:

```
llm_call_logs → delivery_updates → order_items → transactions
→ orders → seller_alerts → conversation_products → conversations
```

This is **irreversible**. Always dry-run and confirm with the user before deleting.

## Procedure

1. **Identify the conversation.** Prefer the UUID. If the user only gives a
   customer Instagram id (and maybe a seller), use `--customer` (add `--seller`
   to disambiguate if several match).

2. **Dry run first** (default — counts only, deletes nothing). Run from
   `/Users/gothi/sellerbot/backend`:
   ```bash
   docker compose run --rm -e PYTHONPATH=/app api \
     python scripts/delete_conversation.py --id <conversation_uuid>
   ```
   or by customer:
   ```bash
   docker compose run --rm -e PYTHONPATH=/app api \
     python scripts/delete_conversation.py --customer <ig_id> [--seller <seller_uuid>]
   ```

3. **Show the user** the conversation summary + per-table row counts the dry run
   prints, and get explicit confirmation that this is the right conversation.

4. **Delete** by re-running the exact same command with `--yes` appended:
   ```bash
   docker compose run --rm -e PYTHONPATH=/app api \
     python scripts/delete_conversation.py --id <conversation_uuid> --yes
   ```
   The script deletes leaf-first inside one transaction (auto-commits on success,
   rolls back on any error) and prints the rows removed per table.

## Notes & safety

- Never run `--yes` before showing the user the dry-run output and getting a go-ahead.
- If `--customer` matches more than one conversation, the script lists them and
  refuses to act — pick one and re-run with `--id`.
- If nothing matches, it says so and deletes nothing.
- The DB credentials/host come from `backend/.env` via the app config; the
  script uses the app's `worker_session`, so no manual psql connection is needed.
- To verify afterwards, re-run the dry run for the same id — it should report
  "No matching conversation found".
