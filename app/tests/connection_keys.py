"""Fake service-account keys for the module 01 tests (no real secret inside)."""

import json

PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC-not-a-real-key-SECRETBODY\n-----END PRIVATE KEY-----\n"
FULL_KEY_ID = "0123456789abcdef0123456789abcdefKEYID9"


def make_key(project="demo-project-123", key_id=FULL_KEY_ID, **over):
    key = {
        "type": "service_account",
        "project_id": project,
        "private_key_id": key_id,
        "private_key": PEM,
        "client_email": f"vertex@{project}.iam.gserviceaccount.com",
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    key.update(over)
    return {k: v for k, v in key.items() if v is not None}


def upload(client, payload, name="key.json"):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post("/api/connection/key", files={"file": (name, data, "application/json")})
