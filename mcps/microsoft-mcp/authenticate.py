#!/usr/bin/env python3
"""
Authenticate Microsoft accounts for use with Microsoft MCP.
Run this script to sign in to one or more Microsoft accounts.
"""

import sys
import argparse
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv, find_dotenv
from microsoft_mcp import auth
from microsoft_mcp.settings import MicrosoftSettings

load_dotenv(find_dotenv())


def main():
    parser = argparse.ArgumentParser(description="Authenticate Microsoft accounts")
    parser.add_argument("--data-dir", type=str, default="./data", help="Directory for storing token cache")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_file = data_dir / "auth_cache.bin"

    try:
        settings = MicrosoftSettings()
    except Exception as e:
        print(f"Error loading settings: {e}")
        print("\nPlease set MICROSOFT_MCP_CLIENT_ID in your .env file")
        sys.exit(1)

    print("Microsoft MCP Authentication")
    print("============================\n")

    # List current accounts
    accounts = auth.list_accounts(cache_file, settings=settings)
    if accounts:
        print("Currently authenticated accounts:")
        for i, account in enumerate(accounts, 1):
            print(f"{i}. {account.username} (ID: {account.account_id})")
        print()
    else:
        print("No accounts currently authenticated.\n")

    # Authenticate new account
    print("Starting authentication flow...\n")
    try:
        new_account = auth.authenticate_new_account(cache_file, ["https://graph.microsoft.com/.default"], settings=settings)

        if new_account:
            print("\n✓ Authentication successful!")
            print(f"Signed in as: {new_account.username}")
            print(f"Account ID: {new_account.account_id}")
        else:
            print("\n✗ Authentication failed: Could not retrieve account information")
    except Exception as e:
        print(f"\n✗ Authentication failed: {e}")

    # Final account summary
    accounts = auth.list_accounts(cache_file, settings=settings)
    if accounts:
        print("\nAuthenticated accounts summary:")
        print("==============================")
        for account in accounts:
            print(f"• {account.username}")
            print(f"  Account ID: {account.account_id}")

        print("\nYou can use these account IDs with any MCP tool by passing account_id parameter.")
        print("Example: send_email(..., account_id='<account-id>')")
    else:
        print("\nNo accounts authenticated.")

    print("\nAuthentication complete!")


if __name__ == "__main__":
    main()
