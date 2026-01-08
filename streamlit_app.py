# -*- coding: utf-8 -*-
import hashlib
import hmac
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import re
import pandas as pd
import numpy as np
import streamlit as st


APP_TITLE = "ディズニー混雑点数ナビ"
SECRET_KEY_NAME = "APP_PASSPHRASE_HASH"

# Selection modes
MODE_WAIT = "並ぶ"
MODE_DPA = "DPA"
MODE_PP = "PP"
# =========================
# Normalization (matching CSV rows robustly)
# =========================
def norm_text(s: Any) -> str:
    """Normalize strings for robust matching across CSVs.
    - trims
    - normalizes spaces
    - removes various quote characters (CSV間で末尾の " が混ざりがち)
    """
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()

    # normalize full-width space -> half-width
    t = t.replace("\u3000", " ")

    # unify quotes then REMOVE them (they often differ between files)
    for q in ["“", "”", "＂", '"', "‘", "’", "'"]:
        t = t.replace(q, "")

    # collapse repeated spaces
    t = re.sub(r"\s+", " ", t).strip()

    # remove trailing/leading punctuation that sometimes sticks to attraction names
    t = t.strip("・:：　-–—〜~()（）[]【】「」『』、。.,/")

    return t


# =========================
# Auth
# =========================
def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_passphrase(passphrase: str) -> bool:
    expected = ""
    try:
        expected = st.secrets.get("PASSWORD_SHA256", "")
        if not expected:
            expected = st.secrets.get(SECRET_KEY_NAME, "")
    except Exception:
        expected = ""

    if not expected:
        st.error(
            "ログイン用の設定（Secrets）が見つかりません。\n\n"
            "ローカルで動かす場合は、このプロジェクト直下に `.streamlit/secrets.toml` を作成し、\n"
            'PASSWORD_SHA256="(sha256)"\n'
            "または\n"
            f'{SECRET_KEY_NAME}="(sha256)"\n'
            "の形式で保存してください。"
        )
        return False

    got = sha256_hex(passphrase.strip())
    return hmac.compare_digest(got, str(expected).strip())


def login_gate() -> bool:
    with st.sidebar:
        st.markdown("## 🔒 メンバー限定ログイン")
        passphrase = st.text_input("合言葉", type="password")
        ok = st.button("ログイン")

    if ok:
        st.session_state["auth_ok"] = bool(verify_passphrase(passphrase))
        if not st.session_state["auth_ok"]:
            st.warning("合言葉が違います。")

    return bool(st.session_state.get("auth_ok", False))


# =========================
# Files / CSV loader
# =========================
def _candidate_paths(filename: str) -> List[Path]:
    """
    Streamlit Cloud/ローカル/この実行環境 で見つけやすい順に探索
    """
    here = Path(__file__).resolve().parent
    return [
        here / filename,
        Path.cwd() / filename,
        Path("/mnt/data") / filename,  # このチャット環境用（ユーザー側では不要）
    ]


def read_csv_safely(filename: str) -> Optional[pd.DataFrame]:
    for p in _candidate_paths(filename):
        if p.exists():
            return pd.read_csv(p)
    return None


# =========================
# About
# =========================
def render_about():
    txt_path = Path(__file__).with_name("点数の考え方.txt")
    try:
        body = txt_path.read_text(encoding="utf-8").strip()
        if not body:
            body = "（説明文ファイルは読み込めましたが、中身が空です）"
    except Exception:
        body = f"（説明文ファイルが見つかりません：{txt_path.name}）\n\n※streamlit_app.py と同じフォルダに置いてください。"

    with st.expander("✍️ 趣旨・仕様・使い方", expanded=True):
        st.markdown(body.replace("\n", "  \n"))


