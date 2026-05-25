"""
Seed the drg_reference table with CMS FY 2026 MS-DRG geometric mean LOS data.

Data source:
  CMS FY 2026 IPPS Final Rule, Table 5 — MS-DRGs, Relative Weighting Factors
  and Geometric and Arithmetic Mean Length of Stay.
  https://www.cms.gov/medicare/payment/prospective-payment-systems/
  acute-inpatient-pps/fy-2026-ipps-final-rule-home-page

The DRG_REFERENCE dict is embedded in db/drg_reference_data.py and covers the
top ~150 MS-DRGs representing approximately 85% of California hospital discharges.

Idempotent: uses ON CONFLICT DO UPDATE — safe to run on every app startup.
Only performs DB writes when rows need to be inserted or updated.
"""
import logging
import sys
import os

# Allow running as standalone script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_log = logging.getLogger(__name__)


def seed_drg_reference() -> int:
    """
    Upsert all DRG rows from the embedded reference dict.
    Returns count of rows processed.
    """
    from db.drg_reference_data import DRG_REFERENCE, HRRP_DRGS
    from db.connection import get_db_conn

    conn = get_db_conn()
    upserted = 0
    try:
        with conn:
            with conn.cursor() as cur:
                for code, (desc, mdc, dtype, weight, geo_los, arith_los) in DRG_REFERENCE.items():
                    cur.execute(
                        """
                        INSERT INTO drg_reference
                          (drg_code, drg_description, mdc_code, drg_type,
                           relative_weight, geometric_mean_los, arithmetic_mean_los,
                           fiscal_year, is_ca_hrrp_drg)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 2026, %s)
                        ON CONFLICT (drg_code) DO UPDATE SET
                          drg_description     = EXCLUDED.drg_description,
                          mdc_code            = EXCLUDED.mdc_code,
                          drg_type            = EXCLUDED.drg_type,
                          relative_weight     = EXCLUDED.relative_weight,
                          geometric_mean_los  = EXCLUDED.geometric_mean_los,
                          arithmetic_mean_los = EXCLUDED.arithmetic_mean_los,
                          fiscal_year         = EXCLUDED.fiscal_year,
                          is_ca_hrrp_drg      = EXCLUDED.is_ca_hrrp_drg
                        """,
                        (
                            code, desc, mdc, dtype, weight,
                            geo_los, arith_los,
                            code in HRRP_DRGS,
                        ),
                    )
                    upserted += 1
        _log.info("DRG reference seeded: %d rows upserted", upserted)
    finally:
        conn.close()
    return upserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = seed_drg_reference()
    print(f"Seeded {count} DRG reference rows.")
