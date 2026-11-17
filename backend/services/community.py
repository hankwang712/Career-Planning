"""社区（Offer 茶水间）：帖子、回复、点赞与浏览计数。

帖子存放在应用数据库中；所有读改写都经过 COMMUNITY_FORUM_LOCK 串行化。
"""
import logging
import re
import threading
import time
import uuid
from functools import wraps

from flask import Blueprint, jsonify, request

from . import db as _app_db

logger = logging.getLogger(__name__)

COMMUNITY_FORUM_BOARD_OPTIONS = ("面经互助", "简历门诊", "实习内推", "选岗热议", "职场日常")
COMMUNITY_FORUM_LOCK = threading.Lock()


def _forum_clean_text(value, limit=800):
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _forum_clean_content(value, limit):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()[:limit]


def _forum_transaction(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        with COMMUNITY_FORUM_LOCK:
            return view_func(*args, **kwargs)
    return wrapped


def _public_forum_author(author):
    author = author if isinstance(author, dict) else {}
    display = str(author.get("display_name") or "匿名同学")
    if "@" in display and display == author.get("username"):
        display = "同学"
    return {"display_name": display,
            "is_system": author.get("username") == "system"}


def _forum_slug(seed):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(seed or "").lower())
    return safe[:24] or uuid.uuid4().hex[:10]


def _forum_normalize_tags(raw_tags, limit=4):
    values = raw_tags if isinstance(raw_tags, list) else re.split(r"[#，,、/\s]+", str(raw_tags or ""))
    result = []
    for item in values:
        tag = _forum_clean_text(item, 17).lstrip("#").strip()[:16]
        if not tag or tag in result:
            continue
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def _forum_normalize_author(raw_author, fallback_username="", fallback_display="匿名同学"):
    author = raw_author if isinstance(raw_author, dict) else {}
    username = _forum_clean_text(author.get("username") or fallback_username, 256) or "guest"
    display_name = _forum_clean_text(author.get("display_name") or author.get("displayName") or fallback_display, 32) or "匿名同学"
    return {
        "username": username,
        "display_name": display_name,
    }


def _forum_normalize_reply(raw_reply):
    reply = raw_reply if isinstance(raw_reply, dict) else {}
    content = _forum_clean_content(reply.get("content"), 1200)
    if not content:
        return None
    created_at = int(reply.get("created_at") or time.time())
    return {
        "id": _forum_clean_text(reply.get("id") or f"reply_{uuid.uuid4().hex[:10]}", 32),
        "content": content,
        "created_at": created_at,
        "author": _forum_normalize_author(reply.get("author")),
    }


def _forum_normalize_post(raw_post):
    post = raw_post if isinstance(raw_post, dict) else {}
    title = _forum_clean_text(post.get("title"), 80)
    content = _forum_clean_content(post.get("content"), 2400)
    if not title or not content:
        return None
    board = _forum_clean_text(post.get("board"), 16)
    if board not in COMMUNITY_FORUM_BOARD_OPTIONS:
        board = "选岗热议"
    replies = []
    for item in post.get("replies") or []:
        normalized_reply = _forum_normalize_reply(item)
        if normalized_reply:
            replies.append(normalized_reply)
    replies.sort(key=lambda item: int(item.get("created_at") or 0))
    liked_by = []
    for value in post.get("liked_by") or []:
        username = _forum_clean_text(value, 256)
        if username and username not in liked_by:
            liked_by.append(username)
    created_at = int(post.get("created_at") or time.time())
    updated_at = int(post.get("updated_at") or created_at)
    last_reply_at = int(replies[-1]["created_at"]) if replies else int(post.get("last_reply_at") or updated_at)
    last_reply_user = ""
    if replies:
        last_reply_user = _forum_clean_text(replies[-1].get("author", {}).get("display_name"), 32)
    elif post.get("last_reply_user"):
        last_reply_user = _forum_clean_text(post.get("last_reply_user"), 32)
    return {
        "id": _forum_clean_text(post.get("id") or f"post_{uuid.uuid4().hex[:10]}", 32),
        "title": title,
        "content": content,
        "board": board,
        "tags": _forum_normalize_tags(post.get("tags") or []),
        "author": _forum_normalize_author(post.get("author")),
        "created_at": created_at,
        "updated_at": updated_at,
        "pinned": bool(post.get("pinned")),
        "views": max(0, int(post.get("views") or 0)),
        "liked_by": liked_by,
        "replies": replies,
        "last_reply_at": last_reply_at,
        "last_reply_user": last_reply_user,
    }


