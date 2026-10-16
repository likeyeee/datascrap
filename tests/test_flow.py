"""队列、打分、API 的集成测试（LLM 使用模拟客户端）。"""
import asyncio

from fastapi.testclient import TestClient

from scout import worker
from scout.db import Store, session
from scout.domains import add_candidates
from scout.llm import scorer

FAKE_RESULT = {
    "store_name": "Demo",
    "main_products": "宠物碗和宠物玩具",
    "main_categories": ["宠物用品"],
    "promotion_channels": ["Meta广告", "Instagram运营"],
    "chinese": {"type": "在美华人", "confidence": 80, "evidence": ["创始人 Jenny Chen", "地址 Walnut, CA"]},
    "scores": {"warehouse_fit": 80, "product_fit": 90, "chinese_affinity": 95, "scale": 60, "activity": 70,
               "reachability": 80},
    "reasoning": "测试",
    "outreach": {"angle": "海外仓", "recommended_channel": "邮箱", "contact": "hello@demo.com",
                 "opening_line": "Hi Jenny"},
}


class FakeClient:
    def __init__(self):
        self.calls = []

    async def chat_json(self, system, user, **kw):
        self.calls.append((system, user, kw))
        return FAKE_RESULT


def test_add_candidates_dedup_and_blacklist():
    assert add_candidates(["https://www.demo.com/a", "demo.com", "amazon.com", "x.myshopify.com"], "test") == 2
    assert add_candidates(["demo.com"], "other", priority=9) == 0
    with session() as s:
        st = s.query(Store).filter_by(domain="demo.com").one()
        assert st.priority == 9 and st.source == "test"


def test_compute_total_and_grade():
    total, grade = scorer.compute_total(FAKE_RESULT["scores"])
    assert 80 <= total <= 85 and grade == "A"
    assert scorer.compute_total({})[1] == "D"


def test_score_batch_with_fake_llm(monkeypatch):
    monkeypatch.setitem(scorer.settings()["llm"], "review_model", "")
    add_candidates(["demo.com"], "test")
    with session() as s:
        st = s.query(Store).filter_by(domain="demo.com").one()
        st.status = "crawled"
        st.crawl_data = {"pages_text": {"about": "Hi, I'm Jenny Chen"}, "products": [{"title": "Dog Bowl"}]}
        st.cn_signals = [{"signal": "surname", "detail": "华人姓氏：Jenny Chen", "weight": 20}]
    client = FakeClient()
    assert asyncio.run(worker.score_batch(client, 10)) == 1
    with session() as s:
        st = s.query(Store).filter_by(domain="demo.com").one()
        assert st.status == "scored" and st.grade == "A" and st.chinese_type == "在美华人"
    system, user, _ = client.calls[0]
    assert "海外仓" in system and "Jenny Chen" in user


def test_save_crawl_alias_and_dead():
    add_candidates(["abc.myshopify.com", "dead.com"], "test")
    with session() as s:
        a = s.query(Store).filter_by(domain="abc.myshopify.com").one().id
        d = s.query(Store).filter_by(domain="dead.com").one().id
    worker.save_crawl(a, {"status": "alias", "alias_of": "realbrand.com", "domain": "abc.myshopify.com"})
    worker.save_crawl(d, {"status": "dead", "error": "404"})
    with session() as s:
        assert s.query(Store).filter_by(domain="realbrand.com").one().status == "new"
        assert s.get(Store, d).status == "dead"


def test_platform_root_is_blacklisted():
    assert add_candidates(["myshopline.com", "https://myshopify.com/"], "test") == 0


def test_failed_crawl_backs_off():
    add_candidates(["flaky.com"], "test")
    with session() as s:
        sid = s.query(Store).filter_by(domain="flaky.com").one().id
    assert worker._claim("new", "crawling", 10) == [sid]
    worker.save_crawl(sid, {"status": "failed", "error": "timeout"})
    with session() as s:
        st = s.get(Store, sid)
        assert st.status == "new" and st.retry_at is not None
    assert worker._claim("new", "crawling", 10) == []   # 退避期内不会被再次领取


SYSTEM = {"X-Token": "test-system-token-0123456789"}


