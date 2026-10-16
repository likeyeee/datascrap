from scout.crawler import cn, extract
from scout.crawler.products import parse_shopify_atom
from scout.domains import normalize


def test_normalize():
    assert normalize("https://www.Shop.example.co.uk/path?x=1") == "example.co.uk"
    assert normalize("abc.myshopify.com") == "abc.myshopify.com"
    assert normalize("https://www.abc.myshopify.com/") == "abc.myshopify.com"
    assert normalize("not a url") is None
    assert normalize("") is None
    # 平台基础设施和模板演示子域名
    for infra in ("img-va.myshopline.com", "cdn-files.myshopline.com", "layout-assets-virginia.myshopline.com",
                  "front.myshopline.com", "flash-theme.myshoplaza.com", "fraud-demo-store.myshopline.com"):
        assert normalize(infra) is None, infra
    assert normalize("frontier-gear.myshopify.com") == "frontier-gear.myshopify.com"
    assert normalize("apparelhub.myshopify.com") == "apparelhub.myshopify.com"


def test_platform_detection():
    assert extract.detect_platform('<script src="https://cdn.shopify.com/x.js"></script>', {}) == "shopify"
    assert extract.detect_platform("<html>shoplazza cdn.shopify.com</html>", {}) == "shoplazza"
    assert extract.detect_platform("<html></html>", {"x-shopid": "1"}) == "shopify"
    assert extract.detect_platform("<html>hello</html>", {}) is None


def test_marketing_and_socials():
    html = """<script>fbq('init','1');</script><script src="https://analytics.tiktok.com/i18n/pixel"></script>
    <a href="https://www.instagram.com/mybrand/">IG</a><a href="https://www.facebook.com/sharer.php?u=x">share</a>
    <a href="https://www.facebook.com/mybrandpage">FB</a><script src="//static.klaviyo.com/onsite.js"></script>"""
    mk = extract.detect_marketing(html)
    assert "Meta 广告像素" in mk["ads"] and "TikTok 广告像素" in mk["ads"]
    assert mk["email_sms"] == ["Klaviyo"]
    so = extract.extract_socials(html)
    assert so["instagram"].endswith("/mybrand")
    assert so["facebook"].endswith("/mybrandpage")


def test_contacts():
    html = 'Mail: hello@brand.com, junk@2x.png, email@exaple.com <a href="mailto:a.zhang@qq.com">x</a>'
    assert extract.extract_emails(html) == ["hello@brand.com", "a.zhang@qq.com"]
    phones = extract.extract_phones("Call (626) 555-1234 or +86 138 1234 5678")
    assert "+1 (626) 555-1234" in phones and any(p.startswith("+86") for p in phones)
    addrs = extract.extract_us_addresses("Our warehouse: 123 Main St, City of Industry, CA 91748")
    assert addrs[0]["zip"] == "91748" and addrs[0]["city"].endswith("City of Industry")


def test_chinese_chars_ignore_language_switcher():
    n, _ = extract.count_chinese_chars("<option>简体中文</option><option>English</option>")
    assert n == 0
    n, sample = extract.count_chinese_chars("<p>页尾菜单</p>")
    assert n == 4 and sample.startswith("页尾")


def test_shopify_base_currency():
    assert extract.shopify_base_currency('Shopify.currency = {"active":"USD","rate":"1.0"};') == "USD"
    # 访问者地区换算后的币种不是店铺本币
    assert extract.shopify_base_currency('Shopify.currency = {"active":"JPY","rate":"151.2"};') is None
    assert extract.shopify_base_currency("<html></html>") is None


def test_atom_parse():
    xml = """<feed><entry><title>Dog Bowl</title><s:type>Pet</s:type><s:vendor>Acme</s:vendor>
    <published>2026-01-01T00:00:00-05:00</published><updated>2026-02-01T00:00:00-05:00</updated>
    <s:variant><s:price currencyCode="USD">15.00</s:price></s:variant></entry></feed>"""
    items = parse_shopify_atom(xml)
    assert items[0]["title"] == "Dog Bowl" and items[0]["price"] == 15.0 and items[0]["type"] == "Pet"


def test_names_and_surnames():
    names = cn.find_names("Hi, I'm Wei Zhang, the founder of this shop. Tim Brown, Co-Founder. Meet our team.")
    assert "Wei Zhang" in names
    assert "Tim Brown" in names
    assert cn.classify_surname("Zhang") == "strong"
    assert cn.classify_surname("Lee") == "weak"
    assert cn.classify_surname("Brown") is None


def test_cn_analysis_china_seller():
    res = cn.analyze({
        "platform": "shoplazza", "html": "<script>17track</script>", "text": "",
        "pages_text": {"terms": "Operated by Shenzhen Abc Technology Co., Ltd. Address: Room 1, Nanshan District, Shenzhen",
                       "shipping": "Orders ship from China and arrive in 7-15 business days."},
        "emails": ["service@163.com"], "phones": ["+86 138 1234 5678"], "us_addresses": [], "meta": {},
        "ns": ["vip3.alidns.com"], "rdap": {"registrar": "Alibaba Cloud Computing Ltd.", "registrant_country": "CN"},
        "cn_chars": (0, ""), "cn_source_chars": (0, ""),
    })
    keys = {s["signal"] for s in res.signals}
    assert {"cn_platform", "cn_dns", "cn_registrar", "registrant_cn", "cn_contact", "cn_company",
            "ships_from_china"} <= keys
    assert res.score == 100 and res.location == "china"


def test_cn_analysis_us_chinese():
    res = cn.analyze({
        "platform": "shopify", "html": "", "text": "",
        "pages_text": {"about": "Hi, I'm Jenny Chen, founder of this little shop in Walnut, CA."},
        "emails": ["hello@brand.com"], "phones": ["+1 (626) 555-1234"],
        "us_addresses": [{"city": "Walnut", "state": "CA", "zip": "91789"}],
        "meta": {"country": "US", "city": "Walnut"}, "ns": [], "rdap": {},
        "cn_chars": (0, ""), "cn_source_chars": (0, ""),
    })
    keys = {s["signal"] for s in res.signals}
    assert {"surname", "us_cn_hub"} <= keys
    assert res.location == "us"


def test_non_chinese_store_has_low_score():
    res = cn.analyze({
        "platform": "shopify", "html": "", "text": "Founded by Tim Brown in Denver.",
        "pages_text": {}, "emails": ["help@brand.com"], "phones": [], "us_addresses": [],
        "meta": {"country": "US"}, "ns": ["ns1.cloudflare.com"], "rdap": {"registrar": "GoDaddy.com, LLC"},
        "cn_chars": (0, ""), "cn_source_chars": (0, ""),
    })
    assert res.score == 0
