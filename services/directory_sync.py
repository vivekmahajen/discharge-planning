"""CMS + CDPH data sync for post-acute directory."""
from __future__ import annotations
import time
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

CMS_API = "https://data.cms.gov/provider-data/api/1/datastore/query/4pq5-n9py/0"
CHHS_API = "https://data.chhs.ca.gov/api/3/action/datastore_search"
CDPH_LOCATIONS_RESOURCE = "e1e6cfa7-94cc-4ac4-9932-f0c34d5ea3c4"
CDPH_BEDS_RESOURCE = "7e7e6a49-a27e-4b5a-bf1d-e42e6a2b0e35"

# A browser-like User-Agent: the CMS / CHHS endpoints sit behind a WAF that
# returns 403 to requests with a default client (e.g. python-httpx) UA.
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Fail fast: a dropped/black-holed connection must not hang a serverless
# invocation for minutes. Bounded connect + read timeouts keep the sync
# resolving (to data or to a clear error) quickly.
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=8.0, pool=5.0)


def debug_cms_fetch() -> dict:
    """Diagnostic probe: report exactly what this host sees when calling the
    CMS endpoint (POST and GET), plus a control request to a known-reachable
    host to distinguish a CMS-specific block from a total egress block."""
    import time as _t

    def probe(method: str, url: str, **kw) -> dict:
        t0 = _t.time()
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS, follow_redirects=True) as c:
                r = c.request(method, url, **kw)
            return {"ok": True, "status": r.status_code,
                    "elapsed_ms": int((_t.time() - t0) * 1000),
                    "body_snippet": (r.text or "")[:200]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((_t.time() - t0) * 1000)}

    payload = {"conditions": [{"property": "state", "value": "CA", "operator": "="}],
               "limit": 1, "offset": 0}
    get_params = [
        ("conditions[0][property]", "state"),
        ("conditions[0][operator]", "="),
        ("conditions[0][value]", "CA"),
        ("limit", "1"),
    ]

    def schema_probe() -> dict:
        """Unfiltered single-row fetch to reveal the dataset's real column names."""
        t0 = _t.time()
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS, follow_redirects=True) as c:
                r = c.get(CMS_API, params=[("limit", "1")])
            data = r.json() if r.status_code == 200 else {}
            results = data.get("results", data.get("data", []))
            cols = sorted(results[0].keys()) if results else []
            return {"ok": r.status_code == 200, "status": r.status_code,
                    "elapsed_ms": int((_t.time() - t0) * 1000), "columns": cols}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((_t.time() - t0) * 1000)}

    return {
        "cms_api": CMS_API,
        "cms_post": probe("POST", CMS_API, json=payload),
        "cms_get": probe("GET", CMS_API, params=get_params),
        "cms_schema": schema_probe(),
        "egress_control": probe("GET", "https://api.github.com"),
    }


def _safe_int(val) -> Optional[int]:
    """Convert val to int or None."""
    if val is None or val == "":
        return None
    try:
        return int(float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    """Convert val to float or None."""
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _cms_query_page(client: "httpx.Client", offset: int, limit: int) -> dict:
    """Fetch one page of CMS data. Tries POST, then falls back to a GET with
    the same conditions (some WAF configurations reject the POST body).
    Raises the last httpx error if both fail."""
    payload = {
        "conditions": [{"property": "state", "value": "CA", "operator": "="}],
        "limit": limit,
        "offset": offset,
    }
    last_err: Exception | None = None
    try:
        resp = client.post(CMS_API, json=payload)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        last_err = e

    params = [
        ("conditions[0][property]", "state"),
        ("conditions[0][operator]", "="),
        ("conditions[0][value]", "CA"),
        ("limit", str(limit)),
        ("offset", str(offset)),
    ]
    try:
        resp = client.get(CMS_API, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        last_err = e
    raise last_err if last_err else RuntimeError("CMS query failed")


def fetch_cms_ca_facilities() -> list[dict]:
    """
    Fetch all CA nursing home facilities from CMS PDC.
    Paginate in pages of 500 (the datastore rejects larger limits with 400),
    retrying each page a couple of times with backoff.
    Raises RuntimeError if the very first page cannot be fetched, so the sync
    surfaces the real reason (e.g. a 403) instead of silently reporting 0.
    """
    facilities: list[dict] = []
    offset = 0
    limit = 500  # CMS datastore caps page size; 2000 returns HTTP 400
    max_retries = 2

    with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS, follow_redirects=True) as client:
        while True:
            data = None
            last_err: Exception | None = None
            for attempt in range(max_retries):
                try:
                    data = _cms_query_page(client, offset, limit)
                    break
                except httpx.HTTPError as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)

            if data is None:
                if offset == 0:
                    # Nothing was fetched at all — make the failure visible.
                    raise RuntimeError(f"CMS API request failed: {last_err}")
                logger.error("CMS fetch stopped at offset %d: %s", offset, last_err)
                break

            results = data.get("results", data.get("data", []))
            if not results:
                break

            for r in results:
                facility = _map_cms_record(r)
                if facility:
                    facilities.append(facility)

            if len(results) < limit:
                break
            offset += limit
            time.sleep(0.5)

    logger.info("Fetched %d CMS CA facilities", len(facilities))
    return facilities


