class AppError(Exception):
    """Ошибка приложения с HTTP-кодом и машинным кодом для фронтенда."""

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
