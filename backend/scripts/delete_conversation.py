"""Delete a conversation and everything that references it, FK-safe.

The conversation FKs have NO ondelete=CASCADE, so children must be removed
leaf-first. This script handles the full tree:

    llm_call_logs → delivery_updates → order_items → transactions
    → orders → seller_alerts → conversation_products → conversations

Locate the conversation by UUID or by customer Instagram id. Defaults to a
DRY RUN (counts only) — pass --yes to actually delete. Deletion is
irreversible.

Run in-container:
    # dry run (shows what would be deleted)
    docker compose run --rm -e PYTHONPATH=/app api \
        python scripts/delete_conversation.py --id <conversation_uuid>

    # actually delete
    docker compose run --rm -e PYTHONPATH=/app api \
        python scripts/delete_conversation.py --id <conversation_uuid> --yes

    # locate by customer Instagram id (optionally scope to a seller)
    docker compose run --rm -e PYTHONPATH=/app api \
        python scripts/delete_conversation.py --customer <ig_id> [--seller <seller_uuid>]
"""
import argparse
import asyncio

from sqlalchemy import text

from app.database import worker_session

# Leaf-first. Each entry: (table, WHERE clause keyed on :cid = conversation id).
# Subqueries resolve order/conversation_product children of the conversation.
_DELETE_STEPS = [
    ("llm_call_logs",
     "conversation_id = :cid "
     "OR conversation_product_id IN (SELECT id FROM conversation_products WHERE conversation_id = :cid)"),
    ("delivery_updates",
     "order_id IN (SELECT id FROM orders WHERE conversation_id = :cid)"),
    ("order_items",
     "order_id IN (SELECT id FROM orders WHERE conversation_id = :cid) "
     "OR conversation_product_id IN (SELECT id FROM conversation_products WHERE conversation_id = :cid)"),
    ("transactions",
     "order_id IN (SELECT id FROM orders WHERE conversation_id = :cid)"),
    ("orders", "conversation_id = :cid"),
    ("seller_alerts", "conversation_id = :cid"),
    ("conversation_products", "conversation_id = :cid"),
    ("conversations", "id = :cid"),
]


async def _resolve_conversation_id(session, args) -> str | None:
    if args.id:
        row = (await session.execute(
            text("SELECT id FROM conversations WHERE id = :cid"), {"cid": args.id}
        )).first()
        return str(row[0]) if row else None

    # locate by customer instagram id
    sql = "SELECT id, seller_id, customer_name, status, created_at FROM conversations WHERE customer_instagram_id = :cust"
    params = {"cust": args.customer}
    if args.seller:
        sql += " AND seller_id = :seller"
        params["seller"] = args.seller
    rows = (await session.execute(text(sql), params)).all()
    if not rows:
        return None
    if len(rows) > 1:
        print(f"Multiple conversations match customer {args.customer!r} — pass --id to pick one:")
        for r in rows:
            print(f"  id={r[0]} seller={r[1]} name={r[2]!r} status={r[3]} created={r[4]}")
        return None
    return str(rows[0][0])


async def main():
    parser = argparse.ArgumentParser(description="Delete a conversation + dependents (FK-safe).")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", help="Conversation UUID")
    g.add_argument("--customer", help="Customer Instagram id (use --seller to disambiguate)")
    parser.add_argument("--seller", help="Seller UUID (scopes --customer lookup)")
    parser.add_argument("--yes", action="store_true", help="Actually delete (default is dry run)")
    args = parser.parse_args()

    async with worker_session() as session:
        cid = await _resolve_conversation_id(session, args)
        if not cid:
            print("No matching conversation found (or ambiguous). Nothing deleted.")
            return

        # Show a one-line summary of the conversation.
        meta = (await session.execute(text(
            "SELECT seller_id, customer_instagram_id, customer_name, status, created_at "
            "FROM conversations WHERE id = :cid"), {"cid": cid})).first()
        print(f"\nConversation {cid}")
        print(f"  seller={meta[0]} customer_ig={meta[1]} name={meta[2]!r} status={meta[3]} created={meta[4]}")

        # Count rows each step would remove.
        print("\nRows that " + ("WILL be deleted:" if args.yes else "WOULD be deleted (dry run):"))
        total = 0
        for table, where in _DELETE_STEPS:
            n = (await session.execute(
                text(f"SELECT count(*) FROM {table} WHERE {where}"), {"cid": cid}
            )).scalar() or 0
            total += n
            print(f"  {table:24s} {n}")
        print(f"  {'TOTAL':24s} {total}")

        if not args.yes:
            print("\nDry run — nothing deleted. Re-run with --yes to delete.")
            return

        # Delete leaf-first. worker_session commits on clean exit.
        print("\nDeleting…")
        for table, where in _DELETE_STEPS:
            res = await session.execute(text(f"DELETE FROM {table} WHERE {where}"), {"cid": cid})
            print(f"  {table:24s} deleted {res.rowcount}")
        print("\nDone. Conversation and dependents deleted.")


if __name__ == "__main__":
    asyncio.run(main())