def _first(r: dict, *keys, default=None):
    """Return the first non-empty value among candidate column names."""
    for k in keys:
        v = r.get(k)
        if v is not None and v != "":
            return v
    return default


def _map_cms_record(r: dict) -> Optional[dict]:
    """Map a single CMS record to our schema. Field names follow the current
    CMS Provider Data Catalog datastore machine names (e.g. `state`, `zip_code`,
    `citytown`), with older `provider_*` variants accepted as fallbacks."""
    ccn = _first(r, "cms_certification_number_ccn", "federal_provider_number", "provnum", "ccn")
    if not ccn:
        return None

    # Determine facility type (this dataset is nursing homes; default SNF)
    provider_type = str(_first(r, "provider_type", default="") or "").lower()
    if "rehabilitation" in provider_type or "irf" in provider_type:
        facility_type = "IRF"
    elif "long term" in provider_type or "ltach" in provider_type:
        facility_type = "LTACH"
    else:
        facility_type = "SNF"

    # Zero-pad zip to 5 chars
    raw_zip = str(_first(r, "zip_code", "provider_zip_code", "zip", default="") or "").strip()
    if raw_zip and raw_zip.isdigit():
        zip_code = raw_zip.zfill(5)
    else:
        zip_code = raw_zip[:5] if raw_zip else None

    # Boolean fields
    medicare = str(_first(r, "medicare_provider_agreement", default="") or "").upper() == "Y"
    medicaid = str(_first(r, "medicaid_provider_agreement", default="") or "").upper() == "Y"

    sff_status = str(_first(r, "special_focus_status", default="") or "").upper()
    is_sff = "SFF" in sff_status
    is_sff_candidate = "CANDIDATE" in sff_status

    abuse = str(_first(r, "abuse_icon", default="") or "").upper() == "Y"

    # Name: strip and title-case
    name = str(_first(r, "provider_name", default="") or "").strip()
    if name:
        name = name.title()

    return {
        "ccn": str(ccn).strip(),
        "name": name,
        "facility_type": facility_type,
        "address": str(_first(r, "provider_address", "address", default="") or "").strip() or None,
        "city": str(_first(r, "citytown", "city_town", "provider_city", "city", default="") or "").strip() or None,
        "state": str(_first(r, "state", "provider_state", default="CA") or "CA").strip(),
        "zip": zip_code,
        "phone": str(_first(r, "telephone_number", "phone_number", default="") or "").strip() or None,
        "county": str(_first(r, "countyparish", "county_parish", "county_name", "county", default="") or "").strip() or None,
        "overall_rating": _safe_int(r.get("overall_rating")),
        "health_inspection_rating": _safe_int(r.get("health_inspection_rating")),
        "staffing_rating": _safe_int(r.get("staffing_rating")),
        "quality_measures_rating": _safe_int(_first(r, "qm_rating", "quality_measure_rating")),
        "certified_beds": _safe_int(_first(r, "number_of_certified_beds", "certified_beds")),
        "average_daily_census": _safe_float(_first(r, "average_number_of_residents_per_day")),
        "ownership_type": str(_first(r, "ownership_type", default="") or "").strip() or None,
        "medicare_certified": medicare,
        "medicaid_certified": medicaid,
        "accepts_medi_cal": medicaid,
        "is_special_focus": is_sff,
        "is_special_focus_candidate": is_sff_candidate,
        "abuse_icon": abuse,
        "total_fines_dollars": _safe_float(_first(r, "total_amount_of_fines_in_dollars")) or 0,
        "number_of_fines": _safe_int(_first(r, "number_of_fines")) or 0,
        "total_penalties": _safe_int(_first(r, "total_number_of_penalties")) or 0,
        "data_source": "CMS",
        # CMS now publishes coordinates directly; ZIP-centroid fallback in
        # run_full_sync fills any that are missing.
        "latitude": _safe_float(r.get("latitude")),
        "longitude": _safe_float(r.get("longitude")),
        "cdph_facid": None,
        "licensed_snf_beds": 0,
        "licensed_icf_beds": 0,
        "licensed_alf_beds": 0,
        "licensed_total_beds": 0,
    }


