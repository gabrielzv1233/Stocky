import json, argparse
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]

# ────────────────────────────────────────────────────────────────
def auth(creds_path: str):
    with open(creds_path, "r") as f:
        info = json.load(f)
    return build("drive", "v3",
                 credentials=Credentials.from_service_account_info(info, scopes=SCOPES))
# ────────────────────────────────────────────────────────────────
def dump_everything(drive):
    print("\n=== EVERY ACCESSIBLE FILE / FOLDER ===")
    token, count = None, 0
    while True:
        resp = drive.files().list(
            q="trashed=false",
            corpora="allDrives", includeItemsFromAllDrives=True, supportsAllDrives=True,
            fields=("nextPageToken,"
                    "files(id,name,mimeType,driveId,parents,webViewLink,"
                    "owners(emailAddress))"),
            pageSize=1000, pageToken=token
        ).execute()

        for f in resp.get("files", []):
            count += 1
            kind   = "FOLDER" if f["mimeType"] == "application/vnd.google-apps.folder" else "FILE"
            owners = ", ".join(o["emailAddress"] for o in f.get("owners", [])) or "(unknown)"
            print(f"\n• {kind:6}  {f['name']}")
            print(f"  ID      : {f['id']}")
            print(f"  DriveId : {f.get('driveId','MyDrive')}")
            print(f"  Parents : {', '.join(f.get('parents', [])) or '(root)'}")
            print(f"  Owners  : {owners}")
            print(f"  Link    : {f.get('webViewLink','(no link)')}")

        token = resp.get("nextPageToken")
        if not token:
            break
    print(f"\nTotal items visible to the service-account: {count}")

# ────────────────────────────────────────────────────────────────
def check_folder(drive, fid: str):
    print(f"\n=== Folder sanity-check: {fid} ===")
    try:
        meta = drive.files().get(
            fileId=fid,
            fields="id,name,permissions(emailAddress,role,type)",
            supportsAllDrives=True
        ).execute()
        print("✓ Accessible:", meta['name'])
        for p in meta.get("permissions", []):
            print(f"   {p['role']:7} – {p['type']} ({p.get('emailAddress','n/a')})")
    except HttpError as e:
        print("✗ Cannot access:", e)

# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--creds", default="creds.json", help="service-account JSON file")
    ap.add_argument("--folder", help="optional folder-ID to test separately")
    args = ap.parse_args()

    drv = auth(args.creds)
    dump_everything(drv)
    if args.folder:
        check_folder(drv, args.folder)