def _default_community_forum_payload():
    now = int(time.time())

    def reply(seed, content, author_name, minutes_ago):
        return {
            "id": f"reply_{_forum_slug(seed)}",
            "content": content,
            "created_at": now - minutes_ago * 60,
            "author": {"username": _forum_slug(author_name), "display_name": author_name},
        }

    posts = [
        {
            "id": "post_offer_schedule",
            "title": "暑期实习太晚准备还来得及吗？现在补项目和刷题应该怎么排优先级",
            "content": "我现在大三，前面主要把课上项目做完了，算法和面试准备比较弱。想请教大家，如果目标是暑期实习，接下来两个月应该先补项目包装、刷算法题，还是先把简历改到能投的状态？",
            "board": "面经互助",
            "tags": ["暑期实习", "投递节奏", "项目包装"],
            "author": {"username": "offer_lab", "display_name": "上岸学长"},
            "created_at": now - 5 * 3600,
            "updated_at": now - 35 * 60,
            "pinned": True,
            "views": 286,
            "liked_by": ["system", "23030134", "24110403", "24151007"],
            "replies": [
                reply("offer_schedule_1", "先把简历打磨到可投，再并行补一个能讲清楚指标的项目，这样反馈会更快。", "求职教练", 52),
                reply("offer_schedule_2", "如果算法很薄弱，建议每天固定一小时刷高频题，不要等项目全部做完才开始。", "后端实习生", 35),
            ],
        },
        {
            "id": "post_resume_story",
            "title": "简历里的项目经历怎么写，才能让面试官一眼看到亮点",
            "content": "我发现自己写项目时总是堆技术栈，结果看起来像流水账。有没有比较好的表达结构，比如背景、动作、结果怎么分配篇幅，尤其是实习和课程项目混合在一起的时候。",
            "board": "简历门诊",
            "tags": ["简历修改", "项目经历", "STAR"],
            "author": {"username": "resume_clinic", "display_name": "简历门诊官"},
            "created_at": now - 9 * 3600,
            "updated_at": now - 68 * 60,
            "pinned": False,
            "views": 198,
            "liked_by": ["system", "24110403"],
            "replies": [
                reply("resume_story_1", "把“做了什么”改成“解决了什么问题、怎么做、结果如何”，项目自然就立起来了。", "产品转码同学", 102),
            ],
        },
        {
            "id": "post_city_choice",
            "title": "同样是 AI 产品岗，留在新一线还是去上海北京更合适",
            "content": "目前拿到了两个方向接近的机会，一个在杭州，一个在上海。薪资差距不算特别大，但我更纠结成长密度、导师带教和岗位后续发展空间，想听听大家怎么判断。",
            "board": "选岗热议",
            "tags": ["城市选择", "AI产品", "offer对比"],
            "author": {"username": "decision_lab", "display_name": "Offer 观察员"},
            "created_at": now - 18 * 3600,
            "updated_at": now - 2 * 3600,
            "pinned": False,
            "views": 324,
            "liked_by": ["system", "23030134", "24030115"],
            "replies": [
                reply("city_choice_1", "如果你现在更缺方法论，优先看团队带教和业务密度；城市本身反而是第二层因素。", "AI产品新人", 205),
                reply("city_choice_2", "同薪资区间下，先比较岗位能不能让你讲出更强的成长故事。", "运营转产品", 126),
            ],
        },
        {
            "id": "post_referral_tips",
            "title": "找内推时，私信应该怎么写才不会让人觉得唐突",
            "content": "最近想主动联系校友和脉脉上的前辈争取内推，但总担心表达太生硬。大家一般会怎么写第一条消息，既礼貌又能让对方快速判断是否愿意帮忙？",
            "board": "实习内推",
            "tags": ["内推", "私信模板", "校友"],
            "author": {"username": "network_helper", "display_name": "求职小助手"},
            "created_at": now - 27 * 3600,
            "updated_at": now - 11 * 3600,
            "pinned": False,
            "views": 154,
            "liked_by": ["system"],
            "replies": [],
        },
    ]
    return {"posts": posts}


def _load_community_forum_store():
    stored = _app_db.load_community_forum()
    created = not isinstance(stored, dict)
    payload = stored if isinstance(stored, dict) else _default_community_forum_payload()
    posts = []
    for item in payload.get("posts") or []:
        normalized_post = _forum_normalize_post(item)
        if normalized_post:
            posts.append(normalized_post)
    normalized = {"posts": posts}
    if created:
        _app_db.save_community_forum(normalized)
    return normalized


