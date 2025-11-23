# -*- coding: utf-8 -*-
# @File: project_repository.py
# @Description: 众筹项目相关数据库访问与基础聚合逻辑

from __future__ import annotations

from typing import Any, Dict, List, Optional

from infrastructure.mlogger import mlogger


class ProjectRepository:
    """
    封装众筹相关的 SQL 访问与基础计算：
      - 众筹项目榜单（多平台 / 多指标）
      - 关键项目搜索
      - 单个项目的完整上下文（ys_project + kickstarter_project + makuake_projects）
    """

    def __init__(self, storage: Any) -> None:
        """
        :param storage: 项目统一的 Storage 实例（例如 DataStorageManager.get() 返回值）
        """
        self._storage = storage

    # ===== 通用 DB 访问封装 =====

    async def _fetch_all(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        try:
            return await self._storage.fetch_all(sql, params or {})
        except Exception as e:
            mlogger.error(self.__class__.__name__, "_fetch_all", msg=str(e))
            raise

    async def _fetch_one(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        rows = await self._fetch_all(sql, params)
        return rows[0] if rows else None

    # ===== 众筹项目榜单计算 =====

    async def calc_project_ranking(
        self,
        *,
        metric: str,
        start_ts: int,
        end_ts: int,
        category: Optional[str] = None,
        source: Optional[str] = None,
        country: Optional[str] = None,
        top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        计算众筹项目榜单。

        metric:
          - funds_total: 按总筹款额排序
          - funds_speed: 按筹款速度（总筹款额 / 项目时长）排序

        source:
          - None / "all": 综合 Kickstarter + Indiegogo + Makuake
          - "kickstarter": 只看 Kickstarter
          - "indiegogo": 只看 Indiegogo（ys_project.source='indiegogo'）
          - "makuake": 只看 Makuake
        """
        metric = (metric or "funds_total").strip()
        if metric not in ("funds_total", "funds_speed"):
            metric = "funds_total"

        src = (source or "").strip().lower() or None

        rows: List[Dict[str, Any]] = []

        # Kickstarter
        if src in (None, "", "all", "kickstarter"):
            rows.extend(
                await self._calc_kickstarter_ranking(
                    metric=metric,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    category=category,
                    country=country,
                )
            )

        # Indiegogo（通过 ys_project）
        if src in (None, "", "all", "indiegogo"):
            rows.extend(
                await self._calc_indiegogo_ranking(
                    metric=metric,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    category=category,
                    country=country,
                )
            )

        # Makuake
        if src in (None, "", "all", "makuake"):
            rows.extend(
                await self._calc_makuake_ranking(
                    metric=metric,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    category=category,
                    country=country,
                )
            )

        if not rows:
            return []

        # 按 metric 排序
        key = "usd_raised" if metric == "funds_total" else "funds_speed"
        rows = [r for r in rows if r.get(key, 0) is not None]
        rows.sort(key=lambda x: float(x.get(key) or 0.0), reverse=True)

        # 加 rank
        for idx, r in enumerate(rows, start=1):
            r["rank"] = idx

        return rows[:top_n]

    async def _calc_kickstarter_ranking(
        self,
        *,
        metric: str,
        start_ts: int,
        end_ts: int,
        category: Optional[str],
        country: Optional[str],
    ) -> List[Dict[str, Any]]:
        sql = """
        SELECT
            project_id,
            name,
            category_parent_name AS category,
            country,
            COALESCE(converted_pledged_amount, usd_pledged, 0) AS usd_raised,
            COALESCE(backers_count, 0) AS backers_num,
            launched_at,
            deadline
        FROM kickstarter_project
        WHERE launched_at BETWEEN :start_ts AND :end_ts
        """
        params: Dict[str, Any] = {"start_ts": start_ts, "end_ts": end_ts}

        if category:
            sql += " AND (category_parent_name LIKE :cate OR category_name LIKE :cate)"
            params["cate"] = f"%{category}%"

        if country:
            sql += " AND country = :country"
            params["country"] = country

        rows = await self._fetch_all(sql, params)
        result: List[Dict[str, Any]] = []

        for r in rows:
            usd_raised = float(r.get("usd_raised") or 0.0)
            launched_at = int(r.get("launched_at") or 0)
            deadline = int(r.get("deadline") or 0)
            duration_days = max((deadline - launched_at) / 86400.0, 0.0) if (deadline and launched_at) else 0.0
            funds_speed = usd_raised / duration_days if duration_days > 0 else 0.0

            result.append(
                {
                    "source": "kickstarter",
                    "project_id": r.get("project_id"),
                    "title": r.get("name") or "",
                    "category": r.get("category") or "",
                    "country": r.get("country") or "",
                    "usd_raised": usd_raised,
                    "backers_num": int(r.get("backers_num") or 0),
                    "duration_days": duration_days,
                    "funds_speed": funds_speed,
                }
            )

        return result

    async def _calc_indiegogo_ranking(
        self,
        *,
        metric: str,
        start_ts: int,
        end_ts: int,
        category: Optional[str],
        country: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        使用 ys_project 中 source='indiegogo' 的数据。
        """
        sql = """
        SELECT
            id,
            project_id,
            title,
            category,
            country,
            COALESCE(funds_raised_amount, 0) * COALESCE(to_usd_rate, 1) AS usd_raised,
            COALESCE(backers_num, 0) AS backers_num,
            open_date,
            close_date
        FROM ys_project
        WHERE source = 'indiegogo'
          AND open_date BETWEEN :start_ts AND :end_ts
        """
        params: Dict[str, Any] = {"start_ts": start_ts, "end_ts": end_ts}

        if category:
            sql += " AND (category LIKE :cate OR category2 LIKE :cate)"
            params["cate"] = f"%{category}%"

        if country:
            sql += " AND country = :country"
            params["country"] = country

        rows = await self._fetch_all(sql, params)
        result: List[Dict[str, Any]] = []

        for r in rows:
            usd_raised = float(r.get("usd_raised") or 0.0)
            open_date = int(r.get("open_date") or 0)
            close_date = int(r.get("close_date") or 0)
            duration_days = max((close_date - open_date) / 86400.0, 0.0) if (close_date and open_date) else 0.0
            funds_speed = usd_raised / duration_days if duration_days > 0 else 0.0

            result.append(
                {
                    "source": "indiegogo",
                    "ys_id": int(r.get("id")),
                    "project_id": r.get("project_id"),
                    "title": r.get("title") or "",
                    "category": r.get("category") or "",
                    "country": r.get("country") or "",
                    "usd_raised": usd_raised,
                    "backers_num": int(r.get("backers_num") or 0),
                    "duration_days": duration_days,
                    "funds_speed": funds_speed,
                }
            )

        return result

    async def _calc_makuake_ranking(
        self,
        *,
        metric: str,
        start_ts: int,
        end_ts: int,
        category: Optional[str],
        country: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Makuake 项目榜单。
        注意：collected_money 为日元，真实美元换算可在后续需要时补充。
        当前实现中我们直接视为“统一货币”，用于相对排序。
        """
        sql = """
        SELECT
            project_id,
            title_zh AS title,
            category_name,
            collected_money,
            collected_supporter AS backers_num,
            start_date,
            expiration_date
        FROM makuake_projects
        WHERE start_date BETWEEN :start_ts AND :end_ts
        """
        params: Dict[str, Any] = {"start_ts": start_ts, "end_ts": end_ts}

        if category:
            sql += " AND (category_name LIKE :cate OR category_code LIKE :cate)"
            params["cate"] = f"%{category}%"

        # Makuake 没有国家字段，这里暂时忽略 country 条件

        rows = await self._fetch_all(sql, params)
        result: List[Dict[str, Any]] = []

        for r in rows:
            money = float(r.get("collected_money") or 0.0)
            start_date = int(r.get("start_date") or 0)
            expiration_date = int(r.get("expiration_date") or 0)
            duration_days = max((expiration_date - start_date) / 86400.0, 0.0) if (expiration_date and start_date) else 0.0
            funds_speed = money / duration_days if duration_days > 0 else 0.0

            result.append(
                {
                    "source": "makuake",
                    "project_id": r.get("project_id"),
                    "title": r.get("title") or "",
                    "category": r.get("category_name") or "",
                    "country": "JP",  # 统一视为日本项目
                    "usd_raised": money,
                    "backers_num": int(r.get("backers_num") or 0),
                    "duration_days": duration_days,
                    "funds_speed": funds_speed,
                }
            )

        return result

    # ===== 项目搜索 / 单项目上下文 =====

    async def search_projects(self, keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        根据关键词在 ys_project 中搜索项目（以 Indiegogo + 部分 Kickstarter 聚合数据为主）。

        返回字段：
          - id: ys_project.id
          - source: 'indiegogo' / 'kickstarter' 等
          - project_id: 第三方平台项目 ID
          - title: 标题
          - category: 一级类目
          - country: 国家
        """
        kw = (keyword or "").strip()
        if not kw:
            return []

        sql = """
        SELECT
            id,
            source,
            project_id,
            title,
            category,
            country,
            open_date
        FROM ys_project
        WHERE title LIKE :kw
        ORDER BY open_date DESC
        LIMIT :limit
        """
        params = {"kw": f"%{kw}%", "limit": int(limit)}
        rows = await self._fetch_all(sql, params)

        results: List[Dict[str, Any]] = []
        for r in rows:
            results.append(
                {
                    "id": int(r.get("id")),
                    "source": r.get("source") or "",
                    "project_id": r.get("project_id"),
                    "title": r.get("title") or "",
                    "category": r.get("category") or "",
                    "country": r.get("country") or "",
                }
            )

        return results

    async def get_project_full_context(
        self,
        *,
        ys_id: Optional[int],
        source: str,
        project_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        拉取单个众筹项目的完整上下文数据。
        - base: ys_project 中的聚合信息（如有）；
        - kickstarter_raw: kickstarter_project 表中的原始字段（如 source 或关联平台为 Kickstarter）；
        - makuake_raw: makuake_projects 表中的原始字段（如 source 或关联平台为 Makuake）。
        """
        source = (source or "").strip().lower()
        ctx: Dict[str, Any] = {
            "base": None,
            "kickstarter_raw": None,
            "makuake_raw": None,
        }

        # base 信息
        if ys_id:
            base_sql = """
            SELECT *
            FROM ys_project
            WHERE id = :id
            LIMIT 1
            """
            base_row = await self._fetch_one(base_sql, {"id": ys_id})
            ctx["base"] = base_row

        # Kickstarter 原始数据
        if source == "kickstarter" and project_id:
            ks_sql = """
            SELECT *
            FROM kickstarter_project
            WHERE project_id = :pid
            ORDER BY crawl_time DESC
            LIMIT 1
            """
            ks_row = await self._fetch_one(ks_sql, {"pid": int(project_id)})
            ctx["kickstarter_raw"] = ks_row

        # Makuake 原始数据
        if source == "makuake" and project_id:
            mk_sql = """
            SELECT *
            FROM makuake_projects
            WHERE project_id = :pid
            ORDER BY crawl_time DESC
            LIMIT 1
            """
            mk_row = await self._fetch_one(mk_sql, {"pid": int(project_id)})
            ctx["makuake_raw"] = mk_row

        return ctx
