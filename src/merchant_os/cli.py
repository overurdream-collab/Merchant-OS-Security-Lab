import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .database import DB_PATH
from .database_audit import audit_database
from .migrations import apply_migrations, create_backup
from .commerce_agent import CommerceControlPlane
from .professor import build_runtime, run_professor


def main():
    parser = argparse.ArgumentParser(description="Merchant OS Agent Runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("agents", help="List registered agents")

    context = sub.add_parser("commerce-context", help="Read the Commerce agent project memory")
    context.add_argument("--root", default=".", help="Merchant OS repository root")

    run = sub.add_parser("run", help="Run Professor against a JSON payload")
    run.add_argument("--goal", required=True)
    run.add_argument("--payload", required=True, help="JSON object")

    audit = sub.add_parser("db-audit", help="Read-only audit of the SQLite database")
    audit.add_argument("--database", default=DB_PATH, help="SQLite database path")

    migrate = sub.add_parser("db-migrate", help="Back up the SQLite database and apply pending migrations")
    migrate.add_argument("--database", default=DB_PATH, help="SQLite database path")
    migrate.add_argument("--backup", help="Use this pre-existing backup only if it exactly matches the database")

    args = parser.parse_args()

    if args.command == "agents":
        print(json.dumps(build_runtime().list_agents(), ensure_ascii=False, indent=2))
        return

    if args.command == "commerce-context":
        control = CommerceControlPlane(args.root)
        print(json.dumps({
            "project_root": str(control.memory.root),
            "current_phase": control.memory.current_phase(),
            "next_phase": control.memory.next_phase(),
            "documents": control.memory.load(),
            "approval_required_for_actions": True,
            "reasoning_provider": "interface_only",
        }, ensure_ascii=True, indent=2))
        return

    if args.command == "db-audit":
        print(json.dumps(audit_database(args.database), ensure_ascii=False, indent=2))
        return

    if args.command == "db-migrate":
        database = Path(args.database)
        if not database.is_file():
            parser.error(f"Database does not exist: {database}")
        if args.backup:
            backup = Path(args.backup)
            if not backup.is_file():
                parser.error(f"Backup does not exist: {backup}")
            source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
            backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
            if source_hash != backup_hash:
                parser.error("Provided backup does not match the current database; refusing to migrate")
        else:
            backup_dir = database.parent / "backups"
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            backup = backup_dir / f"{database.stem}_pre_migration_{stamp}{database.suffix}"
            suffix = 1
            while backup.exists():
                backup = backup_dir / f"{database.stem}_pre_migration_{stamp}_{suffix}{database.suffix}"
                suffix += 1
            create_backup(database, backup)
        result = apply_migrations(database)
        result["backup_path"] = str(backup.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    payload = json.loads(args.payload)
    result = run_professor(args.goal, payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
