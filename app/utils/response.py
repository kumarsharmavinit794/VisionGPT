from math import ceil
from typing import Any


class APIResponse:
    @staticmethod
    def success(data: Any = None, message: str = "Success", status_code: int = 200) -> dict:
        return {"success": True, "message": message, "data": data}

    @staticmethod
    def error(
        message: str,
        code: str,
        detail: Any = None,
        status_code: int = 400,
    ) -> dict:
        return {"success": False, "error": message, "code": code, "detail": detail}

    @staticmethod
    def paginated(data: Any, total: int, page: int, limit: int) -> dict:
        return {
            "success": True,
            "data": data,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "pages": ceil(total / limit) if limit else 0,
            },
        }
