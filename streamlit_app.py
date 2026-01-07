# -*- coding: utf-8 -*-
import hashlib
import hmac
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st


# =========================
# Utils
# =========================
def _rerun():
    # どうしても必要な箇所だけで使う（多用すると瞬断が増える）
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def fmt_hhmm(minutes_from_midnight: int) -> str:
    h = minutes_from_midnight // 60
    m = minutes_from_midnight % 60
    return f"{h:02d}:{m:02d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


APP_TITLE = "ディズニー混雑点数ナビ"

# =========================
# Secrets / Login
# =========================
SECRET_KEY_NAME = "APP_PASSPHRASE_HASH"


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
# Constants (selection modes)
# =========================
MODE_WAIT = "並ぶ"
MODE_DPA = "DPA"
MODE_PP = "PP"  # 追加


# =========================
# Data
# =========================
@st.cache_data
def load_default_attractions() -> pd.DataFrame:
    """
    attractions_master.csv をリポジトリに置く想定。
    列想定：
      park, attraction, wait, dpa, pp
    """
    import os

    if os.path.exists("attractions_master.csv"):
        df = pd.read_csv("attractions_master.csv")

        for c in ["wait", "dpa", "pp"]:
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

        return df

    # フォールバック
    return pd.DataFrame(
        [
            {"park": "TDS", "attraction": "ソアリン：ファンタスティック・フライト", "wait": 5, "dpa": 4, "pp": pd.NA},
            {"park": "TDS", "attraction": "センター・オブ・ジ・アース", "wait": 4, "dpa": 3, "pp": pd.NA},
            {"park": "TDS", "attraction": "トイ・ストーリー・マニア！", "wait": 4, "dpa": 3, "pp": pd.NA},
            {"park": "TDS", "attraction": "タワー・オブ・テラー", "wait": 3, "dpa": 2, "pp": pd.NA},
            {"park": "TDS", "attraction": "インディ・ジョーンズ・アドベンチャー：クリスタルスカルの魔宮", "wait": 3, "dpa": 2, "pp": pd.NA},
            {"park": "TDS", "attraction": "アナとエルサのフローズンジャーニー", "wait": 5, "dpa": 5, "pp": pd.NA},
        ]
    )


# =========================
# Modifiers / Evaluation
# =========================
def perk_modifier(happy_entry: bool) -> float:
    factor = 1.00
    if happy_entry:
        factor *= 1.15
    return factor


def wait_tolerance_factor(wait_tolerance: str) -> float:
    return {
        "30分まで": 1.00,
        "60分まで": 1.25,
        "90分まで": 1.45,
    }[wait_tolerance]


# ★時期リスト（ユーザー指定）
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


def crowd_limit_30min_from_stars(stars: int) -> float:
    base = {
        1: 12.0,  # 空いてる
        2: 9.0,   # ふつう
        3: 6.0,   # 混む
    }
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


def normalize_raw_total(raw_total: float) -> float:
    return float(raw_total)


# =========================
# About (txt from same folder)
# =========================
def render_about():
    txt_path = Path(__file__).with_name("点数の考え方.txt")
    try:
        body = txt_path.read_text(encoding="utf-8").strip()
        if not body:
            body = "（説明文ファイルは読み込めましたが、中身が空です）"
    except Exception:
        body = f"（説明文ファイルが見つかりません：{txt_path.name}）\n\n※Streamlit Cloud運用では、リポジトリ直下にこのtxtを置いてください。"

    with st.expander("✍️ 趣旨・仕様・使い方", expanded=True):
        st.markdown(body.replace("\n", "  \n"))


# =========================
# Selection state
# =========================
def _ensure_state():
    st.session_state.setdefault("confirmed", False)
    st.session_state.setdefault("selected", {})  # row_key -> mode
    st.session_state.setdefault("park_filter", "ALL")
    st.session_state.setdefault("sim_confirmed", False)


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
    st.session_state["sim_confirmed"] = False


def compute_total_and_rows(df_points: pd.DataFrame, selected: Dict[str, str]) -> Tuple[float, List[Dict[str, Any]]]:
    raw_total = 0.0
    chosen_rows: List[Dict[str, Any]] = []

    for row_key, mode in selected.items():
        try:
            park, name = row_key.split("__", 1)
        except ValueError:
            continue

        match = df_points[(df_points["park"].astype(str) == park) & (df_points["attraction"].astype(str) == name)]
        if match.empty:
            continue
        r = match.iloc[0]

        p = 0.0
        if mode == MODE_WAIT:
            p = float(r["wait"]) if pd.notna(r["wait"]) else 0.0
        elif mode == MODE_DPA:
            p = float(r["dpa"]) if pd.notna(r["dpa"]) else 0.0
        elif mode == MODE_PP:
            p = float(r["pp"]) if pd.notna(r["pp"]) else 0.0

        raw_total += p
        chosen_rows.append({"パーク": park, "アトラクション": name, "選択": mode, "点": p})

    return normalize_raw_total(raw_total), chosen_rows


