# -*- coding: utf-8 -*-
# @File: brand_repository.py
# @Author: yaccii
# @Time: 2025-11-23 17:36
# @Description: 品牌相关数据库访问与基础聚合逻辑
from __future__ import annotations

from typing import Any, Dict, List, Optional

from infrastructure.mlogger import mlogger


class BrandRepository:
    """
    封装品牌相关的 SQL 访问与基础计算：
      - 品牌榜单（多种指标）
      - 单品牌基本信息、官网信息
      - 单品牌多渠道时间序列
    """

    def __init__(self, storage: Any):
        """
        :param storage: 项目统一的 Storage 实例（例如 DataStorageManager.get() 返回值）
        """
        self._storage = storage

    # ===== 通用 DB 访问封装 =====

    async def _fetch_all(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        统一封装底层查询，便于与实际 storage 适配。
        你可以根据项目实际情况，把这里改成 self._storage.query / fetch_all 等。
        """
        try:
            return await self._storage.fetch_all(sql, params or {})
        except Exception as e:
            mlogger.error(self.__class__.__name__, "_fetch_all", msg=str(e))
            raise

    async def _fetch_one(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        rows = await self._fetch_all(sql, params)
        return rows[0] if rows else None

    # ===== 品牌榜单计算 =====

    async def calc_brand_ranking(
        self,
        *,
        metric: str,
        start_ts: int,
        end_ts: int,
        category_name: Optional[str] = None,
        top_n: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        计算品牌榜单。
        metric:
          - amazon_search: 基于 ys_brand_amazon_data.search_volume 汇总
          - google_search: 基于 ys_brand_google_data.search_volume 汇总
          - independence_traffic: 基于 ys_brand_independence_data.month_visits 汇总
          - composite: 三项归一化加权求和（0.4, 0.3, 0.3）
        """
        metric = (metric or "composite").strip()
        if metric not in ("amazon_search", "google_search", "independence_traffic", "composite"):
            metric = "composite"

        if metric == "amazon_search":
            base = await self._aggregate_amazon_search(start_ts, end_ts, category_name)
            rows = sorted(base.values(), key=lambda x: x.get("amazon_search", 0.0), reverse=True)
            for idx, r in enumerate(rows, start=1):
                r["score"] = float(r.get("amazon_search") or 0.0)
                r["rank"] = idx
            return rows[:top_n]

        if metric == "google_search":
            base = await self._aggregate_google_search(start_ts, end_ts, category_name)
            rows = sorted(base.values(), key=lambda x: x.get("google_search", 0.0), reverse=True)
            for idx, r in enumerate(rows, start=1):
                r["score"] = float(r.get("google_search") or 0.0)
                r["rank"] = idx
            return rows[:top_n]

        if metric == "independence_traffic":
            base = await self._aggregate_independence_traffic(start_ts, end_ts, category_name)
            rows = sorted(base.values(), key=lambda x: x.get("independence_traffic", 0.0), reverse=True)
            for idx, r in enumerate(rows, start=1):
                r["score"] = float(r.get("independence_traffic") or 0.0)
                r["rank"] = idx
            return rows[:top_n]

        # composite: 0.4 * amazon + 0.3 * google + 0.3 * independence （归一化到 0~100）
        amazon = await self._aggregate_amazon_search(start_ts, end_ts, category_name)
        google = await self._aggregate_google_search(start_ts, end_ts, category_name)
        indep = await self._aggregate_independence_traffic(start_ts, end_ts, category_name)

        all_ids = set(amazon.keys()) | set(google.keys()) | set(indep.keys())
        if not all_ids:
            return []

        # 收集原始值
        amazon_vals = [float(amazon[i].get("amazon_search") or 0.0) for i in all_ids]
        google_vals = [float(google[i].get("google_search") or 0.0) for i in all_ids]
        indep_vals = [float(indep[i].get("independence_traffic") or 0.0) for i in all_ids]

        max_amz = max(amazon_vals) if amazon_vals else 0.0
        max_goo = max(google_vals) if google_vals else 0.0
        max_ind = max(indep_vals) if indep_vals else 0.0

        rows: List[Dict[str, Any]] = []
        for bid in all_ids:
            b_amz = float(amazon.get(bid, {}).get("amazon_search") or 0.0)
            b_goo = float(google.get(bid, {}).get("google_search") or 0.0)
            b_ind = float(indep.get(bid, {}).get("independence_traffic") or 0.0)

            amz_norm = (b_amz / max_amz * 100.0) if max_amz > 0 else 0.0
            goo_norm = (b_goo / max_goo * 100.0) if max_goo > 0 else 0.0
            ind_norm = (b_ind / max_ind * 100.0) if max_ind > 0 else 0.0

            score = 0.4 * amz_norm + 0.3 * goo_norm + 0.3 * ind_norm
            name = (
                amazon.get(bid, {}).get("brand_name")
                or google.get(bid, {}).get("brand_name")
                or indep.get(bid, {}).get("brand_name")
                or ""
            )
            rows.append(
                {
                    "brand_id": bid,
                    "brand_name": name,
                    "amazon_search": b_amz,
                    "google_search": b_goo,
                    "independence_traffic": b_ind,
                    "score": score,
                }
            )

        rows.sort(key=lambda x: x["score"], reverse=True)
        for idx, r in enumerate(rows, start=1):
            r["rank"] = idx

        return rows[:top_n]

    async def _aggregate_amazon_search(
        self,
        start_ts: int,
        end_ts: int,
        category_name: Optional[str],
    ) -> Dict[int, Dict[str, Any]]:
        sql = """
        SELECT
            b.id AS brand_id,
            b.brand_name AS brand_name,
            SUM(d.search_volume) AS amazon_search
        FROM ys_brand_amazon_data d
        JOIN ys_brand b ON d.brand_id = b.id
        WHERE d.search_date BETWEEN :start_ts AND :end_ts
          AND b.status = '1'
        """
        params: Dict[str, Any] = {"start_ts": start_ts, "end_ts": end_ts}
        if category_name:
            sql += " AND (b.category1 LIKE :cate OR b.category2 LIKE :cate)"
            params["cate"] = f"%{category_name}%"
        sql += " GROUP BY b.id, b.brand_name"
        rows = await self._fetch_all(sql, params)
        result: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            bid = int(r.get("brand_id"))
            result[bid] = {
                "brand_id": bid,
                "brand_name": r.get("brand_name") or "",
                "amazon_search": float(r.get("amazon_search") or 0.0),
            }
        return result

    async def _aggregate_google_search(
        self,
        start_ts: int,
        end_ts: int,
        category_name: Optional[str],
    ) -> Dict[int, Dict[str, Any]]:
        sql = """
        SELECT
            b.id AS brand_id,
            b.brand_name AS brand_name,
            SUM(d.search_volume) AS google_search
        FROM ys_brand_google_data d
        JOIN ys_brand b ON d.brand_id = b.id
        WHERE d.search_date BETWEEN :start_ts AND :end_ts
          AND b.status = '1'
        """
        params: Dict[str, Any] = {"start_ts": start_ts, "end_ts": end_ts}
        if category_name:
            sql += " AND (b.category1 LIKE :cate OR b.category2 LIKE :cate)"
            params["cate"] = f"%{category_name}%"
        sql += " GROUP BY b.id, b.brand_name"
        rows = await self._fetch_all(sql, params)
        result: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            bid = int(r.get("brand_id"))
            result[bid] = {
                "brand_id": bid,
                "brand_name": r.get("brand_name") or "",
                "google_search": float(r.get("google_search") or 0.0),
            }
        return result

    async def _aggregate_independence_traffic(
        self,
        start_ts: int,
        end_ts: int,
        category_name: Optional[str],
    ) -> Dict[int, Dict[str, Any]]:
        sql = """
        SELECT
            b.id AS brand_id,
            b.brand_name AS brand_name,
            SUM(d.month_visits) AS independence_traffic
        FROM ys_brand_independence_data d
        JOIN ys_brand b ON d.brand_id = b.id
        WHERE d.search_date BETWEEN :start_ts AND :end_ts
        """
        params: Dict[str, Any] = {"start_ts": start_ts, "end_ts": end_ts}
        if category_name:
            sql += " AND (b.category1 LIKE :cate OR b.category2 LIKE :cate)"
            params["cate"] = f"%{category_name}%"
        sql += " GROUP BY b.id, b.brand_name"
        rows = await self._fetch_all(sql, params)
        result: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            bid = int(r.get("brand_id"))
            result[bid] = {
                "brand_id": bid,
                "brand_name": r.get("brand_name") or "",
                "independence_traffic": float(r.get("independence_traffic") or 0.0),
            }
        return result

    # ===== 单品牌信息与时间序列 =====

    async def get_brands_by_names(self, names: List[str]) -> List[Dict[str, Any]]:
        """
        根据品牌名列表查 ys_brand，返回匹配到的全部记录。
        注意：这里简单使用 brand_name 精确匹配，你可以根据需要改成大小写不敏感或模糊匹配。
        """
        clean_names = [n.strip() for n in names if n and n.strip()]
        if not clean_names:
            return []

        # 简单用 IN 查询；如果数据量大，可拆分或改成多次查询
        placeholders = ", ".join([f":n{i}" for i in range(len(clean_names))])
        sql = f"""
        SELECT *
        FROM ys_brand
        WHERE brand_name IN ({placeholders})
          AND status = '1'
        """
        params: Dict[str, Any] = {f"n{i}": name for i, name in enumerate(clean_names)}
        rows = await self._fetch_all(sql, params)
        return rows

    async def get_brand_profile(self, brand_id: int) -> Dict[str, Any]:
        """
        聚合单个品牌的基础信息 + 网站信息 + 最近一次独立站数据。
        """
        brand_sql = """
        SELECT *
        FROM ys_brand
        WHERE id = :bid
        LIMIT 1
        """
        brand = await self._fetch_one(brand_sql, {"bid": brand_id}) or {}

        website_sql = """
        SELECT *
        FROM ys_brand_website
        WHERE brand_id = :bid
          AND status = '1'
        ORDER BY update_time DESC
        """
        websites = await self._fetch_all(website_sql, {"bid": brand_id})

        indep_sql = """
        SELECT *
        FROM ys_brand_independence_data
        WHERE brand_id = :bid
        ORDER BY search_date DESC
        LIMIT 1
        """
        latest_indep = await self._fetch_one(indep_sql, {"bid": brand_id}) or {}

        return {
            "basic": brand,
            "websites": websites,
            "latest_independence": latest_indep,
        }

    async def get_brand_metric_timeseries(
        self,
        *,
        brand_id: int,
        metric: str,
        start_ts: int,
        end_ts: int,
    ) -> List[Dict[str, Any]]:
        """
        拉取某品牌在指定时间段内的单指标时间序列。
        返回 [{"ts": 1710000000, "value": 123.4}, ...]
        """
        metric = (metric or "").strip()
        if metric == "amazon_search":
            sql = """
            SELECT search_date AS ts, SUM(search_volume) AS value
            FROM ys_brand_amazon_data
            WHERE brand_id = :bid
              AND search_date BETWEEN :start_ts AND :end_ts
            GROUP BY search_date
            ORDER BY search_date
            """
        elif metric == "google_search":
            sql = """
            SELECT search_date AS ts, SUM(search_volume) AS value
            FROM ys_brand_google_data
            WHERE brand_id = :bid
              AND search_date BETWEEN :start_ts AND :end_ts
            GROUP BY search_date
            ORDER BY search_date
            """
        elif metric == "independence_traffic":
            sql = """
            SELECT search_date AS ts, SUM(month_visits) AS value
            FROM ys_brand_independence_data
            WHERE brand_id = :bid
              AND search_date BETWEEN :start_ts AND :end_ts
            GROUP BY search_date
            ORDER BY search_date
            """
        else:
            # 未知指标，直接返回空
            return []

        rows = await self._fetch_all(sql, {"bid": brand_id, "start_ts": start_ts, "end_ts": end_ts})
        result: List[Dict[str, Any]] = []
        for r in rows:
            result.append(
                {
                    "ts": int(r.get("ts")),
                    "value": float(r.get("value") or 0.0),
                }
            )
        return result
