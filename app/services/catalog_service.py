"""開課查詢服務 - 直接呼叫長庚課程 API"""

import json
import httpx
from typing import Optional

from lib.catalog import CATALOG_API, TERM_IDS, term_id_for


class CatalogService:
    @staticmethod
    def get_term_id(year: int, term: int) -> Optional[int]:
        """取得學期代碼"""
        return TERM_IDS.get((year, term))

    @staticmethod
    def get_available_terms() -> list[dict]:
        """取得可用學期清單"""
        return [
            {
                "year": year,
                "term": term,
                "termid": termid,
                "label": f"{year} / {term}",
            }
            for (year, term), termid in sorted(
                TERM_IDS.items(), key=lambda item: item[1], reverse=True
            )
        ]

    @staticmethod
    def _build_query_params(
        termid: int,
        departmentid: str = "",
        keyward: str = "",
        sectionid: str = "",
        call_id: str = "",
        teaName: str = "",
        cName: str = "",
        year: str = "",
        fieldid: str = "",
        week: str = "",
        stime: str = "",
        etime: str = "",
        lang: str = "",
    ) -> dict:
        return {
            "termid": str(termid),
            "departmentid": departmentid,
            "call_id": call_id,
            "keyward": keyward,
            "sectionid": sectionid,
            "teaName": teaName,
            "cName": cName,
            "year": year,
            "fieldid": fieldid,
            "week": week,
            "stime": stime,
            "etime": etime,
            "lang": lang,
        }

    @staticmethod
    def fetch_courses(params: dict) -> list[dict]:
        """依官方 API 參數取得課程"""
        with httpx.Client(timeout=30.0) as client:
            response = client.get(CATALOG_API, params=params, headers={"User-Agent": "Mozilla/5.0"})
            return response.json()

    @staticmethod
    def fetch_all_courses(termid: int) -> list[dict]:
        """取得該學期所有課程"""
        return CatalogService.fetch_courses(CatalogService._build_query_params(termid))

    @staticmethod
    def search_courses(
        termid: int,
        departmentid: str = "",
        keyward: str = "",
        sectionid: str = "",
        call_id: str = "",
        teaName: str = "",
        cName: str = "",
        year: str = "",
        fieldid: str = "",
        week: str = "",
        stime: str = "",
        etime: str = "",
        lang: str = "",
    ) -> list[dict]:
        """使用官方欄位搜尋課程"""
        if termid not in TERM_IDS.values():
            return []

        params = CatalogService._build_query_params(
            termid=termid,
            departmentid=departmentid,
            keyward=keyward,
            sectionid=sectionid,
            call_id=call_id,
            teaName=teaName,
            cName=cName,
            year=year,
            fieldid=fieldid,
            week=week,
            stime=stime,
            etime=etime,
            lang=lang,
        )
        return CatalogService.fetch_courses(params)

    @staticmethod
    def get_departments(termid: int) -> list[dict]:
        """取得該學期所有開課單位"""
        courses = CatalogService.fetch_all_courses(termid)
        departments = {
            c.get("DEPARTMENTID", ""): c.get("DEPARTMENTNAME_C", "")
            for c in courses
            if c.get("DEPARTMENTID") and c.get("DEPARTMENTNAME_C")
        }
        return [
            {"id": department_id, "name": name}
            for department_id, name in sorted(departments.items(), key=lambda item: item[1])
        ]

    @staticmethod
    def query_course(year: int, term: int, sectionid: str) -> dict:
        """查詢單一課程詳情"""
        termid = TERM_IDS.get((year, term))
        if not termid:
            raise ValueError(f"找不到學期代碼: {year}-{term}")

        payload = CatalogService.search_courses(termid=termid, sectionid=sectionid)

        if not payload:
            raise LookupError(f"查無資料：sectionid={sectionid}")
        if isinstance(payload, dict):
            return payload

        for item in payload:
            if str(item.get("SECTIONID", "")).strip() == str(sectionid).strip():
                return item
        return payload[0]
