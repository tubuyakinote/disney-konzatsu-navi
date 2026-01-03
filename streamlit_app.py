# -*- coding: utf-8 -*-
import hashlib
import hmac
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
import streamlit as st

def _rerun():
    # Streamlitのバージョン差分吸収（st.experimental_rerun は新しめで削除されています）
    if hasattr(st, 'rerun'):
        st.rerun()
    else:
        st.experimental_rerun()


APP_TITLE = "ディズニー混雑点数ナビ"

# =========================
# Secrets / Login
# =========================
# Streamlit Cloud: App settings → Secrets に TOML形式で貼り付け
# 例: PASSWORD_SHA256="(sha256の16進文字列)"  または APP_PASSPHRASE_HASH="(sha256の16進文字列)"
SECRET_KEY_NAME = "APP_PASSPHRASE_HASH"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_passphrase(passphrase: str) -> bool:
    """
    passphrase を sha256 して、Secrets のハッシュと一致するか。
    Secrets は以下どちらのキーでもOK（互換運用）:
      - PASSWORD_SHA256
      - APP_PASSPHRASE_HASH（旧キー）
    """
    expected = ""
    try:
        # まず新キーを優先
        expected = st.secrets.get("PASSWORD_SHA256", "")
        if not expected:
            expected = st.secrets.get(SECRET_KEY_NAME, "")
    except Exception:
        expected = ""  # local で secrets が無い場合など

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

        # 文字の揺れを吸収して重複排除（同一パーク×同一名称）
        if "park" in df.columns:
            df["park"] = df["park"].astype(str).str.strip()
        if "attraction" in df.columns:
            df["attraction"] = df["attraction"].astype(str).str.strip()
        if "park" in df.columns and "attraction" in df.columns:
            df = df.drop_duplicates(subset=["park", "attraction"], keep="first").reset_index(drop=True)
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


def evaluate(total_points: float, limit: float) -> Dict[str, Any]:
    """
    total_points: 合計点（選択した点の単純合計）
    limit: この条件で「待ち許容内」を狙う目安上限（条件補正は limit 側に反映）
    """
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
    """
    互換のため残しているが、v2以降は「合計点は補正しない」方針。
    そのため raw_total をそのまま返す。
    """
    return float(raw_total)


