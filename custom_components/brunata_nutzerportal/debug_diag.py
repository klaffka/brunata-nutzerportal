from __future__ import annotations

import re
from uuid import uuid4

from brunata_api.errors import LoginError


async def diagnose_dashboard_batch(client) -> dict:
    await client.login()

    info = {
        "user_unit_id": getattr(client, "_user_unit_id", None),
        "contact_person": getattr(client, "_contact_person", None),
    }

    uid = info["user_unit_id"]
    if not uid:
        raise LoginError("No UserUnitID present for diagnostics.")

    rel = (
        f"DatesSet?sap-client={client.sap_client}"
        f"&$expand=Units&$filter=Nutzein%20eq%20%27{uid}%27"
    )

    csrf = await client._fetch_csrf_token("NP_DASHBOARD_SRV", referer=client._referer_services())
    boundary = f"batch_{uuid4().hex[:4]}-{uuid4().hex[:4]}-{uuid4().hex[:4]}"

    body = client._build_batch_get(
        boundary=boundary,
        relative_get=rel,
        extra_headers={
            "sap-cancel-on-close": "true",
            "UserUnitID": info["user_unit_id"] or "",
            "ContactPerson": info["contact_person"] or "",
            "sap-contextid-accept": "header",
            "Accept": "application/json",
            "x-csrf-token": csrf,
            "Accept-Language": "de",
            "DataServiceVersion": "2.0",
            "MaxDataServiceVersion": "2.0",
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    headers = {
        **client._odata_headers(
            referer=client._referer_services(),
            csrf_token=csrf,
            user_unit_id=info["user_unit_id"],
            contact_person=info["contact_person"],
        ),
        "Accept": "multipart/mixed",
        "Content-Type": f"multipart/mixed;boundary={boundary}",
    }

    r = await client._post_batch("NP_DASHBOARD_SRV", body=body, headers=headers)

    text = r.text or ""
    info["outer_status"] = r.status_code
    info["outer_content_type"] = r.headers.get("content-type")

    m = re.search(r"HTTP/1\.1\s+(?P<code>\d{3})\s+(?P<msg>[^\r\n]+)", text)
    if m:
        info["inner_status_code"] = int(m.group("code"))
        info["inner_status_msg"] = m.group("msg")

    loc = re.search(r"\r\nLocation:\s*(?P<loc>[^\r\n]+)", text, flags=re.IGNORECASE)
    if loc:
        info["inner_location"] = loc.group("loc")

    try:
        info["cookie_names"] = sorted({c.name for c in client._client.cookies.jar})
    except Exception:
        info["cookie_names"] = []

    info["body_snippet"] = text[:400].replace("\n", "\\n").replace("\r", "\\r")

    try:
        objs = client._extract_json_objects(text)
        info["json_objects_found"] = len(objs)
        if objs:
            info["json_top_keys"] = [sorted(list(o.keys())) for o in objs[:5]]
    except Exception:
        info["json_objects_found"] = None

    return info