# =========================
# Default points table
# =========================
@st.cache_data
def load_default_attractions_points() -> pd.DataFrame:
    """
    attractions_master.csv（点数表）
    列想定：park, attraction, wait, dpa, pp, duration
    """
    import os

    if os.path.exists("attractions_master.csv"):
        df = pd.read_csv("attractions_master.csv")
        for c in ["wait", "dpa", "pp", "duration"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        if "park" in df.columns:
            df["park"] = df["park"].astype(str).str.strip()
        if "attraction" in df.columns:
            df["attraction"] = df["attraction"].astype(str).str.strip()
        if "park" in df.columns and "attraction" in df.columns:
            df = df.drop_duplicates(subset=["park", "attraction"], keep="first").reset_index(drop=True)
        if "pp" not in df.columns:
            df["pp"] = pd.NA
        if "duration" not in df.columns:
            df["duration"] = pd.NA
        if "duration" not in df.columns:
            df["duration"] = pd.NA
        return df

    # fallback
    return pd.DataFrame(
        [
            {"park": "TDS", "attraction": "ソアリン：ファンタスティック・フライト", "wait": 5, "dpa": 4, "pp": pd.NA, "duration": pd.NA},
            {"park": "TDS", "attraction": "センター・オブ・ジ・アース", "wait": 4, "dpa": 3, "pp": pd.NA, "duration": pd.NA},
            {"park": "TDS", "attraction": "トイ・ストーリー・マニア！", "wait": 4, "dpa": 3, "pp": pd.NA, "duration": pd.NA},
            {"park": "TDS", "attraction": "タワー・オブ・テラー", "wait": 3, "dpa": 2, "pp": pd.NA, "duration": pd.NA},
            {"park": "TDS", "attraction": "インディ・ジョーンズ・アドベンチャー：クリスタルスカルの魔宮", "wait": 3, "dpa": 2, "pp": pd.NA, "duration": pd.NA},
            {"park": "TDS", "attraction": "アナとエルサのフローズンジャーニー", "wait": 5, "dpa": 5, "pp": pd.NA, "duration": pd.NA},
        ]
    )


# =========================
# Crowd options (user-defined)
# =========================
CROWD_PERIOD_OPTIONS = [
    "1月 上旬（★★★）",
    "1月 中旬（★★）",
    "1月 下旬（★）",
    "2月（★）",
    "3月上旬（★★）",
    "3月中旬〜下旬（★★★）",
    "4月上旬（★★★）",
    "4月中旬〜下旬（★）",
    "5月上旬（★★★）",
    "5月中旬〜下旬（★）",
    "6月（★）",
    "7月上旬〜中旬（★）",
    "7月下旬（★★）",
    "8月上旬（★★）",
    "8月中旬〜下旬（★★★）",
    "9月初旬～中旬（★★）",
    "9月中旬〜10月下旬（★★★）",
    "11月上旬（★★）",
    "11月中旬〜12月上旬（★★）",
    "12月中旬〜下旬（★★★）",
]
CROWD_STARS_BY_PERIOD = {label: label.count("★") for label in CROWD_PERIOD_OPTIONS}


def wait_tolerance_factor(wait_tolerance: str) -> float:
    return {"30分まで": 1.00, "60分まで": 1.25, "90分まで": 1.45}[wait_tolerance]


def perk_modifier(happy_entry: bool) -> float:
    factor = 1.00
    if happy_entry:
        factor *= 1.15
    return factor


def crowd_limit_30min_from_stars(stars: int) -> float:
    base = {1: 12.0, 2: 9.0, 3: 6.0}
    return base.get(stars, 9.0)


def evaluate(total_points: float, limit: float) -> Dict[str, Any]:
    ratio = total_points / limit if limit > 0 else 999
    if ratio <= 0.75:
        label = "かなりラク（余白あり）"
        msg = "待ち許容内に収めやすい構成です。ショー/休憩/偶然の寄り道も入れやすい。"
    elif ratio <= 1.00:
        label = "だいたいOK（計画通りなら成立）"
        msg = "目安上限付近です。開園待ち・移動・食事の段取り次第で体感が変わります。"
    elif ratio <= 1.25:
        label = "けっこう大変（待ち・妥協が出やすい）"
        msg = "どこかで待ち時間超過 or 予定変更が起きやすいです。『捨てる候補』を先に決めるのが安全。"
    else:
        label = "無理寄り（超・計画職人向け）"
        msg = "この条件だと、待ち許容内を維持するのはかなり厳しめ。DPA/入園アドバンテージ前提に。"
    return {"limit": float(limit), "ratio": ratio, "label": label, "message": msg}


# =========================
# Selection state
# =========================
def _ensure_state():
    st.session_state.setdefault("confirmed", False)
    st.session_state.setdefault("selected", {})  # row_key -> mode
    st.session_state.setdefault("park_filter", "ALL")
    st.session_state.setdefault("plan_confirmed", False)  # 計画表示用（別管理）


def _row_id(park: str, attraction: str) -> str:
    return f"{park}__{attraction}"


def toggle_select(row_key: str, mode: str):
    cur = st.session_state["selected"].get(row_key)
    if cur == mode:
        st.session_state["selected"].pop(row_key, None)
    else:
        st.session_state["selected"][row_key] = mode


def clear_all_selections():
    st.session_state["selected"] = {}
    st.session_state["confirmed"] = False
    st.session_state["plan_confirmed"] = False


# =========================
# Convert selected -> plans
# =========================
def selected_to_plans(df_points: pd.DataFrame, selected: Dict[str, str]) -> List[Dict[str, Any]]:
    plans: List[Dict[str, Any]] = []
    # add normalized columns for robust matching
    if "_park_norm" not in df_points.columns:
        df_points["_park_norm"] = df_points["park"].apply(norm_text)
    if "_attr_norm" not in df_points.columns:
        df_points["_attr_norm"] = df_points["attraction"].apply(norm_text)
    for row_key, mode in selected.items():
        try:
            park, name = row_key.split("__", 1)
        except ValueError:
            continue
        match = df_points[(df_points["_park_norm"] == norm_text(park)) & (df_points["_attr_norm"] == norm_text(name))]
        if match.empty:
            continue
        r = match.iloc[0]
        plans.append(
            {
                "park": park,
                "attraction": name,
                "mode": mode,
                "points_wait": float(r["wait"]) if pd.notna(r.get("wait", pd.NA)) else 0.0,
                "points_dpa": float(r["dpa"]) if pd.notna(r.get("dpa", pd.NA)) else None,
                "points_pp": float(r["pp"]) if pd.notna(r.get("pp", pd.NA)) else None,
                "duration": float(r.get("duration", 10.0)) if pd.notna(r.get("duration", pd.NA)) else 10.0,
                "duration": float(r["duration"]) if pd.notna(r.get("duration", pd.NA)) else 10.0,
            }
        )
    return plans


# =========================
# Wait CSV (minutes per hour) / Sellout / Factor
# =========================
def _parse_hour_columns(cols: List[str]) -> List[int]:
    """
    wait CSV想定: hour_09, hour_10 ... hour_21
    ただしテンプレの列名が崩れても末尾の数字から拾えるようにする
    """
    hours = []
    for c in cols:
        if c.startswith("hour_"):
            import re

            m = re.findall(r"(\d{1,2})", c)
            if m:
                h = int(m[-1])
                if 0 <= h <= 23:
                    hours.append(h)
    hours = sorted(list(set(hours)))
    return [h for h in hours if 9 <= h <= 21]


def load_wait_table_minutes(dataset_id: str) -> pd.DataFrame:
    """
    wait_{dataset_id}.csv
    columns: park, attraction, hour_09..hour_21 (minutes)
    """
    fn = f"wait_{dataset_id}.csv"
    df = read_csv_safely(fn)
    if df is None:
        return pd.DataFrame(columns=["park", "attraction"])

    # normalize
    for c in ["park", "attraction"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    df["_park_norm"] = df["park"].apply(norm_text)
    df["_attr_norm"] = df["attraction"].apply(norm_text)

    hour_cols = _parse_hour_columns(list(df.columns))
    # numeric
    for h in hour_cols:
        # find matching col (best-effort)
        candidates = [c for c in df.columns if c.startswith("hour_")]
        col = None
        # prefer exact
        for c in candidates:
            if c in (f"hour_{h:02d}", f"hour_{h}"):
                col = c
                break
        if col is None and candidates:
            col = candidates[0]
        if col is not None:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_sellout_table(dataset_id: str) -> pd.DataFrame:
    """
    sellout_{dataset_id}.csv
    columns: park, attraction, dpa_sellout_hour, pp_sellout_hour
    """
    fn = f"sellout_{dataset_id}.csv"
    df = read_csv_safely(fn)
    if df is None:
        return pd.DataFrame(columns=["park", "attraction", "dpa_sellout_hour", "pp_sellout_hour"])

    for c in ["park", "attraction"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    df["_park_norm"] = df["park"].apply(norm_text)
    df["_attr_norm"] = df["attraction"].apply(norm_text)

    for c in ["dpa_sellout_hour", "pp_sellout_hour"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def load_factor_table(dataset_id: str) -> pd.DataFrame:
    """
    factor_{dataset_id}.csv
    columns (expected):
      park, attraction,
      dpa_sellout_speed, pp_sellout_speed,
      wait_multiplier_morning, wait_multiplier_noon, wait_multiplier_evening
    """
    fn = f"factor_{dataset_id}.csv"
    df = read_csv_safely(fn)
    if df is None:
        return pd.DataFrame(columns=["park", "attraction"])

    for c in ["park", "attraction"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    df["_park_norm"] = df["park"].apply(norm_text)
    df["_attr_norm"] = df["attraction"].apply(norm_text)

    # best-effort: numeric conversions for known-ish columns
    for c in df.columns:
        if "sellout_speed" in c or c.startswith("wait_multiplier_"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def factor_wait_multiplier(df_factor: pd.DataFrame, park: str, attraction: str, hour: int) -> float:
    """
    morning/noon/evening の簡易係数
    morning: 9-11
    noon: 12-17
    evening: 18-21
    """
    # defaults
    wm = 1.00
    wn = 1.15
    we = 0.90

    if not df_factor.empty:
        m = df_factor[(df_factor.get("_park_norm", df_factor["park"].astype(str).str.strip()) == norm_text(park)) & (df_factor.get("_attr_norm", df_factor["attraction"].astype(str).str.strip()) == norm_text(attraction))]
        if not m.empty:
            r = m.iloc[0]
            # 欲しい列名が崩れてても拾えるように、部分一致で探す
            def pick(prefix: str, default: float) -> float:
                cols = [c for c in df_factor.columns if c.startswith(prefix)]
                if cols:
                    v = r.get(cols[0], default)
                    return float(v) if pd.notna(v) else default
                return default

            wm = pick("wait_multiplier_morning", wm)
            wn = pick("wait_multiplier_noon", wn)
            we = pick("wait_multiplier_evening", we)

    if 9 <= hour <= 11:
        return wm
    if 12 <= hour <= 17:
        return wn
    return we


def factor_sellout_speed(df_factor: pd.DataFrame, park: str, attraction: str, mode: str) -> float:
    """
    混雑★★★ほど早く枠が消える、等の「なくなり速度係数」
    DPA/PPで係数列を分ける想定。無ければ1.0
    """
    if df_factor.empty:
        return 1.00
    m = df_factor[(df_factor.get("_park_norm", df_factor["park"].astype(str).str.strip()) == norm_text(park)) & (df_factor.get("_attr_norm", df_factor["attraction"].astype(str).str.strip()) == norm_text(attraction))]
    if m.empty:
        return 1.00
    r = m.iloc[0]
    if mode == MODE_DPA:
        cols = [c for c in df_factor.columns if "dpa_sellout_speed" in c]
        if cols:
            v = r.get(cols[0], 1.0)
            return float(v) if pd.notna(v) else 1.0
    if mode == MODE_PP:
        cols = [c for c in df_factor.columns if "pp_sellout_speed" in c]
        if cols:
            v = r.get(cols[0], 1.0)
            return float(v) if pd.notna(v) else 1.0
    return 1.00


def get_wait_minutes(df_wait: pd.DataFrame, park: str, attraction: str, hour: int) -> float:
    """
    df_wait: park, attraction, hour_09..hour_21 (minutes)
    """
    if df_wait.empty:
        return 30.0  # fallback
    m = df_wait[(df_wait.get("_park_norm", df_wait["park"].astype(str).str.strip()) == norm_text(park)) & (df_wait.get("_attr_norm", df_wait["attraction"].astype(str).str.strip()) == norm_text(attraction))]
    if m.empty:
        return 30.0
    r = m.iloc[0]

    # find a column for this hour (strict)
    col = None
    if f"hour_{hour:02d}" in df_wait.columns:
        col = f"hour_{hour:02d}"
    elif f"hour_{hour}" in df_wait.columns:
        col = f"hour_{hour}"
    else:
        for c in df_wait.columns:
            if c.startswith("hour_") and c[5:].isdigit() and int(c[5:]) == int(hour):
                col = c
                break

    if col is None:
        return 30.0

    v = r.get(col, 30.0)
    try:
        return float(v) if pd.notna(v) else 30.0
    except Exception:
        return 30.0


def get_sellout_hour(df_sellout: pd.DataFrame, park: str, attraction: str, mode: str) -> Optional[int]:
    """
    sellout_hour: 例) 13 => 13:00頃にはもう無い（購入時刻が13以上なら不可）
    """
    if df_sellout.empty:
        return None
    m = df_sellout[(df_sellout.get("_park_norm", df_sellout["park"].astype(str).str.strip()) == norm_text(park)) & (df_sellout.get("_attr_norm", df_sellout["attraction"].astype(str).str.strip()) == norm_text(attraction))]
    if m.empty:
        return None
    r = m.iloc[0]
    col = "dpa_sellout_hour" if mode == MODE_DPA else "pp_sellout_hour"
    if col not in df_sellout.columns:
        return None
    v = r.get(col, None)
    if pd.isna(v):
        return None
    try:
        return int(v)
    except Exception:
        return None


# =========================
# Simple simulation (skeleton, but executable)
# =========================
def minutes_to_hhmm(min_from_open: int, open_hour: int = 9) -> str:
    total = open_hour * 60 + min_from_open
    h = total // 60
    m = total % 60
    return f"{h:02d}:{m:02d}"


def hour_from_min(min_from_open: int, open_hour: int = 9) -> int:
    return (open_hour * 60 + min_from_open) // 60


def build_schedule(
    plans: List[Dict[str, Any]],
    df_wait: pd.DataFrame,
    df_sellout: pd.DataFrame,
    df_factor: pd.DataFrame,
    crowd_stars: int,
    interval_min: int,
    open_hour: int = 9,
    close_hour: int = 21,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    ざっくり骨組み：
    - WAIT は「その時刻の待ち(分) × 時間帯係数」を使って所要時間にする
    - DPA は「売切れ時刻」と「60分ルール」を反映して、最短枠を取りに行く
    - PP  は「売切れ時刻」と「120分ルール」＋「時間選択不可（最短枠）」を反映
    - できるだけ早く“消える”ものを先に確保する（簡易の貪欲）
    """
    notes: List[str] = []

    # operate minutes from open
    T_OPEN = 0
    T_CLOSE = (close_hour - open_hour) * 60

    # internal state
    tasks = []
    for p in plans:
        tasks.append(
            {
                "park": p["park"],
                "attraction": p["attraction"],
                "mode": p["mode"],
                "duration": float(p.get("duration", 10.0)) if p.get("duration", None) is not None else 10.0,
                "status": "todo",       # todo/booked/done
                "return_min": None,     # for DPA/PP
                "duration": float(p.get("duration", 10.0)) if pd.notna(p.get("duration", pd.NA)) else 10.0,
                "wait_override_min": p.get("wait_override_min", float("nan")),
            }
        )

    # rights
    next_dpa_buy_min = 0
    next_pp_get_min = 0

    # helper: crowd affects sellout "effective hour"
    # ★★★ほど早く消える：stars=3 を基準に、starsが少ないほど遅くなる（ゆるい補正）
    # 例: ★★★: 1.00, ★★: 0.90, ★: 0.80
    crowd_speed = {3: 1.00, 2: 0.90, 1: 0.80}.get(crowd_stars, 0.90)

    timeline = []
    t = 0

    def add_event(
        ride_start_min: int,
        dur_min: int,
        task: Dict[str, Any],
        note: str = "",
        queue_start_min: Optional[int] = None,
    ) -> int:
        """Append one timeline row.
        - 開始: 乗車開始（ユーザー表示の主開始）
        - 列開始: 並び始め時刻（WAITのときのみ）
        """
        ride_end_min = min(ride_start_min + dur_min, T_CLOSE)

        row = {
            "列開始": minutes_to_hhmm(queue_start_min, open_hour) if queue_start_min is not None else "",
            "開始": minutes_to_hhmm(ride_start_min, open_hour),
            "終了": minutes_to_hhmm(ride_end_min, open_hour),
            "パーク": task["park"],
            "アトラクション": task["attraction"],
            "手段": task["mode"],
            "メモ": note,
        }
        timeline.append(row)
        return ride_end_min
        return end_min

    def find_booked_ready(now_min: int) -> Optional[int]:
        idx = None
        best_return = 10**9
        for i, task in enumerate(tasks):
            if task["status"] == "booked" and task["return_min"] is not None and task["return_min"] <= now_min:
                if task["return_min"] < best_return:
                    best_return = task["return_min"]
                    idx = i
        return idx

    def earliest_possible_return_min(task: Dict[str, Any], now_min: int) -> Optional[int]:
        now_hour = hour_from_min(now_min, open_hour)
        sellout_hour_raw = get_sellout_hour(df_sellout, task["park"], task["attraction"], task["mode"])
        sp = factor_sellout_speed(df_factor, task["park"], task["attraction"], task["mode"])
        # effective sellout hour (smaller => earlier sellout)
        if sellout_hour_raw is None:
            sellout_hour_eff = None
        else:
            # 混雑と係数で売切れが早まる（簡易）
            sellout_hour_eff = int(round(sellout_hour_raw / max(0.2, crowd_speed * sp)))

        # if sold out already
        if sellout_hour_eff is not None and now_hour >= sellout_hour_eff:
            return None

        # DPA: 時間選択の自由あり→最短で “今の時間枠” を狙い、ダメなら次の時間へ
        # PP : 時間選択不可 → 常に最短枠（今枠→次枠…）
        # 今回はどちらも「最短枠」を返す（骨組み）
        cand_hour = now_hour
        while cand_hour <= close_hour:
            if sellout_hour_eff is not None and cand_hour >= sellout_hour_eff:
                return None
            # return time = cand_hour:00
            cand_min = (cand_hour - open_hour) * 60
            if cand_min < T_OPEN:
                cand_min = T_OPEN
            # already past this hour start -> allow immediate use if we're within this hour
            # (骨組みなので「同一時間なら即利用可」とする)
            if cand_hour == now_hour:
                return now_min  # "今すぐ"
            return cand_min
        return None

    def book_one(now_min: int, mode: str) -> Optional[str]:
        nonlocal next_dpa_buy_min, next_pp_get_min

        # pick a task to book: earliest sellout / fastest speed
        candidates = [task for task in tasks if task["status"] == "todo" and task["mode"] == mode]
        if not candidates:
            return None

        # scoring: smaller sellout hour first, then bigger speed first
        def score(task: Dict[str, Any]) -> Tuple[int, float]:
            s = get_sellout_hour(df_sellout, task["park"], task["attraction"], mode)
            if s is None:
                s = 99
            sp = factor_sellout_speed(df_factor, task["park"], task["attraction"], mode)
            return (s, -sp)

        candidates_sorted = sorted(candidates, key=score)
        task = candidates_sorted[0]

        ret = earliest_possible_return_min(task, now_min)
        if ret is None:
            task["status"] = "done"
            return f"{task['attraction']}：{mode}枠が見つからず（売切れ想定）"
        task["status"] = "booked"
        task["return_min"] = ret

        # right return rule
        if mode == MODE_DPA:
            # すぐ使えるなら、使った後すぐ戻る扱い（=ここでは booked なので戻さない）
            # すぐ使えない場合、購入権は60分後に復活
            if ret > now_min:
                next_dpa_buy_min = max(next_dpa_buy_min, now_min + 60)
        else:
            if ret > now_min:
                next_pp_get_min = max(next_pp_get_min, now_min + 120)

        return f"{mode}確保：{task['attraction']}（{minutes_to_hhmm(ret, open_hour)}〜想定）"

    def do_booked(task: Dict[str, Any], now_min: int) -> int:
        nonlocal next_dpa_buy_min, next_pp_get_min

        duration = float(task.get("duration", 10.0))
        if pd.isna(duration) or duration <= 0:
            duration = 10.0
        duration_min = int(round(duration))

        ride_start = now_min
        ride_end = add_event(
            ride_start,
            duration_min,
            task,
            note="DPA/PP 消化",
            queue_start_min=None
        )

        task["status"] = "done"
        task["return_min"] = None

        # rights: "すぐ使えばすぐ戻る" をここで反映（骨組み）
        if task["mode"] == MODE_DPA:
            next_dpa_buy_min = min(next_dpa_buy_min, ride_end)
        if task["mode"] == MODE_PP:
            next_pp_get_min = min(next_pp_get_min, ride_end)

        return ride_end + interval_min



    def do_wait(task: Dict[str, Any], now_min: int) -> int:
        hour = hour_from_min(now_min, open_hour)

        # wait minutes (CSV) + time-of-day multiplier (factor)
        wait_min = float(task.get("wait_override_min", float("nan")))
        if not pd.isna(wait_min):
            base_wait = wait_min
        else:
            base_wait = get_wait_minutes(df_wait, task["park"], task["attraction"], hour)

        mult = factor_wait_multiplier(df_factor, task["park"], task["attraction"], hour)
        wait_total = int(round(float(base_wait) * float(mult)))

        # official duration (minutes)
        duration = float(task.get("duration", 10.0))
        if pd.isna(duration) or duration <= 0:
            duration = 10.0
        duration_min = int(round(duration))

        # IMPORTANT:
        # 「開始」は“乗車開始”として扱う（ユーザー要望）
        queue_start = now_min
        ride_start = now_min + wait_total
        ride_end = add_event(
            ride_start,
            duration_min,
            task,
            note=f"待ち={base_wait:.0f}分×係数{mult:.2f} / 所要{duration_min}分",
            queue_start_min=queue_start
        )

        task["status"] = "done"
        return ride_end + interval_min



    def next_booked_return_min() -> Optional[int]:
        mins = [t["return_min"] for t in tasks if t["status"] == "booked" and t["return_min"] is not None]
        return min(mins) if mins else None

    # main loop
    while t < T_CLOSE:
        # 1) if any booked is ready -> do it
        idx = find_booked_ready(t)
        if idx is not None:
            t = do_booked(tasks[idx], t)
            continue

        # 2) try to book DPA/PP if rights available
        booked_note = None
        if t >= next_dpa_buy_min:
            booked_note = book_one(t, MODE_DPA)
            if booked_note:
                notes.append(booked_note)
        if t >= next_pp_get_min:
            booked_note2 = book_one(t, MODE_PP)
            if booked_note2:
                notes.append(booked_note2)

        # 3) if any newly booked is "now" return -> execute immediately
        idx2 = find_booked_ready(t)
        if idx2 is not None:
            t = do_booked(tasks[idx2], t)
            continue

        # 4) do a WAIT task if exists
        wait_tasks = [task for task in tasks if task["status"] == "todo" and task["mode"] == MODE_WAIT]
        if wait_tasks:
            # pick smallest expected wait at this hour
            hour = hour_from_min(t, open_hour)
            wait_tasks_sorted = sorted(
                wait_tasks,
                key=lambda x: get_wait_minutes(df_wait, x["park"], x["attraction"], hour),
            )
            t = do_wait(wait_tasks_sorted[0], t)
            continue

        # 5) nothing to do now -> jump to next booked return time, else finish
        nb = next_booked_return_min()
        if nb is None:
            break
        if nb > t:
            # idle block
            timeline.append(
                {
                    "開始": minutes_to_hhmm(t, open_hour),
                    "終了": minutes_to_hhmm(min(nb, T_CLOSE), open_hour),
                    "パーク": "",
                    "アトラクション": "（待機）",
                    "手段": "",
                    "メモ": "次の確保枠まで待機",
                }
            )
            t = nb
            continue

        # safety
        t += 5

    df = pd.DataFrame(timeline)
    if df.empty:
        df = pd.DataFrame(columns=["列開始", "開始", "終了", "パーク", "アトラクション", "手段", "メモ"])
    return df, notes


# =========================
# Main
# =========================
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")

    if not login_gate():
        st.title(APP_TITLE)
        st.info("メンバー限定機能です。合言葉を入力してください。")
        return

    _ensure_state()

    # points table init (needed early for download_button etc.)
    if "df_points" not in st.session_state:
        st.session_state["df_points"] = load_default_attractions_points().copy()

    st.title(APP_TITLE)
    render_about()

    # dataset selector (ID)
    with st.sidebar:
        st.markdown("---")
        st.markdown("## 🗂 データセット")
        dataset_id = st.text_input("データセットID", value="2026-02-star1", help="例：2026-02-star1（wait/sellout/factor のファイル名に使います）")

    # load dataset CSVs (minutes + sellout + factor)
    df_wait = load_wait_table_minutes(dataset_id)
    df_sellout = load_sellout_table(dataset_id)
    df_factor = load_factor_table(dataset_id)

    col_left, col_right = st.columns([1.0, 1.4], gap="large")

    # =========================
    # LEFT: conditions + evaluation + plan UI
    # =========================
    with col_left:
        st.markdown("## 条件（補正）")

        crowd_period = st.selectbox("混雑（時期の目安）", CROWD_PERIOD_OPTIONS, index=0)
        crowd_stars = CROWD_STARS_BY_PERIOD.get(crowd_period, 2)

        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"], index=1)
        happy = st.checkbox("ハッピーエントリーあり（宿泊）", value=False)

        st.markdown("---")
        st.markdown("## 計画（シミュレーション）")

        interval_min = st.selectbox("インターバル（移動/休憩の目安）", [0, 5, 10, 15, 20, 30], index=2)
        st.caption("※待ち時間CSV（分）＋係数＋公式所要時間（duration）＋インターバルで、タイムラインを組みます。")

        # compute points total from selection (points still used for your evaluation logic)
        df_points_now = st.session_state["df_points"].copy()
        for c in ["wait", "dpa", "pp", "duration"]:
            if c not in df_points_now.columns:
                df_points_now[c] = pd.NA
        df_points_now["wait"] = pd.to_numeric(df_points_now["wait"], errors="coerce").fillna(0.0)
        df_points_now["dpa"] = pd.to_numeric(df_points_now["dpa"], errors="coerce")
        df_points_now["pp"] = pd.to_numeric(df_points_now["pp"], errors="coerce")
        df_points_now["duration"] = pd.to_numeric(df_points_now.get("duration", pd.NA), errors="coerce")
        df_points_now["duration"] = pd.to_numeric(df_points_now["duration"], errors="coerce")

        plans = selected_to_plans(df_points_now, st.session_state["selected"])

        # points total (simple sum by chosen mode)
        total_points = 0.0
        chosen_rows_points = []
        for p in plans:
            mode = p["mode"]
            point = 0.0
            if mode == MODE_WAIT:
                point = float(p["points_wait"] or 0.0)
            elif mode == MODE_DPA:
                point = float(p["points_dpa"] or 0.0)
            elif mode == MODE_PP:
                point = float(p["points_pp"] or 0.0)
            total_points += point
            chosen_rows_points.append({"パーク": p["park"], "アトラクション": p["attraction"], "選択": mode, "点": point})

        limit = (
            crowd_limit_30min_from_stars(crowd_stars)
            * wait_tolerance_factor(wait_tol)
            * perk_modifier(happy)
        )
        ev = evaluate(total_points, limit)

        # big metrics
        m1, m2 = st.columns(2)
        with m1:
            st.metric("合計点", f"{total_points:.1f} 点")
        with m2:
            st.metric("目安上限", f"{ev['limit']:.1f} 点")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("決定（評価文を表示）", key="btn_confirm_left"):
                st.session_state["confirmed"] = True
        with b2:
            if st.button("選択全解除（点数表）", key="btn_clear_left"):
                clear_all_selections()

        st.markdown("---")

        if st.session_state.get("confirmed", False):
            st.markdown(f"### 評価：{ev['label']}")
            st.write(ev["message"])
        else:
            st.info("「決定」を押すと、評価とコピペ用文章が表示されます。")

        st.markdown("---")
        st.markdown("### 選択内容")
        if chosen_rows_points:
            df_sel = pd.DataFrame(chosen_rows_points).sort_values(["パーク", "点"], ascending=[True, False])
            st.dataframe(df_sel, height=220, hide_index=True, use_container_width=True)
        else:
            st.caption("まだ何も選択されていません。")

        # ---- Plan generation ----
        
        # ---- Plan editor (editable like points table) ----
        if plans:
            st.markdown("#### 計画の編集（順番/上書き）")
            base_plan_df = pd.DataFrame(
                [
                    {
                        "順番": i + 1,
                        "パーク": p["park"],
                        "アトラクション": p["attraction"],
                        "手段": p["mode"],
                        "所要(分)": float(p.get("duration", 10.0)),
                        "待ち上書き(分/任意)": np.nan,
                    }
                    for i, p in enumerate(plans)
                ]
            )
            # reset editor if selection changed
            sig = "|".join([f"{p['park']}::{p['attraction']}::{p['mode']}" for p in plans])
            if st.session_state.get("plan_editor_sig") != sig:
                st.session_state["plan_editor_df"] = base_plan_df
                st.session_state["plan_editor_sig"] = sig
            else:
                st.session_state.setdefault("plan_editor_df", base_plan_df)


            with st.expander("（編集）計画を編集する", expanded=False):
                edited_plan = st.data_editor(
                    st.session_state["plan_editor_df"],
                    key="plan_editor",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "順番": st.column_config.NumberColumn("順番", min_value=1, step=1),
                        "パーク": st.column_config.TextColumn("パーク", disabled=True),
                        "アトラクション": st.column_config.TextColumn("アトラクション", disabled=True),
                        "手段": st.column_config.SelectboxColumn("手段", options=[MODE_WAIT, MODE_DPA, MODE_PP]),
                        "所要(分)": st.column_config.NumberColumn("所要(分)", min_value=1, step=1),
                        "待ち上書き(分/任意)": st.column_config.NumberColumn("待ち上書き(分/任意)", min_value=0, step=5),
                    },
                )
                st.session_state["plan_editor_df"] = edited_plan

            # apply edits back to plans (order/mode/overrides)
            ed = st.session_state["plan_editor_df"].copy()
            ed["順番"] = pd.to_numeric(ed["順番"], errors="coerce").fillna(9999).astype(int)
            ed = ed.sort_values("順番").reset_index(drop=True)

            # rebuild plans list in edited order
            plans_edited = []
            for _, rr in ed.iterrows():
                plans_edited.append(
                    {
                        "park": rr["パーク"],
                        "attraction": rr["アトラクション"],
                        "mode": rr["手段"],
                        "duration": float(rr["所要(分)"]) if pd.notna(rr["所要(分)"]) else 10.0,
                        "wait_override_min": float(rr["待ち上書き(分/任意)"]) if pd.notna(rr["待ち上書き(分/任意)"]) else float("nan"),
                    }
                )
            plans = plans_edited

        st.markdown("---")
        gen1, gen2 = st.columns([0.6, 0.4])
        with gen1:
            if st.button("🗓 計画を作る（時間割を提示）", key="btn_make_plan"):
                st.session_state["plan_confirmed"] = True
        with gen2:
            if st.button("計画を非表示", key="btn_hide_plan"):
                st.session_state["plan_confirmed"] = False

        if st.session_state.get("plan_confirmed", False):
            st.caption(f"インターバル: {interval_min}分")

            df_plan, notes = build_schedule(
                plans=plans,
                df_wait=df_wait,
                df_sellout=df_sellout,
                df_factor=df_factor,
                crowd_stars=crowd_stars,
                interval_min=interval_min,
                open_hour=9,
                close_hour=21,
            )

            st.markdown("### アトラクション計画（時間割）")
            st.dataframe(df_plan, use_container_width=True, hide_index=True, height=420)

            with st.expander("（参考）確保ログ / 注意点", expanded=False):
                if notes:
                    for n in notes:
                        st.write("・" + n)
                else:
                    st.write("（ログはありません）")

            # copy text (updates every rerun; only shown after confirmed)
            st.markdown("### 評価文（コピペ用）")
            if st.session_state.get("confirmed", False):
                copy_text = (
                    f"条件：{crowd_period} / 待ち許容={wait_tol}"
                    + (" / ハッピーエントリーあり" if happy else "")
                    + f"\n合計点：{total_points:.1f}点（目安上限 {ev['limit']:.1f}点）"
                    + f"\n評価：{ev['label']}\n{ev['message']}"
                )
                st.text_area(" ", value=copy_text, height=140)
            else:
                st.info("「決定」を押すと、ここに評価文が出ます。")

        else:
            # copy section even if plan hidden
            st.markdown("### 評価文（コピペ用）")
            if st.session_state.get("confirmed", False):
                copy_text = (
                    f"条件：{crowd_period} / 待ち許容={wait_tol}"
                    + (" / ハッピーエントリーあり" if happy else "")
                    + f"\n合計点：{total_points:.1f}点（目安上限 {ev['limit']:.1f}点）"
                    + f"\n評価：{ev['label']}\n{ev['message']}"
                )
                st.text_area(" ", value=copy_text, height=140)
            else:
                st.info("「決定」を押すと、ここに評価文が出ます。")

        # =========================
        # RIGHT: points table
        # =========================
    with col_right:
        st.markdown("## 点数表（選ぶ）")
        st.caption("一覧はスクロールできます。点数もこの画面上で編集できます（自分用カスタム）。")

        # CSV IO (points table)
        with st.expander("（任意）点数表CSVの読み込み/書き出し", expanded=False):
            up = st.file_uploader("attractions_master.csv をアップロード（上書き）", type=["csv"])
            if up is not None:
                df_up = pd.read_csv(up)
                for c in ["wait", "dpa", "pp", "duration"]:
                    if c in df_up.columns:
                        df_up[c] = pd.to_numeric(df_up[c], errors="coerce")
                if "pp" not in df_up.columns:
                    df_up["pp"] = pd.NA
                if "duration" not in df_up.columns:
                    df_up["duration"] = pd.NA
                if "duration" not in df_up.columns:
                    df_up["duration"] = pd.NA
                if "park" in df_up.columns:
                    df_up["park"] = df_up["park"].astype(str).str.strip()
                if "attraction" in df_up.columns:
                    df_up["attraction"] = df_up["attraction"].astype(str).str.strip()
                if "park" in df_up.columns and "attraction" in df_up.columns:
                    df_up = df_up.drop_duplicates(subset=["park", "attraction"], keep="first").reset_index(drop=True)

                st.session_state["df_points"] = df_up
                st.success("点数表を読み込みました。")
                st.rerun()  # ここは反映優先

            st.download_button(
                "現在の点数表をCSVでダウンロード",
                st.session_state["df_points"].to_csv(index=False).encode("utf-8-sig"),
                file_name="attractions_master.csv",
                mime="text/csv",
            )

        # Park filter
        fcol1, fcol2 = st.columns([0.45, 0.55])
        with fcol1:
            park_filter = st.selectbox("パーク絞り込み", ["ALL", "TDLのみ", "TDSのみ"], index=0)
            st.session_state["park_filter"] = park_filter

        # base df
        df_points = st.session_state["df_points"].copy()
        for c in ["wait", "dpa", "pp", "duration"]:
            if c not in df_points.columns:
                df_points[c] = pd.NA

        df_points["wait"] = pd.to_numeric(df_points["wait"], errors="coerce").fillna(0.0)
        df_points["dpa"] = pd.to_numeric(df_points["dpa"], errors="coerce")
        df_points["pp"] = pd.to_numeric(df_points["pp"], errors="coerce")
        df_points["duration"] = pd.to_numeric(df_points["duration"], errors="coerce")

        # view filter
        df_view = df_points.copy()
        if park_filter == "TDLのみ":
            df_view = df_view[df_view["park"] == "TDL"]
        elif park_filter == "TDSのみ":
            df_view = df_view[df_view["park"] == "TDS"]
        df_view = df_view.reset_index(drop=True)

        # header
        h1, h2, h3, h4, h5 = st.columns([0.12, 0.55, 0.11, 0.11, 0.11])
        h1.markdown("**パーク**")
        h2.markdown("**アトラクション**")
        h3.markdown("**並ぶ（点）**")
        h4.markdown("**DPA（点）**")
        h5.markdown("**PP（点）**")

        st.caption("点数セルを押して選択（同一アトラクションは排他。もう一度押すと解除）")

        with st.container(height=520):
            for _, r in df_view.iterrows():
                park = str(r.get("park", "")).strip()
                name = str(r.get("attraction", "")).strip()
                row_key = _row_id(park, name)

                wait_p = float(r["wait"]) if pd.notna(r["wait"]) else 0.0
                dpa_p = r["dpa"]
                pp_p = r["pp"]

                selected_mode = st.session_state["selected"].get(row_key)

                c1, c2, c3, c4, c5 = st.columns([0.12, 0.55, 0.11, 0.11, 0.11], vertical_alignment="center")
                c1.write(park)
                c2.write(name)

                c3.button(
                    f"{wait_p:.0f}" if wait_p == int(wait_p) else f"{wait_p}",
                    key=f"btn_wait__{row_key}",
                    on_click=toggle_select,
                    args=(row_key, MODE_WAIT),
                    type=("primary" if selected_mode == MODE_WAIT else "secondary"),
                    disabled=(wait_p <= 0),
                    use_container_width=True,
                )

                c4.button(
                    ("—" if pd.isna(dpa_p) else f"{float(dpa_p):.0f}"),
                    key=f"btn_dpa__{row_key}",
                    on_click=toggle_select,
                    args=(row_key, MODE_DPA),
                    type=("primary" if selected_mode == MODE_DPA else "secondary"),
                    disabled=pd.isna(dpa_p),
                    use_container_width=True,
                )

                c5.button(
                    ("—" if pd.isna(pp_p) else f"{float(pp_p):.0f}"),
                    key=f"btn_pp__{row_key}",
                    on_click=toggle_select,
                    args=(row_key, MODE_PP),
                    type=("primary" if selected_mode == MODE_PP else "secondary"),
                    disabled=pd.isna(pp_p),
                    use_container_width=True,
                )

        with st.expander("（任意）点数表を編集する（並ぶ/DPA/PP）", expanded=False):
            df_edit = df_points.rename(
                columns={"park": "パーク", "attraction": "アトラクション", "wait": "並ぶ（点）", "dpa": "DPA（点）", "pp": "PP（点）", "duration": "所要（分）"}
            )
            edited = st.data_editor(
                df_edit,
                key="points_editor_edit",
                use_container_width=True,
                height=420,
                hide_index=True,
                column_config={
                    "パーク": st.column_config.SelectboxColumn("パーク", options=["TDL", "TDS"], width="small"),
                    "アトラクション": st.column_config.TextColumn("アトラクション", width="large"),
                    "並ぶ（点）": st.column_config.NumberColumn("並ぶ（点）", min_value=0.0, step=1.0, width="small"),
                    "DPA（点）": st.column_config.NumberColumn("DPA（点）", width="small"),
                    "PP（点）": st.column_config.NumberColumn("PP（点）", width="small"),
                    "所要（分）": st.column_config.NumberColumn("所要（分）", min_value=1.0, step=1.0, width="small"),
                    "所要（分）": st.column_config.NumberColumn("所要（分）", min_value=0.0, step=1.0, width="small"),
                },
            )
            back = edited.rename(
                columns={"パーク": "park", "アトラクション": "attraction", "並ぶ（点）": "wait", "DPA（点）": "dpa", "PP（点）": "pp", "所要（分）": "duration"}
            )
            back["wait"] = pd.to_numeric(back["wait"], errors="coerce").fillna(0.0)
            back["dpa"] = pd.to_numeric(back["dpa"], errors="coerce")
            back["pp"] = pd.to_numeric(back["pp"], errors="coerce")
            back["duration"] = pd.to_numeric(back.get("duration", pd.NA), errors="coerce")
            back["duration"] = pd.to_numeric(back["duration"], errors="coerce")

            if not back.equals(st.session_state["df_points"]):
                st.session_state["df_points"] = back
                st.success("点数表を更新しました（選択状態は保持されます）。")
                st.rerun()  # 編集反映は即がよい


if __name__ == "__main__":
    main()