def render_about():
    with st.expander("✍️ 仕様・使い方・注意書き", expanded=True):
        st.markdown(
            """
### 点数の考え方（ざっくり）
- **並ぶ（待ち耐性）**：待ち時間が長いほど、体力・時間・判断が削られやすい → 高得点  
- **DPA（課金/確保難易度）**：DPAなど「お金で時間を買う」手段が**必要になる度合い**が高いほど高得点。さらに、DPAは先着枠のため**確保に労力（開園待ち・取得争奪）**が必要になりやすい点も加味しています。  
  ※DPAは先着で、**取得のための労力（開園待ち/朝イチの動き）**も発生しうるため、難易度として加点します。

### このアプリは誰向け？
- 「並ぶか」「DPA（など）を使うか」で、混雑日に無理をしない計画にしたい人
- 子連れ/初心者で、回れる現実感を先に把握したい人
- ハッピーエントリー/バケパ等のアドバンテージ有無も含めて整理したい人

### 使い方
1. 右の条件（混雑・同伴者・待ち許容など）を設定
2. 下の点数表で、各アトラクションを **「並ぶ」or「DPA」** で選択
3. 右側に **合計点** と評価が出ます（評価文は「決定」で表示）

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
    st.session_state.setdefault("confirmed", False)
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
        edited = st.data_editor(
            df_show,
            key="points_editor",
            use_container_width=True,
            height=520,
            hide_index=True,
            column_config={
                "パーク": st.column_config.SelectboxColumn("パーク", options=["TDL", "TDS"], width="small"),
                "アトラクション": st.column_config.TextColumn("アトラクション", width="large"),
                "並ぶ（点）": st.column_config.NumberColumn("並ぶ（点）", min_value=0.0, step=1.0, width="small"),
                "DPA（点）": st.column_config.NumberColumn("DPA（点）", width="small"),
                "選択": st.column_config.SelectboxColumn("選択", options=["採用しない", "並ぶ", "DPA"], width="small"),
            },
        )

        # --- ここが重要：data_editor の編集結果を session_state に保存して次回以降も保持する ---
        edited = edited.copy()
        # 数値列を確実に数値化（None/空欄は NaN になる）
        if "wait" in edited.columns:
            edited["wait"] = pd.to_numeric(edited["wait"], errors="coerce")
        if "dpa" in edited.columns:
            edited["dpa"] = pd.to_numeric(edited["dpa"], errors="coerce")
        # 念のため選択列の欠損を埋める
        if "choice" in edited.columns:
            edited["choice"] = edited["choice"].fillna(CHOICES["none"])
        st.session_state["df_points"] = edited
        df_points = edited

        # 編集結果を内部形式に戻す
        df_back = edited.rename(
            columns={"パーク": "park", "アトラクション": "attraction", "並ぶ（点）": "wait", "DPA（点）": "dpa", "選択": "choice"}
        )
        # 数値へ（DPAが空欄/Noneでも安全に扱う）
        df_back["wait"] = pd.to_numeric(df_back["wait"], errors="coerce").fillna(0.0)
        df_back["dpa"] = pd.to_numeric(df_back["dpa"], errors="coerce")
        df_back["choice"] = df_back["choice"].fillna(CHOICES["none"])

        # DPA点が無い行で「DPA」を選ばれたら、点がNaNになって合計が壊れるので自動で戻す
        invalid_dpa = (df_back["choice"] == CHOICES["dpa"]) & (df_back["dpa"].isna())
        if invalid_dpa.any():
            df_back.loc[invalid_dpa, "choice"] = CHOICES["none"]
            st.warning("DPA点が登録されていないアトラクションはDPAを選べないため、自動で「採用しない」に戻しました。")

        # 変更があった場合だけ保存し、即時反映のために再実行（2回操作が必要になる現象を抑止）
        if ("df_points" not in st.session_state) or (not df_back.equals(st.session_state["df_points"])):
            st.session_state["df_points"] = df_back
            _rerun()
    # ----- Compute -----
    df_points = st.session_state["df_points"].copy()
    chosen = df_points[df_points["choice"].isin(["並ぶ", "DPA"])].copy()

    raw_total = 0.0
    chosen_rows = []
    for _, r in chosen.iterrows():
        if r["choice"] == CHOICES["wait"]:
            p = float(r["wait"]) if pd.notna(r["wait"]) else 0.0
        elif r["choice"] == CHOICES["dpa"]:
            p = float(r["dpa"]) if pd.notna(r["dpa"]) else 0.0
        else:
            p = 0.0
        raw_total += p
        chosen_rows.append(
            {
                "パーク": r["park"],
                "アトラクション": r["attraction"],
                "選択": r["choice"],
                "点": p,
            }
        )

    total_points = normalize_raw_total(raw_total)  # 合計点は補正しない（raw_totalをそのまま返す）
    limit = crowd_limit_30min(crowd) * wait_tolerance_factor(wait_tol) * child_modifier(group) * perk_modifier(happy, vacap)
    ev = evaluate(total_points, limit)

    with col_right:
        st.metric("合計点", f"{total_points:.1f} 点")
        st.caption(f"目安上限（この条件で“待ち許容内”を狙うライン）: **{ev['limit']:.1f} 点**")

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("決定（評価文を表示）"):
                st.session_state["confirmed"] = True
                _rerun()
        with btn_col2:
            if st.button("選択全解除"):
                st.session_state["df_points"]["choice"] = "採用しない"
                st.session_state["confirmed"] = False
                _rerun()

        if st.session_state.get("confirmed", False):
            st.markdown(f"### 評価：{ev['label']}")
            st.write(ev["message"])
        else:
            st.info("「決定」を押すと、評価とコピペ用文章が表示されます。")

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
                + f"\n合計点：{total_points:.1f}点（目安上限 {ev['limit']:.1f}点）"
                + f"\n評価：{ev['label']}\n{ev['message']}"
            ),
            height=140,
        )


if __name__ == "__main__":
    main()