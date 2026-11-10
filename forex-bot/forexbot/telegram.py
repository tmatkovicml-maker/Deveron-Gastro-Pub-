"""Telegram obavijesti i komande (/status, /pauza, /nastavi, /zatvori_sve, /pomoc)."""

from __future__ import annotations

import logging
from typing import List, Optional

import requests

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, token: str, chat_id: str, session: Optional[requests.Session] = None):
        self.token = token
        self.chat_id = str(chat_id)
        self.session = session or requests.Session()
        self._offset: Optional[int] = None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send(self, text: str) -> bool:
        if not self.enabled:
            log.info("[telegram isključen] %s", text)
            return False
        try:
            resp = self.session.post(
                self._url("sendMessage"),
                json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
                timeout=15,
            )
            if resp.status_code != 200:
                log.warning("Telegram greška %s: %s", resp.status_code, resp.text[:200])
                return False
            return True
        except requests.RequestException as exc:
            log.warning("Telegram nedostupan: %s", exc)
            return False

    def poll_commands(self) -> List[str]:
        """Vraća nove komande (npr. '/status') poslane iz dopuštenog chata."""
        if not self.enabled:
            return []
        first_poll = self._offset is None
        params = {"timeout": 0}
        if not first_poll:
            params["offset"] = self._offset
        try:
            resp = self.session.get(self._url("getUpdates"), params=params, timeout=15)
            updates = resp.json().get("result", []) if resp.status_code == 200 else []
        except (requests.RequestException, ValueError) as exc:
            log.warning("Telegram getUpdates greška: %s", exc)
            return []

        commands: List[str] = []
        for upd in updates:
            self._offset = upd["update_id"] + 1
            if first_poll:
                continue  # ne izvršavaj stare komande nakon restarta
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != self.chat_id:
                continue  # ignoriraj tuđe poruke
            text = (msg.get("text") or "").strip()
            if text.startswith("/"):
                commands.append(text.split()[0].split("@")[0].lower())
        if first_poll and self._offset is None:
            self._offset = 0
        return commands