# =========================
# Simulation (骨組み)
# =========================
def tod_factor(hour: int) -> float:
    """
    時間帯係数（例：午前低め/昼高め/夜低め）
    必要ならここをあとで“実測に近い形”へ差し替え。
    """
    if 9 <= hour <= 11:
        return 0.90
    if 12 <= hour <= 16:
        return 1.25
    if 17 <= hour <= 20:
        return 1.00
    return 0.85  # 20-21


def crowd_factor_from_stars(stars: int) -> float:
    # ★★★ほど全体的に待ち増え
    return {1: 0.95, 2: 1.05, 3: 1.20}.get(stars, 1.05)


def wait_minutes_from_points(points: float, base_min_per_point: float) -> float:
    return max(0.0, float(points) * float(base_min_per_point))


def pseudo_random01(key: str) -> float:
    # 安定乱数（0-1）
    hx = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(hx[:8], 16) / 0xFFFFFFFF


def build_hourly_wait_profile(points_wait: float, stars: int, base_min_per_point: float, park: str, name: str) -> Dict[int, int]:
    """
    9-21の各時刻（毎時）待ち時間（分）を作る簡易モデル
    """
    prof: Dict[int, int] = {}
    cf = crowd_factor_from_stars(stars)
    base = wait_minutes_from_points(points_wait, base_min_per_point)

    # アトラクション固有の“ブレ”を少しだけ
    jitter = (pseudo_random01(f"jitter::{park}::{name}") - 0.5) * 0.12  # ±6%
    base = base * (1.0 + jitter)

    for hour in range(9, 22):  # 9..21
        v = base * cf * tod_factor(hour)
        v = clamp(v, 0, 240)  # 上限は仮
        prof[hour] = int(round(v))
    return prof


def build_availability_hours(
    stars: int,
    kind: str,
    park: str,
    name: str,
    open_hour: int = 9,
    close_hour: int = 21,
) -> List[int]:
    """
    DPA/PP枠が「混雑★★★ほど早く枠が消える」簡易モデル
    - kind: "DPA" or "PP"
    - 返すのは「残ってる時間（時）」のリスト
    """
    hours = list(range(open_hour, close_hour + 1))

    # 混雑で“残りにくさ”を上げる（★★★が一番厳しい）
    # 早い時間ほど消えやすい
    star_penalty = {1: 0.10, 2: 0.22, 3: 0.36}.get(stars, 0.22)
    kind_bias = 0.00 if kind == "DPA" else 0.06  # PPのほうが取れない寄り（仮）

    remain: List[int] = []
    for h in hours:
        early_bias = (21 - h) / 12.0  # 早いほど大きい
        p_drop = clamp(star_penalty + kind_bias + 0.25 * early_bias, 0.05, 0.90)

        r = pseudo_random01(f"avail::{kind}::{stars}::{park}::{name}::{h}")
        if r > p_drop:
            remain.append(h)

    # 最低限、何も残らない事故を減らす（ゼロなら遅い時間を1つ残す）
    if not remain:
        remain = [21]
    return remain


