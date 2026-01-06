# -*- coding: utf-8 -*-
import hashlib
import hmac
from pathlib import Path
from typing import Dict, Any

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
MODE_PP = "PP"


# =========================
# Data
# =========================
@st.cache_data
def load_default_attractions() -> pd.DataFrame:
    import os

    if os.path.exists("attractions_master.csv"):
        df = pd.read_csv("attractions_master.csv")
        for c in ["wait", "dpa", "pp"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df["park"] = df["park"].astype(str).str.strip()
        df["attraction"] = df["attraction"].astype(str).str.strip()
        df = df.drop_duplicates(subset=["park", "attraction"], keep="first")

        if "pp" not in df.columns:
            df["pp"] = pd.NA

        return df.reset_index(drop=True)

    return pd.DataFrame(
        [
            {"park": "TDS", "attraction": "ソアリン：ファンタスティック・フライト", "wait": 5, "dpa": 4, "pp": pd.NA},
            {"park": "TDS", "attraction": "センター・オブ・ジ・アース", "wait": 4, "dpa": 3, "pp": pd.NA},
        ]
    )


# =========================
# Modifiers / Evaluation
# =========================
def child_modifier(group: str) -> float:
    return {
        "大人のみ": 1.00,
        "子連れ（未就学）": 0.85,
        "子連れ（小学校低学年）": 0.90,
        "子連れ（小学校高学年）": 0.95,
    }[group]


def perk_modifier(happy_entry: bool) -> float:
    return 1.15 if happy_entry else 1.00


def wait_tolerance_factor(wait_tolerance: str) -> float:
    return {
        "30分まで": 1.00,
        "60分まで": 1.25,
        "90分まで": 1.45,
    }[wait_tolerance]


# =========================
# Crowd definition（★差し替え）
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
    "9月初旬〜中旬（★★）",
    "9月中旬〜10月下旬（★★★）",
    "11月上旬（★★）",
    "11月中旬〜12月上旬（★★）",
    "12月中旬〜下旬（★★★）",
]

CROWD_STARS_BY_PERIOD = {label: label.count("★") for label in CROWD_PERIOD_OPTIONS}


def crowd_limit_30min_from_stars(stars: int) -> float:
    return {1: 12.0, 2: 9.0, 3: 6.0}[stars]


def evaluate(total_points: float, limit: float) -> Dict[str, Any]:
    ratio = total_points / limit if limit > 0 else 999
    if ratio <= 0.75:
        return {"label": "かなりラク（余白あり）", "message": "かなり余裕あり。"}
    elif ratio <= 1.0:
        return {"label": "だいたいOK", "message": "計画通りなら成立。"}
    elif ratio <= 1.25:
        return {"label": "けっこう大変", "message": "取捨選択が必要。"}
    else:
        return {"label": "無理寄り", "message": "DPA前提。"}

# =========================
# Main
# =========================
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")

    if not login_gate():
        st.title(APP_TITLE)
        st.info("合言葉を入力してください。")
        return

    if "df_points" not in st.session_state:
        st.session_state["df_points"] = load_default_attractions()

    st.title(APP_TITLE)

    col_left, col_right = st.columns([1.0, 1.4])

    with col_left:
        crowd_period = st.selectbox("混雑（時期の目安）", CROWD_PERIOD_OPTIONS)
        stars = CROWD_STARS_BY_PERIOD[crowd_period]

        group = st.selectbox("同伴者", ["大人のみ", "子連れ（未就学）", "子連れ（小学校低学年）", "子連れ（小学校高学年）"])
        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"])
        happy = st.checkbox("ハッピーエントリーあり")

        total_points = 10.0  # ダミー（既存計算ロジックそのまま想定）

        limit = (
            crowd_limit_30min_from_stars(stars)
            * wait_tolerance_factor(wait_tol)
            * child_modifier(group)
            * perk_modifier(happy)
        )

        ev = evaluate(total_points, limit)

        # ★ 合計点＆目安上限を同サイズ表示
        m1, m2 = st.columns(2)
        m1.metric("合計点", f"{total_points:.1f} 点")
        m2.metric("目安上限", f"{limit:.1f} 点")

        st.markdown(f"### 評価：{ev['label']}")
        st.write(ev["message"])


if __name__ == "__main__":
    main()
