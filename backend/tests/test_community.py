"""社区：发帖、回复、点赞、浏览计数、管理员删帖与作者信息保护。"""
import pytest

from services import community, db

TITLE = "第一次面试前应该准备什么"
BODY = "想听听大家的经验，面试前一周到底该准备哪些内容？"


def create_post(account, **overrides):
    payload = {"title": TITLE, "content": BODY, "board": "面经互助", "tags": ["面试", "#经验"], **overrides}
    return account.post("/api/community-feed/posts", json=payload)


def find(feed, post_id):
    return next(post for post in feed["posts"] if post["id"] == post_id)


def test_create_post_appears_in_the_feed(make_account):
    account = make_account("poster")
    response = create_post(account)
    assert response.status_code == 200
    post = response.get_json()["post"]
    assert post["title"] == TITLE and post["board"] == "面经互助"
    assert set(post["tags"]) == {"面试", "经验"}
    feed = account.get("/api/community-feed").get_json()
    assert find(feed, post["id"])["content"] == BODY
    assert feed["boards"][0] == {"key": "all", "label": "全部", "count": feed["boards"][0]["count"]}


@pytest.mark.parametrize("overrides,fragment", [({"title": "短"}, "标题"), ({"content": "太短了"}, "内容")])
def test_post_validation(make_account, overrides, fragment):
    response = create_post(make_account("validator"), **overrides)
    assert response.status_code == 400
    assert fragment in response.get_json()["message"]


def test_unknown_board_falls_back_to_default(make_account):
    post = create_post(make_account("boards"), board="不存在的板块").get_json()["post"]
    assert post["board"] == "选岗热议"


def test_reply_updates_counts_and_last_reply(make_account):
    author, replier = make_account("author"), make_account("replier")
    post_id = create_post(author).get_json()["post"]["id"]
    response = replier.post(f"/api/community-feed/posts/{post_id}/reply", json={"content": "我的建议是先练项目讲述。"})
    assert response.status_code == 200
    post = response.get_json()["post"]
    assert post["reply_count"] == 1
    assert post["replies"][0]["content"].startswith("我的建议")
    assert post["last_reply_user"] == "replier"
    assert replier.post(f"/api/community-feed/posts/{post_id}/reply", json={"content": "短"}).status_code == 400


def test_like_toggles_per_user(make_account):
    author, fan = make_account("likeauthor"), make_account("fan")
    post_id = create_post(author).get_json()["post"]["id"]
    first = fan.post(f"/api/community-feed/posts/{post_id}/like").get_json()
    assert first["liked"] is True and first["post"]["likes"] == 1
    # 作者自己看到的 liked 状态不受别人点赞影响
    assert find(author.get("/api/community-feed").get_json(), post_id)["liked"] is False
    second = fan.post(f"/api/community-feed/posts/{post_id}/like").get_json()
    assert second["liked"] is False and second["post"]["likes"] == 0


def test_view_counter_increments(make_account):
    account = make_account("viewer")
    post_id = create_post(account).get_json()["post"]["id"]
    before = find(account.get("/api/community-feed").get_json(), post_id)["views"]
    after = account.post(f"/api/community-feed/posts/{post_id}/view").get_json()["post"]["views"]
    assert after == before + 1


@pytest.mark.parametrize("action", ["reply", "like", "view"])
def test_actions_on_missing_posts_return_404(make_account, action):
    account = make_account("missing")
    response = account.post(f"/api/community-feed/posts/does-not-exist/{action}", json={"content": "内容足够长的回复"})
    assert response.status_code == 404


def test_only_super_admin_can_delete_posts(make_account):
    author, admin = make_account("deleter"), make_account("admin")
    post_id = create_post(author).get_json()["post"]["id"]
    # 作者本人也不能删除
    assert author.delete(f"/api/community-feed/posts/{post_id}").status_code == 403
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET role = 'super_admin' WHERE username = ?", (admin.email,))
    assert admin.delete(f"/api/community-feed/posts/does-not-exist").status_code == 404
    assert admin.delete(f"/api/community-feed/posts/{post_id}").status_code == 200
    assert all(post["id"] != post_id for post in author.get("/api/community-feed").get_json()["posts"])


def test_feed_never_exposes_author_email(make_account):
    account = make_account("privacy")
    create_post(account)
    raw = account.get("/api/community-feed").get_data(as_text=True)
    assert account.email not in raw
    assert "password" not in raw.lower()


def test_public_author_hides_email_style_display_names():
    shown = community._public_forum_author({"username": "me@example.com", "display_name": "me@example.com"})
    assert shown == {"display_name": "同学", "is_system": False}
    assert community._public_forum_author({"username": "system", "display_name": "官方"})["is_system"] is True
    assert community._public_forum_author(None)["display_name"] == "匿名同学"


def test_text_cleaning_helpers():
    assert community._forum_clean_text("  多   余\n空白  ", 10) == "多 余 空白"
    assert community._forum_clean_text("x" * 100, 5) == "xxxxx"
    assert community._forum_clean_content("a\x00b\x07c\r\nd", 50) == "abc\nd"
    assert community._forum_normalize_tags("#前端，后端、#前端 面试", limit=3) == ["前端", "后端", "面试"]
    assert community._forum_normalize_tags(["a", "a", "b", "", "c", "d", "e"], limit=4) == ["a", "b", "c", "d"]


def test_anonymous_users_cannot_use_the_forum(client):
    assert client.get("/api/community-feed").status_code == 401
    assert client.post("/api/community-feed/posts", json={"title": TITLE, "content": BODY}).status_code == 401