def _save_community_forum_store(payload):
    normalized = {"posts": []}
    for item in (payload or {}).get("posts") or []:
        normalized_post = _forum_normalize_post(item)
        if normalized_post:
            normalized["posts"].append(normalized_post)
    _app_db.save_community_forum(normalized)
    return normalized


def _find_community_forum_post(payload, post_id):
    normalized_id = _forum_clean_text(post_id, 32)
    for item in (payload or {}).get("posts") or []:
        if item.get("id") == normalized_id:
            return item
    return None


def _public_community_forum_reply(raw_reply):
    reply = _forum_normalize_reply(raw_reply) or {}
    return {
        "id": str(reply.get("id") or ""),
        "content": str(reply.get("content") or ""),
        "created_at": int(reply.get("created_at") or 0),
        "author": _public_forum_author(reply.get("author")),
    }


def _public_community_forum_post(raw_post, user=None):
    post = _forum_normalize_post(raw_post) or {}
    replies = [_public_community_forum_reply(item) for item in post.get("replies") or []]
    current_username = str((user or {}).get("username") or "").strip()
    liked_by = post.get("liked_by") or []
    return {
        "id": str(post.get("id") or ""),
        "title": str(post.get("title") or ""),
        "content": str(post.get("content") or ""),
        "board": str(post.get("board") or ""),
        "tags": post.get("tags") or [],
        "author": _public_forum_author(post.get("author")),
        "created_at": int(post.get("created_at") or 0),
        "updated_at": int(post.get("updated_at") or 0),
        "pinned": bool(post.get("pinned")),
        "views": int(post.get("views") or 0),
        "likes": len(liked_by),
        "liked": bool(current_username and current_username in liked_by),
        "reply_count": len(replies),
        "replies": replies,
        "last_reply_at": int(post.get("last_reply_at") or post.get("updated_at") or 0),
        "last_reply_user": replies[-1]["author"]["display_name"] if replies else "",
    }


