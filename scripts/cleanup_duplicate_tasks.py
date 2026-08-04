"""Script to detect and remove duplicate tasks in SQLite (tasks_cache) and Notion.

Usage:
    python scripts/cleanup_duplicate_tasks.py [--apply]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import config, db
from backend.notion_client import NotionError, _patch


def find_duplicate_tasks() -> dict[str, list[dict]]:
    """Group tasks in tasks_cache by title where count > 1."""
    with db.get_connection() as conn:
        conn.row_factory = db.sqlite3.Row
        title_rows = conn.execute(
            "SELECT title, COUNT(*) as c FROM tasks_cache GROUP BY title HAVING c > 1"
        ).fetchall()
        
        duplicates: dict[str, list[dict]] = {}
        for row in title_rows:
            title = row["title"]
            task_rows = conn.execute(
                "SELECT * FROM tasks_cache WHERE title = ? ORDER BY id ASC",
                (title,)
            ).fetchall()
            duplicates[title] = [dict(r) for r in task_rows]
            
    return duplicates


def select_keeper_and_deletes(tasks: list[dict]) -> tuple[dict, list[dict]]:
    """Determine which task to keep and which to delete.
    
    Priority rules for keeping:
    1. Active status ('Yet' or non-Done) preferred over 'Done' / 'Chancel' IF active exists.
       (Or if all are 'Yet' or all are 'Done', pick the one with highest ID/latest timestamp).
    2. Latest source_updated_at / last_synced_at.
    3. Highest id as fallback.
    """
    def score(task: dict) -> tuple[int, str, int]:
        status = str(task.get("status") or "").lower()
        # Non-terminal statuses get a higher status score
        is_active = 1 if status not in ("done", "chancel", "cancel", "canceled", "cancelled") else 0
        timestamp = str(task.get("source_updated_at") or task.get("last_synced_at") or "")
        task_id = int(task.get("id") or 0)
        return (is_active, timestamp, task_id)

    sorted_tasks = sorted(tasks, key=score, reverse=True)
    keeper = sorted_tasks[0]
    deletes = sorted_tasks[1:]
    return keeper, deletes


def archive_notion_page(external_id: str) -> bool:
    """Archive a page in Notion if configured."""
    if not config.notion_configured() or not external_id:
        return False
    try:
        page_id = external_id.replace("-", "")
        _patch(f"/pages/{page_id}", {"archived": True})
        return True
    except NotionError as err:
        print(f"  [Notion Error] Failed to archive page {external_id}: {err}")
        return False


def run_cleanup(apply: bool = False) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    duplicates = find_duplicate_tasks()
    
    if not duplicates:
        print("重複しているタスクは見つかりませんでした。")
        return
        
    print(f"重複しているタイトル数: {len(duplicates)}")
    print("=" * 60)
    
    all_delete_ids: list[int] = []
    notion_archived_count = 0
    
    for title, tasks in duplicates.items():
        keeper, deletes = select_keeper_and_deletes(tasks)
        delete_ids = [d["id"] for d in deletes]
        all_delete_ids.extend(delete_ids)
        
        print(f"・タイトル: 「{title}」 (合計 {len(tasks)} 件)")
        print(f"   [保持] ID={keeper['id']} | ExternalID={keeper.get('external_id')} | Status={keeper['status']} | Updated={keeper.get('source_updated_at')}")
        for d in deletes:
            print(f"   [削除] ID={d['id']} | ExternalID={d.get('external_id')} | Status={d['status']} | Updated={d.get('source_updated_at')}")
        print("-" * 60)
        
        if apply:
            for d in deletes:
                ext_id = d.get("external_id")
                if ext_id and d.get("source") == "notion":
                    if archive_notion_page(ext_id):
                        notion_archived_count += 1

    print(f"\n合計削除対象レコード数: {len(all_delete_ids)} 件")
    
    if not apply:
        print("\n[DRY RUN モード] 実際の変更・削除は行われていません。")
        print("本反映を行うには `--apply` オプションを付けて実行してください:")
        print("  python scripts/cleanup_duplicate_tasks.py --apply")
    else:
        # Perform DB deletion
        with db.get_connection() as conn:
            placeholders = ",".join("?" for _ in all_delete_ids)
            conn.execute(f"DELETE FROM tasks_cache WHERE id IN ({placeholders})", all_delete_ids)
            
        print(f"\n[実行完了] SQLiteから {len(all_delete_ids)} 件の重複タスクを削除しました。")
        if config.notion_configured():
            print(f"Notionから {notion_archived_count} 件のページをアーカイブ（ゴミ箱移動）しました。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cleanup duplicate tasks")
    parser.add_argument("--apply", action="store_true", help="Apply deletions to Notion and SQLite")
    args = parser.parse_args()
    
    run_cleanup(apply=args.apply)
