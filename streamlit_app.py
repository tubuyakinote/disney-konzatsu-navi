
import streamlit as st
import pandas as pd
import hashlib
import hmac
from datetime import date

# =========================================================
# ディズニー混雑点数ナビ（Streamlit）
# - メンバー限定運用用に「合言葉ログイン」を実装
#   （配布・拡散対策は“完全防止”は難しいため、月替わり合言葉運用を推奨）
# =========================================================

APP_TITLE = "ディズニー混雑点数ナビ"

# -------------------------
# データ（例：代表アトラクション 仮点数表）
# ※必要に応じて増やせます
# -------------------------
ATTRACTIONS = [
    {"アトラクション": "アナ雪", "並ぶ": 5, "DPA": 5},
    {"アトラクション": "ソアリン", "並ぶ": 5, "DPA": 4},
    {"アトラクション": "センター・オブ・ジ・アース", "並ぶ": 4, "DPA": 3},
    {"アトラクション": "トイマニ", "並ぶ": 4, "DPA": 3},
    {"アトラクション": "タワー・オブ・テラー", "並ぶ": 3, "DPA": 2},
    {"アトラクション": "インディ", "並ぶ": 3, "DPA": 2},
]

# -------------------------
# 点数の意味（表示用）
# -------------------------
SCORE_DEFINITION = """
### 点数の考え方（ざっくり）
- **並ぶ（待ち耐性）**：待ち時間・移動・体力消耗が増えやすいほど高得点
- **DPA（課金耐性）**：DPA/PP/有料席など「お金で時間を買う」必要度が高いほど高得点

> 同じ“点数”でも、  
> - **閑散期**：同点数でもラク  
> - **混雑期**：同点数でもキツい  
> という前提で評価文が変わります。
"""

USAGE_NOTE = """
### このアプリは誰向け？
- 「行きたいものはあるけど、**混雑日に無理をしたくない**」人  
- 子連れ／初めて／久々で、**“回り方の難易度”を先に見積もりたい**人  
- DPA/ハッピーエントリー/バケパを、**戦略として使いたい**人

### 使い方
1. 下の点数表から、乗りたいアトラクションを選ぶ  
2. 「並ぶ」「DPA」をどちら採用するか選ぶ（両方は非推奨：二重に盛れるので）
3. **ハッピーエントリー／バケパ有無**と、**混雑度・同伴者**を選ぶ  
4. 「決定」で総合点と評価文を出す

### 注意（大事）
- 本アプリは**“快適さの目安”**。絶対解ではありません。  
- 当日の天候・休止・運営・ショースケ・入園列で難易度はブレます。  
- 点数を下げる＝つまらない、ではなく **「余白を残す」** ための指標です。
"""

# -------------------------
# 簡易ログイン（合言葉）
# -------------------------
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def verify_passphrase(passphrase: str) -> bool:
    """
    secrets.toml に APP_PASSPHRASE_HASH を入れて運用。
    例:
      APP_PASSPHRASE_HASH = "sha256 hex..."
    """
    expected = st.secrets.get("APP_PASSPHRASE_HASH", "")
    if not expected:
        # secrets 未設定ならログインをスキップ（ローカル検証用）
        return True
    given = _sha256(passphrase.strip())
    return hmac.compare_digest(given, expected)

def login_gate():
    if st.session_state.get("logged_in"):
        return True

    st.sidebar.header("🔒 メンバー限定ログイン")
    passphrase = st.sidebar.text_input("合言葉", type="password", help="noteメンバーシップで配布する合言葉を入力")
    if st.sidebar.button("ログイン"):
        ok = verify_passphrase(passphrase)
        if ok:
            st.session_state.logged_in = True
            st.sidebar.success("ログインOK")
            return True
        st.sidebar.error("合言葉が違います")
    st.info("メンバー限定機能です。合言葉を入力してください。")
    return False

# -------------------------
# 評価ロジック（シンプル版）
# -------------------------
def child_modifier(group: str) -> float:
    # 年齢別補正（体力/待機耐性の違い）
    return {
        "大人のみ": 1.00,
        "子連れ（未就学）": 1.18,
        "子連れ（小学校低学年）": 1.12,
        "子連れ（小学校高学年）": 1.06,
    }.get(group, 1.00)

def crowd_modifier(crowd: str) -> float:
    return {
        "閑散": 0.90,
        "通常": 1.00,
        "混雑": 1.15,
        "超混雑（完売級）": 1.25,
    }.get(crowd, 1.00)

def perk_modifier(happy_entry: bool, vacap: bool) -> float:
    # ハッピーエントリー/バケパは“難易度を下げる”方向
    mod = 1.00
    if happy_entry:
        mod *= 0.90
    if vacap:
        mod *= 0.85
    return mod