def plan_day_greedy(
    chosen_rows: List[Dict[str, Any]],
    stars: int,
    base_min_per_point: float,
    interval_min: int,
    ride_min: int,
    dpa_cooldown: int,
    pp_cooldown: int,
    dpa_mode: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    骨組み：ざっくり“回り方”を出す
    - DPA: (1)今すぐ優先 or (2)最短枠優先
    - PP: 常に「今から最も近い枠」（選択不可）
    - 次回取得権利：使えたら即復帰、使えないなら cooldown 後
    """
    # 入力を正規化
    items = []
    for r in chosen_rows:
        park = str(r["パーク"])
        name = str(r["アトラクション"])
        mode = str(r["選択"])
        p_wait = float(r["点"]) if mode == MODE_WAIT else 0.0  # wait pointsはここに無いので後でdfから引けない
        items.append((park, name, mode))

    # ここでは “待ち点”を points table から引けないので、
    # chosen_rows には「点」が入っている（選択方式の点）だけ。
    # しかし待ち時間の仮換算は「並ぶ点」を使いたいので、ここは簡易的に：
    # - 並ぶ選択：その点を待ち点として使う
    # - DPA/PP選択：待ち点は 0扱い（時間は ride+interval だけ）
    #  → 後で “並ぶ点列を別で持つ” 改良に繋げる前提
    wait_points_map: Dict[Tuple[str, str], float] = {}
    for park, name, mode in items:
        if mode == MODE_WAIT:
            # chosen_rowsの「点」を待ち点として使う（骨組み）
            # ※より正確にするなら df_pointsのwait列で上書きする
            wait_points_map[(park, name)] = float([x for x in chosen_rows if x["パーク"] == park and x["アトラクション"] == name][0]["点"])
        else:
            wait_points_map[(park, name)] = 0.0

    # 事前に：待ちプロファイル / 枠残り
    wait_prof: Dict[Tuple[str, str], Dict[int, int]] = {}
    dpa_avail: Dict[Tuple[str, str], List[int]] = {}
    pp_avail: Dict[Tuple[str, str], List[int]] = {}

    for park, name, mode in items:
        wp = wait_points_map[(park, name)]
        wait_prof[(park, name)] = build_hourly_wait_profile(wp, stars, base_min_per_point, park, name)
        if mode == MODE_DPA:
            dpa_avail[(park, name)] = build_availability_hours(stars, "DPA", park, name)
        if mode == MODE_PP:
            pp_avail[(park, name)] = build_availability_hours(stars, "PP", park, name)

    # 時間管理
    t = 9 * 60  # 9:00
    end = 21 * 60  # 21:00

    # 次回購入/取得可能時刻（分）
    next_dpa_ok = 9 * 60
    next_pp_ok = 9 * 60

    # 予約（start_time, park, name, mode）
    reservations: List[Tuple[int, str, str, str]] = []

    remaining = items.copy()

    timeline: List[Dict[str, Any]] = []

    def add_action(start: int, dur: int, park: str, name: str, mode: str, note: str):
        timeline.append(
            {
                "開始": fmt_hhmm(start),
                "終了": fmt_hhmm(min(start + dur, end)),
                "パーク": park,
                "アトラクション": name,
                "方式": mode,
                "メモ": note,
            }
        )

    while t < end:
        # 1) 予約が今の時刻に来てたら消化
        reservations.sort(key=lambda x: x[0])
        if reservations and reservations[0][0] <= t:
            stime, park, name, mode = reservations.pop(0)
            if t < stime:
                t = stime

            dur = ride_min + interval_min
            add_action(t, dur, park, name, mode, "予約枠で体験")
            t += dur

            # 使えたら即権利復帰
            if mode == MODE_DPA:
                next_dpa_ok = t
            elif mode == MODE_PP:
                next_pp_ok = t
            continue

        # 2) まだ予約があるが未来 → その前にできることがあれば実行
        next_res_time = reservations[0][0] if reservations else None

        # 2-a) 取得可能なら DPA/PP を「先に確保」する（骨組み）
        #      → ただし予約時刻が近い場合は邪魔しない
        booked = False
        cur_hour = t // 60

        # DPA booking
        if not booked and t >= next_dpa_ok:
            # 残ってるDPA候補から、最も早い枠が取れるものを優先
            cand = [(park, name) for (park, name, mode) in remaining if mode == MODE_DPA]
            best: Optional[Tuple[int, str, str]] = None  # (slot_hour, park, name)

            for park, name in cand:
                avail_hours = dpa_avail.get((park, name), [])
                if not avail_hours:
                    continue

                # DPAは時間選択可：今すぐ優先 or 最短枠
                slot_hour = None
                if dpa_mode == "今すぐ優先":
                    if cur_hour in avail_hours:
                        slot_hour = cur_hour
                    else:
                        slot_hour = min([h for h in avail_hours if h >= cur_hour], default=None)
                else:
                    slot_hour = min([h for h in avail_hours if h >= cur_hour], default=None)

                if slot_hour is None:
                    continue

                if best is None or slot_hour < best[0]:
                    best = (slot_hour, park, name)

            if best is not None:
                slot_hour, park, name = best
                slot_time = slot_hour * 60  # その時間ちょうどに体験開始（骨組み）
                # 予約化
                reservations.append((slot_time, park, name, MODE_DPA))
                # 残りから消す
                remaining = [x for x in remaining if not (x[0] == park and x[1] == name and x[2] == MODE_DPA)]
                # 枠は確保したので、その枠を消費扱い
                dpa_avail[(park, name)] = [h for h in dpa_avail[(park, name)] if h != slot_hour]

                # 取得に少しだけ時間がかかる扱い（1分）
                add_action(t, 1, park, name, "DPA", f"枠確保（{slot_hour:02d}:00）")
                t += 1

                # すぐ使える枠なら、使えば即復帰なので next_dpa_ok を早めに戻す
                if slot_time <= t:
                    next_dpa_ok = t
                else:
                    next_dpa_ok = t + dpa_cooldown

                booked = True

        # PP booking
        if not booked and t >= next_pp_ok:
            cand = [(park, name) for (park, name, mode) in remaining if mode == MODE_PP]
            best: Optional[Tuple[int, str, str]] = None

            for park, name in cand:
                avail_hours = pp_avail.get((park, name), [])
                if not avail_hours:
                    continue

                # PPは時間選択不可：最も近い時間のみ
                slot_hour = min([h for h in avail_hours if h >= cur_hour], default=None)
                if slot_hour is None:
                    continue

                if best is None or slot_hour < best[0]:
                    best = (slot_hour, park, name)

            if best is not None:
                slot_hour, park, name = best
                slot_time = slot_hour * 60
                reservations.append((slot_time, park, name, MODE_PP))
                remaining = [x for x in remaining if not (x[0] == park and x[1] == name and x[2] == MODE_PP)]
                pp_avail[(park, name)] = [h for h in pp_avail[(park, name)] if h != slot_hour]

                add_action(t, 1, park, name, "PP", f"枠取得（{slot_hour:02d}:00）")
                t += 1

                if slot_time <= t:
                    next_pp_ok = t
                else:
                    next_pp_ok = t + pp_cooldown

                booked = True

        if booked:
            continue

        # 2-b) WAITを消化（予約までの隙間があるならそこに収めたい）
        wait_cands = [(park, name) for (park, name, mode) in remaining if mode == MODE_WAIT]
        if wait_cands:
            # 今時刻で最短の待ちを優先（単純貪欲）
            best = None  # (dur, park, name)
            for park, name in wait_cands:
                prof = wait_prof[(park, name)]
                w = int(prof.get(cur_hour, prof.get(21, 0)))
                dur = w + ride_min + interval_min

                # 次予約があるなら、そこまでに終わるものを優先
                if next_res_time is not None and t + dur > next_res_time:
                    # 終わらないものは少しペナルティ
                    dur_eff = dur + 9999
                else:
                    dur_eff = dur

                if best is None or dur_eff < best[0]:
                    best = (dur_eff, park, name)

            if best is not None:
                _, park, name = best
                w = int(wait_prof[(park, name)].get(cur_hour, 0))
                dur = w + ride_min + interval_min
                add_action(t, dur, park, name, "並ぶ", f"待ち={w}分（仮）")
                t += dur
                remaining = [x for x in remaining if not (x[0] == park and x[1] == name and x[2] == MODE_WAIT)]
                continue

        # 2-c) 何もできないなら次予約へワープ
        if next_res_time is not None and t < next_res_time:
            add_action(t, max(1, next_res_time - t), "-", "移動/休憩", "-", "予約待ち（空き時間）")
            t = next_res_time
            continue

        break

    df_timeline = pd.DataFrame(timeline)

    # 時間帯（毎時）サマリ（添付イメージ寄せ）
    hour_rows = []
    for hour in range(9, 21):  # 9..20
        label = f"{hour}時台"
        # この時間帯に開始したものを並べる
        starts = df_timeline[df_timeline["開始"].str.startswith(f"{hour:02d}:")]["アトラクション"].tolist()
        if starts:
            hour_rows.append({"時間": label, "選択アトラクション": " / ".join(starts)})
        else:
            hour_rows.append({"時間": label, "選択アトラクション": ""})
    df_hourly = pd.DataFrame(hour_rows)

    return df_timeline, df_hourly


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

    # df_points を先に初期化（download_button等で参照するため）
    if "df_points" not in st.session_state:
        st.session_state["df_points"] = load_default_attractions().copy()

    st.title(APP_TITLE)
    render_about()

    col_left, col_right = st.columns([1.0, 1.4], gap="large")

    # =========================
    # LEFT
    # =========================
    with col_left:
        st.markdown("## 条件（補正）")

        crowd_period = st.selectbox("混雑（時期の目安）", CROWD_PERIOD_OPTIONS, index=0)
        crowd_stars = CROWD_STARS_BY_PERIOD.get(crowd_period, 2)

        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"], index=1)
        happy = st.checkbox("ハッピーエントリーあり（宿泊）", value=False)

        st.divider()

        # 現在の点数表で計算
        df_points_now = st.session_state["df_points"].copy()
        for c in ["wait", "dpa", "pp"]:
            if c not in df_points_now.columns:
                df_points_now[c] = pd.NA
        df_points_now["wait"] = pd.to_numeric(df_points_now["wait"], errors="coerce").fillna(0.0)
        df_points_now["dpa"] = pd.to_numeric(df_points_now["dpa"], errors="coerce")
        df_points_now["pp"] = pd.to_numeric(df_points_now["pp"], errors="coerce")

        total_points, chosen_rows = compute_total_and_rows(df_points_now, st.session_state["selected"])

        limit = (
            crowd_limit_30min_from_stars(crowd_stars)
            * wait_tolerance_factor(wait_tol)
            * perk_modifier(happy)
        )
        ev = evaluate(total_points, limit)

        # 目安上限を合計点と同じ大きさ
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

        st.divider()

        if st.session_state.get("confirmed", False):
            st.markdown(f"### 評価：{ev['label']}")
            st.write(ev["message"])
        else:
            st.info("「決定」を押すと、評価とコピペ用文章が表示されます。")

        st.divider()

        st.markdown("### 選択内容")
        if chosen_rows:
            df_sel = pd.DataFrame(chosen_rows).sort_values(["パーク", "点"], ascending=[True, False])
            st.dataframe(df_sel, height=240, hide_index=True, use_container_width=True)
        else:
            st.caption("まだ何も選択されていません。")

        # コピペ文（決定後だけ、常に最新に更新）
        st.markdown("### 評価文（コピペ用）")
        if st.session_state.get("confirmed", False):
            copy_text = (
                f"条件：{crowd_period} / 待ち許容={wait_tol}"
                + (" / ハッピーエントリーあり" if happy else "")
                + f"\n合計点：{total_points:.1f}点（目安上限 {ev['limit']:.1f}点）"
                + f"\n評価：{ev['label']}\n{ev['message']}"
            )
            # keyの値を上書きしてから描画（value=は渡さない）
            st.session_state["copy_text_left"] = copy_text
            st.text_area(" ", key="copy_text_left", height=140)
        else:
            st.info("「決定」を押すと、ここに評価文（コピペ用）が表示されます。")

        # =========================
        # 順序提示（シミュレーションUI）
        # =========================
        st.divider()
        st.markdown("## 順序提示（シミュレーション）")

        with st.expander("設定（待ち仮換算 / DPA/PPモデル / インターバル）", expanded=True):
            interval = st.selectbox(
                "インターバル（分）",
                [15, 30, 60, 90, 120, 150, 180],
                index=1,
                help="アトラクション間の移動/休憩/食事の“平均”として加算します。",
            )
            base_min_per_point = st.slider(
                "待ち：点数→分の仮換算（1点あたり）",
                min_value=5,
                max_value=25,
                value=12,
                step=1,
                help="例：1点=12分。ここに時間帯係数と混雑係数を掛けます。",
            )
            ride_min = st.slider(
                "体験（乗車/鑑賞）時間（分）",
                min_value=5,
                max_value=30,
                value=12,
                step=1,
                help="シミュレーション上の固定値（骨組み）。",
            )
            dpa_mode = st.selectbox(
                "DPAの枠取り方",
                ["今すぐ優先", "最短枠優先"],
                index=0,
                help="骨組み：今すぐ取れる枠があればそれを優先するかどうか。",
            )
            st.caption("DPA/PPの“次回権利”はあなたのルール通り：使えたら即 / 使えないなら DPA=60分後、PP=120分後。")
            dpa_cd = 60
            pp_cd = 120

        sim_cols = st.columns([0.55, 0.45])
        with sim_cols[0]:
            sim_run = st.button("順序を作る（シミュレーション実行）", use_container_width=True)
        with sim_cols[1]:
            sim_clear = st.button("順序表示を消す", use_container_width=True)

        if sim_clear:
            st.session_state["sim_confirmed"] = False

        if sim_run:
            st.session_state["sim_confirmed"] = True

        if not st.session_state.get("sim_confirmed", False):
            st.info("「順序を作る」を押すと、9:00〜21:00の計画案（骨組み）が表示されます。")
        else:
            if not chosen_rows:
                st.warning("まず点数表でアトラクションを選択してください。")
            else:
                df_timeline, df_hourly = plan_day_greedy(
                    chosen_rows=chosen_rows,
                    stars=crowd_stars,
                    base_min_per_point=float(base_min_per_point),
                    interval_min=int(interval),
                    ride_min=int(ride_min),
                    dpa_cooldown=int(dpa_cd),
                    pp_cooldown=int(pp_cd),
                    dpa_mode=str(dpa_mode),
                )

                st.markdown("### 計画（時間割：添付イメージ寄せ）")
                st.dataframe(df_hourly, hide_index=True, use_container_width=True, height=360)

                st.markdown("### 詳細タイムライン（デバッグ用）")
                st.dataframe(df_timeline, hide_index=True, use_container_width=True, height=360)

                st.caption(
                    "※これは“骨組み”です。次のステップで、(A)各アトラクションの毎時待ちをCSVで持つ／"
                    "(B)DPA/PP枠の消え方をパラメータ化／(C)予約待ち時間の間に別行動を挿入、まで精密化します。"
                )

    # =========================
    # RIGHT: points table
    # =========================
    with col_right:
        st.markdown("## 点数表（選ぶ）")
        st.caption("一覧はスクロールできます。点数もこの画面上で編集できます（自分用カスタム）。")

        with st.expander("（任意）点数表CSVの読み込み/書き出し", expanded=False):
            up = st.file_uploader("attractions_master.csv をアップロード（上書き）", type=["csv"])
            if up is not None:
                df_up = pd.read_csv(up)

                for c in ["wait", "dpa", "pp"]:
                    if c in df_up.columns:
                        df_up[c] = pd.to_numeric(df_up[c], errors="coerce")
                if "pp" not in df_up.columns:
                    df_up["pp"] = pd.NA

                if "park" in df_up.columns:
                    df_up["park"] = df_up["park"].astype(str).str.strip()
                if "attraction" in df_up.columns:
                    df_up["attraction"] = df_up["attraction"].astype(str).str.strip()
                if "park" in df_up.columns and "attraction" in df_up.columns:
                    df_up = df_up.drop_duplicates(subset=["park", "attraction"], keep="first").reset_index(drop=True)

                st.session_state["df_points"] = df_up
                st.success("点数表を読み込みました。")
                _rerun()

            st.download_button(
                "現在の点数表をCSVでダウンロード",
                st.session_state["df_points"].to_csv(index=False).encode("utf-8-sig"),
                file_name="attractions_master.csv",
                mime="text/csv",
            )

        fcol1, _ = st.columns([0.45, 0.55])
        with fcol1:
            park_filter = st.selectbox("パーク絞り込み", ["ALL", "TDLのみ", "TDSのみ"], index=0)
            st.session_state["park_filter"] = park_filter

        df_points = st.session_state["df_points"].copy()
        for c in ["wait", "dpa", "pp"]:
            if c not in df_points.columns:
                df_points[c] = pd.NA

        df_points["wait"] = pd.to_numeric(df_points["wait"], errors="coerce").fillna(0.0)
        df_points["dpa"] = pd.to_numeric(df_points["dpa"], errors="coerce")
        df_points["pp"] = pd.to_numeric(df_points["pp"], errors="coerce")

        df_view = df_points.copy()
        if park_filter == "TDLのみ":
            df_view = df_view[df_view["park"] == "TDL"]
        elif park_filter == "TDSのみ":
            df_view = df_view[df_view["park"] == "TDS"]
        df_view = df_view.reset_index(drop=True)

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
                columns={"park": "パーク", "attraction": "アトラクション", "wait": "並ぶ（点）", "dpa": "DPA（点）", "pp": "PP（点）"}
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
                },
            )
            back = edited.rename(
                columns={"パーク": "park", "アトラクション": "attraction", "並ぶ（点）": "wait", "DPA（点）": "dpa", "PP（点）": "pp"}
            )
            back["wait"] = pd.to_numeric(back["wait"], errors="coerce").fillna(0.0)
            back["dpa"] = pd.to_numeric(back["dpa"], errors="coerce")
            back["pp"] = pd.to_numeric(back["pp"], errors="coerce")

            if not back.equals(st.session_state["df_points"]):
                st.session_state["df_points"] = back
                st.success("点数表を更新しました（選択状態は保持されます）。")
                _rerun()


if __name__ == "__main__":
    main()
