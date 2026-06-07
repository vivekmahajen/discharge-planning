"""Directory persistence layer — facilities, search, sync."""
from __future__ import annotations
from typing import Optional
import math
from db.connection import get_db_conn

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS facilities (
    id SERIAL PRIMARY KEY,
    ccn VARCHAR(20) UNIQUE,
    cdph_facid VARCHAR(30),
    name VARCHAR(300) NOT NULL,
    facility_type VARCHAR(50) DEFAULT 'SNF',
    address VARCHAR(300),
    city VARCHAR(100),
    county VARCHAR(100),
    state VARCHAR(2) DEFAULT 'CA',
    zip VARCHAR(10),
    phone VARCHAR(20),
    latitude FLOAT,
    longitude FLOAT,
    overall_rating INTEGER,
    health_inspection_rating INTEGER,
    staffing_rating INTEGER,
    quality_measures_rating INTEGER,
    total_beds INTEGER,
    certified_beds INTEGER,
    average_daily_census FLOAT,
    ownership_type VARCHAR(100),
    medicare_certified BOOLEAN DEFAULT FALSE,
    medicaid_certified BOOLEAN DEFAULT FALSE,
    accepts_medi_cal BOOLEAN DEFAULT FALSE,
    is_special_focus BOOLEAN DEFAULT FALSE,
    is_special_focus_candidate BOOLEAN DEFAULT FALSE,
    abuse_icon BOOLEAN DEFAULT FALSE,
    total_fines_dollars FLOAT DEFAULT 0,
    number_of_fines INTEGER DEFAULT 0,
    total_penalties INTEGER DEFAULT 0,
    licensed_snf_beds INTEGER DEFAULT 0,
    licensed_icf_beds INTEGER DEFAULT 0,
    licensed_alf_beds INTEGER DEFAULT 0,
    licensed_total_beds INTEGER DEFAULT 0,
    data_source VARCHAR(50) DEFAULT 'CMS',
    last_synced_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS zip_coordinates (
    zip VARCHAR(10) PRIMARY KEY,
    city VARCHAR(100),
    state VARCHAR(2),
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    county VARCHAR(100)
);
CREATE TABLE IF NOT EXISTS directory_sync_log (
    id SERIAL PRIMARY KEY,
    sync_type VARCHAR(50),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    facilities_upserted INTEGER DEFAULT 0,
    facilities_deactivated INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running',
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_facilities_zip ON facilities(zip);
CREATE INDEX IF NOT EXISTS idx_facilities_county ON facilities(county);
CREATE INDEX IF NOT EXISTS idx_facilities_type ON facilities(facility_type);
CREATE INDEX IF NOT EXISTS idx_facilities_rating ON facilities(overall_rating);
CREATE INDEX IF NOT EXISTS idx_facilities_active ON facilities(is_active);
CREATE INDEX IF NOT EXISTS idx_facilities_latlong ON facilities(latitude, longitude);
"""


def run_directory_migrations() -> None:
    """Create directory tables if they don't exist."""
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            for stmt in SCHEMA_SQL.split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
        conn.commit()


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    R = 3958.8  # Earth radius in miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_zip_coords(zip_code: str) -> Optional[tuple[float, float]]:
    """Look up lat/lon for a zip. Returns (lat, lon) or None."""
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT latitude, longitude FROM zip_coordinates WHERE zip = %s",
                (zip_code,)
            )
            row = cur.fetchone()
            if row:
                return float(row["latitude"]), float(row["longitude"])
    return None


def seed_zip_coordinates(csv_path: str) -> int:
    """Seed zip_coordinates from CSV. Returns count inserted. Idempotent (skip if table has data)."""
    import csv
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM zip_coordinates")
            row = cur.fetchone()
            if row and row["cnt"] > 0:
                return 0
        count = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            seen_zips: set[str] = set()
            with conn.cursor() as cur:
                for record in reader:
                    z = record.get("zip", "").strip()
                    if not z or z in seen_zips:
                        continue
                    seen_zips.add(z)
                    try:
                        cur.execute(
                            """INSERT INTO zip_coordinates (zip, city, state, latitude, longitude, county)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               ON CONFLICT (zip) DO NOTHING""",
                            (
                                z,
                                record.get("city", "").strip(),
                                record.get("state_id", "CA").strip(),
                                float(record["lat"]),
                                float(record["lng"]),
                                record.get("county_name", "").strip(),
                            )
                        )
                        count += 1
                    except (ValueError, KeyError):
                        continue
        conn.commit()
    return count


def upsert_facility(facility_dict: dict) -> bool:
    """INSERT ... ON CONFLICT (ccn) DO UPDATE SET ..."""
    d = facility_dict
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO facilities (
                    ccn, cdph_facid, name, facility_type, address, city, county, state, zip, phone,
                    latitude, longitude, overall_rating, health_inspection_rating, staffing_rating,
                    quality_measures_rating, total_beds, certified_beds, average_daily_census,
                    ownership_type, medicare_certified, medicaid_certified, accepts_medi_cal,
                    is_special_focus, is_special_focus_candidate, abuse_icon,
                    total_fines_dollars, number_of_fines, total_penalties,
                    licensed_snf_beds, licensed_icf_beds, licensed_alf_beds, licensed_total_beds,
                    data_source, last_synced_at, is_active, updated_at
                ) VALUES (
                    %(ccn)s, %(cdph_facid)s, %(name)s, %(facility_type)s, %(address)s, %(city)s,
                    %(county)s, %(state)s, %(zip)s, %(phone)s,
                    %(latitude)s, %(longitude)s, %(overall_rating)s, %(health_inspection_rating)s,
                    %(staffing_rating)s, %(quality_measures_rating)s, %(total_beds)s,
                    %(certified_beds)s, %(average_daily_census)s, %(ownership_type)s,
                    %(medicare_certified)s, %(medicaid_certified)s, %(accepts_medi_cal)s,
                    %(is_special_focus)s, %(is_special_focus_candidate)s, %(abuse_icon)s,
                    %(total_fines_dollars)s, %(number_of_fines)s, %(total_penalties)s,
                    %(licensed_snf_beds)s, %(licensed_icf_beds)s, %(licensed_alf_beds)s,
                    %(licensed_total_beds)s, %(data_source)s, NOW(), TRUE, NOW()
                )
                ON CONFLICT (ccn) DO UPDATE SET
                    cdph_facid = EXCLUDED.cdph_facid,
                    name = EXCLUDED.name,
                    facility_type = EXCLUDED.facility_type,
                    address = EXCLUDED.address,
                    city = EXCLUDED.city,
                    county = EXCLUDED.county,
                    state = EXCLUDED.state,
                    zip = EXCLUDED.zip,
                    phone = EXCLUDED.phone,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    overall_rating = EXCLUDED.overall_rating,
                    health_inspection_rating = EXCLUDED.health_inspection_rating,
                    staffing_rating = EXCLUDED.staffing_rating,
                    quality_measures_rating = EXCLUDED.quality_measures_rating,
                    total_beds = EXCLUDED.total_beds,
                    certified_beds = EXCLUDED.certified_beds,
                    average_daily_census = EXCLUDED.average_daily_census,
                    ownership_type = EXCLUDED.ownership_type,
                    medicare_certified = EXCLUDED.medicare_certified,
                    medicaid_certified = EXCLUDED.medicaid_certified,
                    accepts_medi_cal = EXCLUDED.accepts_medi_cal,
                    is_special_focus = EXCLUDED.is_special_focus,
                    is_special_focus_candidate = EXCLUDED.is_special_focus_candidate,
                    abuse_icon = EXCLUDED.abuse_icon,
                    total_fines_dollars = EXCLUDED.total_fines_dollars,
                    number_of_fines = EXCLUDED.number_of_fines,
                    total_penalties = EXCLUDED.total_penalties,
                    licensed_snf_beds = EXCLUDED.licensed_snf_beds,
                    licensed_icf_beds = EXCLUDED.licensed_icf_beds,
                    licensed_alf_beds = EXCLUDED.licensed_alf_beds,
                    licensed_total_beds = EXCLUDED.licensed_total_beds,
                    data_source = EXCLUDED.data_source,
                    last_synced_at = NOW(),
                    is_active = TRUE,
                    updated_at = NOW()
                """,
                {
                    "ccn": d.get("ccn"),
                    "cdph_facid": d.get("cdph_facid"),
                    "name": d.get("name", ""),
                    "facility_type": d.get("facility_type", "SNF"),
                    "address": d.get("address"),
                    "city": d.get("city"),
                    "county": d.get("county"),
                    "state": d.get("state", "CA"),
                    "zip": d.get("zip"),
                    "phone": d.get("phone"),
                    "latitude": d.get("latitude"),
                    "longitude": d.get("longitude"),
                    "overall_rating": d.get("overall_rating"),
                    "health_inspection_rating": d.get("health_inspection_rating"),
                    "staffing_rating": d.get("staffing_rating"),
                    "quality_measures_rating": d.get("quality_measures_rating"),
                    "total_beds": d.get("total_beds"),
                    "certified_beds": d.get("certified_beds"),
                    "average_daily_census": d.get("average_daily_census"),
                    "ownership_type": d.get("ownership_type"),
                    "medicare_certified": d.get("medicare_certified", False),
                    "medicaid_certified": d.get("medicaid_certified", False),
                    "accepts_medi_cal": d.get("accepts_medi_cal", False),
                    "is_special_focus": d.get("is_special_focus", False),
                    "is_special_focus_candidate": d.get("is_special_focus_candidate", False),
                    "abuse_icon": d.get("abuse_icon", False),
                    "total_fines_dollars": d.get("total_fines_dollars", 0),
                    "number_of_fines": d.get("number_of_fines", 0),
                    "total_penalties": d.get("total_penalties", 0),
                    "licensed_snf_beds": d.get("licensed_snf_beds", 0),
                    "licensed_icf_beds": d.get("licensed_icf_beds", 0),
                    "licensed_alf_beds": d.get("licensed_alf_beds", 0),
                    "licensed_total_beds": d.get("licensed_total_beds", 0),
                    "data_source": d.get("data_source", "CMS"),
                }
            )
        conn.commit()
    return True


# Column order shared by the batch upsert. Mirrors upsert_facility().
_FACILITY_COLUMNS = [
    "ccn", "cdph_facid", "name", "facility_type", "address", "city", "county", "state", "zip", "phone",
    "latitude", "longitude", "overall_rating", "health_inspection_rating", "staffing_rating",
    "quality_measures_rating", "total_beds", "certified_beds", "average_daily_census", "ownership_type",
    "medicare_certified", "medicaid_certified", "accepts_medi_cal", "is_special_focus",
    "is_special_focus_candidate", "abuse_icon", "total_fines_dollars", "number_of_fines", "total_penalties",
    "licensed_snf_beds", "licensed_icf_beds", "licensed_alf_beds", "licensed_total_beds", "data_source",
]


def _facility_row(d: dict) -> tuple:
    return (
        d.get("ccn"), d.get("cdph_facid"), d.get("name", ""), d.get("facility_type", "SNF"),
        d.get("address"), d.get("city"), d.get("county"), d.get("state", "CA"), d.get("zip"), d.get("phone"),
        d.get("latitude"), d.get("longitude"), d.get("overall_rating"), d.get("health_inspection_rating"),
        d.get("staffing_rating"), d.get("quality_measures_rating"), d.get("total_beds"), d.get("certified_beds"),
        d.get("average_daily_census"), d.get("ownership_type"), d.get("medicare_certified", False),
        d.get("medicaid_certified", False), d.get("accepts_medi_cal", False), d.get("is_special_focus", False),
        d.get("is_special_focus_candidate", False), d.get("abuse_icon", False), d.get("total_fines_dollars", 0),
        d.get("number_of_fines", 0), d.get("total_penalties", 0), d.get("licensed_snf_beds", 0),
        d.get("licensed_icf_beds", 0), d.get("licensed_alf_beds", 0), d.get("licensed_total_beds", 0),
        d.get("data_source", "CMS"),
    )


def upsert_facilities(facilities: list[dict], batch_size: int = 500) -> int:
    """Batch upsert many facilities on a single connection (one round-trip per
    batch via execute_values). Far faster than per-row upsert_facility and avoids
    opening/leaking a connection per facility. Returns count upserted.
    """
    from psycopg2.extras import execute_values

    rows = [_facility_row(d) for d in facilities if d.get("ccn")]
    if not rows:
        return 0

    cols = ", ".join(_FACILITY_COLUMNS)
    update_cols = [c for c in _FACILITY_COLUMNS if c != "ccn"]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO facilities ({cols}, last_synced_at, is_active, updated_at) VALUES %s "
        f"ON CONFLICT (ccn) DO UPDATE SET {set_clause}, "
        f"last_synced_at = NOW(), is_active = TRUE, updated_at = NOW()"
    )
    template = "(" + ", ".join(["%s"] * len(_FACILITY_COLUMNS)) + ", NOW(), TRUE, NOW())"

    total = 0
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    chunk = rows[i:i + batch_size]
                    execute_values(cur, sql, chunk, template=template, page_size=batch_size)
                    total += len(chunk)
    finally:
        conn.close()
    return total


def get_all_zip_coords() -> dict[str, tuple[float, float]]:
    """Return {zip: (lat, lon)} for all seeded ZIP centroids — used as a
    coordinate fallback for facilities that lack precise lat/long."""
    out: dict[str, tuple[float, float]] = {}
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT zip, latitude, longitude FROM zip_coordinates")
            for r in cur.fetchall():
                try:
                    out[r["zip"]] = (float(r["latitude"]), float(r["longitude"]))
                except (TypeError, ValueError):
                    continue
    finally:
        conn.close()
    return out


def deactivate_missing_facilities(active_ccns: list[str]) -> int:
    """Set is_active=FALSE for CCNs not in active_ccns. Returns count."""
    if not active_ccns:
        return 0
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE facilities SET is_active = FALSE, updated_at = NOW() "
                "WHERE ccn != ALL(%s) AND is_active = TRUE",
                (active_ccns,)
            )
            count = cur.rowcount
        conn.commit()
    return count


def search_facilities(
    zip_code: str,
    radius_miles: float = 25.0,
    facility_types: Optional[list[str]] = None,
    min_rating: Optional[int] = None,
    accepts_medi_cal: Optional[bool] = None,
    medicare_certified: Optional[bool] = None,
    exclude_sff: bool = False,
    sort_by: str = "distance",
    limit: int = 50,
) -> list[dict]:
    """
    Search active facilities within radius_miles of zip_code.
    1. Get lat/lon for zip from zip_coordinates
    2. Bounding box pre-filter
    3. Haversine exact filter in Python
    4. Apply remaining filters, sort, return
    """
    coords = get_zip_coords(zip_code)
    if coords is None:
        return []

    center_lat, center_lon = coords
    lat_delta = radius_miles / 69.0
    lon_delta = radius_miles / (69.0 * math.cos(math.radians(center_lat)))

    lat_min = center_lat - lat_delta
    lat_max = center_lat + lat_delta
    lon_min = center_lon - lon_delta
    lon_max = center_lon + lon_delta

    params: list = [lat_min, lat_max, lon_min, lon_max]
    where_clauses = [
        "is_active = TRUE",
        "latitude BETWEEN %s AND %s",
        "longitude BETWEEN %s AND %s",
    ]

    if facility_types:
        where_clauses.append(f"facility_type = ANY(%s)")
        params.append(facility_types)

    if min_rating is not None:
        where_clauses.append("overall_rating >= %s")
        params.append(min_rating)

    if accepts_medi_cal is True:
        where_clauses.append("accepts_medi_cal = TRUE")
    elif accepts_medi_cal is False:
        where_clauses.append("accepts_medi_cal = FALSE")

    if medicare_certified is True:
        where_clauses.append("medicare_certified = TRUE")
    elif medicare_certified is False:
        where_clauses.append("medicare_certified = FALSE")

    if exclude_sff:
        where_clauses.append("is_special_focus = FALSE")

    sql = f"SELECT * FROM facilities WHERE {' AND '.join(where_clauses)}"

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    results = []
    for row in rows:
        lat = row.get("latitude")
        lon = row.get("longitude")
        if lat is None or lon is None:
            continue
        dist = haversine_miles(center_lat, center_lon, float(lat), float(lon))
        if dist > radius_miles:
            continue
        item = dict(row)
        item["distance_miles"] = round(dist, 1)

        # Star display
        rating = item.get("overall_rating")
        if rating and isinstance(rating, int) and 1 <= rating <= 5:
            item["star_display"] = "★" * rating + "☆" * (5 - rating)
        else:
            item["star_display"] = "Not rated"

        # Quality flag
        if item.get("is_special_focus"):
            item["quality_flag"] = "SFF"
        elif item.get("abuse_icon"):
            item["quality_flag"] = "ABUSE"
        elif rating and rating <= 2:
            item["quality_flag"] = "LOW_RATING"
        else:
            item["quality_flag"] = None

        # Serialize datetime fields
        import datetime as _dt
        for k, v in item.items():
            if isinstance(v, (_dt.datetime, _dt.date)):
                item[k] = v.isoformat()

        results.append(item)

    # Sort
    if sort_by == "rating":
        results.sort(key=lambda x: (-(x.get("overall_rating") or 0), x["distance_miles"]))
    elif sort_by == "name":
        results.sort(key=lambda x: x.get("name", ""))
    else:  # distance
        results.sort(key=lambda x: x["distance_miles"])

    return results[:limit]


def get_facility_by_ccn(ccn: str) -> Optional[dict]:
    """Return full facility dict or None."""
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM facilities WHERE ccn = %s", (ccn,))
            row = cur.fetchone()
            if row:
                return dict(row)
    return None


def get_county_summary() -> list[dict]:
    """Aggregated stats per county: county, total_facilities, avg_rating, total_beds, medi_cal_count."""
    sql = """
        SELECT
            county,
            COUNT(*) AS total_facilities,
            ROUND(AVG(overall_rating)::numeric, 1) AS avg_rating,
            SUM(COALESCE(certified_beds, licensed_total_beds, 0)) AS total_beds,
            SUM(CASE WHEN accepts_medi_cal THEN 1 ELSE 0 END) AS medi_cal_count
        FROM facilities
        WHERE is_active = TRUE AND county IS NOT NULL
        GROUP BY county
        ORDER BY county
    """
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_sync_status() -> dict:
    """Most recent sync_log row + total_active_facilities + data_freshness_hours."""
    import datetime as _dt
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM directory_sync_log ORDER BY started_at DESC LIMIT 1"
            )
            last_sync = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS cnt FROM facilities WHERE is_active = TRUE")
            total_row = cur.fetchone()

    total_active = int(total_row["cnt"]) if total_row else 0
    result: dict = {
        "last_sync": dict(last_sync) if last_sync else None,
        "total_active_facilities": total_active,
    }

    if last_sync and last_sync.get("completed_at"):
        completed_at = last_sync["completed_at"]
        if isinstance(completed_at, _dt.datetime):
            now = _dt.datetime.now(_dt.timezone.utc)
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=_dt.timezone.utc)
            diff = now - completed_at
            result["data_freshness_hours"] = round(diff.total_seconds() / 3600, 1)
        else:
            result["data_freshness_hours"] = None
    else:
        result["data_freshness_hours"] = None

    return result


def start_sync_log(sync_type: str) -> int:
    """Insert sync_log row, return id."""
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO directory_sync_log (sync_type, status) VALUES (%s, 'running') RETURNING id",
                (sync_type,)
            )
            row = cur.fetchone()
            log_id = row["id"]
        conn.commit()
    return log_id


def finish_sync_log(
    log_id: int,
    upserted: int,
    deactivated: int,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update sync_log row with completion info."""
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE directory_sync_log
                   SET completed_at = NOW(), facilities_upserted = %s,
                       facilities_deactivated = %s, status = %s, error_message = %s
                   WHERE id = %s""",
                (upserted, deactivated, status, error, log_id)
            )
        conn.commit()
