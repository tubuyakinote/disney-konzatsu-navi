# -*- coding: utf-8 -*-
import hashlib
import hmac
from pathlib import Path
from typing import Dict, Any, List, Tuple

import pandas as pd
import streamlit as st


# =========================
# Utils
# =========================
def _rerun():
    # ※基本は呼ばない（瞬断を増やす原因）
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
    # ハッピーエントリーのみ
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


# ★①：ユーザー指定の時期リストへ差し替え
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
    st.session_state.setdefault("copy_text_left", "")
    st.session_state.setdefault("copy_sig_left", "")  # 表示内容の署名（更新判定用）


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
    st.session_state["copy_text_left"] = ""
    st.session_state["copy_sig_left"] = ""


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


def _make_copy_text(crowd_period: str, wait_tol: str, happy: bool, total_points: float, limit: float, label: str, msg: str) -> str:
    return (
        f"条件：{crowd_period} / 待ち許容={wait_tol}"
        + (" / ハッピーエントリーあり" if happy else "")
        + f"\n合計点：{total_points:.1f}点（目安上限 {limit:.1f}点）"
        + f"\n評価：{label}\n{msg}"
    )


def _make_sig(crowd_period: str, wait_tol: str, happy: bool, total_points: float, limit: float, label: str, msg: str) -> str:
    # 画面が更新されても「同じ内容なら書き換えない」用の署名
    base = f"{crowd_period}|{wait_tol}|{int(happy)}|{total_points:.3f}|{limit:.3f}|{label}|{msg}"
    return sha256_hex(base)


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

    # 先に点数表を確実に初期化（右カラムのdownload_buttonで参照するため）
    if "df_points" not in st.session_state:
        st.session_state["df_points"] = load_default_attractions().copy()

    st.title(APP_TITLE)
    render_about()

    col_left, col_right = st.columns([1.0, 1.4], gap="large")

    # =========================
    # LEFT: conditions + results
    # =========================
    with col_left:
        st.markdown("## 条件（補正）")

        crowd_period = st.selectbox("混雑（時期の目安）", CROWD_PERIOD_OPTIONS, index=0)
        crowd_stars = CROWD_STARS_BY_PERIOD.get(crowd_period, 2)

        wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"], index=1)
        happy = st.checkbox("ハッピーエントリーあり（宿泊）", value=False)

        st.divider()

        # 計算（現時点の session_state で）
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

        # ★② 目安上限を合計点と同じ大きさに（st.metricで並べる）
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

        st.divider()

        # ===== コピー文（決定したら表示、決定後は内容を常に最新化）=====
        st.markdown("### 評価文（コピペ用）")

        if st.session_state.get("confirmed", False):
            copy_text = _make_copy_text(
                crowd_period=crowd_period,
                wait_tol=wait_tol,
                happy=happy,
                total_points=total_points,
                limit=ev["limit"],
                label=ev["label"],
                msg=ev["message"],
            )
            sig = _make_sig(
                crowd_period=crowd_period,
                wait_tol=wait_tol,
                happy=happy,
                total_points=total_points,
                limit=ev["limit"],
                label=ev["label"],
                msg=ev["message"],
            )

            # 署名が変わったときだけ更新（ユーザーがtext_areaを触った場合の破壊を避けつつ、内容は追従）
            if st.session_state.get("copy_sig_left", "") != sig:
                st.session_state["copy_text_left"] = copy_text
                st.session_state["copy_sig_left"] = sig

            # value= は渡さない（keyのsession_stateが優先されるため）
            st.text_area(" ", key="copy_text_left", height=140)
        else:
            st.info("「決定」を押すと、ここに評価文（コピペ用）が表示されます。")

    # =========================
    # RIGHT: points table + filter + editor + CSV IO
    # =========================
    with col_right:
        st.markdown("## 点数表（選ぶ）")
        st.caption("一覧はスクロールできます。点数もこの画面上で編集できます（自分用カスタム）。")

        # CSV IO
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
                # 読み込み直後は反映が必要
                _rerun()

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
        for c in ["wait", "dpa", "pp"]:
            if c not in df_points.columns:
                df_points[c] = pd.NA

        df_points["wait"] = pd.to_numeric(df_points["wait"], errors="coerce").fillna(0.0)
        df_points["dpa"] = pd.to_numeric(df_points["dpa"], errors="coerce")
        df_points["pp"] = pd.to_numeric(df_points["pp"], errors="coerce")

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

        # scroll container
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

        # editor
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
