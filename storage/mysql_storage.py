# -*- coding: utf-8 -*-
# @File: mysql_storage.py
# @Author: yaccii
# @Time: 2025-11-07 12:39
# @Description:
import asyncio
import json
import struct
import time
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Tuple, Any

import aiomysql

from domain.enums import Role
from domain.message import Message, RagSource
from domain.rag import RagChunk, RagDocument
from domain.session import Session
from infrastructure.mlogger import mlogger
from storage.base import IStorage

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
        mlogger.info("[MySQLStorage] 连接池初始化完成。")

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def create_session(self, session: Session) -> None:
        sql = """
            INSERT INTO chat_sessions (session_id, user_id, bot_name, channel, session_name, 
            rag_enabled, stream_enabled, is_deleted, created_at, updated_at)
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
                getattr(session.channel, "value", str(session.channel)),
                session.session_name,
                int(getattr(session, "rag_enabled", False)),
                int(getattr(session, "stream_enabled", False)),
                created_at,
                updated_at,
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
            SELECT session_id, user_id, bot_name, channel, session_name,
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
            SELECT session_id, user_id, bot_name, channel, session_name,
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

    async def upsert_rag_document(self, doc: RagDocument, chunks: List[RagChunk]) -> None:
        await self._execute(
            """
            INSERT INTO rag_documents
              (doc_id,user_id,title,source,url,tags,scope,is_deleted,created_at,updated_at,
               embed_provider,embed_model,embed_dim,embed_version,split_params,preprocess_flags)
            VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              title=VALUES(title),
              url=VALUES(url),
              tags=VALUES(tags),
              scope=VALUES(scope),
              embed_provider=VALUES(embed_provider),
              embed_model=VALUES(embed_model),
              embed_dim=VALUES(embed_dim),
              embed_version=VALUES(embed_version),
              split_params=VALUES(split_params),
              preprocess_flags=VALUES(preprocess_flags),
              updated_at=VALUES(updated_at),
              is_deleted=0
            """,
            (
                doc.doc_id,
                doc.user_id,
                doc.title,
                doc.source,
                doc.url,
                json.dumps(doc.tags, ensure_ascii=False),
                doc.scope,
                doc.created_at,
                doc.updated_at,
                doc.embed_provider,
                doc.embed_model,
                doc.embed_dim,
                doc.embed_version,
                json.dumps(doc.split_params, ensure_ascii=False),
                doc.preprocess_flags,
            ),
            fetch=False,
        )

        await self._execute("DELETE FROM rag_chunks WHERE doc_id=%s", (doc.doc_id,), fetch=False)

        if chunks:
            sql = """
                INSERT INTO rag_chunks
                  (doc_id,user_id,chunk_index,content,embedding,created_at,is_deleted)
                VALUES (%s,%s,%s,%s,%s,%s,0)
            """
            args: List[tuple] = []
            for c in chunks:
                blob = self._vector_to_blob(c.embedding) if c.embedding else None
                args.append((c.doc_id, c.user_id, c.chunk_index, c.content, blob, c.created_at))

            BATCH = 512
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    for i in range(0, len(args), BATCH):
                        part = args[i: i + BATCH]
                        await cursor.executemany(sql, part)

    async def list_rag_documents(self, user_id: int) -> List[RagDocument]:
        rows = await self._execute(
            """
            SELECT doc_id,user_id,title,source,url,tags,scope,is_deleted,created_at,updated_at,
                   embed_provider,embed_model,embed_dim,embed_version,split_params,preprocess_flags
              FROM rag_documents
             WHERE is_deleted=0 AND user_id=%s
             ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        output: List[RagDocument] = []
        for r in rows:
            output.append(
                RagDocument(
                    doc_id=r["doc_id"],
                    user_id=int(r["user_id"]),
                    title=r["title"],
                    source=r["source"],
                    url=r["url"],
                    tags=json.loads(r["tags"] or "[]"),
                    scope=r["scope"],
                    is_deleted=int(r["is_deleted"]),
                    created_at=int(r["created_at"]),
                    updated_at=int(r["updated_at"]),
                    embed_provider=r["embed_provider"],
                    embed_model=r["embed_model"],
                    embed_dim=int(r["embed_dim"]),
                    embed_version=int(r["embed_version"]),
                    split_params=json.loads(r["split_params"] or "{}"),
                    preprocess_flags=r.get("preprocess_flags") or "",
                )
            )
        return output

    async def delete_rag_document(self, user_id: int, doc_id: str) -> None:
        await self._execute(
            "UPDATE rag_documents SET is_deleted=1 WHERE user_id=%s AND doc_id=%s AND is_deleted=0",
            (user_id, doc_id),
            fetch=False,
        )
        await self._execute(
            "UPDATE rag_chunks SET is_deleted=1 WHERE doc_id=%s AND is_deleted=0",
            (doc_id,),
            fetch=False,
        )

    async def get_rag_chunks_with_embeddings(
            self,
            *,
            scan_limit: int,
            user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scan chunks with embeddings. When user_id is provided, only global
        documents and the user's private documents are returned.
        """
        where = ["c.is_deleted=0", "d.is_deleted=0", "c.embedding IS NOT NULL"]
        args: List[Any] = []
        if user_id is not None:
            where.append("(d.scope='global' OR (d.scope='private' AND d.user_id=%s))")
            args.append(int(user_id))
        else:
            where.append("d.scope='global'")

        where_sql = " AND ".join(where)
        sql_ids = f"""
            SELECT c.id
              FROM rag_chunks c
              JOIN rag_documents d ON d.doc_id = c.doc_id
             WHERE {where_sql}
             ORDER BY c.id ASC
             LIMIT %s
        """
        rows_ids = await self._execute(sql_ids, tuple(args + [int(scan_limit)]))
        if not rows_ids:
            return []

        id_list = [r["id"] for r in rows_ids]
        placeholders = ",".join(["%s"] * len(id_list))
        sql_data = f"""
            SELECT c.id, c.doc_id, c.user_id, c.chunk_index,
                   c.content, c.embedding, c.created_at,
                   d.title, d.url
              FROM rag_chunks c
              JOIN rag_documents d ON d.doc_id = c.doc_id
             WHERE c.id IN ({placeholders})
             ORDER BY FIELD(c.id, {",".join(["%s"] * len(id_list))})
        """
        rows = await self._execute(sql_data, tuple(id_list + id_list))

        output: List[Dict[str, Any]] = []
        for r in rows:
            embedding = None
            blob = r.get("embedding")
            if blob:
                n = len(blob) // 4
                embedding = list(struct.unpack(f"<{n}f", blob))
            output.append(
                {
                    "doc_id": r["doc_id"],
                    "user_id": int(r["user_id"]),
                    "chunk_index": int(r["chunk_index"]),
                    "content": r["content"],
                    "embedding": embedding,
                    "created_at": int(r["created_at"]),
                    "title": r.get("title"),
                    "url": r.get("url"),
                }
            )
        return output

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
                mlogger.warning(f"[MySQLStorage] retry once due to connection error: {e}")
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
                `channel`        VARCHAR ( 20 )  NOT NULL,
                `rag_enabled`    TINYINT                  DEFAULT '0',
                `stream_enabled` TINYINT                  DEFAULT '0',
                `is_deleted`     TINYINT ( 1 )   NOT NULL DEFAULT '0',
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

        rag_doc_sql = """
            CREATE TABLE IF NOT EXISTS rag_documents (
              doc_id           VARCHAR(64)  NOT NULL,
              user_id          INT          NOT NULL,
              title            VARCHAR(255) NOT NULL,
              source           VARCHAR(32)  NOT NULL DEFAULT 'upload',
              url              VARCHAR(1024),
              tags             JSON,
              scope            VARCHAR(16)  NOT NULL DEFAULT 'global',
              is_deleted       TINYINT(1)   NOT NULL DEFAULT 0,
              created_at       INT          NOT NULL,
              updated_at       INT          NOT NULL,

              embed_provider   VARCHAR(32)  NOT NULL,
              embed_model      VARCHAR(64)  NOT NULL,
              embed_dim        INT          NOT NULL,
              embed_version    INT          NOT NULL DEFAULT 1,
              split_params     JSON,
              preprocess_flags VARCHAR(128),

              PRIMARY KEY (doc_id),
              KEY idx_user (user_id),
              KEY idx_deleted (is_deleted),
              KEY idx_updated (updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        rag_chunk_sql = """
            CREATE TABLE IF NOT EXISTS rag_chunks (
              id           BIGINT       NOT NULL AUTO_INCREMENT,
              doc_id       VARCHAR(64)  NOT NULL,
              user_id      INT          NOT NULL,
              chunk_index  INT          NOT NULL,
              content      MEDIUMTEXT   NOT NULL,
              embedding    BLOB         NULL,
              created_at   INT          NOT NULL,
              is_deleted   TINYINT(1)   NOT NULL DEFAULT 0,
              PRIMARY KEY (id),
              KEY idx_doc (doc_id),
              KEY idx_user (user_id),
              CONSTRAINT fk_rag_chunk_doc FOREIGN KEY (doc_id)
                REFERENCES rag_documents(doc_id) ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(session_sql)
                await cursor.execute(message_sql)
                await cursor.execute(rag_doc_sql)
                await cursor.execute(rag_chunk_sql)
                try:
                    await cursor.execute(
                        "CREATE INDEX idx_user_del_updated ON chat_sessions(user_id, is_deleted, updated_at)"
                    )
                except Exception:
                    pass

    @staticmethod
    def _row_to_session(row: dict) -> Session:
        return Session(
            session_id=row["session_id"],
            user_id=int(row["user_id"]),
            bot_name=row["bot_name"],
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
