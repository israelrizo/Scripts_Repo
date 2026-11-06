#!/usr/bin/env python3
"""CLI user management (run on the Master):

  python3 manage_users.py add alice --role admin      # prompts for password
  python3 manage_users.py passwd alice
  python3 manage_users.py role alice operator
  python3 manage_users.py delete alice
  python3 manage_users.py list
"""
import argparse
import getpass
import sys

from srapp import users


def _ask():
    p1 = getpass.getpass("Password: ")
    if p1 != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    return p1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("username"); a.add_argument("--role", default="operator", choices=users.ROLES)
    p = sub.add_parser("passwd"); p.add_argument("username")
    r = sub.add_parser("role"); r.add_argument("username"); r.add_argument("role", choices=users.ROLES)
    d = sub.add_parser("delete"); d.add_argument("username")
    sub.add_parser("list")
    args = ap.parse_args()
    try:
        if args.cmd == "add":
            users.create(args.username, _ask(), args.role)
        elif args.cmd == "passwd":
            users.set_password(args.username, _ask())
        elif args.cmd == "role":
            users.set_role(args.username, args.role)
        elif args.cmd == "delete":
            users.delete(args.username)
        elif args.cmd == "list":
            for u in users.list_users():
                print(f"{u['username']:<24} {u['role']}")
            return
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print("OK")


if __name__ == "__main__":
    main()
