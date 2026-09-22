"""Administrative commands (run inside the backend environment).

  python -m app.cli create-key --role specialist --label "Иванова А., УОЗ г. Астана"   (make create-key)
  python -m app.cli seed-demo-key          key from DEMO_API_KEY, role specialist (backend container start)
  python -m app.cli list-keys
  python -m app.cli revoke-key --id 3
  python -m app.cli publish-assurance --bundle /path/to/model_assurance.json
  python -m app.cli publish-operational-intelligence --bundle /path/to/operational_intelligence.json

create-key prints the key once; only its SHA-256 is stored.
"""

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.security import KEY_PREFIX, ROLES
from app.db.session import SessionLocal
from app.services import admin, model_assurance
from app.services.common import ConflictError, ValidationError

DEMO_LABEL = "demo (DEMO_API_KEY)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-key", help="create an API key and print it once")
    create.add_argument("--role", choices=ROLES, required=True)
    create.add_argument("--label", required=True, help="who or what uses the key")
    sub.add_parser("seed-demo-key", help="ensure the DEMO_API_KEY from the environment exists (role specialist)")
    sub.add_parser("list-keys", help="list keys (prefix, role, label, revoked)")
    revoke = sub.add_parser("revoke-key", help="revoke a key by id")
    revoke.add_argument("--id", type=int, required=True)
    publish = sub.add_parser("publish-assurance", help="validate and publish a Model Assurance JSON bundle")
    publish.add_argument("--bundle", type=Path, required=True)
    publish_operational = sub.add_parser(
        "publish-operational-intelligence",
        help="validate and publish an operational-intelligence JSON bundle",
    )
    publish_operational.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        if args.command == "create-key":
            if not args.label.strip():
                parser.error("--label must not be empty")
            created = admin.create_key(session, args.role, args.label.strip())
            print(f"API key for {created.label!r} (role {created.role}, id {created.id}) — shown only once:")
            print(created.key)
            return 0
        if args.command == "seed-demo-key":
            key = get_settings().demo_api_key
            if not key:
                print("DEMO_API_KEY is not set: no demo key seeded")
                return 0
            if not key.startswith(KEY_PREFIX) or len(key) < 32:
                print(f"DEMO_API_KEY must start with {KEY_PREFIX!r} and be at least 32 characters", file=sys.stderr)
                return 2
            info, created = admin.ensure_key(session, key, "specialist", DEMO_LABEL)
            state = "created" if created else ("exists, REVOKED" if info.revoked_at else "exists")
            print(f"demo key {info.key_prefix}… (role {info.role}, id {info.id}): {state}")
            return 0
        if args.command == "list-keys":
            for k in admin.list_keys(session):
                revoked = f"revoked {k.revoked_at:%Y-%m-%d %H:%M}" if k.revoked_at else "active"
                print(f"{k.id:>4}  {k.key_prefix}…  {k.role:<10}  {revoked:<24}  {k.label}")
            return 0
        if args.command == "publish-assurance":
            try:
                parsed = model_assurance.load_assurance_bundle(args.bundle)
                result = model_assurance.publish(session, parsed)
            except (ValidationError, ConflictError) as exc:
                print(f"Model Assurance publication failed: {exc}", file=sys.stderr)
                return 2
            state = "published" if result.created else "already published; activated"
            print(
                f"Model Assurance {result.assurance_id} {state} "
                f"(snapshot {result.snapshot_id}, identity {result.assurance_identity_sha256})"
            )
            return 0
        if args.command == "publish-operational-intelligence":
            from app.services import operational_intelligence

            try:
                parsed = operational_intelligence.load_bundle(args.bundle)
                result = operational_intelligence.publish(session, parsed)
            except (ValidationError, ConflictError) as exc:
                print(f"Operational-intelligence publication failed: {exc}", file=sys.stderr)
                return 2
            state = "published" if result.created else "already published; activated"
            print(
                f"Operational intelligence {result.publication_id} {state} "
                f"(snapshot {result.snapshot_id}, identity {result.publication_identity_sha256})"
            )
            return 0
        info = admin.revoke_key(session, args.id)
        print(f"key {info.id} ({info.label}) revoked at {info.revoked_at}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
