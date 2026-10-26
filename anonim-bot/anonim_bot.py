import html
import json
import logging
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

# =====================================================================
# 1. SOZLAMALAR (CONFIG) — PYTHONANYWHERE VA IPHONE UCHUN TAYYOR
# (Hech qanday "pip install" kerak emas, to'g'ridan-to'g'ri ishlaydi!)
# =====================================================================
BOT_TOKEN = os.environ['BOT_TOKEN']
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "mutawakkl").lstrip("@").lower()
ADMIN_ID_ENV = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv('DB_PATH', 'anonim_bot.db')
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# PythonAnywhere bepul akkauntida proxy avtomatik qo'llaniladi
proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
if proxy_url:
    proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(proxy_handler)
    urllib.request.install_opener(opener)


# =====================================================================
# 2. TELEGRAM API BILAN ISHLASH (STANDART KUTUBXONA — ZERO DEPENDENCY)
# =====================================================================
def tg_request(method: str, payload: Optional[dict] = None) -> Optional[Any]:
    url = f"{API_BASE}/{method}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        clean_payload = {k: v for k, v in payload.items() if v is not None}
        data = json.dumps(clean_payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return body.get("result")
            logger.warning(f"Telegram API xatosi ({method}): {body}")
            return None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        logger.warning(f"HTTP xato ({method}): {e.code} - {err_body}")
        return None
    except Exception as e:
        logger.warning(f"Tarmoq xatosi ({method}): {e}")
        return None


# =====================================================================
# 3. MA'LUMOTLAR BAZASI (SQLITE)
# =====================================================================
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    ref_code TEXT UNIQUE,
                    state TEXT,
                    state_data TEXT,
                    joined_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER,
                    receiver_id INTEGER,
                    bot_msg_id INTEGER,
                    msg_type TEXT,
                    content_preview TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS blocks (
                    blocker_id INTEGER,
                    blocked_id INTEGER,
                    created_at TEXT,
                    PRIMARY KEY (blocker_id, blocked_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            conn.commit()

    def set_setting(self, key: str, value: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            conn.commit()

    def get_setting(self, key: str) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def get_admin_id(self) -> Optional[int]:
        if ADMIN_ID_ENV > 0:
            return ADMIN_ID_ENV
        saved_id = self.get_setting("admin_id")
        if saved_id and saved_id.isdigit():
            return int(saved_id)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM users WHERE LOWER(username) = ?",
                (ADMIN_USERNAME,),
            ).fetchone()
            if row:
                self.set_setting("admin_id", str(row["user_id"]))
                return int(row["user_id"])
        return None

    def register_user(
        self, user_id: int, username: Optional[str], full_name: str
    ) -> str:
        if username and username.lower() == ADMIN_USERNAME:
            self.set_setting("admin_id", str(user_id))

        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT ref_code FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                    (username, full_name, user_id),
                )
                conn.commit()
                return row["ref_code"]

            while True:
                ref_code = (
                    secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
                )
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE ref_code = ?", (ref_code,)
                ).fetchone()
                if not exists:
                    break

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO users (user_id, username, full_name, ref_code, state, state_data, joined_at)
                VALUES (?, ?, ?, ?, NULL, NULL, ?)
                """,
                (user_id, username, full_name, ref_code, now),
            )
            conn.commit()
            return ref_code

    def set_state(
        self,
        user_id: int,
        state: Optional[str],
        state_data: Optional[dict] = None,
    ):
        data_json = json.dumps(state_data) if state_data else None
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET state = ?, state_data = ? WHERE user_id = ?",
                (state, data_json, user_id),
            )
            conn.commit()

    def get_state(self, user_id: int) -> tuple[Optional[str], dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT state, state_data FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None, {}
            data = json.loads(row["state_data"]) if row["state_data"] else {}
            return row["state"], data

    def get_user_by_ref(self, ref_code: str) -> Optional[sqlite3.Row]:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE ref_code = ?", (ref_code,)
            ).fetchone()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

    def save_message(
        self,
        sender_id: int,
        receiver_id: int,
        bot_msg_id: int,
        msg_type: str,
        content_preview: str,
    ) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages (sender_id, receiver_id, bot_msg_id, msg_type, content_preview, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sender_id,
                    receiver_id,
                    bot_msg_id,
                    msg_type,
                    content_preview[:300],
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid

    def get_message_by_id(self, msg_id: int) -> Optional[sqlite3.Row]:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM messages WHERE id = ?", (msg_id,)
            ).fetchone()

    def get_message_by_bot_msg(
        self, receiver_id: int, bot_msg_id: int
    ) -> Optional[sqlite3.Row]:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM messages WHERE receiver_id = ? AND bot_msg_id = ?",
                (receiver_id, bot_msg_id),
            ).fetchone()

    def is_blocked(self, blocker_id: int, blocked_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                (blocker_id, blocked_id),
            ).fetchone()
            return row is not None

    def block_user(self, blocker_id: int, blocked_id: int):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
                (blocker_id, blocked_id, now),
            )
            conn.commit()

    def unblock_all(self, blocker_id: int) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM blocks WHERE blocker_id = ?", (blocker_id,)
            )
            conn.commit()
            return cur.rowcount

    def get_stats(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            today_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)
            ).fetchone()[0]
            total_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            today_msgs = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()[0]
            return {
                "total_users": total_users,
                "today_users": today_users,
                "total_msgs": total_msgs,
                "today_msgs": today_msgs,
            }

    def get_recent_messages(self, limit: int = 10) -> list:
        with self._get_conn() as conn:
            return conn.execute(
                """
                SELECT m.*,
                       s.full_name AS sender_name, s.username AS sender_username,
                       r.full_name AS receiver_name, r.username AS receiver_username
                FROM messages m
                LEFT JOIN users s ON m.sender_id = s.user_id
                LEFT JOIN users r ON m.receiver_id = r.user_id
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def get_all_user_ids(self) -> list[int]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT user_id FROM users").fetchall()
            return [r["user_id"] for r in rows]


db = Database(DB_PATH)


# =====================================================================
# 4. YORDAMCHI FUNKSIYALAR VA TUGMALAR
# =====================================================================
def is_user_admin(user_id: int, username: Optional[str]) -> bool:
    if username and username.lower() == ADMIN_USERNAME:
        db.set_setting("admin_id", str(user_id))
        return True
    admin_id = db.get_admin_id()
    return admin_id is not None and user_id == admin_id


def format_user_info(user_id: int, full_name: str, username: Optional[str]) -> str:
    safe_name = html.escape(full_name or "Noma'lum")
    uname = f" (@{html.escape(username)})" if username else ""
    return f"<a href='tg://user?id={user_id}'>{safe_name}</a>{uname} [<code>{user_id}</code>]"


def get_share_keyboard(bot_username: str, ref_code: str) -> dict:
    link = f"https://t.me/{bot_username}?start={ref_code}"
    share_text = urllib.parse.quote(
        "Menga anonim xabar yuboring! Kim yozgani sir saqlanadi 👇"
    )
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(link)}&text={share_text}"
    return {
        "inline_keyboard": [
            [{"text": "📤 Havolani ulashish", "url": share_url}],
            [{"text": "🔗 Havolamni yangilash", "callback_data": "my_link"}],
        ]
    }


