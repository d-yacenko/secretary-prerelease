import argparse
import sys
from uuid import UUID

from app.auth.token_service import AuthTokenService
from app.db.session import SessionLocal
from app.services.errors import NotFoundError, ValidationError
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _issue(args: argparse.Namespace) -> int:
    user_id = UUID(args.user_id) if args.user_id else BOOTSTRAP_USER_ID
    session = SessionLocal()
    try:
        service = AuthTokenService(session)
        plaintext, token = service.issue_token(
            user_id=user_id,
            label=args.label,
            expires_in_days=args.expires_days,
        )
        session.commit()
        print(f"user_id={token.user_id}")
        print(f"token_prefix={token.token_prefix}")
        print(f"token={plaintext}")
        return 0
    except (NotFoundError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        session.rollback()
        return 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _revoke(args: argparse.Namespace) -> int:
    user_id = UUID(args.user_id) if args.user_id else BOOTSTRAP_USER_ID
    session = SessionLocal()
    try:
        service = AuthTokenService(session)
        count = service.revoke_by_prefix(user_id=user_id, token_prefix=args.prefix)
        session.commit()
        print(f"revoked={count}")
        return 0
    except (NotFoundError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        session.rollback()
        return 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Secretary bearer token operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="Issue a new bearer token for an existing user")
    issue.add_argument("--user-id", help="Target user UUID (defaults to bootstrap owner)")
    issue.add_argument("--label", help="Operator-visible token prefix label")
    issue.add_argument("--expires-days", type=int, help="Optional expiry in days")
    issue.set_defaults(func=_issue)

    revoke = sub.add_parser("revoke", help="Revoke active tokens matching a prefix label")
    revoke.add_argument("--prefix", required=True, help="Token prefix label to revoke")
    revoke.add_argument("--user-id", help="Owner user UUID (defaults to bootstrap owner)")
    revoke.set_defaults(func=_revoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
