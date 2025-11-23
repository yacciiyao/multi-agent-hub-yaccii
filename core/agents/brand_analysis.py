# -*- coding: utf-8 -*-
# @File: brand_analysis.py
# @Author: yaccii
# @Time: 2025-11-23 17:36
# @Description: 品牌分析 payload 组装工具
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .brand_repository import BrandRepository


def _compute_series_summary(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [float(p.get("value") or 0.0) for p in points if p.get("value") is not None]
    if not values:
        return {
            "has_data": False,
            "total": 0.0,
            "avg": 0.0,
            "min": 0.0,
            "max": 0.0,
            "first": 0.0,
            "last": 0.0,
            "growth_abs": 0.0,
            "growth_rate": 0.0,
        }
    total = float(sum(values))
    avg = total / len(values)
    min_v = min(values)
    max_v = max(values)
    first = values[0]
    last = values[-1]
    growth_abs = last - first
    growth_rate = (growth_abs / first) if first not in (0.0, -0.0) else 0.0
    return {
        "has_data": True,
        "total": total,
        "avg": avg,
        "min": min_v,
        "max": max_v,
        "first": first,
        "last": last,
        "growth_abs": growth_abs,
        "growth_rate": growth_rate,
    }


async def build_brand_analysis_payload(
    *,
    repo: BrandRepository,
    brand_names: List[str],
    metric: str,
    start_ts: int,
    end_ts: int,
    period_label: str,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """
    聚合多个品牌的分析所需数据，供 LLM 生成各种“单品牌 / 多品牌”报告或 QA 使用。

    返回结构大致为：

    {
      "period": {"start_ts": ..., "end_ts": ..., "label": "..."},
      "metric": "composite",
      "region": "...",
      "brands": [
        {
          "brand_id": 1,
          "brand_name": "Anker",
          "profile": {...},                 # ys_brand + website + latest independence
          "metrics_summary": {
              "amazon_search": {...},
              "google_search": {...},
              "independence_traffic": {...},
              "composite": {...}
          },
          "metrics_timeseries": {
              "amazon_search": [{"ts": 1710000000, "value": ...}, ...],
              ...
          },
        },
        ...
      ],
      "not_found": ["xxx", "yyy"]
    }
    """
    metric = (metric or "composite").strip()
    if metric not in ("amazon_search", "google_search", "independence_traffic", "composite"):
        metric = "composite"

    # 需要计算的指标集合：如果是 composite，就把三种底层指标都拉上来
    if metric == "composite":
        metrics_to_fetch: List[str] = ["amazon_search", "google_search", "independence_traffic"]
    else:
        metrics_to_fetch = [metric]

    period_info = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "label": period_label,
    }

    result: Dict[str, Any] = {
        "period": period_info,
        "metric": metric,
        "region": region,
        "brands": [],
        "not_found": [],
    }

    if not brand_names:
        return result

    # 先根据品牌名查 ys_brand
    brand_rows = await repo.get_brands_by_names(brand_names)
    name_to_row = {(row.get("brand_name") or "").lower(): row for row in brand_rows}

    for name in brand_names:
        key = (name or "").strip().lower()
        row = name_to_row.get(key)
        if not row:
            result["not_found"].append(name)
            continue

        bid = int(row.get("id"))
        profile = await repo.get_brand_profile(bid)

        metrics_summary: Dict[str, Any] = {}
        metrics_ts: Dict[str, List[Dict[str, Any]]] = {}

        for m in metrics_to_fetch:
            series = await repo.get_brand_metric_timeseries(
                brand_id=bid,
                metric=m,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            metrics_ts[m] = series
            metrics_summary[m] = _compute_series_summary(series)

        # 如果请求的是 composite，可以在 summary 里给一个综合分（简单平均三项 avg）
        if metric == "composite":
            comps: List[float] = []
            for m in ("amazon_search", "google_search", "independence_traffic"):
                s = metrics_summary.get(m) or {}
                if s.get("has_data"):
                    comps.append(float(s.get("avg") or 0.0))
            if comps:
                composite_score = float(sum(comps)) / len(comps)
            else:
                composite_score = 0.0
            metrics_summary["composite"] = {
                "has_data": bool(comps),
                "avg": composite_score,
            }

        result["brands"].append(
            {
                "brand_id": bid,
                "brand_name": row.get("brand_name") or "",
                "profile": profile,
                "metrics_summary": metrics_summary,
                "metrics_timeseries": metrics_ts,
            }
        )

    return result
