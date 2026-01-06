# -*- coding: utf-8 -*-
import hashlib
import hmac
from typing import Dict, Any
from pathlib import Path

import pandas as pd
import streamlit as st


# =========================
# Utils
# =========================
def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


APP_TITLE = "ディズニー混雑点数ナビ"

MODE_WAIT = "並ぶ"
MODE_DPA = "DPA"
MODE_PP = "PP"

SECRET_KEY_NAME = "APP_PASSPHRASE_HASH"


# =========================
# Auth
# =========================
def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_passphrase(passphrase: str) -> bool:
    try:
        expected = st.secrets.get("PASSWORD_SHA256") or st.secrets.get(SECRET_KEY_NAME)
    except Exception:
        expected = None

    if not expected:
        st.error("Secrets に PASSWORD_SHA256 が設定されていません。")
        return False

    return hmac.compare_digest(sha256_hex(passphrase.strip()), str(expected).strip())


def login_gate() -> bool:
    with st.sidebar:
        st.markdown("## 🔒 メンバー限定ログイン")
        pw = st.text_input("合言葉", type="password")
        if st.button("ログイン"):
            st.session_state["auth_ok"] = verify_passphrase(pw)
            if not st.session_state["auth_ok"]:
                st.warning("合言葉が違います。")
    return bool(st.session_state.get("auth_ok"))


# =========================
# Data
# =========================
@st.cache_data
def load_default_attractions() -> pd.DataFrame:
    if Path("attractions_master.csv").exists():
        df = pd.read_csv("attractions_master.csv")
        for c in ["wait", "dpa", "pp"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        if "pp" not in df.columns:
            df["pp"] = pd.NA
        return df

    return pd.DataFrame(
        [
            {"park": "TDS", "attraction": "ソアリン", "wait": 5, "dpa": 4, "pp": pd.NA},
        ]
    )


# =========================
# Crowd（★置換済）
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

CROWD_STARS = {label: label.count("★") for label in CROWD_PERIOD_OPTIONS}


def crowd_limit_30min_from_stars(stars: int) -> float:
    return {1: 12.0, 2: 9.0, 3: 6.0}.get(stars, 9.0)


# =========================
# Modifiers
# =========================
def child_modifier(group: str) -> float:
    return {
        "大人のみ": 1.00,
        "子連れ（未就学）": 0.85,
        "子連れ（小学校低学年）": 0.90,
        "子連れ（小学校高学年）": 0.95,
    }.get(group, 1.00)


def wait_tolerance_factor(t: str) -> float:
    return {"30分まで": 1.00, "60分まで": 1.25, "90分まで": 1.45}[t]


def perk_modifier(happy: bool) -> float:
    return 1.15 if happy else 1.00


# =========================
# Evaluate
# =========================
def evaluate(total: float, limit: float) -> Dict[str, Any]:
    r = total / limit if limit else 999
    if r <= 0.75:
        return {"label": "かなりラク", "msg": "余白あり"}
    if r <= 1.0:
        return {"label": "だいたいOK", "msg": "計画通りなら成立"}
    if r <= 1.25:
        return {"label": "けっこう大変", "msg": "妥協が必要"}
    return {"label": "無理寄り", "msg": "かなり厳しい"}


# =========================
# About
# =========================
def render_about():
    p = Path(__file__).with_name("点数の考え方.txt")
    body = p.read_text(encoding="utf-8") if p.exists() else "説明文ファイルがありません"
    with st.expander("✍️ 趣旨・仕様・使い方", expanded=True):
        st.markdown(body.replace("\n", "  \n"))


# =========================
# Main
# =========================
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")

    if not login_gate():
        st.title(APP_TITLE)
        return

    if "df_points" not in st.session_state:
        st.session_state["df_points"] = load_default_attractions()

    if "selected" not in st.session_state:
        st.session_state["selected"] = {}

    st.title(APP_TITLE)
    render_about()

    col_left, col_right = st.columns([1.0, 1.4])

    # ===== Left =====
    with col_left:
        st.markdown("## 条件")

        period = st.selectbox("混雑（時期の目安）", CROWD_PERIOD_OPTIONS)
        stars = CROWD_STARS[period]

        group = st.selectbox("同伴者", ["大人のみ", "子連れ（未就学）", "子連れ（小学校低学年）", "子連れ（小学校高学年）"])
        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"])
        happy = st.checkbox("ハッピーエントリーあり")

        st.divider()
        ph_metric = st.empty()
        ph_limit = st.empty()
        ph_eval = st.empty()

    # ===== Right（点数表）=====
    with col_right:
        st.markdown("## 点数表（選択）")
        df = st.session_state["df_points"]

        for _, r in df.iterrows():
            key = f"{r['park']}__{r['attraction']}"
            c1, c2, c3 = st.columns([0.6, 0.2, 0.2])
            c1.write(r["attraction"])
            if c2.button(r["wait"], key=f"w_{key}"):
                st.session_state["selected"][key] = r["wait"]
            if pd.notna(r["dpa"]) and c3.button(r["dpa"], key=f"d_{key}"):
                st.session_state["selected"][key] = r["dpa"]

    total = sum(st.session_state["selected"].values())
    limit = (
        crowd_limit_30min_from_stars(stars)
        * wait_tolerance_factor(wait_tol)
        * child_modifier(group)
        * perk_modifier(happy)
    )
    ev = evaluate(total, limit)

    with ph_metric.container():
        st.metric("合計点", f"{total:.1f}")

    with ph_limit.container():
        st.metric("目安上限", f"{limit:.1f}")

    with ph_eval.container():
        st.markdown(f"### 評価：{ev['label']}")
        st.write(ev["msg"])


if __name__ == "__main__":
    main()