def evaluate(total: float, crowd: str, wait_tolerance: str, happy_entry: bool, vacap: bool) -> str:
    """
    total は補正後スコア。目安で評価文を出す。
    """
    tol = {
        "30分まで": 0.90,
        "60分まで": 1.00,
        "90分まで": 1.08,
    }[wait_tolerance]

    # 同じ点数でも混雑が上がるほど厳しいので、閾値を crowd で変える
    base_easy = 28 * tol
    base_ok = 38 * tol
    base_tough = 48 * tol

    crowd_bump = {
        "閑散": -4,
        "通常": 0,
        "混雑": +6,
        "超混雑（完売級）": +10,
    }[crowd]
    easy = base_easy + crowd_bump
    ok = base_ok + crowd_bump
    tough = base_tough + crowd_bump

    lines = []
    # 具体コメントの種
    if wait_tolerance == "30分まで":
        lines.append("待ち時間30分縛りなら、**“点数を下げる”＝余白を残す**が正義です。")
    elif wait_tolerance == "90分まで":
        lines.append("90分まで許容できるなら、同点数でも成立しやすいです（ただし体力は削れます）。")
    else:
        lines.append("60分待ちまで許容できる前提で評価しています。")

    if happy_entry and vacap:
        lines.append("ハッピーエントリー＋バケパは強い。**点数の高い攻略も現実的**です。")
    elif happy_entry:
        lines.append("ハッピーエントリーがあるなら、朝の1～2本で“高得点枠”を先に潰せます。")
    elif vacap:
        lines.append("バケパがあるなら、時間指定で主要どころを押さえやすく、難易度が下がります。")
    else:
        lines.append("ハッピーエントリー/バケパなしの場合、**朝イチの優先順位**がかなり重要です。")

    if total <= easy:
        verdict = "かなりラク"
        advice = [
            "この組合せは、閑散～通常なら**子連れでも比較的ラク**に回せるライン。",
            "“偶然の産物”（ショー待ち、寄り道、休憩）を楽しむ余白を残せます。",
        ]
    elif total <= ok:
        verdict = "ちょうど良い（標準）"
        advice = [
            "無理はないですが、混雑日だと**どこかで調整**が必要になりがち。",
            "高得点アトラクションは**朝 or 夜に寄せる**、移動は1エリア集中が安定です。",
        ]
    elif total <= tough:
        verdict = "やや攻め（疲れやすい）"
        advice = [
            "混雑日だと“待ち＋移動＋食事”が重なり、**崩れやすい**プランです。",
            "DPAを使うなら、**一番重い2つだけ**に絞ると費用対効果が出ます。",
            "子連れは休憩（屋内）を先にスケジュール化すると安定します。",
        ]
    else:
        verdict = "かなり攻め（修羅）"
        advice = [
            "混雑日にこの点数は、ほぼ“戦闘編成”。**完走より満足度を優先**した方が幸福度が上がります。",
            "点数の高いものを1つ落として、代わりに“軽い体験（散歩/ショップ/ショー）”を入れるのが吉。",
            "ハッピーエントリーやバケパが無いなら、**先に勝ち筋（朝の導線）を決める**のが必須。",
        ]

    out = [f"## 評価：{verdict}", f"**補正後 総合点：{total:.1f} 点**", ""]
    out.extend(lines)
    out.append("")
    out.extend([f"- {a}" for a in advice])
    return "\n".join(out)

# -------------------------
# メインUI
# -------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

# ログインゲート
if not login_gate():
    st.stop()

left, right = st.columns([1.15, 0.85], gap="large")

with left:
    with st.expander("📌 仕様・使い方・注意書き", expanded=True):
        st.markdown(SCORE_DEFINITION)
        st.markdown(USAGE_NOTE)

    st.subheader("点数表（選ぶ）")
    df = pd.DataFrame(ATTRACTIONS)

    # 選択方式：各行で「採用しない / 並ぶ / DPA」を選ぶ
    choices = []
    for i, row in df.iterrows():
        c1, c2, c3, c4 = st.columns([0.38, 0.2, 0.2, 0.22])
        with c1:
            st.markdown(f"**{row['アトラクション']}**")
        with c2:
            st.caption(f"並ぶ: {int(row['並ぶ'])}")
        with c3:
            st.caption(f"DPA: {int(row['DPA'])}")
        with c4:
            sel = st.selectbox(
                "採用",
                ["採用しない", "並ぶ", "DPA"],
                key=f"pick_{i}",
                label_visibility="collapsed",
            )
        choices.append(sel)

with right:
    st.subheader("条件（補正）")
    crowd = st.selectbox("混雑度", ["閑散", "通常", "混雑", "超混雑（完売級）"], index=2)
    group = st.selectbox("同伴者", ["大人のみ", "子連れ（未就学）", "子連れ（小学校低学年）", "子連れ（小学校高学年）"], index=0)
    wait_tol = st.selectbox("待ち許容", ["30分まで", "60分まで", "90分まで"], index=1)
    happy_entry = st.checkbox("ハッピーエントリーあり（宿泊）", value=False)
    vacap = st.checkbox("バケーションパッケージあり", value=False)

    st.divider()

    # 合計点計算（素点）
    base_total = 0
    picked = []
    for (i, row), sel in zip(pd.DataFrame(ATTRACTIONS).iterrows(), choices):
        if sel == "並ぶ":
            base_total += float(row["並ぶ"])
            picked.append((row["アトラクション"], "並ぶ", row["並ぶ"]))
        elif sel == "DPA":
            base_total += float(row["DPA"])
            picked.append((row["アトラクション"], "DPA", row["DPA"]))

    # 補正
    total = base_total
    total *= crowd_modifier(crowd)
    total *= child_modifier(group)
    total *= perk_modifier(happy_entry, vacap)

    st.metric("総合点（補正後）", f"{total:.1f} 点", help="選択した素点に、混雑・同伴者・特典の補正を掛けた目安")

    cbtn1, cbtn2 = st.columns(2)
    do_eval = cbtn1.button("決定（評価文を表示）", use_container_width=True)
    do_reset = cbtn2.button("選択全解除", use_container_width=True)

    if do_reset:
        for i in range(len(ATTRACTIONS)):
            st.session_state[f"pick_{i}"] = "採用しない"
        st.experimental_rerun()

    st.subheader("選択内容")
    if picked:
        st.dataframe(pd.DataFrame(picked, columns=["アトラクション", "採用", "点数"]), use_container_width=True, hide_index=True)
    else:
        st.caption("まだ何も選ばれていません。")

    st.subheader("評価文")
    if do_eval:
        st.markdown(evaluate(total, crowd, wait_tol, happy_entry, vacap))
    else:
        st.caption("「決定」を押すと評価文が出ます。")
