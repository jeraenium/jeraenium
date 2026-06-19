import csv
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import config

"""
Jeraenium greenhouse API.

Lightweight REST-ish API for greenhouse ESP32 data and Apple Shortcuts / Apple Watch.

Architecture:
- The CSV remains the immutable sensor stream.
- SQLite stores rolling summaries derived from the CSV.
- Manual Watch logs live in a separate `manual_log` table and annotate time, rather
  than mutating sensor rows.
- Request-time work is kept lightweight by updating summaries incrementally.

Expected CSV columns, best effort; extra columns are ignored:
- timestamp_iso, timestamp, or ts
- tC
- rH
- hPa
- lux
- optional SGP41-style fields:
  - srawVoc / sraw_voc / raw_voc
  - srawNox / sraw_nox / raw_nox
  - voc_index / voc / VOC
  - nox_index / nox / NOx

Useful local URLs:
- http://jeraenium.local:PORT/
- http://192.168.1.145:PORT/
"""

PORT = config.PORT
CSV_PATH = config.CSV_PATH
EXTERNAL_JSON_PATH = getattr(config, "EXTERNAL_JSON_PATH", None)
SQLITE_SUMMARY_PATH = getattr(
    config,
    "SQLITE_SUMMARY_PATH",
    os.path.splitext(CSV_PATH)[0] + "_summary.sqlite" if CSV_PATH else "greenhouse_summary.sqlite",
)

API_HOSTNAME = getattr(config, "API_HOSTNAME", "jeraenium.local")
API_LAN_IP = getattr(config, "API_LAN_IP", "192.168.1.145")

_DB_LOCK = threading.RLock()
_RESPONSE_CACHE = {}
_RESPONSE_CACHE_LOCK = threading.Lock()
_RESPONSE_CACHE_TTL = 15.0

_ALLOWED_HOUR_BLOCKS = (1, 2, 3, 4, 6, 8, 12, 24)

_SENSOR_AVG_FIELDS = {
    "t": ("t_sum", "samples", "Tavg"),
    "rh": ("rh_sum", "samples", "RHavg"),
    "hpa": ("hpa_sum", "hpa_n", "Pavg"),
    "lux": ("lux_sum", "lux_n", "Luxavg"),
    "srawVoc": ("srawVoc_sum", "srawVoc_n", "SrawVocAvg"),
    "srawNox": ("srawNox_sum", "srawNox_n", "SrawNoxAvg"),
    "voc_index": ("voc_index_sum", "voc_index_n", "VocIndexAvg"),
    "nox_index": ("nox_index_sum", "nox_index_n", "NoxIndexAvg"),
}


_LOG_OPTIONS = {
    "rain": {
        "actions": ["now", "started", "stopped", "increased", "eased"],
        "intensities": ["none", "mist", "light", "medium", "heavy", "biblical"],
    },
    "plant_intervention": {
        "actions": [
            "pruned",
            "pinched_out",
            "tied_in",
            "moved",
            "repotted",
            "planted_out",
            "sowed",
            "watered",
            "fed",
            "mulched",
            "cutting_taken",
            "harvested",
        ],
        "intensities": ["none", "minor", "moderate", "major"],
    },
    "environment": {
        "actions": [
            "door_opened",
            "door_closed",
            "vent_opened",
            "vent_closed",
            "shade_added",
            "shade_removed",
            "fan_on",
            "fan_off",
            "heat_on",
            "heat_off",
            "water_tray_added",
            "water_tray_removed",
            "thermal_mass_added",
            "thermal_mass_removed",
        ],
        "intensities": ["partial", "full", "minor", "moderate", "major"],
    },
    "observation": {
        "actions": [
            "flowering",
            "fruit_set",
            "new_growth",
            "wilt",
            "recovered",
            "pest_seen",
            "disease_seen",
            "slug_damage",
            "fungal_sign",
            "leaf_yellowing",
            "mould_spotted",
            "interesting",
        ],
        "intensities": ["none", "mild", "moderate", "severe"],
    },
    "system": {
        "actions": [
            "sensor_moved",
            "sensor_cleaned",
            "sensor_shaded",
            "sensor_wet",
            "sensor_fault",
            "api_updated",
            "esp_restarted",
            "power_issue",
            "new_sensor_added",
        ],
        "intensities": ["none", "minor", "moderate", "major"],
    },
}


def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _safe_int(x, default=0, minimum=None, maximum=None):
    value = _safe_float(x, None)
    if value is None:
        value = default
    value = int(value)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _parse_ts(s: str):
    s = (s or "").strip()
    if not s:
        return None

    is_utc = s.endswith("Z")
    if is_utc:
        s = s[:-1]

    s = s.replace("T", " ")

    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, f)
            if is_utc:
                return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            pass

    return None


def _now_local_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _utc_now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _round(x, n=1):
    return None if x is None else round(float(x), n)


def _fmt_compact_num(v, decimals=1):
    if v is None:
        return "-"
    v = float(v)
    if abs(v - round(v)) < 0.05:
        return str(int(round(v)))
    return f"{v:.{decimals}f}"


def _spark(values):
    values = [v for v in values if v is not None]
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        return blocks[0] * len(values)

    out = []
    for v in values:
        idx = int(round((v - vmin) / (vmax - vmin) * (len(blocks) - 1)))
        idx = max(0, min(len(blocks) - 1, idx))
        out.append(blocks[idx])
    return "".join(out)


def _month_name_from_key(month_key):
    return datetime.strptime(month_key, "%Y-%m").strftime("%B")


def _month_letter(month_key):
    return datetime.strptime(month_key, "%Y-%m").strftime("%b")[0].upper()


def _clean_text(value, default=""):
    if value is None:
        return default
    return str(value).strip()


def _normalise_choice(value):
    return _clean_text(value).lower().replace(" ", "_").replace("-", "_")


def _first_present(row, names):
    for name in names:
        if name in row and str(row.get(name, "")).strip() != "":
            return row.get(name)
    return None


def _row_float(row, *names):
    return _safe_float(_first_present(row, names), None)


def _value_sum_n(value):
    return (0.0 if value is None else float(value), 0 if value is None else 1)


def _cache_key(prefix, args):
    if not isinstance(args, dict):
        return (prefix,)
    return (prefix, tuple(sorted((str(k), str(v)) for k, v in args.items())))


def _response_cache_get(prefix, args):
    key = _cache_key(prefix, args)
    now = time.time()

    with _RESPONSE_CACHE_LOCK:
        item = _RESPONSE_CACHE.get(key)
        if not item:
            return None

        expires_at, value = item
        if now >= expires_at:
            _RESPONSE_CACHE.pop(key, None)
            return None

        return value


def _response_cache_set(prefix, args, value, ttl=_RESPONSE_CACHE_TTL):
    key = _cache_key(prefix, args)
    with _RESPONSE_CACHE_LOCK:
        _RESPONSE_CACHE[key] = (time.time() + ttl, value)
    return value


def _invalidate_response_cache():
    with _RESPONSE_CACHE_LOCK:
        _RESPONSE_CACHE.clear()


def _flatten_args(args):
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, list) and len(v) == 1:
            out[k] = v[0]
        else:
            out[k] = v
    return out


def _base_urls():
    return [
        f"http://{API_HOSTNAME}:{PORT}",
        f"http://{API_LAN_IP}:{PORT}",
        f"http://127.0.0.1:{PORT}",
    ]


