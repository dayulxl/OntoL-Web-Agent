"""
对话业务域
---------
对话元数据管理 — ontol_char 表 CRUD。
消息内容仍存浏览器 localStorage，本模块只管理对话元数据（id/名称/时间）。
"""

from business.chat.chat_service import create_chat, list_chats, update_chat, delete_chat  # noqa: F401