def _scored(domain: str, **kw) -> int:
    add_candidates([domain], "test")
    with session() as s:
        st = s.query(Store).filter_by(domain=domain).one()
        st.status, st.grade, st.total_score = "scored", kw.get("grade", "A"), kw.get("score", 80)
        st.main_categories, st.chinese_type = kw.get("cats", ["宠物用品"]), kw.get("cn", "在美华人")
        st.crawl_data = {"products": []}
        return st.id


def _client_as(username: str, password: str = "password123"):
    from scout.api import app
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
    return c


def test_first_admin_setup_and_login():
    from scout.api import app
    c = TestClient(app)
    assert c.get("/api/auth/state").json()["needs_setup"] is True
    bad = c.post("/api/auth/setup", json={"system_token": "wrong", "username": "boss", "password": "password123"})
    assert bad.status_code == 403
    ok = c.post("/api/auth/setup", json={"system_token": SYSTEM["X-Token"], "username": "Boss", "password": "password123"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "admin"
    assert c.get("/api/auth/me").json()["username"] == "boss"          # 用户名统一小写，且已登录
    assert c.post("/api/auth/setup", json={"system_token": SYSTEM["X-Token"], "username": "x",
                                           "password": "password123"}).status_code == 400   # 只能初始化一次
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"username": "boss", "password": "nope"}).status_code == 400


def test_roles_and_permissions():
    from scout import auth
    from scout.api import app
    auth.create_user("admin1", "password123", "admin")
    auth.create_user("lily", "password123", "user")
    anon = TestClient(app)
    assert anon.get("/api/stores").status_code == 401
    assert anon.get("/api/admin/monitor").status_code == 401
    lily = _client_as("lily")
    assert lily.get("/api/admin/monitor").status_code == 403
    assert lily.get("/api/stores?status=new").status_code == 403         # 成员只能看已打分线索
    admin = _client_as("admin1")
    m = admin.get("/api/admin/monitor").json()
    assert {"queue", "throughput", "workers", "sources"} <= set(m)
    # 默认的弱系统令牌不被接受
    assert TestClient(app).get("/api/stats", headers={"X-Token": "change-me"}).status_code == 401
    assert TestClient(app).get("/api/admin/users", headers=SYSTEM).status_code == 200


def test_claim_followups_and_ownership():
    from scout import auth
    auth.create_user("lily", "password123")
    auth.create_user("tom", "password123")
    sid = _scored("pets.com")
    lily, tom = _client_as("lily"), _client_as("tom")
    # 推进状态即自动认领
    assert lily.patch(f"/api/stores/{sid}", json={"outreach_status": "已联系"}).json()["ok"]
    detail = lily.get(f"/api/stores/{sid}").json()
    assert detail["owner"] and detail["can_edit"]
    # 其他成员不能修改已被认领的线索，但可以加星标
    assert tom.patch(f"/api/stores/{sid}", json={"outreach_status": "洽谈中"}).status_code == 403
    assert tom.post(f"/api/stores/{sid}/claim").status_code == 403
    assert tom.patch(f"/api/stores/{sid}", json={"starred": True}).json()["ok"]
    assert lily.post(f"/api/stores/{sid}/followups", json={"content": "发了邮件"}).json()["ok"]
    actions = [f["action"] for f in lily.get(f"/api/stores/{sid}/followups").json()]
    assert {"status", "claim", "note"} <= set(actions)
    mine = lily.get("/api/stores?scope=mine").json()
    assert mine["total"] == 1 and mine["items"][0]["outreach_status"] == "已联系"
    assert tom.get("/api/stores?scope=mine").json()["total"] == 0
    assert lily.get("/api/stores?scope=starred").json()["total"] == 1
    assert lily.post(f"/api/stores/{sid}/release").json()["ok"]
    assert tom.post(f"/api/stores/{sid}/claim").json()["ok"]


