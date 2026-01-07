# sim_core.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math
import pandas as pd


# =========
# Time utils
# =========
OPEN_MIN = 9 * 60
CLOSE_MIN = 21 * 60

def hhmm(tmin: int) -> str:
    h = tmin // 60
    m = tmin % 60
    return f"{h:02d}:{m:02d}"

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def hour_bucket_from_min(tmin: int) -> int:
    """09:00〜21:59 を 9〜21 に丸める"""
    h = tmin // 60
    return int(clamp(h, 9, 21))


# =========
# Data models
# =========
@dataclass
class AttractionPlan:
    park: str
    attraction: str
    mode: str  # "並ぶ" / "DPA" / "PP"

@dataclass
class Action:
    start_min: int
    end_min: int
    kind: str  # "MOVE" / "WAIT" / "RIDE" / "DPA_BOOK" / "PP_GET" etc
    park: str
    attraction: str
    note: str = ""


# =========
# CSV loaders
# =========
def load_wait_csv(path: str, date_id: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["date_id"].astype(str) == str(date_id)].copy()
    # expected: hour_09..hour_21 in minutes
    return df

def load_sellout_csv(path: str, date_id: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["date_id"].astype(str) == str(date_id)].copy()
    # columns: date_id, park, attraction, mode, last_bookable_hour
    return df

def load_factor_csv(path: str) -> pd.DataFrame:
    # optional
    return pd.read_csv(path)


# =========
# Wait time query
# =========
def get_wait_minutes(wait_df: pd.DataFrame, park: str, attraction: str, tmin: int) -> int:
    h = hour_bucket_from_min(tmin)
    col = f"hour_{h:02d}"
    r = wait_df[(wait_df["park"] == park) & (wait_df["attraction"] == attraction)]
    if r.empty or col not in r.columns:
        return 0
    v = r.iloc[0][col]
    if pd.isna(v):
        return 0
    return int(float(v))


def get_last_bookable_hour(sellout_df: pd.DataFrame, park: str, attraction: str, mode: str) -> Optional[int]:
    r = sellout_df[(sellout_df["park"] == park) & (sellout_df["attraction"] == attraction) & (sellout_df["mode"] == mode)]
    if r.empty:
        return None
    v = r.iloc[0].get("last_bookable_hour", None)
    if pd.isna(v):
        return None
    return int(v)


# =========
# DPA/PP availability (simple)
# =========
def next_available_slot_min(now_min: int, last_bookable_hour: Optional[int]) -> Optional[int]:
    """
    簡易： '今の時間の枠' がまだ買えるなら now の時間枠（=その時刻）とみなす。
    だめなら次の時間枠（+60分単位）。
    last_bookable_hour は「その時間台まで新規取得可能」。超えたら None。
    """
    if last_bookable_hour is None:
        return None

    now_h = hour_bucket_from_min(now_min)
    if now_h > last_bookable_hour:
        return None

    # まず「今すぐ枠」を候補
    # （実データ化するときは、ここを “在庫テーブル” に差し替える）
    return now_min