def get_incoming_msg_keyboard(msg_db_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✍️ Javob yozish", "callback_data": f"reply:{msg_db_id}"},
                {"text": "🚫 Bloklash", "callback_data": f"block:{msg_db_id}"},
            ]
        ]
    }


def get_cancel_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "❌ Bekor qilish", "callback_data": "cancel_action"}]
        ]
    }


def get_admin_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Statistika", "callback_data": "admin_stats"},
                {"text": "🕵️ Oxirgi xabarlar", "callback_data": "admin_recent"},
            ],
            [
                {
                    "text": "📢 Rassilka yuborish",
                    "callback_data": "admin_broadcast",
                }
            ],
        ]
    }


def extract_preview(msg: dict) -> tuple[str, str]:
    if "text" in msg:
        return "text", msg["text"]
    caption = msg.get("caption", "")
    if "photo" in msg:
        return "photo", f"[Rasm] {caption}"
    if "video" in msg:
        return "video", f"[Video] {caption}"
    if "voice" in msg:
        return "voice", f"[Ovozli xabar] {caption}"
    if "video_note" in msg:
        return "video_note", "[Yumaloq video]"
    if "sticker" in msg:
        return "sticker", "[Stiker]"
    if "audio" in msg:
        return "audio", f"[Audio] {caption}"
    if "document" in msg:
        return "document", f"[Fayl] {caption}"
    return "other", "[Media]"


