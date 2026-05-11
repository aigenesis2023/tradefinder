import sqlite3
import json
from datetime import datetime, date
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "data" / "trading_research.db"


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS research_logs (
                run_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                first_seen_date TEXT,
                last_seen_date TEXT,
                last_material_update TEXT,
                composite_score REAL,
                confidence TEXT,
                probationary INTEGER DEFAULT 0,
                liquidity_warning INTEGER DEFAULT 0,
                catalyst_type TEXT,
                catalyst_type_prior REAL,
                catalyst_date TEXT,
                days_since_catalyst INTEGER,
                confirming_signals TEXT DEFAULT '[]',
                confirming_signal_count INTEGER DEFAULT 0,
                insider_buying_cluster INTEGER DEFAULT 0,
                insider_buy_total_usd REAL DEFAULT 0,
                insider_buy_names TEXT DEFAULT '[]',
                hiring_surge_detected INTEGER DEFAULT 0,
                hiring_surge_delta_pct REAL DEFAULT 0,
                specialist_fund_initiation INTEGER DEFAULT 0,
                specialist_fund_name TEXT,
                russell_inclusion_candidate INTEGER DEFAULT 0,
                neglect_screen_pass INTEGER DEFAULT 0,
                regime_gate_pass INTEGER DEFAULT 0,
                agent1b_bear_summary TEXT,
                agent1c_resolution TEXT,
                agent1c_conflict_level TEXT,
                agent1d_result TEXT,
                information_asymmetry_score REAL,
                catalyst_strength_score REAL,
                quant_confirmation_score REAL,
                data_quality_score REAL,
                risk_asymmetry_score REAL,
                marginal_buyer_score REAL,
                short_interest_flag INTEGER DEFAULT 0,
                float_risk_flag INTEGER DEFAULT 0,
                stale_data_flag INTEGER DEFAULT 0,
                sector_beta_flag INTEGER DEFAULT 0,
                rs_vs_iwm REAL,
                proxies_computed INTEGER DEFAULT 0,
                missing_data_fields TEXT DEFAULT '[]',
                theme_cluster_id TEXT,
                discard_reason TEXT,
                thesis TEXT,
                invalidation_trigger TEXT,
                outcome_7d REAL,
                outcome_10d REAL,
                outcome_30d REAL,
                outcome_7d_logged_at TEXT,
                outcome_10d_logged_at TEXT,
                outcome_30d_logged_at TEXT,
                high_upside_score REAL DEFAULT 0,
                high_upside_markers TEXT DEFAULT '[]',
                regime_override INTEGER DEFAULT 0,
                PRIMARY KEY (run_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS regime_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                vix_value REAL,
                vix_sma60 REAL,
                vix_pass INTEGER,
                iwm_value REAL,
                iwm_ma20 REAL,
                iwm_pass INTEGER,
                gate_pass INTEGER
            );

            CREATE TABLE IF NOT EXISTS run_health (
                run_id TEXT PRIMARY KEY,
                run_date TEXT NOT NULL,
                regime_gate_pass INTEGER,
                total_candidates INTEGER DEFAULT 0,
                candidates_passed_neglect INTEGER DEFAULT 0,
                candidates_probationary INTEGER DEFAULT 0,
                candidates_disqualified_1c INTEGER DEFAULT 0,
                candidates_disqualified_1d INTEGER DEFAULT 0,
                candidates_below_threshold INTEGER DEFAULT 0,
                final_report_count INTEGER DEFAULT 0,
                avg_data_quality REAL,
                stale_data_pct REAL,
                missing_data_pct REAL,
                api_calls_used INTEGER DEFAULT 0,
                api_budget INTEGER DEFAULT 80,
                run_status TEXT DEFAULT 'ok',
                run_notes TEXT
            );

            CREATE TABLE IF NOT EXISTS signal_hit_rates (
                signal_type TEXT NOT NULL,
                ticker TEXT NOT NULL,
                run_id TEXT NOT NULL,
                detected_at TEXT,
                outcome_7d REAL,
                outcome_10d REAL,
                outcome_30d REAL,
                PRIMARY KEY (signal_type, ticker, run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_research_ticker ON research_logs(ticker);
            CREATE INDEX IF NOT EXISTS idx_research_date ON research_logs(last_seen_date);
            CREATE INDEX IF NOT EXISTS idx_research_cluster ON research_logs(theme_cluster_id);
        """)
        # Forward-compat migrations: add columns introduced after the initial schema.
        # SQLite has no CREATE COLUMN IF NOT EXISTS so we attempt and ignore the
        # "duplicate column" error on existing DBs.
        for ddl in (
            "ALTER TABLE research_logs ADD COLUMN high_upside_score REAL DEFAULT 0",
            "ALTER TABLE research_logs ADD COLUMN high_upside_markers TEXT DEFAULT '[]'",
            "ALTER TABLE research_logs ADD COLUMN regime_override INTEGER DEFAULT 0",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass


def log_regime(vix_value, vix_sma60, iwm_value, iwm_ma20, gate_pass):
    vix_pass = int(vix_value < vix_sma60) if vix_value and vix_sma60 else 0
    iwm_pass = int(iwm_value > iwm_ma20) if iwm_value and iwm_ma20 else 0
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO regime_history
               (timestamp, vix_value, vix_sma60, vix_pass, iwm_value, iwm_ma20, iwm_pass, gate_pass)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), vix_value, vix_sma60, vix_pass,
             iwm_value, iwm_ma20, iwm_pass, int(gate_pass))
        )


def log_candidate(run_id, data: dict):
    now = datetime.utcnow().isoformat()
    data.setdefault("first_seen_date", now)
    data.setdefault("last_seen_date", now)

    for field in ("confirming_signals", "insider_buy_names", "missing_data_fields", "high_upside_markers"):
        if isinstance(data.get(field), list):
            data[field] = json.dumps(data[field])

    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" * len(data))
    update_cols = ", ".join(f"{k}=excluded.{k}" for k in data if k not in ("run_id", "ticker"))

    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO research_logs (run_id, {cols})
                VALUES (?, {placeholders})
                ON CONFLICT(run_id, ticker) DO UPDATE SET {update_cols}""",
            [run_id] + list(data.values())
        )


def log_run_health(run_id, health: dict):
    health["run_id"] = run_id
    health.setdefault("run_date", date.today().isoformat())
    cols = ", ".join(health.keys())
    placeholders = ", ".join("?" * len(health))
    update_cols = ", ".join(f"{k}=excluded.{k}" for k in health if k != "run_id")
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO run_health ({cols}) VALUES ({placeholders})
                ON CONFLICT(run_id) DO UPDATE SET {update_cols}""",
            list(health.values())
        )


def update_outcome(ticker, run_id, days, price_change_pct):
    col = {7: "outcome_7d", 10: "outcome_10d", 30: "outcome_30d"}.get(days)
    logged_col = {7: "outcome_7d_logged_at", 10: "outcome_10d_logged_at", 30: "outcome_30d_logged_at"}.get(days)
    if not col:
        raise ValueError(f"days must be 7, 10, or 30, got {days}")
    with get_conn() as conn:
        conn.execute(
            f"UPDATE research_logs SET {col}=?, {logged_col}=? WHERE ticker=? AND run_id=?",
            (price_change_pct, datetime.utcnow().isoformat(), ticker, run_id)
        )


def is_deduped(ticker, theme_cluster_id=None, supply_chain_source_ticker=None):
    """Returns (is_blocked, reason) tuple."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT last_seen_date, last_material_update, catalyst_type
               FROM research_logs WHERE ticker=?
               ORDER BY last_seen_date DESC LIMIT 1""",
            (ticker,)
        ).fetchone()

        if row:
            last_seen = datetime.fromisoformat(row["last_seen_date"])
            last_update_str = row["last_material_update"]
            last_update = datetime.fromisoformat(last_update_str) if last_update_str else last_seen
            days_since = (datetime.utcnow() - last_seen).days
            has_material_update = last_update > last_seen

            # Insider signals: new insiders can file Form 4 any day, so a discard
            # today shouldn't prevent re-evaluation for 14 days. 5-day window lets
            # us catch strengthening clusters (more insiders joining) without
            # reprocessing the exact same data immediately.
            catalyst_type = row["catalyst_type"] if "catalyst_type" in row.keys() else None
            dedup_days = 5 if catalyst_type == "insider_buying_cluster" else 14

            if days_since < dedup_days and not has_material_update:
                return True, f"ticker seen {days_since}d ago, no material update"

        if theme_cluster_id:
            theme_row = conn.execute(
                """SELECT last_seen_date FROM research_logs
                   WHERE theme_cluster_id=?
                   ORDER BY last_seen_date DESC LIMIT 1""",
                (theme_cluster_id,)
            ).fetchone()
            if theme_row:
                days = (datetime.utcnow() - datetime.fromisoformat(theme_row["last_seen_date"])).days
                if days < 7:
                    return True, f"theme cluster {theme_cluster_id} seen {days}d ago"

        if supply_chain_source_ticker:
            sc_row = conn.execute(
                """SELECT last_seen_date FROM research_logs
                   WHERE confirming_signals LIKE ?
                   ORDER BY last_seen_date DESC LIMIT 1""",
                (f"%{supply_chain_source_ticker}%",)
            ).fetchone()
            if sc_row:
                days = (datetime.utcnow() - datetime.fromisoformat(sc_row["last_seen_date"])).days
                if days < 7:
                    return True, f"supply chain source {supply_chain_source_ticker} seen {days}d ago"

    return False, None


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
