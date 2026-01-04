# -*- coding: utf-8 -*-
import hashlib
import hmac
from typing import Dict, Any

import pandas as pd
import streamlit as st


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


# 表示文字の一元管理（内部状態にも使う）
MODE_WAIT = "並ぶ"
MODE_DPA = "DPA"
MODE_PP = "PP"  # 今回追加

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
# Data
# =========================
@st.cache_data
def load_default_attractions() -> pd.DataFrame:
    """
    attractions_master.csv をリポジトリに置く想定。
    列想定：
      park, attraction, wait, dpa, pp
    無い場合は最小セットで起動。
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

        # pp列が無い古いCSVでも動くように補完
        if "pp" not in df.columns:
            df["pp"] = pd.NA

        return df

    # フォールバック（万一ファイルが無いとき）
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


def child_modifier(group: str) -> float:
    return {
        "大人のみ": 1.00,
        "子連れ（未就学）": 0.85,
        "子連れ（小学校低学年）": 0.90,
        "子連れ（小学校高学年）": 0.95,
    }.get(group, 1.00)


def perk_modifier(happy_entry: bool) -> float:
    # ★今回：バケパ削除（ハッピーエントリーのみ残す）
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


# =========================
# Crowd (3-level, by season)  ★:empty  ★★:normal  ★★★:busy
# =========================
CROWD_PERIOD_OPTIONS = [
    "1月（★）",
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
    "9月初旬〜中旬（★）",
    "9月中旬〜10月下旬（★★★）",
    "11月上旬（★★）",
    "11月中旬〜12月上旬（★★）",
    "12月中旬〜下旬（★★★）",
]
CROWD_STARS_BY_PERIOD = {label: label.count("★") for label in CROWD_PERIOD_OPTIONS}


def crowd_limit_30min_from_stars(stars: int) -> float:
    """
    ★が少ないほど空いている＝許容点（目安上限）は高い
    """
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
    # v2以降：合計点は補正しない
    return float(raw_total)


# =========================
# About (keep layout, replace title/content)
# =========================
def render_about():
    # レイアウトは expander のまま維持。表題だけ変更＋本文はテキストファイルに差替え。
    body = ""
    try:
        # デプロイ時はリポジトリに置く想定。無ければ下のfallback。
        with open("点数の考え方.txt", "r", encoding="utf-8") as f:
            body = f.read().strip()
    except Exception:
        # 念のためのフォールバック（ローカル/環境差）
        body = "（説明文ファイル `点数の考え方.txt` が見つかりません）"

    with st.expander("✍️ 趣旨・仕様・使い方", expanded=True):
        # txtはプレーンテキストなので、そのまま読みやすく表示
        st.text(body)


# =========================
# Selection logic (cell-buttons)
# =========================
def _ensure_state():
    st.session_state.setdefault("confirmed", False)
    st.session_state.setdefault("selected", {})  # key: row_id(str) -> mode (並ぶ/DPA/PP)
    st.session_state.setdefault("park_filter", "ALL")


def _row_id(park: str, attraction: str) -> str:
    # 重複排除の前提はあるが、念のためkeyを安定化
    return f"{park}__{attraction}"


def toggle_select(row_key: str, mode: str):
    """
    同一アトラクションで排他：
      - 未選択 → mode を選択
      - 同じmodeを再度押す → 解除
      - 別modeを押す → 差し替え
    """
    cur = st.session_state["selected"].get(row_key)
    if cur == mode:
        st.session_state["selected"].pop(row_key, None)
    else:
        st.session_state["selected"][row_key] = mode


def clear_all_selections():
    st.session_state["selected"] = {}
    st.session_state["confirmed"] = False


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

    st.title(APP_TITLE)

    render_about()

    # ----- Layout (same 2-col base, per your current stable right panel) -----
    col_left, col_right = st.columns([1.4, 1.0], gap="large")

    # ===== Right: conditions / score / buttons / selection summary =====
    with col_right:
        st.markdown("## 条件（補正）")

        crowd_period = st.selectbox("混雑（時期の目安）", CROWD_PERIOD_OPTIONS, index=0)
        crowd_stars = CROWD_STARS_BY_PERIOD.get(crowd_period, 2)

        group = st.selectbox(
            "同伴者",
            ["大人のみ", "子連れ（未就学）", "子連れ（小学校低学年）", "子連れ（小学校高学年）"],
            index=0,
        )

        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"], index=1)

        happy = st.checkbox("ハッピーエントリーあり（宿泊）", value=False)

        st.divider()

    # ===== Left: points table =====
    df_default = load_default_attractions()

    # ユーザー編集用に session_state に保持（点数表そのもの）
    if "df_points" not in st.session_state:
        st.session_state["df_points"] = df_default.copy()

    with col_left:
        st.markdown("## 点数表（選ぶ）")
        st.caption("一覧はスクロールできます。点数もこの画面上で編集できます（自分用カスタム）。")

        # 任意：CSV入出力は残す（現状のまま）
        with st.expander("（任意）点数表CSVの読み込み/書き出し", expanded=False):
            up = st.file_uploader("attractions_master.csv をアップロード（上書き）", type=["csv"])
            if up is not None:
                df_up = pd.read_csv(up)
                for c in ["wait", "dpa", "pp"]:
                    if c in df_up.columns:
                        df_up[c] = pd.to_numeric(df_up[c], errors="coerce")
                if "pp" not in df_up.columns:
                    df_up["pp"] = pd.NA
                st.session_state["df_points"] = df_up
                st.success("点数表を読み込みました。")

            st.download_button(
                "現在の点数表をCSVでダウンロード",
                st.session_state["df_points"].to_csv(index=False).encode("utf-8-sig"),
                file_name="attractions_master.csv",
                mime="text/csv",
            )

        # ★② パーク絞り込み
        fcol1, fcol2 = st.columns([0.45, 0.55])
        with fcol1:
            park_filter = st.selectbox("パーク絞り込み", ["ALL", "TDLのみ", "TDSのみ"], index=0)
            st.session_state["park_filter"] = park_filter

        # 点数表（内部）
        df_points = st.session_state["df_points"].copy()
        for c in ["wait", "dpa", "pp"]:
            if c not in df_points.columns:
                df_points[c] = pd.NA
        df_points["wait"] = pd.to_numeric(df_points["wait"], errors="coerce").fillna(0.0)
        df_points["dpa"] = pd.to_numeric(df_points["dpa"], errors="coerce")
        df_points["pp"] = pd.to_numeric(df_points["pp"], errors="coerce")

        # 表示対象フィルタ
        df_view = df_points.copy()
        if park_filter == "TDLのみ":
            df_view = df_view[df_view["park"] == "TDL"]
        elif park_filter == "TDSのみ":
            df_view = df_view[df_view["park"] == "TDS"]
        df_view = df_view.reset_index(drop=True)

        # ★③ セルをボタン化した選択UI（スクロールコンテナ）
        # ヘッダ行
        h1, h2, h3, h4, h5 = st.columns([0.12, 0.55, 0.11, 0.11, 0.11])
        h1.markdown("**パーク**")
        h2.markdown("**アトラクション**")
        h3.markdown("**並ぶ（点）**")
        h4.markdown("**DPA（点）**")
        h5.markdown("**PP（点）**")

        st.caption("点数セルを押して選択（同一アトラクションは排他。もう一度押すと解除）")

        # スクロール枠（高さは現状の表のイメージに合わせて）
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

                # 並ぶ（点）は常に押せる（0点でも押せるが意味薄いので 0 は disabled）
                c3.button(
                    f"{wait_p:.0f}" if wait_p == int(wait_p) else f"{wait_p}",
                    key=f"btn_wait__{row_key}",
                    on_click=toggle_select,
                    args=(row_key, MODE_WAIT),
                    type=("primary" if selected_mode == MODE_WAIT else "secondary"),
                    disabled=(wait_p <= 0),
                    use_container_width=True,
                )

                # DPA（点）空欄なら押せない
                c4.button(
                    ("—" if pd.isna(dpa_p) else f"{float(dpa_p):.0f}"),
                    key=f"btn_dpa__{row_key}",
                    on_click=toggle_select,
                    args=(row_key, MODE_DPA),
                    type=("primary" if selected_mode == MODE_DPA else "secondary"),
                    disabled=pd.isna(dpa_p),
                    use_container_width=True,
                )

                # PP（点）空欄なら押せない
                c5.button(
                    ("—" if pd.isna(pp_p) else f"{float(pp_p):.0f}"),
                    key=f"btn_pp__{row_key}",
                    on_click=toggle_select,
                    args=(row_key, MODE_PP),
                    type=("primary" if selected_mode == MODE_PP else "secondary"),
                    disabled=pd.isna(pp_p),
                    use_container_width=True,
                )

        # 点数編集（ここは“編集したい人用”として残す：現状の「編集できる」を守る）
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

    # ===== Compute (合計点は単純合算 / 目安上限は別ロジック) =====
    df_points = st.session_state["df_points"].copy()
    selected = st.session_state["selected"].copy()

    raw_total = 0.0
    chosen_rows = []

    # 選択されたrow_keyから点数を引く
    # row_key = "park__attraction"
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

    total_points = normalize_raw_total(raw_total)

    limit = (
        crowd_limit_30min_from_stars(crowd_stars)
        * wait_tolerance_factor(wait_tol)
        * child_modifier(group)
        * perk_modifier(happy)
    )
    ev = evaluate(total_points, limit)

    # ===== Right panel (unchanged stable block, but vacap removed) =====
    with col_right:
        st.metric("合計点", f"{total_points:.1f} 点")
        st.caption(f"目安上限（この条件で“待ち許容内”を狙うライン）: **{ev['limit']:.1f} 点**")

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("決定（評価文を表示）"):
                st.session_state["confirmed"] = True
                _rerun()
        with btn_col2:
            if st.button("選択全解除（点数表）"):
                clear_all_selections()
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
            st.dataframe(df_sel, height=240, hide_index=True, use_container_width=True)
        else:
            st.caption("まだ何も選択されていません。")

        st.markdown("### 評価文（コピペ用）")
        st.text_area(
            " ",
            value=(
                f"条件：{crowd_period} / {group} / 待ち許容={wait_tol}"
                + (" / ハッピーエントリーあり" if happy else "")
                + f"\n合計点：{total_points:.1f}点（目安上限 {ev['limit']:.1f}点）"
                + f"\n評価：{ev['label']}\n{ev['message']}"
            ),
            height=140,
        )


if __name__ == "__main__":
    main()
    