def send_content_to_target(
    source_msg: dict,
    target_id: int,
    header_text: str,
    reply_markup: Optional[dict] = None,
) -> Optional[dict]:
    caption_body = html.escape(source_msg.get("caption", ""))
    full_caption = f"{header_text}\n\n{caption_body}".strip()

    if "text" in source_msg:
        text_body = html.escape(source_msg["text"])
        return tg_request(
            "sendMessage",
            {
                "chat_id": target_id,
                "text": f"{header_text}\n\n💬 {text_body}",
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "photo" in source_msg:
        file_id = source_msg["photo"][-1]["file_id"]
        return tg_request(
            "sendPhoto",
            {
                "chat_id": target_id,
                "photo": file_id,
                "caption": full_caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "video" in source_msg:
        return tg_request(
            "sendVideo",
            {
                "chat_id": target_id,
                "video": source_msg["video"]["file_id"],
                "caption": full_caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "voice" in source_msg:
        return tg_request(
            "sendVoice",
            {
                "chat_id": target_id,
                "voice": source_msg["voice"]["file_id"],
                "caption": full_caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "audio" in source_msg:
        return tg_request(
            "sendAudio",
            {
                "chat_id": target_id,
                "audio": source_msg["audio"]["file_id"],
                "caption": full_caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "document" in source_msg:
        return tg_request(
            "sendDocument",
            {
                "chat_id": target_id,
                "document": source_msg["document"]["file_id"],
                "caption": full_caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "animation" in source_msg:
        return tg_request(
            "sendAnimation",
            {
                "chat_id": target_id,
                "animation": source_msg["animation"]["file_id"],
                "caption": full_caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
    elif "video_note" in source_msg:
        tg_request(
            "sendMessage",
            {"chat_id": target_id, "text": header_text, "parse_mode": "HTML"},
        )
        return tg_request(
            "sendVideoNote",
            {
                "chat_id": target_id,
                "video_note": source_msg["video_note"]["file_id"],
                "reply_markup": reply_markup,
            },
        )
    elif "sticker" in source_msg:
        tg_request(
            "sendMessage",
            {"chat_id": target_id, "text": header_text, "parse_mode": "HTML"},
        )
        return tg_request(
            "sendSticker",
            {
                "chat_id": target_id,
                "sticker": source_msg["sticker"]["file_id"],
                "reply_markup": reply_markup,
            },
        )
    else:
        return tg_request(
            "sendMessage",
            {
                "chat_id": target_id,
                "text": f"{header_text}\n\n📎 <i>(Maxsus media xabar)</i>",
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )


def notify_admin_monitor(
    sender_msg: dict, receiver_id: int, is_reply: bool = False
):
    admin_id = db.get_admin_id()
    if not admin_id or receiver_id == admin_id:
        return

    sender = sender_msg["from"]
    s_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
    s_uname = sender.get("username")

    receiver_row = db.get_user(receiver_id)
    r_name = receiver_row["full_name"] if receiver_row else "Foydalanuvchi"
    r_uname = receiver_row["username"] if receiver_row else None

    action_label = (
        "↩️ <b>ANONIM JAVOB (REPLY)</b>"
        if is_reply
        else "📨 <b>YANGI ANONIM XABAR</b>"
    )
    sender_info = format_user_info(sender["id"], s_name, s_uname)
    receiver_info = format_user_info(receiver_id, r_name, r_uname)

    log_header = (
        f"🕵️‍♂️ {action_label}\n"
        f"👤 <b>Kimdan:</b> {sender_info}\n"
        f"🎯 <b>Kimga:</b> {receiver_info}"
    )
    send_content_to_target(
        source_msg=sender_msg, target_id=admin_id, header_text=log_header
    )


# =====================================================================
# 5. XABARLAR VA TUGMALARNI BOSHQARISH
# =====================================================================
def handle_message(msg: dict, bot_username: str):
    if "from" not in msg:
        return
    user = msg["from"]
    user_id = user["id"]
    username = user.get("username")
    full_name = (
        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        or "Foydalanuvchi"
    )

    my_ref_code = db.register_user(user_id, username, full_name)
    my_link = f"https://t.me/{bot_username}?start={my_ref_code}"
    text = msg.get("text", "")

    # 1. /start buyrug'i
    if text.startswith("/start"):
        db.set_state(user_id, None)
        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""

        if args:
            target_user = db.get_user_by_ref(args)
            if not target_user:
                tg_request(
                    "sendMessage",
                    {
                        "chat_id": user_id,
                        "text": (
                            "⚠️ <b>Bunday havola topilmadi yoki eskirgan.</b>\n\n"
                            f"🔗 Sizning shaxsiy anonim havolangiz:\n<code>{my_link}</code>"
                        ),
                        "parse_mode": "HTML",
                        "reply_markup": get_share_keyboard(
                            bot_username, my_ref_code
                        ),
                    },
                )
                return

            target_id = target_user["user_id"]
            if target_id == user_id:
                tg_request(
                    "sendMessage",
                    {
                        "chat_id": user_id,
                        "text": (
                            "ℹ️ <b>Bu sizning shaxsiy havolangiz!</b>\n\n"
                            "Uni do'stlaringizga yuboring yoki Telegram bio / kanalingizga joylang. "
                            "Ular shu havola orqali sizga anonim xabar yoza olishadi:\n\n"
                            f"🔗 <code>{my_link}</code>"
                        ),
                        "parse_mode": "HTML",
                        "reply_markup": get_share_keyboard(
                            bot_username, my_ref_code
                        ),
                    },
                )
                return

            if db.is_blocked(blocker_id=target_id, blocked_id=user_id):
                tg_request(
                    "sendMessage",
                    {
                        "chat_id": user_id,
                        "text": "🚫 Kechirasiz, ushbu foydalanuvchi sizni bloklagan.",
                    },
                )
                return

            db.set_state(
                user_id,
                "waiting_for_anon_message",
                {"target_id": target_id, "target_ref": args},
            )
            tg_request(
                "sendMessage",
                {
                    "chat_id": user_id,
                    "text": (
                        "💌 <b>Anonim xabar yuborish</b>\n\n"
                        "Shu yerga xabaringizni yozing (matn, rasm, video, ovozli xabar yoki stiker yuborishingiz mumkin).\n"
                        "🔒 <i>Kim yozgani qabul qiluvchiga mutlaqo ko'rinmaydi!</i>"
                    ),
                    "parse_mode": "HTML",
                    "reply_markup": get_cancel_keyboard(),
                },
            )
            return

        admin_badge = ""
        if is_user_admin(user_id, username):
            admin_badge = (
                "\n\n👑 <b>Siz bot admini sifatida ro'yxatga olindingiz!</b>\n"
                "Barcha foydalanuvchilarning yozishmalari avtomatik sizga kelib turadi. "
                "Admin panelga kirish: /admin"
            )

        tg_request(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    f"👋 Salom, <b>{html.escape(full_name)}</b>!\n\n"
                    "📬 Bu bot orqali do'stlaringiz va obunachilaringizdan <b>anonim xabarlar</b> qabul qilishingiz "
                    "hamda ularga ikki tomonlama javob qaytarishingiz mumkin.\n\n"
                    "🔗 <b>Sizning shaxsiy havolangiz:</b>\n"
                    f"<code>{my_link}</code>\n\n"
                    "📌 <i>Havolani nusxalab o'z profilingizga (Bio), Instagram stories yoki kanalingizga joylang!</i>"
                    f"{admin_badge}"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_share_keyboard(bot_username, my_ref_code),
            },
        )
        return

    # 2. /admin buyrug'i
    if text.startswith("/admin"):
        if not is_user_admin(user_id, username):
            tg_request(
                "sendMessage",
                {
                    "chat_id": user_id,
                    "text": "⛔ Bu bo'lim faqat bot admini uchun!",
                },
            )
            return

        stats = db.get_stats()
        tg_request(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    f"👑 <b>Admin Boshqaruv Paneli (@{ADMIN_USERNAME})</b>\n\n"
                    f"👥 Jami foydalanuvchilar: <b>{stats['total_users']}</b> ta (Bugun: +{stats['today_users']})\n"
                    f"💬 Jami anonim xabarlar: <b>{stats['total_msgs']}</b> ta (Bugun: +{stats['today_msgs']})\n\n"
                    "🕵️‍♂️ <i>Eslatma: Botda kim kimga xabar yozsa, barchasi avtomatik tarzda sizga real vaqtda yuborib turiladi.</i>"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_admin_keyboard(),
            },
        )
        return

    # 3. /unblock_all buyrug'i
    if text.startswith("/unblock_all"):
        count = db.unblock_all(user_id)
        tg_request(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": f"✅ Siz bloklagan barcha foydalanuvchilar ({count} ta) blokdan chiqarildi.",
            },
        )
        return

    # 4. Foydalanuvchi holatini (State) tekshirish
    state, state_data = db.get_state(user_id)

    if state == "waiting_for_anon_message":
        target_id = state_data.get("target_id")
        target_ref = state_data.get("target_ref")
        if not target_id:
            db.set_state(user_id, None)
            return

        if db.is_blocked(blocker_id=target_id, blocked_id=user_id):
            db.set_state(user_id, None)
            tg_request(
                "sendMessage",
                {
                    "chat_id": user_id,
                    "text": "🚫 Kechirasiz, ushbu foydalanuvchi sizni bloklagan.",
                },
            )
            return

        msg_type, preview = extract_preview(msg)
        admin_id = db.get_admin_id()

        if admin_id and target_id == admin_id:
            sender_info = format_user_info(user_id, full_name, username)
            header = (
                "📬 <b>Sizga yangi anonim xabar keldi!</b>\n"
                f"🕵️‍♂️ <i>(Admin uchun maxsus: {sender_info})</i>"
            )
        else:
            header = (
                "📬 <b>Sizga yangi anonim xabar keldi!</b>\n"
                "<i>Javob yozish uchun xabarga 'Reply' qiling yoki pastdagi tugmani bosing:</i>"
            )

        sent_msg = send_content_to_target(
            source_msg=msg, target_id=target_id, header_text=header
        )
        if sent_msg and "message_id" in sent_msg:
            msg_db_id = db.save_message(
                sender_id=user_id,
                receiver_id=target_id,
                bot_msg_id=sent_msg["message_id"],
                msg_type=msg_type,
                content_preview=preview,
            )
            tg_request(
                "editMessageReplyMarkup",
                {
                    "chat_id": target_id,
                    "message_id": sent_msg["message_id"],
                    "reply_markup": get_incoming_msg_keyboard(msg_db_id),
                },
            )
            notify_admin_monitor(msg, target_id, is_reply=False)
            db.set_state(user_id, None)

            share_url = f"https://t.me/share/url?url={urllib.parse.quote(my_link)}&text=Menga%20anonim%20xabar%20yuboring!"
            again_kb = {
                "inline_keyboard": [
                    [
                        {
                            "text": "🔄 Yana xabar yuborish",
                            "callback_data": f"write_again:{target_ref}",
                        }
                    ],
                    [{"text": "📤 O'z havolamni ulashish", "url": share_url}],
                ]
            }
            tg_request(
                "sendMessage",
                {
                    "chat_id": user_id,
                    "text": (
                        "✅ <b>Xabaringiz anonim tarzda yetkazildi!</b>\n\n"
                        f"🔗 Sizning shaxsiy havolangiz:\n<code>{my_link}</code>"
                    ),
                    "parse_mode": "HTML",
                    "reply_markup": again_kb,
                },
            )
        else:
            db.set_state(user_id, None)
            tg_request(
                "sendMessage",
                {
                    "chat_id": user_id,
                    "text": "⚠️ Xabarni yetkazib bo'lmadi (qabul qiluvchi botni bloklagan bo'lishi mumkin).",
                },
            )
        return

    if state == "waiting_for_reply":
        reply_target_id = state_data.get("reply_target_id")
        if reply_target_id:
            process_two_way_reply(msg, user_id, full_name, username, reply_target_id)
        return

    if state == "waiting_for_broadcast" and is_user_admin(user_id, username):
        db.set_state(user_id, None)
        user_ids = db.get_all_user_ids()
        sent_count = 0
        failed_count = 0
        for uid in user_ids:
            res = tg_request(
                "copyMessage",
                {
                    "chat_id": uid,
                    "from_chat_id": user_id,
                    "message_id": msg["message_id"],
                },
            )
            if res:
                sent_count += 1
            else:
                failed_count += 1
            time.sleep(0.04)

        tg_request(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    f"✅ <b>Rassilka yakunlandi!</b>\n\n"
                    f"📬 Yetkazildi: <b>{sent_count}</b> ta\n"
                    f"❌ Yetkazilmadi: <b>{failed_count}</b> ta"
                ),
                "parse_mode": "HTML",
            },
        )
        return

    # 5. Bevosita "Reply" (Svo'p) orqali javob berish
    if "reply_to_message" in msg:
        replied_bot_msg_id = msg["reply_to_message"]["message_id"]
        msg_row = db.get_message_by_bot_msg(
            receiver_id=user_id, bot_msg_id=replied_bot_msg_id
        )
        if msg_row:
            process_two_way_reply(
                msg, user_id, full_name, username, msg_row["sender_id"]
            )
            return

    # 6. Oddiy xabar yozilganda shaxsiy havolani eslatish
    tg_request(
        "sendMessage",
        {
            "chat_id": user_id,
            "text": (
                "ℹ️ <b>Kimdirga anonim xabar yuborish uchun uning maxsus havolasi ustiga bosing!</b>\n"
                "<i>(Yoki sizga kelgan xabarga javob berish uchun o'sha xabarga 'Reply' qiling)</i>\n\n"
                f"🔗 Sizning shaxsiy havolangiz:\n<code>{my_link}</code>"
            ),
            "parse_mode": "HTML",
            "reply_markup": get_share_keyboard(bot_username, my_ref_code),
        },
    )


def process_two_way_reply(
    msg: dict,
    sender_id: int,
    sender_name: str,
    sender_uname: Optional[str],
    target_id: int,
):
    if db.is_blocked(blocker_id=target_id, blocked_id=sender_id):
        db.set_state(sender_id, None)
        tg_request(
            "sendMessage",
            {
                "chat_id": sender_id,
                "text": "🚫 Kechirasiz, suhbatdosh sizni bloklagan.",
            },
        )
        return

    msg_type, preview = extract_preview(msg)
    admin_id = db.get_admin_id()

    if admin_id and target_id == admin_id:
        sender_info = format_user_info(sender_id, sender_name, sender_uname)
        header = (
            "🔔 <b>Anonim xabaringizga javob keldi!</b>\n"
            f"🕵️‍♂️ <i>(Admin uchun maxsus: {sender_info})</i>"
        )
    else:
        header = (
            "🔔 <b>Anonim xabaringizga javob keldi!</b>\n"
            "<i>Javob qaytarish uchun xabarga 'Reply' qiling yoki pastdagi tugmani bosing:</i>"
        )

    sent_msg = send_content_to_target(
        source_msg=msg, target_id=target_id, header_text=header
    )
    if sent_msg and "message_id" in sent_msg:
        msg_db_id = db.save_message(
            sender_id=sender_id,
            receiver_id=target_id,
            bot_msg_id=sent_msg["message_id"],
            msg_type=msg_type,
            content_preview=preview,
        )
        tg_request(
            "editMessageReplyMarkup",
            {
                "chat_id": target_id,
                "message_id": sent_msg["message_id"],
                "reply_markup": get_incoming_msg_keyboard(msg_db_id),
            },
        )
        notify_admin_monitor(msg, target_id, is_reply=True)
        db.set_state(sender_id, None)
        tg_request(
            "sendMessage",
            {
                "chat_id": sender_id,
                "text": "✅ <b>Javobingiz yetkazildi!</b>",
                "parse_mode": "HTML",
            },
        )
    else:
        db.set_state(sender_id, None)
        tg_request(
            "sendMessage",
            {"chat_id": sender_id, "text": "⚠️ Javobni yetkazib bo'lmadi."},
        )


def handle_callback(call: dict, bot_username: str):
    call_id = call["id"]
    user = call["from"]
    user_id = user["id"]
    username = user.get("username")
    full_name = (
        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        or "Foydalanuvchi"
    )
    data = call.get("data", "")
    msg = call.get("message", {})
    chat_id = msg.get("chat", {}).get("id", user_id)
    message_id = msg.get("message_id")

    my_ref_code = db.register_user(user_id, username, full_name)
    my_link = f"https://t.me/{bot_username}?start={my_ref_code}"
    if data == "my_link":
        db.set_state(user_id, None)
        tg_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": (
                    "🔗 <b>Sizning shaxsiy anonim havolangiz:</b>\n"
                    f"<code>{my_link}</code>\n\n"
                    "Shu havolani do'stlaringizga ulashing!"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_share_keyboard(bot_username, my_ref_code),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return

    if data == "cancel_action":
        db.set_state(user_id, None)
        tg_request(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": (
                    "❌ <b>Amal bekor qilindi.</b>\n\n"
                    f"🔗 Sizning shaxsiy havolangiz:\n<code>{my_link}</code>"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_share_keyboard(bot_username, my_ref_code),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return

    if data.startswith("write_again:"):
        target_ref = data.split(":", 1)[1]
        target_user = db.get_user_by_ref(target_ref)
        if not target_user:
            tg_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": call_id,
                    "text": "⚠️ Foydalanuvchi topilmadi.",
                    "show_alert": True,
                },
            )
            return

        target_id = target_user["user_id"]
        if db.is_blocked(blocker_id=target_id, blocked_id=user_id):
            tg_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": call_id,
                    "text": "🚫 Ushbu foydalanuvchi sizni bloklagan.",
                    "show_alert": True,
                },
            )
            return

        db.set_state(
            user_id,
            "waiting_for_anon_message",
            {"target_id": target_id, "target_ref": target_ref},
        )
        tg_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": "💌 <b>Yana anonim xabar yuborish:</b>\n\nXabaringizni yozing:",
                "parse_mode": "HTML",
                "reply_markup": get_cancel_keyboard(),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return

    if data.startswith("reply:"):
        msg_db_id = int(data.split(":", 1)[1])
        msg_row = db.get_message_by_id(msg_db_id)
        if not msg_row:
            tg_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": call_id,
                    "text": "⚠️ Bu xabar bazadan topilmadi.",
                    "show_alert": True,
                },
            )
            return

        target_sender_id = msg_row["sender_id"]
        if db.is_blocked(blocker_id=target_sender_id, blocked_id=user_id):
            tg_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": call_id,
                    "text": "🚫 Suhbatdosh sizni bloklagan.",
                    "show_alert": True,
                },
            )
            return

        db.set_state(
            user_id, "waiting_for_reply", {"reply_target_id": target_sender_id}
        )
        tg_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": "✍️ <b>Javobingizni yozing</b> (matn, rasm, ovozli xabar yoki video yuborishingiz mumkin):",
                "parse_mode": "HTML",
                "reply_markup": get_cancel_keyboard(),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return

    if data.startswith("block:"):
        msg_db_id = int(data.split(":", 1)[1])
        msg_row = db.get_message_by_id(msg_db_id)
        if not msg_row:
            tg_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": call_id,
                    "text": "⚠️ Xabar topilmadi.",
                    "show_alert": True,
                },
            )
            return

        db.block_user(blocker_id=user_id, blocked_id=msg_row["sender_id"])
        tg_request(
            "answerCallbackQuery",
            {
                "callback_query_id": call_id,
                "text": "🚫 Xabar egasi bloklandi! (/unblock_all — blokdan chiqarish)",
                "show_alert": True,
            },
        )
        return

    if data == "admin_stats" and is_user_admin(user_id, username):
        stats = db.get_stats()
        tg_request(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": (
                    "📊 <b>Bot Statistikasi:</b>\n\n"
                    f"👥 Jami foydalanuvchilar: <b>{stats['total_users']}</b> ta\n"
                    f"🆕 Bugun qo'shilganlar: <b>{stats['today_users']}</b> ta\n"
                    f"📨 Jami yuborilgan xabarlar: <b>{stats['total_msgs']}</b> ta\n"
                    f"📅 Bugungi xabarlar: <b>{stats['today_msgs']}</b> ta"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_admin_keyboard(),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return

    if data == "admin_recent" and is_user_admin(user_id, username):
        recent = db.get_recent_messages(limit=10)
        if not recent:
            tg_request(
                "answerCallbackQuery",
                {
                    "callback_query_id": call_id,
                    "text": "Hozircha xabarlar yo'q.",
                    "show_alert": True,
                },
            )
            return

        lines = ["🕵️‍♂️ <b>Oxirgi 10 ta yozishma tarixi:</b>\n"]
        for row in recent:
            s_info = format_user_info(
                row["sender_id"], row["sender_name"], row["sender_username"]
            )
            r_info = format_user_info(
                row["receiver_id"],
                row["receiver_name"],
                row["receiver_username"],
            )
            preview = html.escape(row["content_preview"] or "")
            lines.append(
                f"🔹 <b>#{row['id']}</b> ({row['created_at']})\n"
                f"   👤 Kimdan: {s_info}\n"
                f"   🎯 Kimga: {r_info}\n"
                f"   💬 Xabar: <i>{preview}</i>\n"
            )
        tg_request(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
                "reply_markup": get_admin_keyboard(),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return

    if data == "admin_broadcast" and is_user_admin(user_id, username):
        db.set_state(user_id, "waiting_for_broadcast")
        tg_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": (
                    "📢 <b>Rassilka xabarini yuboring:</b>\n\n"
                    "Barcha foydalanuvchilarga yuboriladigan matn, rasm yoki videoni kiriting:"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_cancel_keyboard(),
            },
        )
        tg_request("answerCallbackQuery", {"callback_query_id": call_id})
        return


# =====================================================================
# 6. ASOSIY ISHGA TUSHIRISH SIKLI (LONG POLLING)
# =====================================================================
def main():
    me = tg_request("getMe")
    if not me:
        logger.error("Bot tokeni noto'g'ri yoki internet aloqasi yo'q!")
        return

    bot_username = me.get("username", "")
    logger.info(
        f"Anonim bot (@{bot_username}) muvaffaqiyatli ishga tushdi! Admin: @{ADMIN_USERNAME}"
    )

    offset = 0
    while True:
        try:
            updates = tg_request(
                "getUpdates", {"offset": offset, "timeout": 25}
            )
            if updates:
                for upd in updates:
                    offset = upd["update_id"] + 1
                    if "message" in upd:
                        handle_message(upd["message"], bot_username)
                    elif "callback_query" in upd:
                        handle_callback(upd["callback_query"], bot_username)
        except KeyboardInterrupt:
            logger.info("Bot to'xtatildi.")
            break
        except Exception as e:
            logger.error(f"Polling xatosi: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()