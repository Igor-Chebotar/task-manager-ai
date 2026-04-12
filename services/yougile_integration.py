"""Интеграция с YouGile - проекты, доски, задачи через REST API."""

import logging
from datetime import datetime
from typing import Any

import aiohttp

from config import settings

logger = logging.getLogger(__name__)


class YougileService:
    """Работа с YouGile API v2."""

    def __init__(self) -> None:
        self.base_url = settings.yougile_base_url
        logger.info("Сервис YouGile: %s", self.base_url)

    def _get_headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def get_projects(self, api_key: str) -> list[dict[str, Any]]:
        """Список проектов пользователя."""
        url = f"{self.base_url}/projects"
        headers = self._get_headers(api_key)

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.error("Ошибка получения проектов: %s", await resp.text())
                        return []
                    data = await resp.json()

            projects = data.get("content", [])
            logger.info("Получено %d проектов", len(projects))
            return projects
        except Exception as exc:
            logger.error("Ошибка запроса проектов: %s", exc)
            return []

    async def get_boards(self, api_key: str, project_id: str) -> list[dict[str, Any]]:
        """Доски в проекте."""
        url = f"{self.base_url}/boards"
        headers = self._get_headers(api_key)
        params = {"projectId": project_id}

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        logger.error("Ошибка получения досок: %s", await resp.text())
                        return []
                    data = await resp.json()

            return data.get("content", [])
        except Exception as exc:
            logger.error("Ошибка запроса досок: %s", exc)
            return []

    async def get_columns(self, api_key: str, board_id: str) -> list[dict[str, Any]]:
        """Колонки на доске."""
        url = f"{self.base_url}/columns"
        headers = self._get_headers(api_key)
        params = {"boardId": board_id}

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        logger.error("Ошибка получения колонок: %s", await resp.text())
                        return []
                    data = await resp.json()

            return data.get("content", [])
        except Exception as exc:
            logger.error("Ошибка запроса колонок: %s", exc)
            return []

    async def create_task(
        self, api_key: str, title: str, column_id: str,
        description: str = "", deadline: str | None = None,
    ) -> dict[str, Any] | None:
        """Создаёт задачу в указанной колонке."""
        url = f"{self.base_url}/tasks"
        headers = self._get_headers(api_key)

        task_body: dict[str, Any] = {
            "title": title,
            "columnId": column_id,
        }

        if description:
            task_body["description"] = description

        # дедлайн в YouGile - timestamp в миллисекундах
        if deadline:
            try:
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
                deadline_dt = deadline_dt.replace(hour=23, minute=59, second=59)
                task_body["deadline"] = {
                    "deadline": int(deadline_dt.timestamp() * 1000),
                }
            except ValueError:
                logger.warning("Некорректный формат дедлайна: %s", deadline)

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(url, json=task_body, headers=headers) as resp:
                    if resp.status in (200, 201):
                        task = await resp.json()
                        logger.info("Задача создана: '%s'", title)
                        return task
                    else:
                        logger.error("Ошибка создания задачи: %s", await resp.text())
                        return None
        except Exception as exc:
            logger.error("Ошибка при создании задачи: %s", exc)
            return None

    async def find_column_by_name(
        self, api_key: str,
        board_name: str | None = None, column_name: str | None = None,
    ) -> str | None:
        """Ищет ID колонки по названиям доски и колонки. Без аргументов - берёт первую попавшуюся."""
        projects = await self.get_projects(api_key)
        if not projects:
            return None

        target_board_id = None
        for project in projects:
            boards = await self.get_boards(api_key, project["id"])
            if board_name:
                for board in boards:
                    if board["title"].lower() == board_name.lower():
                        target_board_id = board["id"]
                        break
            elif boards:
                target_board_id = boards[0]["id"]

            if target_board_id:
                break

        if not target_board_id:
            logger.warning("Доска '%s' не найдена", board_name)
            return None

        columns = await self.get_columns(api_key, target_board_id)
        if column_name:
            for column in columns:
                if column["title"].lower() == column_name.lower():
                    return column["id"]
            logger.warning("Колонка '%s' не найдена", column_name)
            return None

        return columns[0]["id"] if columns else None

    async def get_tasks(self, api_key: str, column_id: str) -> list[dict[str, Any]]:
        """Активные задачи в колонке (без архивных/удалённых)."""
        url = f"{self.base_url}/tasks"
        headers = self._get_headers(api_key)
        params = {"columnId": column_id}

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()

            tasks = data.get("content", [])
            active = [
                t for t in tasks
                if not t.get("archived", False)
                and not t.get("completed", False)
                and not t.get("deleted", False)
            ]
            return active
        except Exception as exc:
            logger.error("Ошибка получения задач: %s", exc)
            return []

    async def delete_task(self, api_key: str, task_id: str) -> bool:
        """Soft delete через PUT {deleted: true}."""
        url = f"{self.base_url}/tasks/{task_id}"
        headers = self._get_headers(api_key)

        try:
            async with aiohttp.ClientSession() as http:
                async with http.put(url, json={"deleted": True}, headers=headers) as resp:
                    if resp.status in (200, 204):
                        logger.info("Задача %s удалена", task_id)
                        return True
                    logger.error("Ошибка удаления задачи: %s", await resp.text())
                    return False
        except Exception as exc:
            logger.error("Ошибка при удалении задачи: %s", exc)
            return False

    async def find_task_by_name(self, api_key: str, title: str) -> dict[str, Any] | None:
        """Ищет задачу по названию во всех колонках (точное совпадение, потом подстрока)."""
        title_lower = title.lower().strip()
        projects = await self.get_projects(api_key)

        all_tasks: list[dict[str, Any]] = []
        for project in projects:
            boards = await self.get_boards(api_key, project["id"])
            for board in boards:
                columns = await self.get_columns(api_key, board["id"])
                for column in columns:
                    tasks = await self.get_tasks(api_key, column["id"])
                    all_tasks.extend(tasks)

        for task in all_tasks:
            if task.get("title", "").lower().strip() == title_lower:
                return task

        for task in all_tasks:
            task_title = task.get("title", "").lower().strip()
            if title_lower in task_title or task_title in title_lower:
                return task

        return None

    async def find_column_by_name_global(
        self, api_key: str, column_name: str,
    ) -> tuple[str, str] | None:
        """Ищет колонку во всех проектах, возвращает (column_id, path) или None."""
        column_lower = column_name.lower().strip()
        projects = await self.get_projects(api_key)

        for project in projects:
            boards = await self.get_boards(api_key, project["id"])
            for board in boards:
                columns = await self.get_columns(api_key, board["id"])
                for column in columns:
                    if column["title"].lower().strip() == column_lower:
                        path = f"{project['title']} > {board['title']} > {column['title']}"
                        return column["id"], path
        return None

    async def clear_column(self, api_key: str, column_id: str) -> int:
        """Удаляет все активные задачи из колонки, возвращает кол-во удалённых."""
        tasks = await self.get_tasks(api_key, column_id)
        deleted = 0
        for task in tasks:
            if await self.delete_task(api_key, task["id"]):
                deleted += 1
        logger.info("Очистка колонки %s: удалено %d/%d", column_id, deleted, len(tasks))
        return deleted