def test_extension_token_and_endpoints():
    import io
    import zipfile

    from scout import auth
    auth.create_user("lily", "password123")
    _scored("known-shop.com", grade="B", score=66)
    lily = _client_as("lily")
    token = lily.post("/api/auth/token").json()["token"]
    from scout.api import app
    ext = TestClient(app)
    h = {"X-Token": token}
    r = ext.post("/api/ingest", json={"domains": ["https://shop-one.com", "shop-two.com", "known-shop.com"]}, headers=h)
    assert r.json() == {"received": 3, "added": 2}
    found = ext.post("/api/lookup_batch", json={"domains": ["www.known-shop.com", "shop-one.com", "nope.com"]},
                     headers=h).json()
    assert found["www.known-shop.com"]["grade"] == "B" and found["shop-one.com"]["status"] == "new"
    assert "nope.com" not in found
    # 下载插件包会生成新令牌，旧令牌失效
    z = lily.get("/api/extension.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "store-scout-extension/manifest.json" in names and "store-scout-extension/config.js" in names
    assert not any(n.endswith(".py") for n in names)
    preset = zipfile.ZipFile(io.BytesIO(z.content)).read("store-scout-extension/config.js").decode()
    assert '"token": "sk_' in preset
    assert ext.get("/api/lookup?domain=x.com", headers=h).status_code == 401


def test_admin_users_settings_and_bulk():
    from scout import auth
    from scout.config import scoring
    auth.create_user("admin1", "password123", "admin")
    admin = _client_as("admin1")
    assert admin.post("/api/admin/users", json={"username": "newbie", "password": "short"}).status_code == 400
    assert admin.post("/api/admin/users", json={"username": "newbie", "password": "password123"}).json()["ok"]
    users = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    me_id = users["admin1"]["id"]
    assert admin.patch(f"/api/admin/users/{me_id}", json={"active": False}).status_code == 400   # 不能停用自己
    nb = _client_as("newbie")
    assert admin.patch(f"/api/admin/users/{users['newbie']['id']}", json={"active": False}).json()["ok"]
    assert nb.get("/api/auth/me").status_code == 401          # 停用后旧登录立即失效
    # 在线修改打分权重，立即影响总分计算
    cfg = admin.get("/api/admin/settings").json()["scoring"]["value"]
    cfg["dimensions"]["warehouse_fit"]["weight"] = 0
    assert admin.put("/api/admin/settings/scoring", json={"value": cfg}).json()["ok"]
    assert scoring()["dimensions"]["warehouse_fit"]["weight"] == 0
    bad = {"dimensions": {"x": {"weight": "abc"}}, "grades": {}}
    assert admin.put("/api/admin/settings/scoring", json={"value": bad}).status_code == 400
    assert admin.delete("/api/admin/settings/scoring").json()["ok"]
    assert scoring()["dimensions"]["warehouse_fit"]["weight"] == 0.25
    # 批量操作
    sid = _scored("bulk.com")
    assert admin.post("/api/admin/stores/bulk", json={"ids": [sid], "action": "rescore"}).json()["affected"] == 1
    assert admin.post("/api/admin/stores/import", json={"domains": ["a1.com", "a2.com", "a1.com"]}).json()["added"] == 2
    assert admin.post("/api/admin/stores/bulk", json={"ids": [sid], "action": "delete"}).json()["affected"] == 1
    srcs = {s["name"] for s in admin.get("/api/admin/sources").json()}
    assert {"commoncrawl", "crtsh", "outlinks", "search", "manual"} <= srcs


def test_overview_and_export():
    from scout import auth
    auth.create_user("lily", "password123")
    _scored("a.com", grade="A", cats=["宠物用品"])
    _scored("b.com", grade="C", cats=["宠物用品", "厨房用品"], cn="国内跨境卖家")
    lily = _client_as("lily")
    o = lily.get("/api/overview?days=7").json()
    assert o["kpi"]["scored"] == 2 and o["kpi"]["ab"] == 1
    assert o["categories"][0] == {"label": "宠物用品", "value": 2}
    assert len(o["trend"]["discovered"]) == 7
    assert lily.get("/api/stores?category=厨房").json()["total"] == 1     # 中文品类可按文本搜索
    r = lily.get("/api/export?fmt=csv")
    assert r.status_code == 200 and "a.com" in r.content.decode("utf-8-sig")


def test_pages_served():
    from scout.api import app
    c = TestClient(app)
    for path in ("/login", "/app", "/admin", "/static/ui.js", "/static/base.css"):
        assert c.get(path).status_code == 200, path
    assert c.get("/static/ui.js").headers["cache-control"] == "no-cache"