# =========
# Scheduler core
# =========
def simulate_day(
    plans: List[AttractionPlan],
    wait_df: pd.DataFrame,
    sellout_df: pd.DataFrame,
    interval_min: int = 10,
    ride_duration_min: int = 15,
    move_duration_min: int = 10,
) -> Tuple[List[Action], List[AttractionPlan]]:
    """
    返り値:
      actions: タイムライン
      remaining: 時間切れ等で実行できなかった残り
    """
    remaining = plans.copy()
    actions: List[Action] = []

    now = OPEN_MIN

    # 次にDPA/PPを取れる時刻（権利復活）
    next_dpa_ok = OPEN_MIN
    next_pp_ok = OPEN_MIN

    # 予約済み（未来枠）の保持
    booked: List[Tuple[str, str, str, int]] = []  # (park, attraction, mode, slot_min)

    def can_do_now(p: AttractionPlan) -> bool:
        if p.mode == "並ぶ":
            return True
        if p.mode == "DPA":
            return now >= next_dpa_ok and next_available_slot_min(now, get_last_bookable_hour(sellout_df, p.park, p.attraction, "DPA")) is not None
        if p.mode == "PP":
            return now >= next_pp_ok and next_available_slot_min(now, get_last_bookable_hour(sellout_df, p.park, p.attraction, "PP")) is not None
        return False

    def score_candidate(p: AttractionPlan) -> float:
        """
        小さいほど優先（貪欲）。
        - 今の待ちが小さいほど良い
        - DPA/PP は売切が近いほど優先（last_bookable_hourが小さいほど）
        """
        base = 0.0
        if p.mode == "並ぶ":
            base += get_wait_minutes(wait_df, p.park, p.attraction, now)
        elif p.mode == "DPA":
            last_h = get_last_bookable_hour(sellout_df, p.park, p.attraction, "DPA")
            # 売切近いほど優先: 残り時間台を小さく
            base += 20.0
            if last_h is not None:
                base += max(0, (last_h - hour_bucket_from_min(now))) * 3.0
        elif p.mode == "PP":
            last_h = get_last_bookable_hour(sellout_df, p.park, p.attraction, "PP")
            base += 15.0
            if last_h is not None:
                base += max(0, (last_h - hour_bucket_from_min(now))) * 3.0
        return base

    while now < CLOSE_MIN and remaining:
        # 1) 予約済み未来枠が「今すぐ使える」になってたら優先消化
        usable_idx = None
        for i, (park, name, mode, slot_min) in enumerate(booked):
            if slot_min <= now:
                usable_idx = i
                break
        if usable_idx is not None:
            park, name, mode, slot_min = booked.pop(usable_idx)

            # MOVE
            actions.append(Action(now, now + move_duration_min, "MOVE", park, name, "移動"))
            now += move_duration_min

            # RIDE
            actions.append(Action(now, now + ride_duration_min, "RIDE", park, name, f"{mode} 利用"))
            now += ride_duration_min

            # 「すぐ使えた」扱い → 権利復活
            if mode == "DPA":
                next_dpa_ok = now
            elif mode == "PP":
                next_pp_ok = now

            continue

        # 2) 今すぐ実行できる候補から選ぶ
        doable = [p for p in remaining if can_do_now(p)]
        if doable:
            doable.sort(key=score_candidate)
            pick = doable[0]

            if pick.mode == "並ぶ":
                w = get_wait_minutes(wait_df, pick.park, pick.attraction, now)

                actions.append(Action(now, now + move_duration_min, "MOVE", pick.park, pick.attraction, "移動"))
                now += move_duration_min

                actions.append(Action(now, now + w, "WAIT", pick.park, pick.attraction, f"待ち {w}分"))
                now += w

                actions.append(Action(now, now + ride_duration_min, "RIDE", pick.park, pick.attraction, "スタンバイ"))
                now += ride_duration_min

                remaining.remove(pick)
                continue

            if pick.mode == "DPA":
                last_h = get_last_bookable_hour(sellout_df, pick.park, pick.attraction, "DPA")
                slot = next_available_slot_min(now, last_h)
                if slot is None:
                    # 取れないなら除外（または並びに切替等）
                    remaining.remove(pick)
                    continue

                # 「今すぐ枠」なら即消化→即復活
                if slot <= now:
                    actions.append(Action(now, now, "DPA_BOOK", pick.park, pick.attraction, "DPA購入（即時枠）"))

                    actions.append(Action(now, now + move_duration_min, "MOVE", pick.park, pick.attraction, "移動"))
                    now += move_duration_min

                    actions.append(Action(now, now + ride_duration_min, "RIDE", pick.park, pick.attraction, "DPA即利用"))
                    now += ride_duration_min

                    next_dpa_ok = now
                    remaining.remove(pick)
                else:
                    # 未来枠なら予約→60分後に購入権利復活
                    actions.append(Action(now, now, "DPA_BOOK", pick.park, pick.attraction, f"DPA購入（{hhmm(slot)}枠）"))
                    booked.append((pick.park, pick.attraction, "DPA", slot))
                    next_dpa_ok = now + 60
                    remaining.remove(pick)
                continue

            if pick.mode == "PP":
                last_h = get_last_bookable_hour(sellout_df, pick.park, pick.attraction, "PP")
                slot = next_available_slot_min(now, last_h)
                if slot is None:
                    remaining.remove(pick)
                    continue

                # PP：時間選択の自由なし（簡易では slot=now とみなす）
                if slot <= now:
                    actions.append(Action(now, now, "PP_GET", pick.park, pick.attraction, "PP取得（即時枠）"))

                    actions.append(Action(now, now + move_duration_min, "MOVE", pick.park, pick.attraction, "移動"))
                    now += move_duration_min

                    actions.append(Action(now, now + ride_duration_min, "RIDE", pick.park, pick.attraction, "PP即利用"))
                    now += ride_duration_min

                    next_pp_ok = now
                    remaining.remove(pick)
                else:
                    actions.append(Action(now, now, "PP_GET", pick.park, pick.attraction, f"PP取得（{hhmm(slot)}枠）"))
                    booked.append((pick.park, pick.attraction, "PP", slot))
                    next_pp_ok = now + 120
                    remaining.remove(pick)
                continue

        # 3) 何もできない場合：時間を進める（インターバル）
        now += interval_min

    return actions, remaining


def actions_to_df(actions: List[Action]) -> pd.DataFrame:
    rows = []
    for a in actions:
        rows.append({
            "開始": hhmm(a.start_min),
            "終了": hhmm(a.end_min),
            "種別": a.kind,
            "パーク": a.park,
            "アトラクション": a.attraction,
            "メモ": a.note,
        })
    return pd.DataFrame(rows)
