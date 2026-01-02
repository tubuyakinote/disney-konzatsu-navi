# -*- coding: utf-8 -*-
import hashlib
import hmac
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
import streamlit as st

APP_TITLE = "ディズニー混雑点数ナビ"

# =========================
# Secrets / Login
# =========================
# Streamlit Cloud: App settings → Secrets に TOML形式で貼り付け
# 例: APP_PASSPHRASE_HASH="(sha256の16進文字列)"
SECRET_KEY_NAME = "APP_PASSPHRASE_HASH"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_passphrase(passphrase: str) -> bool:
    """
    passphrase を sha256 して、Secrets のハッシュと一致するか。
    """
    try:
        expected = st.secrets.get(SECRET_KEY_NAME, "")
    except Exception:
        expected = ""  # local で secrets が無い場合など

    if not expected:
        # 秘密鍵が未設定なら「ログインできない」のではなく、セットアップ案内を出す
        st.error(
            "ログイン用の設定（Secrets）が見つかりません。\n\n"
            "ローカルで動かす場合は、このプロジェクト直下に `.streamlit/secrets.toml` を作成し、\n"
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
        if verify_passphrase(passphrase):
            st.session_state["auth_ok"] = True
        else:
            st.session_state["auth_ok"] = False
            st.warning("合言葉が違います。")

    return bool(st.session_state.get("auth_ok", False))


# =========================
# Data
# =========================
@st.cache_data
def load_default_attractions() -> pd.DataFrame:
    """
    attractions_master.csv をリポジトリに置く想定。
    無い場合は最小セットで起動。
    """
    import os
    if os.path.exists("attractions_master.csv"):
        df = pd.read_csv("attractions_master.csv")
        # 型を整える
        for c in ["wait", "dpa"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    # フォールバック（万一ファイルが無いとき）
    return pd.DataFrame(
        [
            {"park": "TDS", "attraction": "ソアリン：ファンタスティック・フライト", "wait": 5, "dpa": 4},
            {"park": "TDS", "attraction": "センター・オブ・ジ・アース", "wait": 4, "dpa": 3},
            {"park": "TDS", "attraction": "トイ・ストーリー・マニア！", "wait": 4, "dpa": 3},
            {"park": "TDS", "attraction": "タワー・オブ・テラー", "wait": 3, "dpa": 2},
            {"park": "TDS", "attraction": "インディ・ジョーンズ・アドベンチャー：クリスタルスカルの魔宮", "wait": 3, "dpa": 2},
            {"park": "TDS", "attraction": "アナとエルサのフローズンジャーニー", "wait": 5, "dpa": 5},
        ]
    )


def child_modifier(group: str) -> float:
    # 年齢別補正（体力/待機耐性の違い）
    return {
        "大人のみ": 1.00,
        "子連れ（未就学）": 1.18,
        "子連れ（小学校低学年）": 1.12,
        "子連れ（小学校高学年）": 1.06,
    }.get(group, 1.00)


def perk_modifier(happy_entry: bool, vacap: bool) -> float:
    # ハッピーエントリー/バケパは “難易度を下げる” 方向
    mod = 1.00
    if happy_entry:
        mod *= 0.90
    if vacap:
        mod *= 0.85
    return mod


def wait_tolerance_factor(wait_tolerance: str) -> float:
    # 待てるほど「許容できる合計点」は上がる想定
    return {
        "30分まで": 1.00,
        "60分まで": 1.25,
        "90分まで": 1.45,
    }[wait_tolerance]


def crowd_limit_30min(crowd: str) -> float:
    """
    添付の「点数条件表.xlsx / Sheet1」(待ち30分目標) の目安を採用。
    「閑散=12, やや混雑=10, 混雑=8, 大混雑=6, 超混雑=5」
    """
    return {
        "閑散": 12.0,
        "やや混雑": 10.0,
        "混雑": 8.0,
        "大混雑": 6.0,
        "超混雑（完売級）": 5.0,
    }[crowd]


def evaluate(score: float, crowd: str, wait_tolerance: str) -> Dict[str, Any]:
    """
    score: 補正後の「合計点（正規化）」。
    crowd/待ち許容 に対して、どれくらい厳しいかを返す。
    """
    limit = crowd_limit_30min(crowd) * wait_tolerance_factor(wait_tolerance)

    # 余裕度（<=1 が目標内）
    ratio = score / limit if limit > 0 else 999

    if ratio <= 0.75:
        label = "かなりラク（余白あり）"
        msg = "待ち30分（または選択した許容）に収めやすい構成です。ショー/休憩/偶然の寄り道も入れやすい。"
    elif ratio <= 1.00:
        label = "だいたいOK（計画通りなら成立）"
        msg = "目標ライン上です。開園待ち・移動・食事の段取り次第で体感が変わります。"
    elif ratio <= 1.25:
        label = "けっこう大変（待ち・妥協が出やすい）"
        msg = "どこかで待ち時間超過 or 予定変更が起きやすいです。『捨てる候補』を先に決めるのが安全。"
    else:
        label = "無理寄り（超・計画職人向け）"
        msg = "この条件だと、待ち30分（または許容）を維持するのはかなり厳しめ。DPA/入園アドバンテージ前提に。"

    return {"limit": limit, "ratio": ratio, "label": label, "message": msg}


def normalize_raw_total(raw_total: float) -> float:
    """
    アトラクションの点数（例: 10点満点系）が積み上がると大きくなるので、
    Excelの目安（5〜12点くらい）に合わせてスケールを落とす。
    今回は「/5」を採用。（例：60点→12点）
    """
    return raw_total / 5.0


# =========================
# UI
# =========================
def render_about():
    with st.expander("✍️ 仕様・使い方・注意書き", expanded=True):
        st.markdown(
            """
### 点数の考え方（ざっくり）
- **並ぶ（待ち耐性）**：待ち時間が長いほど、体力・時間・判断が削られやすい → 高得点  
- **DPA（課金/確保難易度）**：DPAなど「お金で時間を買う」手段が**必要になる度合い**が高いほど高得点。  
  ※DPAは先着で、**取得のための労力（開園待ち/朝イチの動き）**も発生しうるため、難易度として加点します。

### このアプリは誰向け？
- 「並ぶか」「DPA（など）を使うか」で、混雑日に無理をしない計画にしたい人
- 子連れ/初心者で、回れる現実感を先に把握したい人
- ハッピーエントリー/バケパ等のアドバンテージ有無も含めて整理したい人

### 使い方
1. 右の条件（混雑・同伴者・待ち許容など）を設定
2. 下の点数表で、各アトラクションを **「並ぶ」or「DPA」** で選択
3. 右側に **合計点（補正後）** と評価が出ます

### 注意（大事）
- これは「現地の回り方を縛る」ツールではなく、**余白を確保するため**の道具です。
- 天候、休止、ショーパス、入園時間などで体感は変わります。
"""
        )


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    if not login_gate():
        st.title(APP_TITLE)
        st.info("メンバー限定機能です。合言葉を入力してください。")
        return

    st.title(APP_TITLE)

    render_about()

    # ----- Conditions (right) -----
    col_left, col_right = st.columns([1.4, 1.0], gap="large")

    with col_right:
        st.markdown("## 条件（補正）")
        crowd = st.selectbox("混雑", ["閑散", "やや混雑", "混雑", "大混雑", "超混雑（完売級）"], index=2)
        group = st.selectbox("同伴者", ["大人のみ", "子連れ（未就学）", "子連れ（小学校低学年）", "子連れ（小学校高学年）"], index=0)
        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"], index=1)
        happy = st.checkbox("ハッピーエントリーあり（宿泊）", value=False)
        vacap = st.checkbox("バケーションパッケージあり", value=False)

        st.divider()

    # ----- Attraction table -----
    df_default = load_default_attractions()

    # ユーザー編集用に session_state に保持
    if "df_points" not in st.session_state:
        st.session_state["df_points"] = df_default.copy()

    with col_left:
        st.markdown("## 点数表（選ぶ）")
        st.caption("一覧はスクロールできます。点数もこの画面上で編集できます（自分用カスタム）。")

        # 追加：ユーザーが自分のCSVを読み込める
        with st.expander("（任意）点数表CSVの読み込み/書き出し", expanded=False):
            up = st.file_uploader("attractions_master.csv をアップロード（上書き）", type=["csv"])
            if up is not None:
                df_up = pd.read_csv(up)
                for c in ["wait", "dpa"]:
                    if c in df_up.columns:
                        df_up[c] = pd.to_numeric(df_up[c], errors="coerce")
                st.session_state["df_points"] = df_up
                st.success("点数表を読み込みました。")

            st.download_button(
                "現在の点数表をCSVでダウンロード",
                st.session_state["df_points"].to_csv(index=False).encode("utf-8-sig"),
                file_name="attractions_master.csv",
                mime="text/csv",
            )

        df_points = st.session_state["df_points"].copy()

        # 選択列を追加
        if "choice" not in df_points.columns:
            df_points["choice"] = "採用しない"

        # 表示用（日本語列名）
        df_show = df_points.rename(
            columns={"park": "パーク", "attraction": "アトラクション", "wait": "並ぶ（点）", "dpa": "DPA（点）", "choice": "選択"}
        )

        # DPAが無いものは「—」表示に寄せる（編集は数値/空でOK）
        def dpa_display(v):
            return "—" if pd.isna(v) else v

        df_show["DPA（点）"] = df_show["DPA（点）"].apply(dpa_display)

        edited = st.data_editor(
            df_show,
            height=520,
            hide_index=True,
            column_config={
                "パーク": st.column_config.SelectboxColumn("パーク", options=["TDL", "TDS"], width="small"),
                "アトラクション": st.column_config.TextColumn("アトラクション", width="large"),
                "並ぶ（点）": st.column_config.NumberColumn("並ぶ（点）", min_value=0.0, step=1.0, width="small"),
                "DPA（点）": st.column_config.TextColumn("DPA（点）", width="small"),
                "選択": st.column_config.SelectboxColumn("選択", options=["採用しない", "並ぶ", "DPA"], width="small"),
            },
        )

        # 編集結果を内部形式に戻す
        df_back = edited.rename(
            columns={"パーク": "park", "アトラクション": "attraction", "並ぶ（点）": "wait", "DPA（点）": "dpa", "選択": "choice"}
        )
        # dpa を数値に戻す（— は NaN）
        df_back["dpa"] = df_back["dpa"].replace("—", pd.NA)
        df_back["dpa"] = pd.to_numeric(df_back["dpa"], errors="coerce")
        df_back["wait"] = pd.to_numeric(df_back["wait"], errors="coerce").fillna(0.0)

        st.session_state["df_points"] = df_back

    # ----- Compute -----
    df_points = st.session_state["df_points"].copy()
    chosen = df_points[df_points["choice"].isin(["並ぶ", "DPA"])].copy()

    raw_total = 0.0
    chosen_rows = []
    for _, r in chosen.iterrows():
        if r["choice"] == "並ぶ":
            p = float(r["wait"] or 0.0)
        else:
            p = float(r["dpa"] or 0.0)
        raw_total += p
        chosen_rows.append(
            {
                "パーク": r["park"],
                "アトラクション": r["attraction"],
                "選択": r["choice"],
                "点": p,
            }
        )

    score = normalize_raw_total(raw_total)
    score_adj = score * child_modifier(group) * perk_modifier(happy, vacap)
    ev = evaluate(score_adj, crowd=crowd, wait_tolerance=wait_tol)

    with col_right:
        st.metric("合計点（補正後）", f"{score_adj:.1f} 点")
        st.caption(f"目安上限（この条件で“待ち許容内”を狙うライン）: **{ev['limit']:.1f} 点**")
        st.markdown(f"### 評価：{ev['label']}")
        st.write(ev["message"])

        if st.button("選択全解除"):
            st.session_state["df_points"]["choice"] = "採用しない"
            st.experimental_rerun()

        st.divider()
        st.markdown("### 選択内容")
        if chosen_rows:
            df_sel = pd.DataFrame(chosen_rows).sort_values(["パーク", "点"], ascending=[True, False])
            st.dataframe(df_sel, height=240, hide_index=True)
        else:
            st.caption("まだ何も選択されていません。")

        st.markdown("### 評価文（コピペ用）")
        st.text_area(
            " ",
            value=(
                f"条件：{crowd} / {group} / 待ち許容={wait_tol}"
                + (" / ハッピーエントリーあり" if happy else "")
                + (" / バケパあり" if vacap else "")
                + f"\n合計点（補正後）：{score_adj:.1f}点（目安上限 {ev['limit']:.1f}点）"
                + f"\n評価：{ev['label']}\n{ev['message']}"
            ),
            height=140,
        )


if __name__ == "__main__":
    main()