def fetch_cdph_ca_facilities() -> dict[str, dict]:
    """
    Fetch CA facility locations from CDPH CHHS.
    Returns dict keyed by FACID with lat/lon and bed counts.
    Graceful degradation on error.
    """
    result: dict[str, dict] = {}

    try:
        _fetch_cdph_locations(result)
        _fetch_cdph_beds(result)
    except Exception as e:
        logger.warning("CDPH fetch failed, continuing without: %s", e)
        return {}

    return result


def _fetch_cdph_locations(result: dict[str, dict]) -> None:
    """Fetch location data from CDPH and populate result dict."""
    offset = 0
    limit = 1000
    with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS, follow_redirects=True) as client:
        while True:
            try:
                resp = client.get(
                    CHHS_API,
                    params={
                        "resource_id": CDPH_LOCATIONS_RESOURCE,
                        "limit": limit,
                        "offset": offset,
                    }
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning("CDPH locations fetch error: %s", e)
                break

            records = data.get("result", {}).get("records", [])
            if not records:
                break

            for rec in records:
                status = str(rec.get("STATUS", "") or "").upper()
                factype = str(rec.get("FACTYPE_DESC", "") or "").upper()

                if status != "LICENSED":
                    continue
                if not any(x in factype for x in ["SKILLED NURSING", "REHABILITATION", "INTERMEDIATE CARE"]):
                    continue

                facid = str(rec.get("FACID", "") or "").strip()
                if not facid:
                    continue

                lat = _safe_float(rec.get("LATITUDE") or rec.get("latitude"))
                lon = _safe_float(rec.get("LONGITUDE") or rec.get("longitude"))

                if facid not in result:
                    result[facid] = {
                        "cdph_facid": facid,
                        "latitude": lat,
                        "longitude": lon,
                        "name": str(rec.get("FACNAME", "") or "").strip(),
                        "zip": str(rec.get("ZIP", "") or "").strip(),
                        "licensed_snf_beds": 0,
                        "licensed_icf_beds": 0,
                        "licensed_alf_beds": 0,
                        "licensed_total_beds": 0,
                    }
                else:
                    if lat:
                        result[facid]["latitude"] = lat
                    if lon:
                        result[facid]["longitude"] = lon

            if len(records) < limit:
                break
            offset += limit
            time.sleep(0.3)


def _fetch_cdph_beds(result: dict[str, dict]) -> None:
    """Fetch bed counts from CDPH and add to result dict."""
    offset = 0
    limit = 1000
    with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS, follow_redirects=True) as client:
        while True:
            try:
                resp = client.get(
                    CHHS_API,
                    params={
                        "resource_id": CDPH_BEDS_RESOURCE,
                        "limit": limit,
                        "offset": offset,
                    }
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning("CDPH beds fetch error: %s", e)
                break

            records = data.get("result", {}).get("records", [])
            if not records:
                break

            for rec in records:
                facid = str(rec.get("FACID", "") or "").strip()
                if not facid or facid not in result:
                    continue

                bed_type = str(rec.get("BED_TYPE", "") or "").upper()
                bed_count = _safe_int(rec.get("BEDS", 0)) or 0

                if "SNF" in bed_type or "SKILLED" in bed_type:
                    result[facid]["licensed_snf_beds"] = (result[facid].get("licensed_snf_beds") or 0) + bed_count
                elif "ICF" in bed_type or "INTERMEDIATE" in bed_type:
                    result[facid]["licensed_icf_beds"] = (result[facid].get("licensed_icf_beds") or 0) + bed_count
                elif "ALF" in bed_type or "ASSISTED" in bed_type:
                    result[facid]["licensed_alf_beds"] = (result[facid].get("licensed_alf_beds") or 0) + bed_count

                result[facid]["licensed_total_beds"] = (
                    (result[facid].get("licensed_snf_beds") or 0)
                    + (result[facid].get("licensed_icf_beds") or 0)
                    + (result[facid].get("licensed_alf_beds") or 0)
                )

            if len(records) < limit:
                break
            offset += limit
            time.sleep(0.3)


def _match_cdph(cms_facility: dict, cdph_by_zip: dict[str, list[dict]]) -> Optional[dict]:
    """
    Try to match a CMS facility to a CDPH facility.
    1. Exact: same zip, first 8 chars of name match
    2. Fuzzy: same zip, SequenceMatcher ratio > 0.7
    """
    zip_code = cms_facility.get("zip", "")
    cms_name = (cms_facility.get("name") or "").upper().strip()

    candidates = cdph_by_zip.get(zip_code, [])
    if not candidates:
        return None

    cms_prefix = cms_name[:8]

    # Pass 1: exact prefix match
    for cdph in candidates:
        cdph_name = (cdph.get("name") or "").upper().strip()
        if cdph_name[:8] == cms_prefix:
            return cdph

    # Pass 2: fuzzy match
    try:
        from difflib import SequenceMatcher
        best_ratio = 0.0
        best_match = None
        for cdph in candidates:
            cdph_name = (cdph.get("name") or "").upper().strip()
            ratio = SequenceMatcher(None, cms_name, cdph_name).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = cdph
        if best_ratio > 0.7:
            return best_match
    except Exception:
        pass

    return None


def run_full_sync(triggered_by: str = "scheduled") -> dict:
    """
    Full sync: fetch CMS + CDPH, match, upsert, deactivate stale, seed zips.
    Returns summary dict.
    """
    from db.directory import (
        start_sync_log, finish_sync_log, upsert_facilities,
        deactivate_missing_facilities, seed_zip_coordinates, get_all_zip_coords,
    )
    import os
    from pathlib import Path

    log_id = start_sync_log(triggered_by)
    start_time = time.time()
    upserted = 0
    deactivated = 0

    try:
        # Fetch CMS data
        cms_facilities = fetch_cms_ca_facilities()
        logger.info("CMS returned %d facilities", len(cms_facilities))

        # Ensure ZIP centroids are seeded, then load them for the coordinate
        # fallback below. CMS records carry no lat/long, and search filters on
        # lat/long — so without coordinates a facility never appears in results.
        data_dir = Path(__file__).parent.parent / "data"
        csv_path = str(data_dir / "ca_zips.csv")
        if os.path.exists(csv_path):
            try:
                seed_zip_coordinates(csv_path)
            except Exception as e:
                logger.warning("Zip seed failed: %s", e)
        try:
            zip_coords = get_all_zip_coords()
        except Exception as e:
            logger.warning("ZIP coordinate load failed: %s", e)
            zip_coords = {}

        # CDPH enrichment (precise coords + licensed-bed counts) is opt-in: the
        # CHHS endpoint is large/slow and can exceed serverless time limits. It
        # is never fatal — CMS data + ZIP-centroid coords stand on their own.
        cdph_by_zip: dict[str, list[dict]] = {}
        if os.getenv("DIRECTORY_ENABLE_CDPH", "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                cdph_data = fetch_cdph_ca_facilities()
                logger.info("CDPH returned %d locations", len(cdph_data))
                for _facid, info in cdph_data.items():
                    z = info.get("zip", "")
                    if z:
                        cdph_by_zip.setdefault(z, []).append(info)
            except Exception as e:
                logger.warning("CDPH enrichment failed (continuing CMS-only): %s", e)

        # Enrich + assign coordinates
        active_ccns = []
        for facility in cms_facilities:
            ccn = facility.get("ccn")
            if not ccn:
                continue
            active_ccns.append(ccn)

            if cdph_by_zip:
                cdph_match = _match_cdph(facility, cdph_by_zip)
                if cdph_match:
                    if facility.get("latitude") is None and cdph_match.get("latitude"):
                        facility["latitude"] = cdph_match["latitude"]
                    if facility.get("longitude") is None and cdph_match.get("longitude"):
                        facility["longitude"] = cdph_match["longitude"]
                    if not facility.get("cdph_facid"):
                        facility["cdph_facid"] = cdph_match.get("cdph_facid")
                    for bed_field in ("licensed_snf_beds", "licensed_icf_beds", "licensed_alf_beds", "licensed_total_beds"):
                        if cdph_match.get(bed_field):
                            facility[bed_field] = cdph_match[bed_field]

            # Coordinate fallback: ZIP centroid so the facility is searchable.
            if facility.get("latitude") is None or facility.get("longitude") is None:
                z = (facility.get("zip") or "")[:5]
                coord = zip_coords.get(z)
                if coord:
                    facility["latitude"], facility["longitude"] = coord[0], coord[1]

        # Batch upsert (single connection)
        upserted = upsert_facilities(cms_facilities)

        # Deactivate missing
        if active_ccns:
            deactivated = deactivate_missing_facilities(active_ccns)

        duration = round(time.time() - start_time, 1)
        finish_sync_log(log_id, upserted, deactivated, "success")
        logger.info("Sync complete: %d upserted, %d deactivated in %.1fs", upserted, deactivated, duration)
        return {
            "upserted": upserted,
            "deactivated": deactivated,
            "duration_seconds": duration,
            "status": "success",
        }

    except Exception as e:
        duration = round(time.time() - start_time, 1)
        logger.error("Sync failed: %s", e, exc_info=True)
        try:
            finish_sync_log(log_id, upserted, deactivated, "error", str(e))
        except Exception:
            pass
        return {
            "upserted": upserted,
            "deactivated": deactivated,
            "duration_seconds": duration,
            "status": "error",
            "error": str(e),
        }
