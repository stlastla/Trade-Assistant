"""One-time helper: store the Twelve Data API key in the macOS login Keychain.

Run:  ./venv/bin/python set_api_key.py
"""
import getpass
import keyring

SERVICE, ACCOUNT = "trade-assistant", "twelvedata"


def main():
    key = getpass.getpass("Twelve Data API key (input hidden): ").strip()
    if not key:
        print("No key entered; nothing stored.")
        return
    keyring.set_password(SERVICE, ACCOUNT, key)
    print(f"Stored under Keychain service '{SERVICE}', account '{ACCOUNT}'.")


if __name__ == "__main__":
    main()
