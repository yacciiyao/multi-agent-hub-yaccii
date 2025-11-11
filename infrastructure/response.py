# -*- coding: utf-8 -*-
# @File: response.py
# @Author: yaccii
# @Time: 2025-11-07 11:38
# @Description:
from fastapi import status
from fastapi.responses import JSONResponse


def success(data=None, message: str = "ok", code: int = 0) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "data": data}, status_code=status.HTTP_200_OK)


def failure(message: str = "error", code: int = 40000, http_status: int = status.HTTP_400_BAD_REQUEST,
            data=None) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "data": data}, status_code=http_status)