def _read_external(args):
    ext = {}

    if EXTERNAL_JSON_PATH:
        try:
            with open(EXTERNAL_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                if isinstance(data, dict):
                    ext.update(data)
        except Exception:
            pass

    def g(key, alt=None):
        return args.get(key) if key in args else (args.get(alt) if alt else None)

    if g("weather"):
        ext["weather"] = g("weather")
    if g("tide"):
        ext["tide"] = g("tide")
    if g("out_temp_c", "out_temp"):
        ext["out_temp_c"] = _safe_float(g("out_temp_c", "out_temp"), None)
    if g("out_wind_mph", "wind_mph"):
        ext["out_wind_mph"] = _safe_float(g("out_wind_mph", "wind_mph"), None)
    if g("out_humidity"):
        ext["out_humidity"] = _safe_float(g("out_humidity"), None)
    if g("water_temp_c", "water_temp"):
        ext["water_temp_c"] = _safe_float(g("water_temp_c", "water_temp"), None)

    return ext


def _connect_db():
    conn = sqlite3.connect(SQLITE_SUMMARY_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column_if_missing(conn, table, column_sql):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")
    except sqlite3.OperationalError as e:
        # SQLite raises "duplicate column name" when the migration has already run.
        if "duplicate column" not in str(e).lower():
            raise


def _init_db(conn):
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS latest (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            timestamp_iso TEXT,
            tC REAL,
            rH REAL,
            hPa REAL,
            lux REAL,
            srawVoc REAL,
            srawNox REAL,
            voc_index REAL,
            nox_index REAL
        );

        CREATE TABLE IF NOT EXISTS hourly (
            hour TEXT PRIMARY KEY,
            samples INTEGER NOT NULL DEFAULT 0,
            t_sum REAL NOT NULL DEFAULT 0,
            rh_sum REAL NOT NULL DEFAULT 0,
            hpa_sum REAL NOT NULL DEFAULT 0,
            hpa_n INTEGER NOT NULL DEFAULT 0,
            lux_sum REAL NOT NULL DEFAULT 0,
            lux_n INTEGER NOT NULL DEFAULT 0,
            srawVoc_sum REAL NOT NULL DEFAULT 0,
            srawVoc_n INTEGER NOT NULL DEFAULT 0,
            srawNox_sum REAL NOT NULL DEFAULT 0,
            srawNox_n INTEGER NOT NULL DEFAULT 0,
            voc_index_sum REAL NOT NULL DEFAULT 0,
            voc_index_n INTEGER NOT NULL DEFAULT 0,
            nox_index_sum REAL NOT NULL DEFAULT 0,
            nox_index_n INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily (
            date TEXT PRIMARY KEY,
            samples INTEGER NOT NULL DEFAULT 0,
            t_sum REAL NOT NULL DEFAULT 0,
            rh_sum REAL NOT NULL DEFAULT 0,
            hpa_sum REAL NOT NULL DEFAULT 0,
            hpa_n INTEGER NOT NULL DEFAULT 0,
            lux_sum REAL NOT NULL DEFAULT 0,
            lux_n INTEGER NOT NULL DEFAULT 0,
            srawVoc_sum REAL NOT NULL DEFAULT 0,
            srawVoc_n INTEGER NOT NULL DEFAULT 0,
            srawNox_sum REAL NOT NULL DEFAULT 0,
            srawNox_n INTEGER NOT NULL DEFAULT 0,
            voc_index_sum REAL NOT NULL DEFAULT 0,
            voc_index_n INTEGER NOT NULL DEFAULT 0,
            nox_index_sum REAL NOT NULL DEFAULT 0,
            nox_index_n INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS monthly (
            month TEXT PRIMARY KEY,
            days INTEGER NOT NULL DEFAULT 0,
            t_sum REAL NOT NULL DEFAULT 0,
            rh_sum REAL NOT NULL DEFAULT 0,
            hpa_sum REAL NOT NULL DEFAULT 0,
            hpa_n INTEGER NOT NULL DEFAULT 0,
            lux_sum REAL NOT NULL DEFAULT 0,
            lux_n INTEGER NOT NULL DEFAULT 0,
            srawVoc_sum REAL NOT NULL DEFAULT 0,
            srawVoc_n INTEGER NOT NULL DEFAULT 0,
            srawNox_sum REAL NOT NULL DEFAULT 0,
            srawNox_n INTEGER NOT NULL DEFAULT 0,
            voc_index_sum REAL NOT NULL DEFAULT 0,
            voc_index_n INTEGER NOT NULL DEFAULT 0,
            nox_index_sum REAL NOT NULL DEFAULT 0,
            nox_index_n INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS manual_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_iso TEXT NOT NULL,
            category TEXT NOT NULL,
            action TEXT NOT NULL,
            intensity TEXT,
            subject TEXT,
            note TEXT,
            source TEXT DEFAULT 'manual',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_hourly_hour ON hourly(hour);
        CREATE INDEX IF NOT EXISTS idx_daily_date ON daily(date);
        CREATE INDEX IF NOT EXISTS idx_monthly_month ON monthly(month);
        CREATE INDEX IF NOT EXISTS idx_manual_log_ts ON manual_log(timestamp_iso);
        CREATE INDEX IF NOT EXISTS idx_manual_log_category ON manual_log(category);
        CREATE INDEX IF NOT EXISTS idx_manual_log_action ON manual_log(action);
        """
    )

    # Migrations for databases created by earlier patches.
    for column_sql in [
        "srawVoc REAL",
        "srawNox REAL",
        "voc_index REAL",
        "nox_index REAL",
    ]:
        _add_column_if_missing(conn, "latest", column_sql)

    for table in ("hourly", "daily", "monthly"):
        for column_sql in [
            "srawVoc_sum REAL NOT NULL DEFAULT 0",
            "srawVoc_n INTEGER NOT NULL DEFAULT 0",
            "srawNox_sum REAL NOT NULL DEFAULT 0",
            "srawNox_n INTEGER NOT NULL DEFAULT 0",
            "voc_index_sum REAL NOT NULL DEFAULT 0",
            "voc_index_n INTEGER NOT NULL DEFAULT 0",
            "nox_index_sum REAL NOT NULL DEFAULT 0",
            "nox_index_n INTEGER NOT NULL DEFAULT 0",
        ]:
            _add_column_if_missing(conn, table, column_sql)

    conn.commit()


def _meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _meta_set(conn, key, value):
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def _clear_summary_tables(conn):
    # Do not delete manual_log here: manual observations are first-class records,
    # not derived summaries. Rebuilds should never wipe them.
    conn.execute("DELETE FROM latest")
    conn.execute("DELETE FROM hourly")
    conn.execute("DELETE FROM daily")
    conn.execute("DELETE FROM monthly")
    conn.execute("DELETE FROM meta")
    conn.commit()


def _iter_csv_rows_from_line(start_line_number):
    if not CSV_PATH or not os.path.exists(CSV_PATH):
        return

    with open(CSV_PATH, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for csv_line_number, r in enumerate(reader, start=2):
            if csv_line_number <= start_line_number:
                continue

            ts = _parse_ts(r.get("timestamp_iso") or r.get("timestamp") or r.get("ts"))
            if ts is None:
                continue

            yield csv_line_number, {
                "ts": ts,
                "timestamp_iso": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "tC": _row_float(r, "tC", "temp_c", "temperature_c", "temperature", "temp"),
                "rH": _row_float(r, "rH", "rh", "RH", "humidity", "humidity_pct", "relative_humidity"),
                "hPa": _row_float(r, "hPa", "hpa", "pressure_hpa", "pressure", "p"),
                "lux": _row_float(r, "lux", "Lux", "light", "light_lux"),
                "srawVoc": _row_float(r, "srawVoc", "sraw_voc", "srawVOC", "raw_voc", "voc_raw"),
                "srawNox": _row_float(r, "srawNox", "sraw_nox", "srawNOx", "raw_nox", "nox_raw"),
                "voc_index": _row_float(r, "voc_index", "vocIndex", "voc_idx", "VOC", "voc"),
                "nox_index": _row_float(r, "nox_index", "noxIndex", "nox_idx", "NOx", "nox"),
            }


def _hour_bucket_start(dt, block_hours):
    block_hours = max(1, int(block_hours))
    bucket_hour = dt.hour - (dt.hour % block_hours)
    return dt.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)


def _format_hour_block_label(start_dt, block_hours):
    if block_hours <= 1:
        return start_dt.strftime("%H:00")
    end_hour = min(23, start_dt.hour + block_hours - 1)
    return f"{start_dt.strftime('%H')}-{end_hour:02d}"


def _apply_row_to_summary(conn, row):
    ts = row["ts"]
    hour_key = ts.strftime("%Y-%m-%d %H:00")
    day = ts.strftime("%Y-%m-%d")
    month = day[:7]

    t = row.get("tC")
    rh = row.get("rH")
    p = row.get("hPa")
    lx = row.get("lux")
    sraw_voc = row.get("srawVoc")
    sraw_nox = row.get("srawNox")
    voc_index = row.get("voc_index")
    nox_index = row.get("nox_index")

    if t is None or rh is None:
        return

    p_sum, p_n = _value_sum_n(p)
    lx_sum, lx_n = _value_sum_n(lx)
    sraw_voc_sum, sraw_voc_n = _value_sum_n(sraw_voc)
    sraw_nox_sum, sraw_nox_n = _value_sum_n(sraw_nox)
    voc_index_sum, voc_index_n = _value_sum_n(voc_index)
    nox_index_sum, nox_index_n = _value_sum_n(nox_index)

    summary_values = (
        t,
        rh,
        p_sum,
        p_n,
        lx_sum,
        lx_n,
        sraw_voc_sum,
        sraw_voc_n,
        sraw_nox_sum,
        sraw_nox_n,
        voc_index_sum,
        voc_index_n,
        nox_index_sum,
        nox_index_n,
    )

    for table, key_column, key_value in (
        ("hourly", "hour", hour_key),
        ("daily", "date", day),
    ):
        conn.execute(
            f"""
            INSERT INTO {table}(
                {key_column},
                samples,
                t_sum,
                rh_sum,
                hpa_sum,
                hpa_n,
                lux_sum,
                lux_n,
                srawVoc_sum,
                srawVoc_n,
                srawNox_sum,
                srawNox_n,
                voc_index_sum,
                voc_index_n,
                nox_index_sum,
                nox_index_n
            )
            VALUES(?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT({key_column}) DO UPDATE SET
                samples = samples + 1,
                t_sum = t_sum + excluded.t_sum,
                rh_sum = rh_sum + excluded.rh_sum,
                hpa_sum = hpa_sum + excluded.hpa_sum,
                hpa_n = hpa_n + excluded.hpa_n,
                lux_sum = lux_sum + excluded.lux_sum,
                lux_n = lux_n + excluded.lux_n,
                srawVoc_sum = srawVoc_sum + excluded.srawVoc_sum,
                srawVoc_n = srawVoc_n + excluded.srawVoc_n,
                srawNox_sum = srawNox_sum + excluded.srawNox_sum,
                srawNox_n = srawNox_n + excluded.srawNox_n,
                voc_index_sum = voc_index_sum + excluded.voc_index_sum,
                voc_index_n = voc_index_n + excluded.voc_index_n,
                nox_index_sum = nox_index_sum + excluded.nox_index_sum,
                nox_index_n = nox_index_n + excluded.nox_index_n
            """,
            (key_value, *summary_values),
        )

    conn.execute(
        """
        INSERT OR REPLACE INTO latest(
            id, timestamp_iso, tC, rH, hPa, lux, srawVoc, srawNox, voc_index, nox_index
        )
        VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (row["timestamp_iso"], t, rh, p, lx, sraw_voc, sraw_nox, voc_index, nox_index),
    )

    month_rows = conn.execute(
        """
        SELECT
            samples, t_sum, rh_sum,
            hpa_sum, hpa_n,
            lux_sum, lux_n,
            srawVoc_sum, srawVoc_n,
            srawNox_sum, srawNox_n,
            voc_index_sum, voc_index_n,
            nox_index_sum, nox_index_n
        FROM daily
        WHERE substr(date, 1, 7) = ?
        """,
        (month,),
    ).fetchall()

    days = len(month_rows)

    def daily_avg_sum(sum_col, n_col):
        vals = [r[sum_col] / r[n_col] for r in month_rows if r[n_col] > 0]
        return sum(vals), len(vals)

    t_sum = sum(r["t_sum"] / r["samples"] for r in month_rows if r["samples"] > 0)
    rh_sum = sum(r["rh_sum"] / r["samples"] for r in month_rows if r["samples"] > 0)
    hpa_sum, hpa_n = daily_avg_sum("hpa_sum", "hpa_n")
    lux_sum, lux_n = daily_avg_sum("lux_sum", "lux_n")
    sraw_voc_month_sum, sraw_voc_month_n = daily_avg_sum("srawVoc_sum", "srawVoc_n")
    sraw_nox_month_sum, sraw_nox_month_n = daily_avg_sum("srawNox_sum", "srawNox_n")
    voc_index_month_sum, voc_index_month_n = daily_avg_sum("voc_index_sum", "voc_index_n")
    nox_index_month_sum, nox_index_month_n = daily_avg_sum("nox_index_sum", "nox_index_n")

    conn.execute(
        """
        INSERT OR REPLACE INTO monthly(
            month,
            days,
            t_sum,
            rh_sum,
            hpa_sum,
            hpa_n,
            lux_sum,
            lux_n,
            srawVoc_sum,
            srawVoc_n,
            srawNox_sum,
            srawNox_n,
            voc_index_sum,
            voc_index_n,
            nox_index_sum,
            nox_index_n
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            month,
            days,
            t_sum,
            rh_sum,
            hpa_sum,
            hpa_n,
            lux_sum,
            lux_n,
            sraw_voc_month_sum,
            sraw_voc_month_n,
            sraw_nox_month_sum,
            sraw_nox_month_n,
            voc_index_month_sum,
            voc_index_month_n,
            nox_index_month_sum,
            nox_index_month_n,
        ),
    )


def _rebuild_summary_from_csv(conn):
    _clear_summary_tables(conn)
    _init_db(conn)

    last_line = 1
    last_ts = ""

    for last_line, row in _iter_csv_rows_from_line(1):
        _apply_row_to_summary(conn, row)
        last_ts = row["timestamp_iso"]

    stat = os.stat(CSV_PATH) if CSV_PATH and os.path.exists(CSV_PATH) else None
    if stat:
        _meta_set(conn, "csv_mtime", stat.st_mtime)
        _meta_set(conn, "csv_size", stat.st_size)

    _meta_set(conn, "last_line", last_line)
    _meta_set(conn, "last_timestamp_iso", last_ts)
    _meta_set(conn, "updated_at", time.time())
    conn.commit()


def _ensure_summary_current():
    with _DB_LOCK:
        conn = _connect_db()
        try:
            _init_db(conn)

            if not CSV_PATH or not os.path.exists(CSV_PATH):
                return

            stat = os.stat(CSV_PATH)
            db_mtime = _safe_float(_meta_get(conn, "csv_mtime"), None)
            db_size = _safe_float(_meta_get(conn, "csv_size"), None)
            last_line = int(_safe_float(_meta_get(conn, "last_line"), 1))

            rebuild = False
            if db_mtime is None or db_size is None:
                rebuild = True
            elif stat.st_size < db_size:
                rebuild = True
            elif stat.st_mtime < db_mtime:
                rebuild = True

            if rebuild:
                _rebuild_summary_from_csv(conn)
                _invalidate_response_cache()
                return

            if stat.st_size == db_size and stat.st_mtime == db_mtime:
                return

            changed = False
            new_last_line = last_line
            new_last_ts = _meta_get(conn, "last_timestamp_iso", "") or ""

            for new_last_line, row in _iter_csv_rows_from_line(last_line):
                _apply_row_to_summary(conn, row)
                new_last_ts = row["timestamp_iso"]
                changed = True

            _meta_set(conn, "csv_mtime", stat.st_mtime)
            _meta_set(conn, "csv_size", stat.st_size)
            _meta_set(conn, "last_line", new_last_line)
            _meta_set(conn, "last_timestamp_iso", new_last_ts)
            _meta_set(conn, "updated_at", time.time())
            conn.commit()

            if changed:
                _invalidate_response_cache()

        finally:
            conn.close()


def _avg_from_row(row, sum_col, n_col):
    if row[n_col]:
        return row[sum_col] / row[n_col]
    return None


def _summary_dict_from_row(row, date_key_name):
    out = {
        date_key_name: row[date_key_name],
        "Tavg": row["t_sum"] / row["samples"] if row["samples"] else None,
        "RHavg": row["rh_sum"] / row["samples"] if row["samples"] else None,
        "Pavg": _avg_from_row(row, "hpa_sum", "hpa_n"),
        "Luxavg": _avg_from_row(row, "lux_sum", "lux_n"),
        "SrawVocAvg": _avg_from_row(row, "srawVoc_sum", "srawVoc_n"),
        "SrawNoxAvg": _avg_from_row(row, "srawNox_sum", "srawNox_n"),
        "VocIndexAvg": _avg_from_row(row, "voc_index_sum", "voc_index_n"),
        "NoxIndexAvg": _avg_from_row(row, "nox_index_sum", "nox_index_n"),
    }

    if "samples" in row.keys():
        out["Samples"] = row["samples"]
    if "days" in row.keys():
        out["Days"] = row["days"]

    return out


def _fetch_latest(conn):
    row = conn.execute(
        """
        SELECT
            timestamp_iso,
            tC,
            rH,
            hPa,
            lux,
            srawVoc,
            srawNox,
            voc_index,
            nox_index
        FROM latest
        WHERE id = 1
        """
    ).fetchone()
    return dict(row) if row else None


def _fetch_daily(conn, date_key):
    row = conn.execute(
        """
        SELECT
            date,
            samples,
            t_sum,
            rh_sum,
            hpa_sum,
            hpa_n,
            lux_sum,
            lux_n,
            srawVoc_sum,
            srawVoc_n,
            srawNox_sum,
            srawNox_n,
            voc_index_sum,
            voc_index_n,
            nox_index_sum,
            nox_index_n
        FROM daily
        WHERE date = ?
        """,
        (date_key,),
    ).fetchone()

    if not row:
        return None

    return _summary_dict_from_row(row, "date")


def _fetch_last_days(conn, n=10):
    rows = conn.execute(
        """
        SELECT
            date,
            samples,
            t_sum,
            rh_sum,
            hpa_sum,
            hpa_n,
            lux_sum,
            lux_n,
            srawVoc_sum,
            srawVoc_n,
            srawNox_sum,
            srawNox_n,
            voc_index_sum,
            voc_index_n,
            nox_index_sum,
            nox_index_n
        FROM daily
        ORDER BY date DESC
        LIMIT ?
        """,
        (int(n),),
    ).fetchall()

    return [_summary_dict_from_row(row, "date") for row in reversed(rows)]


def _fetch_monthly(conn, month=None, current_year_only=False):
    q = """
        SELECT
            month,
            days,
            t_sum,
            rh_sum,
            hpa_sum,
            hpa_n,
            lux_sum,
            lux_n,
            srawVoc_sum,
            srawVoc_n,
            srawNox_sum,
            srawNox_n,
            voc_index_sum,
            voc_index_n,
            nox_index_sum,
            nox_index_n
        FROM monthly
    """
    params = []
    where = []

    if month:
        where.append("month = ?")
        params.append(month)

    if current_year_only:
        current_year = datetime.now().strftime("%Y")
        where.append("substr(month,1,4) = ?")
        params.append(current_year)

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY month"

    rows = conn.execute(q, params).fetchall()

    out = []
    for row in rows:
        item = {
            "month": row["month"],
            "Tavg": row["t_sum"] / row["days"] if row["days"] else None,
            "RHavg": row["rh_sum"] / row["days"] if row["days"] else None,
            "Pavg": _avg_from_row(row, "hpa_sum", "hpa_n"),
            "Luxavg": _avg_from_row(row, "lux_sum", "lux_n"),
            "SrawVocAvg": _avg_from_row(row, "srawVoc_sum", "srawVoc_n"),
            "SrawNoxAvg": _avg_from_row(row, "srawNox_sum", "srawNox_n"),
            "VocIndexAvg": _avg_from_row(row, "voc_index_sum", "voc_index_n"),
            "NoxIndexAvg": _avg_from_row(row, "nox_index_sum", "nox_index_n"),
            "Days": row["days"],
        }
        out.append(item)

    return out


def _fetch_hourly(conn, groups=8, block_hours=1):
    groups = max(1, int(groups))
    block_hours = int(block_hours)

    if block_hours not in _ALLOWED_HOUR_BLOCKS:
        block_hours = 1

    raw_limit = max(groups * block_hours + block_hours, groups * 2)

    rows = conn.execute(
        """
        SELECT
            hour,
            samples,
            t_sum,
            rh_sum,
            hpa_sum,
            hpa_n,
            lux_sum,
            lux_n,
            srawVoc_sum,
            srawVoc_n,
            srawNox_sum,
            srawNox_n,
            voc_index_sum,
            voc_index_n,
            nox_index_sum,
            nox_index_n
        FROM hourly
        ORDER BY hour DESC
        LIMIT ?
        """,
        (raw_limit,),
    ).fetchall()

    if not rows:
        return []

    rows = list(reversed(rows))
    buckets = {}
    order = []

    for row in rows:
        dt = datetime.strptime(row["hour"], "%Y-%m-%d %H:00")
        bucket_dt = _hour_bucket_start(dt, block_hours)
        bucket_key = bucket_dt.strftime("%Y-%m-%d %H:00")

        if bucket_key not in buckets:
            buckets[bucket_key] = {
                "bucket_start": bucket_key,
                "date": bucket_dt.strftime("%Y-%m-%d"),
                "label": _format_hour_block_label(bucket_dt, block_hours),
                "block_hours": block_hours,
                "samples": 0,
                "t_sum": 0.0,
                "rh_sum": 0.0,
                "hpa_sum": 0.0,
                "hpa_n": 0,
                "lux_sum": 0.0,
                "lux_n": 0,
                "srawVoc_sum": 0.0,
                "srawVoc_n": 0,
                "srawNox_sum": 0.0,
                "srawNox_n": 0,
                "voc_index_sum": 0.0,
                "voc_index_n": 0,
                "nox_index_sum": 0.0,
                "nox_index_n": 0,
            }
            order.append(bucket_key)

        b = buckets[bucket_key]
        for key in (
            "samples",
            "t_sum",
            "rh_sum",
            "hpa_sum",
            "hpa_n",
            "lux_sum",
            "lux_n",
            "srawVoc_sum",
            "srawVoc_n",
            "srawNox_sum",
            "srawNox_n",
            "voc_index_sum",
            "voc_index_n",
            "nox_index_sum",
            "nox_index_n",
        ):
            b[key] += row[key]

    out = []
    for key in order[-groups:]:
        b = buckets[key]
        out.append({
            "bucket_start": b["bucket_start"],
            "date": b["date"],
            "label": b["label"],
            "block_hours": b["block_hours"],
            "Tavg": b["t_sum"] / b["samples"] if b["samples"] else None,
            "RHavg": b["rh_sum"] / b["samples"] if b["samples"] else None,
            "Pavg": b["hpa_sum"] / b["hpa_n"] if b["hpa_n"] else None,
            "Luxavg": b["lux_sum"] / b["lux_n"] if b["lux_n"] else None,
            "SrawVocAvg": b["srawVoc_sum"] / b["srawVoc_n"] if b["srawVoc_n"] else None,
            "SrawNoxAvg": b["srawNox_sum"] / b["srawNox_n"] if b["srawNox_n"] else None,
            "VocIndexAvg": b["voc_index_sum"] / b["voc_index_n"] if b["voc_index_n"] else None,
            "NoxIndexAvg": b["nox_index_sum"] / b["nox_index_n"] if b["nox_index_n"] else None,
            "Samples": b["samples"],
        })

    return out


def _age_info_from_latest(latest):
    if not latest or not latest.get("timestamp_iso"):
        return {"age_minutes": None, "stale": None}

    ts = _parse_ts(latest["timestamp_iso"])
    if not ts:
        return {"age_minutes": None, "stale": None}

    age_seconds = max(0, (datetime.now() - ts).total_seconds())
    age_minutes = int(round(age_seconds / 60.0))

    return {
        "age_minutes": age_minutes,
        "stale": age_minutes >= 60,
    }


def _get_snapshot(n_last_days=10, hourly_groups=8, hour_block=1):
    _ensure_summary_current()

    conn = _connect_db()
    try:
        latest = _fetch_latest(conn)
        last_days = _fetch_last_days(conn, n_last_days)
        hourly = _fetch_hourly(conn, groups=hourly_groups, block_hours=hour_block)

        today = None
        today_key = None

        if latest and latest.get("timestamp_iso"):
            ts = _parse_ts(latest["timestamp_iso"])
            if ts:
                today_key = ts.strftime("%Y-%m-%d")
                today = _fetch_daily(conn, today_key)

        monthly = _fetch_monthly(conn)

        return {
            "latest": latest,
            "today": today,
            "today_key": today_key,
            "last_days": last_days,
            "hourly": hourly,
            "monthly": monthly,
        }

    finally:
        conn.close()


def _format_log_line(row):
    ts = row.get("timestamp_iso", "")
    category = row.get("category", "")
    action = row.get("action", "")
    intensity = row.get("intensity")
    subject = row.get("subject")
    note = row.get("note")

    bits = [f"{ts}", f"{category}:{action}"]
    if intensity:
        bits.append(str(intensity))
    if subject:
        bits.append(str(subject))
    if note:
        bits.append(f"— {note}")

    return " | ".join(bits)


def _insert_manual_log(args):
    category = _normalise_choice(args.get("category") or args.get("cat"))
    action = _normalise_choice(args.get("action") or args.get("act"))
    intensity = _normalise_choice(args.get("intensity") or args.get("level") or "")
    subject = _clean_text(args.get("subject") or args.get("plant") or args.get("target") or "")
    note = _clean_text(args.get("note") or args.get("notes") or args.get("text") or "")
    source = _normalise_choice(args.get("source") or "manual")
    timestamp_iso = _clean_text(args.get("timestamp_iso") or args.get("ts") or "") or _now_local_iso()

    if not category:
        return {
            "error": "missing_param",
            "param": "category",
            "example": f"http://{API_HOSTNAME}:{PORT}/log/manual?category=rain&action=now&intensity=light",
        }

    if not action:
        return {
            "error": "missing_param",
            "param": "action",
            "example": f"http://{API_HOSTNAME}:{PORT}/log/manual?category=plant_intervention&action=pruned&subject=grape%20vine",
        }

    known_category = category in _LOG_OPTIONS
    known_action = action in _LOG_OPTIONS.get(category, {}).get("actions", []) if known_category else False
    known_intensity = (
        not intensity
        or intensity in _LOG_OPTIONS.get(category, {}).get("intensities", [])
        if known_category
        else False
    )

    with _DB_LOCK:
        conn = _connect_db()
        try:
            _init_db(conn)

            cur = conn.execute(
                """
                INSERT INTO manual_log(
                    timestamp_iso,
                    category,
                    action,
                    intensity,
                    subject,
                    note,
                    source,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp_iso,
                    category,
                    action,
                    intensity or None,
                    subject or None,
                    note or None,
                    source or "manual",
                    _now_local_iso(),
                ),
            )
            conn.commit()
            _invalidate_response_cache()

            item = {
                "id": cur.lastrowid,
                "timestamp_iso": timestamp_iso,
                "category": category,
                "action": action,
                "intensity": intensity or None,
                "subject": subject or None,
                "note": note or None,
                "source": source or "manual",
            }

            return {
                "ok": True,
                **item,
                "known_category": known_category,
                "known_action": known_action,
                "known_intensity": known_intensity,
                "summary": _format_log_line(item),
            }

        finally:
            conn.close()


def _fetch_manual_logs(limit=20, date=None):
    limit = max(1, min(int(limit), 100))

    conn = _connect_db()
    try:
        _init_db(conn)

        if date:
            rows = conn.execute(
                """
                SELECT id, timestamp_iso, category, action, intensity, subject, note, source, created_at
                FROM manual_log
                WHERE substr(timestamp_iso, 1, 10) = ?
                ORDER BY timestamp_iso DESC, id DESC
                LIMIT ?
                """,
                (date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, timestamp_iso, category, action, intensity, subject, note, source, created_at
                FROM manual_log
                ORDER BY timestamp_iso DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        items = [dict(r) for r in rows]
        return {
            "count": len(items),
            "items": items,
            "lines": [_format_log_line(i) for i in items],
            "text": "\n".join(_format_log_line(i) for i in items),
        }

    finally:
        conn.close()


def _format_lockline(latest, today, ext):
    t = latest.get("tC") if latest else None
    rh = latest.get("rH") if latest else None
    lx = latest.get("lux") if latest else None
    voc_index = latest.get("voc_index") if latest else None
    nox_index = latest.get("nox_index") if latest else None
    out_weather = ext.get("weather")
    tide = ext.get("tide")

    parts = []

    if t is not None and rh is not None:
        parts.append(f"GH {_round(t,1)}°C {_round(rh,0)}%")
    if lx is not None:
        parts.append(f"{int(round(lx))}lx")
    if voc_index is not None:
        parts.append(f"VOC {int(round(voc_index))}")
    if nox_index is not None:
        parts.append(f"NOx {int(round(nox_index))}")
    if today and today.get("Tavg") is not None:
        parts.append(f"Today {_round(today['Tavg'],1)}°C/{_round(today['RHavg'],0)}%")
    if out_weather:
        parts.append(f"Out {out_weather}")
    if tide:
        parts.append(f"Tide {tide}")

    return " | ".join(parts)[:180]


def _alerts(latest, today, ext):
    alerts = []

    t = latest.get("tC") if latest else None
    rh = latest.get("rH") if latest else None
    lx = latest.get("lux") if latest else None
    voc_index = latest.get("voc_index") if latest else None
    nox_index = latest.get("nox_index") if latest else None
    out_temp = ext.get("out_temp_c")
    wind = ext.get("out_wind_mph")
    out_h = ext.get("out_humidity")

    if (lx is not None and lx >= 20000) or (
        today and today.get("Luxavg") is not None and today["Luxavg"] >= 5000
    ):
        alerts.append({"emoji": "☀️", "code": "bright", "msg": "Strong light: watch watering and venting."})

    if (out_temp is not None and out_temp <= 1.0) or (t is not None and t <= 1.0):
        alerts.append({"emoji": "❄️", "code": "frost_risk", "msg": "Frost risk: protect tender plants."})

    if wind is not None and wind >= 15 and out_h is not None and rh is not None and out_h + 5 < rh:
        alerts.append({"emoji": "🌬", "code": "vent_opportunity", "msg": "Windy and drier outside: good time to vent."})

    if voc_index is not None and voc_index >= 200:
        alerts.append({"emoji": "🫧", "code": "voc_elevated", "msg": "VOC index is elevated: log likely causes and vent if appropriate."})

    if nox_index is not None and nox_index >= 200:
        alerts.append({"emoji": "🌫", "code": "nox_elevated", "msg": "NOx index is elevated: compare with outdoor air and recent interventions."})

    return alerts


def _siri_report(latest, today, ext):
    t = latest.get("tC") if latest else None
    rh = latest.get("rH") if latest else None
    p = latest.get("hPa") if latest else None
    lx = latest.get("lux") if latest else None
    voc_index = latest.get("voc_index") if latest else None
    nox_index = latest.get("nox_index") if latest else None
    weather = ext.get("weather")
    tide = ext.get("tide")

    chunks = []

    if t is not None and rh is not None:
        chunks.append(f"In the greenhouse it's {round(t,1)} degrees with {round(rh)} percent humidity.")
    if lx is not None:
        chunks.append("It's dark in there right now." if lx <= 5 else f"Light is about {int(round(lx))} lux.")
    if p is not None:
        chunks.append(f"Pressure is {int(round(p))} hectopascals.")
    if voc_index is not None:
        chunks.append(f"VOC index is {int(round(voc_index))}.")
    if nox_index is not None:
        chunks.append(f"NOx index is {int(round(nox_index))}.")
    if today and today.get("Tavg") is not None:
        chunks.append(f"Today's average is {round(today['Tavg'],1)} degrees and {round(today['RHavg'])} percent humidity.")
    if weather:
        chunks.append(f"Outside, it's {weather}.")
    if tide:
        chunks.append(f"Tide update: {tide}.")

    return " ".join(chunks)


def _interpretation(latest, today, ext):
    lines = []

    rh = latest.get("rH") if latest else None
    voc_index = latest.get("voc_index") if latest else None
    nox_index = latest.get("nox_index") if latest else None
    out_h = ext.get("out_humidity")
    wind = ext.get("out_wind_mph")

    if out_h is not None and rh is not None and rh > out_h:
        lines.append("Inside humidity is higher than outside.")
    if wind is not None and wind >= 15:
        lines.append("Wind is strong: venting can be effective if temperature allows.")
    if today and today.get("Luxavg") is not None and today["Luxavg"] >= 5000:
        lines.append("It has been a relatively bright day in the greenhouse.")
    if voc_index is not None or nox_index is not None:
        lines.append("Air-quality readings are available; compare spikes against manual logs.")
    if not lines:
        lines.append("Conditions look stable. Keep tracking trends for changes.")

    return lines


def _latest_dict(latest):
    return {
        "timestamp": latest["timestamp_iso"],
        "tC": _round(latest.get("tC"), 1),
        "rH": _round(latest.get("rH"), 1),
        "hPa": _round(latest.get("hPa"), 1),
        "lux": int(round(latest["lux"])) if latest.get("lux") is not None else None,
        "srawVoc": _round(latest.get("srawVoc"), 1),
        "srawNox": _round(latest.get("srawNox"), 1),
        "voc_index": _round(latest.get("voc_index"), 1),
        "nox_index": _round(latest.get("nox_index"), 1),
    }


def _daily_dict(today):
    today = today or {}
    return {
        "date": today.get("date"),
        "Tavg": _round(today.get("Tavg"), 1),
        "RHavg": _round(today.get("RHavg"), 1),
        "Pavg": _round(today.get("Pavg"), 1),
        "Luxavg": int(round(today["Luxavg"])) if today.get("Luxavg") is not None else None,
        "SrawVocAvg": _round(today.get("SrawVocAvg"), 1),
        "SrawNoxAvg": _round(today.get("SrawNoxAvg"), 1),
        "VocIndexAvg": _round(today.get("VocIndexAvg"), 1),
        "NoxIndexAvg": _round(today.get("NoxIndexAvg"), 1),
        "Samples": today.get("Samples"),
    }


def build_watch_summary(args):
    cached = _response_cache_get("watch_summary", args)
    if cached is not None:
        return cached

    past_days = _safe_int(args.get("days", args.get("past_days", 7)), 7, minimum=1, maximum=60)
    trend_width = _safe_int(args.get("width", 10), 10, minimum=1, maximum=60)

    hour_block = _safe_int(args.get("hour_block", args.get("block_hours", 1)), 1)
    if hour_block not in _ALLOWED_HOUR_BLOCKS:
        hour_block = 1

    hourly_groups = _safe_int(args.get("hourly_groups", args.get("hours", 8)), 8, minimum=1, maximum=48)
    log_count = _safe_int(args.get("log_count", args.get("logs", 5)), 5, minimum=0, maximum=20)

    snap = _get_snapshot(
        n_last_days=max(past_days, trend_width, 12),
        hourly_groups=hourly_groups,
        hour_block=hour_block,
    )

    latest = snap["latest"]
    if not latest:
        return {"error": "no_data", "hint": "Check CSV_PATH in config.py and that your CSV has timestamp_iso,tC,rH,hPa,lux"}

    today = snap["today"] or {}
    today_key = snap["today_key"]
    current_year = (today_key or datetime.now().strftime("%Y-%m-%d"))[:4]
    last_days = snap["last_days"]
    hourly_items = snap["hourly"]
    recent_logs = _fetch_manual_logs(limit=log_count).get("items", []) if log_count else []
    age_info = _age_info_from_latest(latest)

    lines = ["Jeraenium Summary", "", "Now (avg)"]
    lines.append(f"T | {_fmt_compact_num(latest.get('tC'))} ({_fmt_compact_num(today.get('Tavg'))} °C)")
    lines.append(f"H | {_fmt_compact_num(latest.get('rH'))} ({_fmt_compact_num(today.get('RHavg'))} %)")
    lines.append(f"P | {_fmt_compact_num(latest.get('hPa'), 0)} ({_fmt_compact_num(today.get('Pavg'), 0)} hPa)")
    lines.append(f"L | {_fmt_compact_num(latest.get('lux'), 0)} ({_fmt_compact_num(today.get('Luxavg'), 0)} lux)")

    if latest.get("voc_index") is not None:
        lines.append(f"VOC | {_fmt_compact_num(latest.get('voc_index'), 0)} index")
    elif latest.get("srawVoc") is not None:
        lines.append(f"VOC raw | {_fmt_compact_num(latest.get('srawVoc'), 0)}")

    if latest.get("nox_index") is not None:
        lines.append(f"NOx | {_fmt_compact_num(latest.get('nox_index'), 0)} index")
    elif latest.get("srawNox") is not None:
        lines.append(f"NOx raw | {_fmt_compact_num(latest.get('srawNox'), 0)}")

    if age_info["age_minutes"] is not None:
        stale_txt = " stale" if age_info["stale"] else ""
        lines.append(f"Age | {age_info['age_minutes']} min{stale_txt}")

    t_series = [d["Tavg"] for d in last_days if d.get("Tavg") is not None]
    h_series = [d["RHavg"] for d in last_days if d.get("RHavg") is not None]
    p_series = [d["Pavg"] for d in last_days if d.get("Pavg") is not None]
    l_series = [d["Luxavg"] for d in last_days if d.get("Luxavg") is not None]
    voc_series = [d["VocIndexAvg"] for d in last_days if d.get("VocIndexAvg") is not None]
    nox_series = [d["NoxIndexAvg"] for d in last_days if d.get("NoxIndexAvg") is not None]

    lines += [
        "",
        "Trends",
        f"Temperature {_spark(t_series[-trend_width:])}",
        f"Humidity {_spark(h_series[-trend_width:])}",
        f"Pressure {_spark(p_series[-trend_width:])}",
        f"Light {_spark(l_series[-trend_width:])}",
    ]

    if voc_series:
        lines.append(f"VOC {_spark(voc_series[-trend_width:])}")
    if nox_series:
        lines.append(f"NOx {_spark(nox_series[-trend_width:])}")

    if hourly_items:
        lines += ["", "Hourly" if hour_block == 1 else f"{hour_block}-Hourly"]
        prev_date = None

        for h in hourly_items:
            if h["date"] != prev_date:
                if prev_date is not None:
                    lines.append("")
                lines.append(h["date"])
                prev_date = h["date"]

            lines.append(
                f"{h['label']} | "
                f"{_fmt_compact_num(h.get('Tavg'),0)} "
                f"{_fmt_compact_num(h.get('RHavg'),0)} "
                f"{_fmt_compact_num(h.get('Pavg'),0)} "
                f"{_fmt_compact_num(h.get('Luxavg'),0)}"
            )

    if recent_logs:
        lines += ["", "Recent Logs"]
        for item in recent_logs:
            ts = item.get("timestamp_iso", "")
            time_part = ts[11:16] if len(ts) >= 16 else ts
            label = f"{item.get('category')}:{item.get('action')}"
            extra = item.get("subject") or item.get("intensity") or ""
            if extra:
                lines.append(f"{time_part} | {label} | {extra}")
            else:
                lines.append(f"{time_part} | {label}")

    monthly_items = []
    lines += ["", "Monthly"]

    for m in snap["monthly"]:
        if not m["month"].startswith(current_year):
            continue

        monthly_items.append({
            "month": m["month"],
            "month_letter": _month_letter(m["month"]),
            "Tavg": _round(m.get("Tavg"), 1),
            "RHavg": _round(m.get("RHavg"), 1),
            "Pavg": _round(m.get("Pavg"), 1),
            "Luxavg": _round(m.get("Luxavg"), 1),
            "SrawVocAvg": _round(m.get("SrawVocAvg"), 1),
            "SrawNoxAvg": _round(m.get("SrawNoxAvg"), 1),
            "VocIndexAvg": _round(m.get("VocIndexAvg"), 1),
            "NoxIndexAvg": _round(m.get("NoxIndexAvg"), 1),
            "Days": m.get("Days"),
        })

        lines.append(
            f"{_month_letter(m['month'])} | "
            f"{_fmt_compact_num(m.get('Tavg'),0)} "
            f"{_fmt_compact_num(m.get('RHavg'),0)} "
            f"{_fmt_compact_num(m.get('Pavg'),0)} "
            f"{_fmt_compact_num(m.get('Luxavg'),0)}"
        )

    recent_days = last_days[-past_days:]
    recent_items = []
    lines += ["", "Past Week" if past_days == 7 else f"Past {past_days} Days"]

    prev_month = None
    for d in recent_days:
        dkey = d["date"]
        month_key = dkey[:7]
        day_num = str(int(dkey[8:10]))

        if prev_month != month_key:
            if prev_month is not None:
                lines.append("")
            lines.append(_month_name_from_key(month_key))
            prev_month = month_key

        recent_items.append({
            "date": dkey,
            "day": int(dkey[8:10]),
            "month": month_key,
            "month_name": _month_name_from_key(month_key),
            "Tavg": _round(d.get("Tavg"), 1),
            "RHavg": _round(d.get("RHavg"), 1),
            "Pavg": _round(d.get("Pavg"), 1),
            "Luxavg": _round(d.get("Luxavg"), 1),
            "SrawVocAvg": _round(d.get("SrawVocAvg"), 1),
            "SrawNoxAvg": _round(d.get("SrawNoxAvg"), 1),
            "VocIndexAvg": _round(d.get("VocIndexAvg"), 1),
            "NoxIndexAvg": _round(d.get("NoxIndexAvg"), 1),
            "Samples": d.get("Samples"),
        })

        lines.append(
            f"{day_num} | "
            f"{_fmt_compact_num(d.get('Tavg'),0)} "
            f"{_fmt_compact_num(d.get('RHavg'),0)} "
            f"{_fmt_compact_num(d.get('Pavg'),0)} "
            f"{_fmt_compact_num(d.get('Luxavg'),0)}"
        )

    result = {
        "generated_at": _utc_now_iso(),
        "title": "Jeraenium Summary",
        "today_key": today_key,
        "trend_width": trend_width,
        "past_days": past_days,
        "hour_block": hour_block,
        "hourly_groups": hourly_groups,
        "log_count": log_count,
        "age_minutes": age_info["age_minutes"],
        "stale": age_info["stale"],
        "now": {
            "timestamp": latest.get("timestamp_iso"),
            "tC": _round(latest.get("tC"), 1),
            "rH": _round(latest.get("rH"), 1),
            "hPa": _round(latest.get("hPa"), 1),
            "lux": _round(latest.get("lux"), 1),
            "srawVoc": _round(latest.get("srawVoc"), 1),
            "srawNox": _round(latest.get("srawNox"), 1),
            "voc_index": _round(latest.get("voc_index"), 1),
            "nox_index": _round(latest.get("nox_index"), 1),
            "today_Tavg": _round(today.get("Tavg"), 1),
            "today_RHavg": _round(today.get("RHavg"), 1),
            "today_Pavg": _round(today.get("Pavg"), 1),
            "today_Luxavg": _round(today.get("Luxavg"), 1),
            "today_SrawVocAvg": _round(today.get("SrawVocAvg"), 1),
            "today_SrawNoxAvg": _round(today.get("SrawNoxAvg"), 1),
            "today_VocIndexAvg": _round(today.get("VocIndexAvg"), 1),
            "today_NoxIndexAvg": _round(today.get("NoxIndexAvg"), 1),
        },
        "trends": {
            "Temperature": _spark(t_series[-trend_width:]),
            "Humidity": _spark(h_series[-trend_width:]),
            "Pressure": _spark(p_series[-trend_width:]),
            "Light": _spark(l_series[-trend_width:]),
            "VOC": _spark(voc_series[-trend_width:]),
            "NOx": _spark(nox_series[-trend_width:]),
        },
        "hourly": [
            {
                "bucket_start": h["bucket_start"],
                "date": h["date"],
                "label": h["label"],
                "block_hours": h["block_hours"],
                "Tavg": _round(h.get("Tavg"), 1),
                "RHavg": _round(h.get("RHavg"), 1),
                "Pavg": _round(h.get("Pavg"), 1),
                "Luxavg": _round(h.get("Luxavg"), 1),
                "SrawVocAvg": _round(h.get("SrawVocAvg"), 1),
                "SrawNoxAvg": _round(h.get("SrawNoxAvg"), 1),
                "VocIndexAvg": _round(h.get("VocIndexAvg"), 1),
                "NoxIndexAvg": _round(h.get("NoxIndexAvg"), 1),
                "Samples": h.get("Samples"),
            }
            for h in hourly_items
        ],
        "recent_logs": recent_logs,
        "monthly": monthly_items,
        "recent_days": recent_items,
        "lines": lines,
        "text": "\n".join(lines),
    }

    return _response_cache_set("watch_summary", args, result)


def build_shortcuts_payload(args):
    cached = _response_cache_get("shortcuts_payload", args)
    if cached is not None:
        return cached

    n = _safe_int(args.get("n", 10), 10, minimum=1, maximum=120)
    snap = _get_snapshot(n_last_days=max(n, 14), hourly_groups=8, hour_block=1)
    latest = snap["latest"]

    if not latest:
        return {"error": "no_data", "hint": "Check CSV_PATH in config.py and that your CSV has timestamp_iso,tC,rH,hPa,lux"}

    today = snap["today"] or {}
    ext = _read_external(args)
    last_days = snap["last_days"][-n:]

    t_series = [d["Tavg"] for d in last_days if d.get("Tavg") is not None]
    rh_series = [d["RHavg"] for d in last_days if d.get("RHavg") is not None]
    lux_series = [d["Luxavg"] for d in last_days if d.get("Luxavg") is not None]
    voc_series = [d["VocIndexAvg"] for d in last_days if d.get("VocIndexAvg") is not None]
    nox_series = [d["NoxIndexAvg"] for d in last_days if d.get("NoxIndexAvg") is not None]

    payload = {
        "generated_at": _utc_now_iso(),
        "base_urls": _base_urls(),
        "greenhouse": {
            "latest": _latest_dict(latest),
            "today": _daily_dict(today),
            "last_days": last_days,
            "monthly": snap["monthly"],
            "trends": {
                "Tavg": _spark(t_series),
                "RHavg": _spark(rh_series),
                "Luxavg": _spark(lux_series),
                "VocIndexAvg": _spark(voc_series),
                "NoxIndexAvg": _spark(nox_series),
                "WindowDays": n,
            },
            "interpretation": _interpretation(latest, today, ext),
        },
        "external": ext,
        "shortcuts": {
            "lockline": _format_lockline(latest, today, ext),
            "alerts": _alerts(latest, today, ext),
            "siri": _siri_report(latest, today, ext),
        },
    }

    return _response_cache_set("shortcuts_payload", args, payload)


class ApiRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, ref_req, api_ref):
        self.api = api_ref
        super().__init__(request, client_address, ref_req)

    def _send_json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def call_api(self, method, path, args):
        routes = self.api.routing.get(method, {})

        if path in routes:
            try:
                result = routes[path](args)
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": "server_error", "detail": str(e), "path": path})
        else:
            self._send_json(404, {"error": "not_found", "method": method, "path": path})

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        args = _flatten_args(parse_qs(parsed_url.query))
        self.call_api("GET", path, args)

    def do_POST(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        args = _flatten_args(parse_qs(parsed_url.query))

        content_length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if body:
            content_type = self.headers.get("Content-Type", "")

            try:
                if "application/json" in content_type:
                    parsed_body = json.loads(body.decode("utf-8"))
                    if isinstance(parsed_body, dict):
                        args.update(parsed_body)
                    else:
                        self._send_json(400, {"error": "bad_request", "detail": "JSON body must be an object"})
                        return
                else:
                    args.update(_flatten_args(parse_qs(body.decode("utf-8"))))
            except Exception as e:
                self._send_json(400, {"error": "bad_request", "detail": str(e)})
                return

        self.call_api("POST", path, args)


class API:
    def __init__(self):
        self.routing = {"GET": {}, "POST": {}}

    def get(self, path):
        def wrapper(fn):
            self.routing["GET"][path] = fn
            return fn
        return wrapper

    def post(self, path):
        def wrapper(fn):
            self.routing["POST"][path] = fn
            return fn
        return wrapper

    def __call__(self, request, client_address, ref_request):
        return ApiRequestHandler(request, client_address, ref_request, api_ref=self)


api = API()


@api.get("/debug/config")
def debug_config(_):
    return {
        "PORT": PORT,
        "CSV_PATH": str(CSV_PATH),
        "SQLITE_SUMMARY_PATH": str(SQLITE_SUMMARY_PATH),
        "EXTERNAL_JSON_PATH": str(EXTERNAL_JSON_PATH) if EXTERNAL_JSON_PATH else None,
        "API_HOSTNAME": API_HOSTNAME,
        "API_LAN_IP": API_LAN_IP,
        "base_urls": _base_urls(),
        "csv_exists": bool(CSV_PATH and os.path.exists(CSV_PATH)),
        "sqlite_exists": os.path.exists(SQLITE_SUMMARY_PATH),
    }


@api.get("/debug/cache")
def debug_cache(_):
    _ensure_summary_current()
    conn = _connect_db()

    try:
        latest = _fetch_latest(conn)
        hourly_count = conn.execute("SELECT COUNT(*) FROM hourly").fetchone()[0]
        daily_count = conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
        monthly_count = conn.execute("SELECT COUNT(*) FROM monthly").fetchone()[0]
        manual_count = conn.execute("SELECT COUNT(*) FROM manual_log").fetchone()[0]

        return {
            "csv_path": str(CSV_PATH),
            "sqlite_summary_path": str(SQLITE_SUMMARY_PATH),
            "latest_timestamp": latest.get("timestamp_iso") if latest else None,
            "hours": hourly_count,
            "days": daily_count,
            "months": monthly_count,
            "manual_logs": manual_count,
            "meta": {
                "csv_mtime": _meta_get(conn, "csv_mtime"),
                "csv_size": _meta_get(conn, "csv_size"),
                "last_line": _meta_get(conn, "last_line"),
                "last_timestamp_iso": _meta_get(conn, "last_timestamp_iso"),
                "updated_at": _meta_get(conn, "updated_at"),
            },
            "response_cache_entries": len(_RESPONSE_CACHE),
        }

    finally:
        conn.close()


@api.get("/debug/rebuild")
def debug_rebuild(args):
    confirm = str(args.get("confirm", "")).lower()

    if confirm not in ("1", "true", "yes", "y"):
        return {
            "error": "confirmation_required",
            "hint": "/debug/rebuild?confirm=yes",
            "note": "Sensor summaries will be rebuilt from CSV. manual_log rows are preserved.",
        }

    with _DB_LOCK:
        conn = _connect_db()
        try:
            _init_db(conn)
            _rebuild_summary_from_csv(conn)
            _invalidate_response_cache()
        finally:
            conn.close()

    return {"ok": True, "message": "Summary tables rebuilt from CSV. manual_log was preserved."}


@api.get("/")
def index(_):
    return {
        "name": "Jeraenium Greenhouse ESP32 API",
        "version": "5.0.0",
        "storage": "SQLite rolling summary + manual Watch log",
        "base_urls": _base_urls(),
        "endpoints": [
            "/gh/latest",
            "/gh/today",
            "/gh/daily?date=YYYY-MM-DD",
            "/gh/last_days?n=10",
            "/gh/hourly?groups=12&block_hours=1",
            "/gh/monthly?month=YYYY-MM",
            "/gh/summary?n=10",
            "/gh/risk?n=10",
            "/gh/chart?metric=Tavg&n=14",
            "/gh/insights?n=10",
            "/shortcuts/dict?n=10",
            "/shortcuts/lockline?n=10",
            "/shortcuts/alerts?n=10",
            "/shortcuts/siri?n=10",
            "/shortcuts/watch_summary",
            "/shortcuts/watch_summary_text",
            "/log/options",
            "/log/manual?category=rain&action=now&intensity=light&source=watch",
            "/log/recent?n=20",
            "/log/today",
            "/log/text?n=10",
            "/debug/config",
            "/debug/cache",
            "/debug/rebuild?confirm=yes",
        ],
        "watch_shortcut_url": f"http://{API_HOSTNAME}:{PORT}/log/manual",
        "watch_shortcut_url_lan_ip": f"http://{API_LAN_IP}:{PORT}/log/manual",
        "notes": [
            "Sensor summaries are derived from CSV and updated incrementally.",
            "Manual logs annotate time and do not mutate the sensor stream.",
            "POST /log/manual accepts JSON or form-encoded bodies.",
        ],
    }


@api.get("/gh/latest")
def gh_latest(args):
    payload = build_shortcuts_payload(args)
    return payload if "error" in payload else payload["greenhouse"]["latest"]


@api.get("/gh/today")
def gh_today(args):
    payload = build_shortcuts_payload(args)
    return payload if "error" in payload else payload["greenhouse"]["today"]


@api.get("/gh/daily")
def gh_daily(args):
    date = args.get("date")
    if not date:
        return {"error": "missing_param", "param": "date", "example": "/gh/daily?date=2026-02-15"}

    _ensure_summary_current()
    conn = _connect_db()

    try:
        item = _fetch_daily(conn, date)
        return item or {"error": "not_found", "date": date}

    finally:
        conn.close()


@api.get("/gh/last_days")
def gh_last_days(args):
    payload = build_shortcuts_payload(args)
    return payload if "error" in payload else {
        "n": payload["greenhouse"]["trends"]["WindowDays"],
        "items": payload["greenhouse"]["last_days"],
    }


@api.get("/gh/hourly")
def gh_hourly(args):
    groups = _safe_int(args.get("groups", args.get("hours", 12)), 12, minimum=1, maximum=72)
    block_hours = _safe_int(args.get("block_hours", args.get("hour_block", 1)), 1)

    if block_hours not in _ALLOWED_HOUR_BLOCKS:
        block_hours = 1

    _ensure_summary_current()
    conn = _connect_db()

    try:
        items = _fetch_hourly(conn, groups=groups, block_hours=block_hours)
        return {
            "groups": groups,
            "block_hours": block_hours,
            "items": [
                {
                    "bucket_start": h["bucket_start"],
                    "date": h["date"],
                    "label": h["label"],
                    "block_hours": h["block_hours"],
                    "Tavg": _round(h.get("Tavg"), 1),
                    "RHavg": _round(h.get("RHavg"), 1),
                    "Pavg": _round(h.get("Pavg"), 1),
                    "Luxavg": _round(h.get("Luxavg"), 1),
                    "SrawVocAvg": _round(h.get("SrawVocAvg"), 1),
                    "SrawNoxAvg": _round(h.get("SrawNoxAvg"), 1),
                    "VocIndexAvg": _round(h.get("VocIndexAvg"), 1),
                    "NoxIndexAvg": _round(h.get("NoxIndexAvg"), 1),
                    "Samples": h.get("Samples"),
                }
                for h in items
            ],
        }

    finally:
        conn.close()


@api.get("/gh/monthly")
def gh_monthly(args):
    month = args.get("month")

    _ensure_summary_current()
    conn = _connect_db()

    try:
        items = _fetch_monthly(conn, month=month if month else None)

        if month:
            return items[0] if items else {"error": "not_found", "month": month}

        return {"count": len(items), "items": items}

    finally:
        conn.close()


@api.get("/gh/summary")
def gh_summary(args):
    return build_shortcuts_payload(args)


@api.get("/shortcuts/dict")
def shortcuts_dict(args):
    payload = build_shortcuts_payload(args)

    if "error" in payload:
        return payload

    return {
        "generated_at": payload["generated_at"],
        "base_urls": payload["base_urls"],
        "latest": payload["greenhouse"]["latest"],
        "today": payload["greenhouse"]["today"],
        "alerts": payload["shortcuts"]["alerts"],
        "lockline": payload["shortcuts"]["lockline"],
        "siri": payload["shortcuts"]["siri"],
        "interpretation": payload["greenhouse"]["interpretation"],
        "external": payload["external"],
    }


@api.get("/shortcuts/lockline")
def shortcuts_lockline(args):
    payload = build_shortcuts_payload(args)
    return payload if "error" in payload else {"text": payload["shortcuts"]["lockline"]}


@api.get("/shortcuts/alerts")
def shortcuts_alerts(args):
    payload = build_shortcuts_payload(args)

    if "error" in payload:
        return payload

    joined = " ".join([a["emoji"] for a in payload["shortcuts"]["alerts"]]) or "✅"
    return {"count": len(payload["shortcuts"]["alerts"]), "items": payload["shortcuts"]["alerts"], "summary": joined}


@api.get("/shortcuts/siri")
def shortcuts_siri(args):
    payload = build_shortcuts_payload(args)
    return payload if "error" in payload else {"speak": payload["shortcuts"]["siri"]}


@api.get("/shortcuts/watch_summary")
def shortcuts_watch_summary(args):
    return build_watch_summary(args)


@api.get("/shortcuts/watch_summary_text")
def shortcuts_watch_summary_text(args):
    payload = build_watch_summary(args)

    if "error" in payload:
        return payload

    return {
        "text": payload["text"],
        "lines": payload["lines"],
        "generated_at": payload["generated_at"],
        "past_days": payload["past_days"],
        "trend_width": payload["trend_width"],
        "hour_block": payload["hour_block"],
        "hourly_groups": payload["hourly_groups"],
        "log_count": payload["log_count"],
        "age_minutes": payload["age_minutes"],
        "stale": payload["stale"],
        "recent_logs": payload["recent_logs"],
    }


@api.get("/log/options")
def log_options(_):
    return {
        "categories": list(_LOG_OPTIONS.keys()),
        "options": _LOG_OPTIONS,
        "base_urls": _base_urls(),
        "examples": [
            f"http://{API_HOSTNAME}:{PORT}/log/manual?category=rain&action=now&intensity=light&source=watch",
            f"http://{API_HOSTNAME}:{PORT}/log/manual?category=plant_intervention&action=pruned&subject=grape%20vine&note=contralateral%20to%20lux%20sensor&source=watch",
            f"http://{API_HOSTNAME}:{PORT}/log/manual?category=environment&action=vent_opened&intensity=partial&source=watch",
            f"http://{API_HOSTNAME}:{PORT}/log/manual?category=observation&action=flowering&subject=grape%20vine&source=watch",
            f"http://{API_LAN_IP}:{PORT}/log/manual?category=rain&action=now&intensity=light&source=watch",
        ],
        "post": {
            "url": f"http://{API_HOSTNAME}:{PORT}/log/manual",
            "method": "POST",
            "body": {
                "category": "plant_intervention",
                "action": "pruned",
                "intensity": "moderate",
                "subject": "grape vine",
                "note": "possible lux confound marker",
                "source": "watch",
            },
        },
    }


@api.get("/log/manual")
def log_manual_get(args):
    return _insert_manual_log(args)


@api.post("/log/manual")
def log_manual_post(args):
    return _insert_manual_log(args)


@api.get("/log/recent")
def log_recent(args):
    n = _safe_int(args.get("n", 20), 20, minimum=1, maximum=100)
    return _fetch_manual_logs(limit=n)


@api.get("/log/today")
def log_today(args):
    date = args.get("date") or datetime.now().strftime("%Y-%m-%d")
    n = _safe_int(args.get("n", 50), 50, minimum=1, maximum=100)
    return _fetch_manual_logs(limit=n, date=date)


@api.get("/log/text")
def log_text(args):
    n = _safe_int(args.get("n", 10), 10, minimum=1, maximum=100)
    payload = _fetch_manual_logs(limit=n)

    return {
        "text": payload["text"],
        "lines": payload["lines"],
        "count": payload["count"],
    }


@api.get("/gh/risk")
def gh_risk(args):
    payload = build_shortcuts_payload(args)

    if "error" in payload:
        return payload

    latest = payload["greenhouse"]["latest"]
    today = payload["greenhouse"]["today"]
    ext = payload["external"]

    rh = today.get("RHavg") or latest.get("rH") or 0
    out_t = ext.get("out_temp_c")
    in_t = latest.get("tC")
    lux = latest.get("lux") or 0
    voc_index = latest.get("voc_index")
    nox_index = latest.get("nox_index")

    frost = 0
    if out_t is not None:
        frost = max(frost, int(round(max(0, (2.0 - out_t) * 40))))
    if in_t is not None:
        frost = max(frost, int(round(max(0, (2.0 - in_t) * 50))))

    heat = 0
    if in_t is not None:
        heat += max(0, int(round((in_t - 28) * 10)))
    heat += max(0, int(round((lux - 30000) / 2000)))
    heat = min(100, heat)

    humidity = min(100, int(round(max(0, rh - 80) * 5)))
    air = 0
    if voc_index is not None:
        air = max(air, min(100, int(round(max(0, voc_index - 100) / 2))))
    if nox_index is not None:
        air = max(air, min(100, int(round(max(0, nox_index - 100) / 2))))

    actions = []

    if humidity >= 60:
        actions.append("Vent when conditions allow. Increase airflow around dense foliage.")
    if frost >= 40:
        actions.append("Close vents early evening. Add fleece or heat for tender plants.")
    if heat >= 40:
        actions.append("Shade or vent midday. Check watering and wilting.")
    if air >= 50:
        actions.append("Air-quality index is elevated. Compare with manual logs and vent if appropriate.")
    if not actions:
        actions.append("No urgent action suggested. Keep logging and watch trends.")

    return {
        "scores": {
            "humidity": humidity,
            "frost": frost,
            "heat": heat,
            "air_quality": air,
        },
        "actions": actions,
        "signals": payload["shortcuts"]["alerts"],
    }


@api.get("/gh/chart")
def gh_chart(args):
    metric = (args.get("metric") or "Tavg").strip()
    n = _safe_int(args.get("n", 14), 14, minimum=1, maximum=365)

    allowed = {
        "Tavg",
        "RHavg",
        "Pavg",
        "Luxavg",
        "SrawVocAvg",
        "SrawNoxAvg",
        "VocIndexAvg",
        "NoxIndexAvg",
    }

    if metric not in allowed:
        return {"error": "unknown_metric", "metric": metric, "allowed": sorted(allowed)}

    _ensure_summary_current()
    conn = _connect_db()

    try:
        items = _fetch_last_days(conn, n)

    finally:
        conn.close()

    vals = [d.get(metric) for d in items if d.get(metric) is not None]

    return {
        "metric": metric,
        "n": n,
        "spark": _spark(vals),
        "dates": [d["date"] for d in items],
        "values": [_round(d.get(metric), 2) for d in items],
    }


@api.get("/gh/insights")
def gh_insights(args):
    payload = build_shortcuts_payload(args)

    if "error" in payload:
        return payload

    latest = payload["greenhouse"]["latest"]
    today = payload["greenhouse"]["today"]
    ext = payload["external"]

    bullets = []

    if latest.get("rH") is not None and latest["rH"] >= 99:
        bullets.append("RH is effectively 100% right now.")
    if today.get("Samples") is not None:
        bullets.append(f"Samples logged today: {today['Samples']}.")
    if latest.get("voc_index") is not None:
        bullets.append(f"VOC index: {latest['voc_index']}.")
    elif latest.get("srawVoc") is not None:
        bullets.append(f"Raw VOC signal: {latest['srawVoc']}.")
    if latest.get("nox_index") is not None:
        bullets.append(f"NOx index: {latest['nox_index']}.")
    elif latest.get("srawNox") is not None:
        bullets.append(f"Raw NOx signal: {latest['srawNox']}.")
    if ext.get("out_wind_mph") is not None:
        bullets.append(f"Outside wind: {ext['out_wind_mph']} mph.")
    if ext.get("tide"):
        bullets.append(f"Tide: {ext['tide']}")

    logs = _fetch_manual_logs(limit=3).get("items", [])
    if logs:
        bullets.append(f"Recent manual logs: {len(logs)} in latest view.")

    if not bullets:
        bullets.append("No standout signals detected in the latest window.")

    return {"bullets": bullets, "one_liner": payload["shortcuts"]["lockline"], "recent_logs": logs}


if __name__ == "__main__":
    _ensure_summary_current()
    httpd = ThreadingHTTPServer(("", PORT), api)
    print(f"Application started at http://127.0.0.1:{PORT}/")
    print(f"Also try http://{API_HOSTNAME}:{PORT}/ or http://{API_LAN_IP}:{PORT}/")
    print(f"SQLite summary at {SQLITE_SUMMARY_PATH}")
    httpd.serve_forever()