def _community_forum_payload(user=None):
    store = _load_community_forum_store()
    posts = [_public_community_forum_post(item, user) for item in store.get("posts") or []]
    posts.sort(key=lambda item: (not item.get("pinned"), -int(item.get("updated_at") or 0), -int(item.get("created_at") or 0)))
    board_counts = {"all": len(posts)}
    tag_counts = {}
    for post in posts:
        board = str(post.get("board") or "选岗热议")
        board_counts[board] = board_counts.get(board, 0) + 1
        for tag in post.get("tags") or []:
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    hot_tags = [
        {"tag": key, "count": value}
        for key, value in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    now = int(time.time())
    stats = {
        "threads": len(posts),
        "today_posts": sum(1 for item in posts if now - int(item.get("created_at") or 0) <= 24 * 3600),
        "active_users": len({str(item["author"]["username"]) for post in store.get("posts", [])
                             for item in [post, *(post.get("replies") or [])]
                             if (item.get("author") or {}).get("username")}),
        "unanswered": sum(1 for item in posts if not int(item.get("reply_count") or 0)),
    }
    boards = [{"key": "all", "label": "全部", "count": board_counts.get("all", 0)}]
    for board in COMMUNITY_FORUM_BOARD_OPTIONS:
        boards.append({"key": board, "label": board, "count": board_counts.get(board, 0)})
    return {
        "boards": boards,
        "hot_tags": hot_tags,
        "stats": stats,
        "posts": posts,
    }


def create_blueprint(login_required, super_admin_required, current_user):
    blueprint = Blueprint("community", __name__)

    @blueprint.route("/api/community-feed", methods=["GET"])
    @login_required
    @_forum_transaction
    def api_community_feed():
        return jsonify(_community_forum_payload(current_user()))


    @blueprint.route("/api/community-feed/posts", methods=["POST"])
    @login_required
    @_forum_transaction
    def api_community_feed_create_post():
        user = current_user()
        payload = request.get_json(silent=True) or {}
        title = _forum_clean_text(payload.get("title"), 80)
        content = _forum_clean_content(payload.get("content"), 2400)
        board = _forum_clean_text(payload.get("board"), 16)
        tags = _forum_normalize_tags(payload.get("tags") or [])
        if len(title) < 4:
            return jsonify({"message": "帖子标题至少需要 4 个字。"}), 400
        if len(content) < 10:
            return jsonify({"message": "帖子内容至少需要 10 个字。"}), 400
        if board not in COMMUNITY_FORUM_BOARD_OPTIONS:
            board = "选岗热议"

        store = _load_community_forum_store()
        now = int(time.time())
        store.setdefault("posts", []).insert(0, {
            "id": f"post_{uuid.uuid4().hex[:10]}",
            "title": title,
            "content": content,
            "board": board,
            "tags": tags,
            "author": {
                "username": user["username"],
                "display_name": user.get("display_name") or user.get("displayName") or user["username"],
            },
            "created_at": now,
            "updated_at": now,
            "pinned": False,
            "views": 1,
            "liked_by": [],
            "replies": [],
            "last_reply_at": now,
            "last_reply_user": "",
        })
        store = _save_community_forum_store(store)
        created_post = _public_community_forum_post(store["posts"][0], user)
        return jsonify({"message": "帖子已发布。", "post": created_post, "feed": _community_forum_payload(user)})


    @blueprint.route("/api/community-feed/posts/<post_id>", methods=["DELETE"])
    @super_admin_required
    @_forum_transaction
    def api_community_feed_delete_post(post_id):
        """The one thing an administrator can do: remove a post (and its replies)."""
        user = current_user()
        store = _load_community_forum_store()
        posts = store.get("posts") if isinstance(store.get("posts"), list) else []
        remaining = [post for post in posts if str((post or {}).get("id") or "") != str(post_id)]
        if len(remaining) == len(posts):
            return jsonify({"message": "未找到对应帖子。"}), 404
        store["posts"] = remaining
        _save_community_forum_store(store)
        logger.info("administrator %s deleted community post %s", user["username"], post_id)
        return jsonify({"message": "帖子已删除。", "feed": _community_forum_payload(user)})


    @blueprint.route("/api/community-feed/posts/<post_id>/reply", methods=["POST"])
    @login_required
    @_forum_transaction
    def api_community_feed_reply(post_id):
        user = current_user()
        payload = request.get_json(silent=True) or {}
        content = _forum_clean_content(payload.get("content"), 1200)
        if len(content) < 4:
            return jsonify({"message": "回复内容至少需要 4 个字。"}), 400

        store = _load_community_forum_store()
        post = _find_community_forum_post(store, post_id)
        if not post:
            return jsonify({"message": "未找到对应帖子。"}), 404

        now = int(time.time())
        post.setdefault("replies", []).append({
            "id": f"reply_{uuid.uuid4().hex[:10]}",
            "content": content,
            "created_at": now,
            "author": {
                "username": user["username"],
                "display_name": user.get("display_name") or user.get("displayName") or user["username"],
            },
        })
        post["updated_at"] = now
        post["last_reply_at"] = now
        post["last_reply_user"] = user.get("display_name") or user.get("displayName") or user["username"]
        store = _save_community_forum_store(store)
        refreshed = _find_community_forum_post(store, post_id)
        return jsonify({"message": "回复已发送。", "post": _public_community_forum_post(refreshed, user), "feed": _community_forum_payload(user)})


    @blueprint.route("/api/community-feed/posts/<post_id>/like", methods=["POST"])
    @login_required
    @_forum_transaction
    def api_community_feed_like(post_id):
        user = current_user()
        store = _load_community_forum_store()
        post = _find_community_forum_post(store, post_id)
        if not post:
            return jsonify({"message": "未找到对应帖子。"}), 404

        username = user["username"]
        liked_by = post.setdefault("liked_by", [])
        if username in liked_by:
            liked_by = [item for item in liked_by if item != username]
            post["liked_by"] = liked_by
            liked = False
        else:
            liked_by.append(username)
            post["liked_by"] = liked_by
            liked = True
        post["updated_at"] = int(time.time())
        store = _save_community_forum_store(store)
        refreshed = _find_community_forum_post(store, post_id)
        public_post = _public_community_forum_post(refreshed, user)
        return jsonify({"message": "已更新点赞状态。", "liked": liked, "post": public_post})


    @blueprint.route("/api/community-feed/posts/<post_id>/view", methods=["POST"])
    @login_required
    @_forum_transaction
    def api_community_feed_view(post_id):
        user = current_user()
        store = _load_community_forum_store()
        post = _find_community_forum_post(store, post_id)
        if not post:
            return jsonify({"message": "未找到对应帖子。"}), 404
        post["views"] = max(0, int(post.get("views") or 0)) + 1
        store = _save_community_forum_store(store)
        refreshed = _find_community_forum_post(store, post_id)
        return jsonify({"message": "浏览次数已记录。", "post": _public_community_forum_post(refreshed, user)})

    return blueprint
