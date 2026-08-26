import base64
import json
import os
import re
import uuid
from urllib.parse import urlparse

import dotenv
import requests

dotenv.load_dotenv()  # .env Datei laden, damit os.environ die Variablen hat
BASE = "https://nutzerportal.brunata-muenchen.de"
SAP_CLIENT = "201"

EMAIL = os.environ["BRU_EMAIL"]
PASSWORD = os.environ["BRU_PASSWORD"]

LOGON_SRV_ROOT = f"{BASE}/sap/opu/odata/bme/NP_REG_LOGON_SRV_01/"
BATCH_URL = f"{LOGON_SRV_ROOT}$batch?sap-client={SAP_CLIENT}"

def fetch_csrf(session: requests.Session) -> str | None:
    # HEAD wie bei dir: holt i.d.R. x-csrf-token + setzt ggf. SAP Session Cookies
    r = session.head(
        f"{LOGON_SRV_ROOT}?sap-client={SAP_CLIENT}",
        headers={
            "Accept": "application/json",
            "x-csrf-token": "Fetch",
            "X-Requested-With": "XMLHttpRequest",
            "sap-contextid-accept": "header",
        },
        allow_redirects=False,
    )
    # Token kann fehlen, je nach Config – dann versuchen wir es trotzdem
    return r.headers.get("x-csrf-token")

def build_batch_body(email: str, password_plain: str, sap_client: str) -> tuple[str, str]:
    batch_boundary = f"batch_{uuid.uuid4().hex}"
    changeset_boundary = f"changeset_{uuid.uuid4().hex}"

    pw_b64 = base64.b64encode(password_plain.encode("utf-8")).decode("ascii")
    payload = {"Action": "validLCR", "Email": email, "Password": pw_b64}
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_len = len(payload_json.encode("utf-8"))

    # SAP Batch ist extrem pingelig mit CRLF
    crlf = "\r\n"
    body = (
        f"--{batch_boundary}{crlf}"
        f"Content-Type: multipart/mixed; boundary={changeset_boundary}{crlf}{crlf}"
        f"--{changeset_boundary}{crlf}"
        f"Content-Type: application/http{crlf}"
        f"Content-Transfer-Encoding: binary{crlf}{crlf}"
        f"POST CredentialSet?sap-client={sap_client} HTTP/1.1{crlf}"
        f"X-Requested-With: XMLHttpRequest{crlf}"
        f"sap-contextid-accept: header{crlf}"
        f"Accept: application/json{crlf}"
        f"Accept-Language: de{crlf}"
        f"DataServiceVersion: 2.0{crlf}"
        f"MaxDataServiceVersion: 2.0{crlf}"
        f"Content-Type: application/json{crlf}"
        f"Content-ID: 1{crlf}"
        f"Content-Length: {payload_len}{crlf}{crlf}"
        f"{payload_json}{crlf}"
        f"--{changeset_boundary}--{crlf}{crlf}"
        f"--{batch_boundary}--{crlf}"
    )
    content_type = f"multipart/mixed; boundary={batch_boundary}"
    return body, content_type

def extract_first_json(text: str) -> dict:
    # Quick&dirty: in SAP Multipart steckt irgendwo JSON. Wir ziehen das erste JSON-Objekt raus.
    # (Wenn du willst, baue ich dir auch einen sauberen Multipart-Parser.)
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise RuntimeError(
            "Kein JSON in Batch-Response gefunden. "
            "Wahrscheinlich Login fehlgeschlagen oder HTML/Redirect."
        )
    return json.loads(m.group(0))

def normalize_service_url(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/"):
        return f"{BASE}{raw}"
    parsed = urlparse(raw)
    if parsed.scheme:
        return raw
    # If SAP returns a host/path without scheme, default to https
    return f"https://{raw}"

with requests.Session() as s:
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "de",
    })

    # wichtig: sap-usercontext cookie wie bei dir
    s.cookies.set(
        "sap-usercontext",
        f"sap-client={SAP_CLIENT}",
        domain="nutzerportal.brunata-muenchen.de",
    )

    # Optional: Portal-Seite einmal laden (manchmal setzt das weitere Cookies)
    s.get(f"{BASE}/np_anmeldung/index.html?sap-language=DE")

    csrf = fetch_csrf(s)

    body, content_type = build_batch_body(EMAIL, PASSWORD, SAP_CLIENT)

    headers = {
        "Accept": "multipart/mixed",
        "Content-Type": content_type,
        "X-Requested-With": "XMLHttpRequest",
        "sap-contextid-accept": "header",
        "Referer": f"{BASE}/np_anmeldung/index.html?sap-language=DE",
        "Origin": BASE,
    }
    if csrf:
        headers["x-csrf-token"] = csrf

    r = s.post(BATCH_URL, headers=headers, data=body.encode("utf-8"))
    # Typisch: 202 Accepted
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Batch-Login fehlgeschlagen: {r.status_code}\n{r.text[:5000]}")

    data = extract_first_json(r.text)

    # Erwartete Struktur: {"d": {"Userid", "Password", "Serviceurl", ...}}
    d = data.get("d") or {}
    userid = d.get("Userid")
    pw_resp_b64 = d.get("Password")
    serviceurl = d.get("Serviceurl")

    if not userid or not pw_resp_b64:
        raise RuntimeError(
            "Login-Response hat keine Userid/Password Felder.\n"
            f"Keys: {list(d.keys())}\nRaw JSON: {data}"
        )

    sap_pw = base64.b64decode(pw_resp_b64).decode("utf-8", errors="replace")
    print("SAP BasicAuth User:", userid)
    print("Serviceurl:", serviceurl)

    # Manche Flows rufen serviceurl einmal auf, um den Zustand zu finalisieren
    normalized_serviceurl = normalize_service_url(serviceurl)
    if normalized_serviceurl:
        s.get(normalized_serviceurl, auth=(userid, sap_pw))

    # Ab hier: alle weiteren OData Calls mit Basic Auth
    # Beispiel: $metadata von einem Service (muss du im Network Tab finden)
    # meta = s.get(f"{BASE}/sap/opu/odata/bme/NP_DASHBOARD_SRV_01/$metadata?...",
    #              auth=(userid, sap_pw), params={"sap-client": SAP_CLIENT})
    # print(meta.status_code)
