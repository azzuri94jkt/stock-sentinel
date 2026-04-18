"""Generate a default config.yaml if one doesn't already exist.

Run directly (python setup_config.py) or imported by app/main.py on startup.
Safe to re-run — exits immediately if config.yaml is already present.
"""

from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

_DEFAULT_CONFIG = """\
credentials:
  usernames:
    admin:
      email: admin@example.com
      logged_in: false
      name: Admin
      password: "$2b$12$CRBjhTUi2eJma0wuMIc5Se1GTvG/BuZ7aS/vnV4O/or3KxdCvID.K"
    user1:
      email: user1@example.com
      logged_in: false
      name: User One
      password: "$2b$12$nHKcmp54NOg2PNDj.82KteOiIRfr/S9MCc1tq8NibPAAsd/USgS8O"
    user2:
      email: user2@example.com
      logged_in: false
      name: User Two
      password: "$2b$12$Gmz4wLTjfXtMOZYrcWYsseif6z1f8T2VaTZU3ELvGSh14i1yqeVHu"
    user3:
      email: user3@example.com
      logged_in: false
      name: User Three
      password: "$2b$12$bNQAFdBzFWpho5HHbM2a8uVPR5pGTGDI0ecTjWpfbpsdrgFO9Rs92"
    user4:
      email: user4@example.com
      logged_in: false
      name: User Four
      password: "$2b$12$8eYorSXOfoLutkPPBBnEv.ajcmO79zzIIEZx2sV4Mh0WeQhG/JS6."

# All accounts use password: sentinel2026
# To change a password:
#   python3 -c "import bcrypt; print(bcrypt.hashpw(b'newpassword', bcrypt.gensalt(12)).decode())"
# Then replace the password value above (keep the quotes).

cookie:
  expiry_days: 30
  key: "stock-sentinel-cookie-key-change-in-production"
  name: "stock_sentinel_auth"
"""


def ensure_config() -> bool:
    """Write default config.yaml if missing. Returns True if file was created."""
    if _CONFIG_PATH.exists():
        return False
    _CONFIG_PATH.write_text(_DEFAULT_CONFIG)
    print(f"Created default config.yaml at {_CONFIG_PATH}")
    return True


if __name__ == "__main__":
    created = ensure_config()
    if not created:
        print(f"config.yaml already exists at {_CONFIG_PATH} — nothing to do.")
