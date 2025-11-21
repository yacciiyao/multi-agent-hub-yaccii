# -*- coding: utf-8 -*-
# @File: storage_mysql.py
# @Author: yaccii
# @Time: 2025-11-07 12:39
# @Description:
import asyncio
import json
import struct
import time
from contextlib import asynccontextmanager
from typing import Optional, List

import aiomysql

from domain.enums import Role
from domain.message import Message, RagSource
from domain.session import Session
from infrastructure.mlogger import mlogger
from storage.storage_base import IStorage

MYSQL_RETRY_ERRORS = {2006, 2013}


class MySQLStorage(IStorage):
    def __init__(self, config):
        self.config = config
        self.pool: Optional[aiomysql.Pool] = None

    async def init(self):
        self.pool = await aiomysql.create_pool(
            host=self.config["host"],
            port=int(self.config.get("port")),
            user=self.config["user"],
            password=self.config["password"],
            db=self.config["database"],
            autocommit=True,
            charset="utf8mb4",
            connect_timeout=10,
        )

        await self._ensure_tables()
        mlogger.info(self.__class__.__name__, "init", msg="success")

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def create_session(self, session: Session) -> None:
        sql = """
            INSERT INTO chat_sessions (session_id,user_id,bot_name,agent_key,channel,rag_enabled,
                stream_enabled,is_deleted,created_at,updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
        """
        now = int(time.time())
        created_at = session.created_at or now
        updated_at = session.updated_at or now
        await self._execute(
            sql,
            (
                session.session_id,
                session.user_id,
                session.bot_name,
                session.agent_key,
                getattr(session.channel, "value", str(session.channel)),
                int(getattr(session, "rag_enabled", False)),
                int(getattr(session, "stream_enabled", False)),
                created_at,
                updated_at
            ),
            fetch=False,
        )

    async def rename_session(self, user_id: int, session_id: str, new_name: str) -> None:
        sql = """
            UPDATE chat_sessions
               SET session_name=%s, updated_at=%s
             WHERE user_id=%s AND session_id=%s AND is_deleted=0
        """
        await self._execute(sql, (new_name, int(time.time()), user_id, session_id), fetch=False)

    async def update_session_flag(self, user_id: int, session_id: str, rag_enabled: bool, stream_enabled: bool) -> None:
        now = int(time.time())
        sql = """
            UPDATE chat_sessions
               SET rag_enabled=%s,
                   stream_enabled=%s,
                   updated_at=%s
             WHERE user_id=%s AND session_id=%s AND is_deleted=0
        """
        await self._execute(
            sql,
            (int(rag_enabled), int(stream_enabled), now, user_id, session_id),
            fetch=False,
        )

    async def get_session(self, user_id: int, session_id: str) -> Optional[Session]:
        sql = """
            SELECT session_id, user_id, bot_name, agent_key, channel, session_name,
                   rag_enabled, stream_enabled, is_deleted, created_at, updated_at
              FROM chat_sessions
             WHERE user_id=%s AND session_id=%s AND is_deleted=0
        """
        rows = await self._execute(sql, (user_id, session_id))
        if not rows:
            return None
        return self._row_to_session(rows[0])

    async def list_sessions(self, user_id: int) -> List[Session]:
        sql = """
            SELECT session_id, user_id, bot_name, agent_key, channel, session_name,
                   rag_enabled, stream_enabled, is_deleted, created_at, updated_at
              FROM chat_sessions
             WHERE user_id=%s AND is_deleted=0
             ORDER BY updated_at DESC, created_at DESC
        """
        rows = await self._execute(sql, (user_id,))
        return [self._row_to_session(r) for r in rows]

    async def delete_session(self, user_id: int, session_id: str) -> None:
        now = int(time.time())
        await self._execute(
            """UPDATE chat_sessions SET is_deleted=1, updated_at=%s
               WHERE user_id=%s AND session_id=%s AND is_deleted=0""",
            (now, user_id, session_id),
            fetch=False,
        )
        await self._execute(
            """UPDATE chat_messages SET is_deleted=1 WHERE session_id=%s AND is_deleted=0""",
            (session_id,),
            fetch=False,
        )

    async def delete_all_sessions(self, user_id: int) -> None:
        now = int(time.time())
        await self._execute(
            """UPDATE chat_sessions SET is_deleted=1, updated_at=%s WHERE user_id=%s AND is_deleted=0""",
            (now, user_id),
            fetch=False,
        )
        await self._execute(
            """
            UPDATE chat_messages
               SET is_deleted=1
             WHERE is_deleted=0 AND session_id IN (
                   SELECT s.session_id FROM chat_sessions s WHERE s.user_id=%s
             )
            """,
            (user_id,),
            fetch=False,
        )

    async def append_message(self, message: Message) -> None:
        sources_json = json.dumps([s.model_dump() for s in (message.sources or [])], ensure_ascii=False)
        sql = """
            INSERT INTO chat_messages
              (session_id, role, content, rag_enabled, stream_enabled, sources, created_at, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
        """
        created_at = message.created_at or int(time.time())
        stream_enabled = 1 if getattr(message, "stream_enabled", False) else 0
        await self._execute(
            sql,
            (
                message.session_id,
                getattr(message.role, "value", str(message.role)),
                message.content,
                1 if message.rag_enabled else 0,
                stream_enabled,
                sources_json,
                created_at,
            ),
            fetch=False,
        )
        now = int(time.time())
        await self._execute(
            """UPDATE chat_sessions SET updated_at=%s WHERE session_id=%s AND is_deleted=0""",
            (now, message.session_id),
            fetch=False,
        )

    async def get_messages(self, user_id: int, session_id: str) -> List[Message]:
        session = await self.get_session(user_id=user_id, session_id=session_id)
        if not session:
            return []
        rows = await self._execute(
            """
            SELECT id, session_id, role, content, rag_enabled, stream_enabled, sources, created_at, is_deleted
              FROM chat_messages
             WHERE session_id=%s AND is_deleted=0
             ORDER BY created_at ASC
            """,
            (session_id,),
        )
        return [self._row_to_message(r) for r in rows]

    async def _execute(self, sql: str, params: tuple = (), fetch: bool = True):
        if not self.pool:
            raise RuntimeError("MySQL pool not initialized")
        try:
            async with self._conn_cursor() as (_, cursor):
                await cursor.execute(sql, params)
                if fetch:
                    return await cursor.fetchall()
                return None
        except Exception as e:
            if getattr(e, "args", None) and e.args and e.args[0] in MYSQL_RETRY_ERRORS:
                mlogger.exception(self.__class__.__name__, "exception occurred", msg=e, sql=sql, params=params)
                async with self._conn_cursor() as (_, cursor):
                    await cursor.execute(sql, params)
                    if fetch:
                        return await cursor.fetchall()
                    return None
            raise

    @asynccontextmanager
    async def _conn_cursor(self):
        if not self.pool:
            raise RuntimeError("MySQL pool not initialized")
        conn = await self.pool.acquire()
        try:
            try:
                await conn.ping(reconnect=True)
            except Exception:
                await asyncio.sleep(0.1)
                await conn.ping(reconnect=True)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                yield conn, cursor
        finally:
            self.pool.release(conn)

    async def _ensure_tables(self):
        session_sql = """
            CREATE TABLE IF	NOT EXISTS `chat_sessions` (
                `session_id`     CHAR ( 36 ) NOT NULL,
                `session_name`   VARCHAR ( 100 )                  CHARACTER SET utf8mb4,
                `user_id`        INT             NOT NULL,
                `bot_name`       VARCHAR ( 50 )  NOT NULL,
                `agent_key`      VARCHAR ( 50 )  NOT NULL,
                `channel`        VARCHAR ( 20 )  NOT NULL,
                `rag_enabled`    TINYINT                  DEFAULT '0',
                `stream_enabled` TINYINT                  DEFAULT '0',
                `is_deleted`     TINYINT         NOT NULL DEFAULT '0',
                `created_at`     INT UNSIGNED    NOT NULL,
                `updated_at`     INT             NOT NULL,
                PRIMARY KEY ( `session_id` ),
                KEY `idx_user_updated` ( `user_id`, `updated_at` ),
                KEY `idx_user_del` ( `user_id`, `is_deleted` ),
                KEY `idx_updated` ( `updated_at` ) 
            ) ENGINE = INNODB DEFAULT CHARSET = utf8mb4
        """

        message_sql = """
            CREATE TABLE IF NOT EXISTS `chat_messages` (
                `id`             INT            NOT NULL AUTO_INCREMENT,
                `session_id`     VARCHAR ( 64 ) NOT NULL,
                `role`           VARCHAR ( 16 ) NOT NULL,
                `content`        MEDIUMTEXT     NOT NULL,
                `rag_enabled`    TINYINT                 DEFAULT '0',
                `stream_enabled` TINYINT                 DEFAULT '0',
                `sources`        MEDIUMTEXT,
                `created_at`     INT NOT NULL,
                `is_deleted`     TINYINT        NOT NULL DEFAULT '0',
                PRIMARY KEY ( `id` ),
                KEY `idx_sess` ( `session_id` ),
                CONSTRAINT `fk_msg_sess` FOREIGN KEY ( `session_id` ) REFERENCES `chat_sessions` ( `session_id` ) ON DELETE CASCADE ON UPDATE CASCADE 
            ) ENGINE = INNODB DEFAULT CHARSET = utf8mb4
        """

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(session_sql)
                await cursor.execute(message_sql)
                try:
                    await cursor.execute(
                        "CREATE INDEX idx_user_del_updated ON chat_sessions(user_id, is_deleted, updated_at)")
                except Exception:
                    pass

    @staticmethod
    def _row_to_session(row: dict) -> Session:
        return Session(
            session_id=row["session_id"],
            user_id=int(row["user_id"]),
            bot_name=row["bot_name"],
            agent_key=row["agent_key"],
            channel=row["channel"],
            session_name=row["session_name"],
            rag_enabled=bool(int(row.get("rag_enabled", 0))),
            stream_enabled=bool(int(row.get("stream_enabled", 0))),
            is_deleted=int(row.get("is_deleted", 0)),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )

    @staticmethod
    def _row_to_message(row: dict) -> Message:
        sources_str = row["sources"] or "[]"
        try:
            sources_list = json.loads(sources_str)
            sources = [RagSource(**s) for s in sources_list]
        except Exception:
            sources = []

        role_val = row.get("role", "other")
        role = Role(role_val) if role_val in (Role.USER.value, Role.ASSISTANT.value, Role.SYSTEM.value) else Role.SYSTEM

        def to_bool(v, default=False):
            try:
                return bool(int(v)) if v is not None else default
            except (ValueError, TypeError):
                return default

        return Message(
            session_id=row["session_id"],
            role=role,
            content=row.get("content", ""),
            rag_enabled=to_bool(row.get("rag_enabled"), False),
            sources=sources,
            created_at=int(row.get("created_at", 0)),
            is_deleted=bool(int(row.get("is_deleted", 0))),
            stream_enabled=to_bool(row.get("stream_enabled"), False),  # type: ignore
        )

    @staticmethod
    def _vector_to_blob(vector: List[float]) -> bytes:
        if not vector:
            return b""
        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def _blob_to_vector(blob: Optional[bytes]) -> List[float]:
        if not blob:
            return []
        n = len(blob) // 4
        return list(struct.unpack(f"<{n}f", blob))
