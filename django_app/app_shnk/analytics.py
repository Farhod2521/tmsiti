"""
Sayt statistikasi (tmsiti.uz/admin -> "Statistika").

Ma'lumot yig'ish:
    POST /api/analytics/collect/   (text/plain JSON — navigator.sendBeacon uchun)
        {"t": "pv", "pid", "vid", "sid", "path", "title", "ref", "entry"}   sahifa ko'rish
        {"t": "ping", "pid", "sec"}                                          sahifada o'tkazilgan vaqt
    Viloyat IP dan aniqlanadi (DB-IP Lite bazasi, `python manage.py geoip_update`), IP o'zi saqlanmaydi.
    Brauzer, qurilma va OS — User-Agent dan. Botlar hisobga olinmaydi.

Hisobot (admin token bilan):
    GET /api/shnq-admin/analytics/?from=YYYY-MM-DD&to=YYYY-MM-DD
"""
import datetime
import json
import os
import re
import threading
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response

from .models import PageView
from .shnq_views import AdminAPIView, _client_ip

# ---------------------------------------------------------------------
#   Viloyat (IP -> ISO 3166-2)
# ---------------------------------------------------------------------
UZ_REGIONS = {
    "UZ-TK": "Toshkent shahri", "UZ-TO": "Toshkent viloyati", "UZ-AN": "Andijon viloyati",
    "UZ-NG": "Namangan viloyati", "UZ-FA": "Farg'ona viloyati", "UZ-SA": "Samarqand viloyati",
    "UZ-BU": "Buxoro viloyati", "UZ-QA": "Qashqadaryo viloyati", "UZ-SU": "Surxondaryo viloyati",
    "UZ-XO": "Xorazm viloyati", "UZ-NW": "Navoiy viloyati", "UZ-JI": "Jizzax viloyati",
    "UZ-SI": "Sirdaryo viloyati", "UZ-QR": "Qoraqalpog'iston Respublikasi",
}
# IP bazalaridagi nomlar turlicha yoziladi ("Tashkent Region", "Samarqand Region", "Fergana", ...)
_REGION_PATTERNS = [
    ("UZ-TO", r"(tashkent|toshkent)\s*(region|province|viloyati|oblast)"),
    ("UZ-TK", r"^(tashkent|toshkent)(\s*(city|shahri|shahar))?$"),
    ("UZ-SA", r"samar"),
    ("UZ-FA", r"ferg|farg"),
    ("UZ-AN", r"andij"),
    ("UZ-NG", r"namang"),
    ("UZ-BU", r"bukh|buxor"),
    ("UZ-QA", r"kashk|qashq"),
    ("UZ-SU", r"surkh|surx"),
    ("UZ-XO", r"khorez|xorazm|khwarez"),
    ("UZ-NW", r"navo"),
    ("UZ-JI", r"jizz|djiz"),
    ("UZ-SI", r"sird|syrd"),
    ("UZ-QR", r"karakal|qoraqal|qaraqal"),
]

_geo_lock = threading.Lock()
_geo_reader = None
_geo_loaded = False


def geoip_path():
    return getattr(settings, "GEOIP_DB_PATH", "") or os.path.join(str(settings.BASE_DIR), "geoip", "dbip-city-lite.mmdb")


def _reader():
    global _geo_reader, _geo_loaded
    if not _geo_loaded:
        with _geo_lock:
            if not _geo_loaded:
                try:
                    import maxminddb

                    path = geoip_path()
                    _geo_reader = maxminddb.open_database(path) if os.path.exists(path) else None
                except Exception:
                    _geo_reader = None
                _geo_loaded = True
    return _geo_reader


def region_code(name):
    n = (name or "").strip().lower().replace("‘", "'").replace("ʻ", "'")
    for code, pattern in _REGION_PATTERNS:
        if re.search(pattern, n):
            return code
    return ""


def locate(ip):
    """(mamlakat ISO kodi, viloyat ISO kodi) — aniqlanmasa bo'sh qatorlar."""
    reader = _reader()
    if not reader or not ip:
        return "", ""
    try:
        rec = reader.get(ip) or {}
    except Exception:
        return "", ""
    country = (rec.get("country") or {}).get("iso_code") or ""
    region = ""
    if country == "UZ":
        for sub in rec.get("subdivisions") or []:
            if sub.get("iso_code"):  # MaxMind bazasida ISO kod bor
                region = f"UZ-{sub['iso_code']}"
            else:  # DB-IP Lite da faqat nom
                region = region_code((sub.get("names") or {}).get("en"))
            if region in UZ_REGIONS:
                break
        if region not in UZ_REGIONS:
            region = region_code(((rec.get("city") or {}).get("names") or {}).get("en"))
    return country, region if region in UZ_REGIONS else ""


# ---------------------------------------------------------------------
#   User-Agent va manba
# ---------------------------------------------------------------------
BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|headless|lighthouse|preview|python|curl|wget|httpclient|java/|go-http|"
    r"facebookexternalhit|telegrambot|whatsapp|monitor|uptime|scrapy|phantom|selenium|puppeteer",
    re.I,
)


def parse_ua(ua):
    ua = ua or ""
    if re.search(r"ipad|tablet|kindle|silk|(android(?!.*mobile))", ua, re.I):
        device = "tablet"
    elif re.search(r"mobi|iphone|ipod|android|windows phone", ua, re.I):
        device = "mobile"
    else:
        device = "desktop"

    if "YaBrowser" in ua or "YaSearchBrowser" in ua:
        browser = "yandex"
    elif "Edg/" in ua or "EdgA/" in ua or "EdgiOS" in ua:
        browser = "edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "opera"
    elif "SamsungBrowser" in ua:
        browser = "samsung"
    elif "Firefox/" in ua or "FxiOS" in ua:
        browser = "firefox"
    elif "Chrome/" in ua or "CriOS" in ua:
        browser = "chrome"
    elif "Safari/" in ua:
        browser = "safari"
    else:
        browser = "other"

    if "Windows" in ua:
        os_name = "windows"
    elif "Android" in ua:
        os_name = "android"
    elif re.search(r"iPhone|iPad|iPod", ua):
        os_name = "ios"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macos"
    elif "Linux" in ua:
        os_name = "linux"
    else:
        os_name = "other"
    return device, browser, os_name


SOURCES = [
    ("google", r"(^|\.)google\."),
    ("yandex", r"(^|\.)(yandex|ya)\.(ru|uz|com|kz)"),
    ("telegram", r"(^|\.)(t\.me|telegram\.(org|me))$"),
    ("instagram", r"(^|\.)instagram\.com$"),
    ("facebook", r"(^|\.)(facebook\.com|fb\.com|m\.facebook\.com)$"),
    ("youtube", r"(^|\.)(youtube\.com|youtu\.be)$"),
    ("bing", r"(^|\.)bing\.com$"),
]


def classify_source(referrer):
    host = (urlparse(referrer).hostname or "").lower() if referrer else ""
    if host.startswith("www."):
        host = host[4:]
    own = getattr(settings, "ANALYTICS_OWN_HOSTS", ["tmsiti.uz"])
    if not host or any(host == h or host.endswith("." + h) for h in own):
        return "direct", ""
    for key, pattern in SOURCES:
        if re.search(pattern, host):
            return key, host
    return "referral", host


# ---------------------------------------------------------------------
#   Ma'lumot qabul qilish
# ---------------------------------------------------------------------
_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,36}$")
RATE_LIMIT_PER_MIN = 240


@csrf_exempt
def collect(request):
    """Tracker so'rovi. Har doim 204 qaytaradi — sayt ishiga ta'sir qilmasligi kerak."""
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        data = json.loads(request.body.decode("utf-8")[:4000] or "{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=204)

    ip = _client_ip(request)
    key = f"an_rate_{ip}_{timezone.now().strftime('%H%M')}"
    hits = cache.get(key, 0)
    if hits > RATE_LIMIT_PER_MIN:
        return HttpResponse(status=204)
    cache.set(key, hits + 1, 70)

    pid = str(data.get("pid") or "")
    if not _ID_RE.match(pid):
        return HttpResponse(status=204)

    if data.get("t") == "ping":
        try:
            sec = max(0, min(int(data.get("sec") or 0), 3600))
        except (TypeError, ValueError):
            sec = 0
        if sec:  # faqat bot filtridan o'tib yozilgan ko'rishning vaqti yangilanadi
            PageView.objects.filter(view_id=pid, duration__lt=sec).update(duration=sec)
        return HttpResponse(status=204)

    ua = request.META.get("HTTP_USER_AGENT", "")
    if not ua or BOT_RE.search(ua):
        return HttpResponse(status=204)

    vid, sid = str(data.get("vid") or ""), str(data.get("sid") or "")
    path = str(data.get("path") or "/").split("?")[0].split("#")[0][:300] or "/"
    if not _ID_RE.match(vid) or not _ID_RE.match(sid) or path.startswith(("/admin", "/__", "/api")):
        return HttpResponse(status=204)

    entry = bool(data.get("entry"))
    source, ref_host = classify_source(str(data.get("ref") or "")) if entry else ("", "")
    country, region = locate(ip)
    device, browser, os_name = parse_ua(ua)
    try:
        PageView.objects.create(
            view_id=pid, visitor_id=vid, session_id=sid, created_at=timezone.now(),
            path=path, title=str(data.get("title") or "")[:300], is_entry=entry,
            source=source or "direct", referrer_host=ref_host[:200],
            country=country, region=region, device=device, browser=browser, os=os_name,
        )
    except IntegrityError:
        pass  # takroriy yuborish
    return HttpResponse(status=204)


# ---------------------------------------------------------------------
#   Hisobot
# ---------------------------------------------------------------------
def _day_start(day):
    dt = datetime.datetime.combine(day, datetime.time.min)
    return timezone.make_aware(dt) if settings.USE_TZ else dt


def _period(start, end):
    return PageView.objects.filter(created_at__gte=_day_start(start), created_at__lt=_day_start(end + datetime.timedelta(days=1)))


def _kpis(qs):
    agg = qs.aggregate(
        pageviews=Count("id"),
        visits=Count("id", filter=Q(is_entry=True)),
        users=Count("visitor_id", distinct=True),
        seconds=Sum("duration"),
    )
    visits = agg["visits"] or 0
    return {
        "visits": visits,
        "users": agg["users"] or 0,
        "pageviews": agg["pageviews"] or 0,
        "avg_duration": round((agg["seconds"] or 0) / visits) if visits else 0,
    }


def _change(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _parse_day(value, default):
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return default


def build_report(start, end):
    qs = _period(start, end)
    entries = qs.filter(is_entry=True)
    days = (end - start).days + 1
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=days - 1)

    cur, prev = _kpis(qs), _kpis(_period(prev_start, prev_end))

    by_day = {
        row["d"]: row
        for row in qs.annotate(d=TruncDate("created_at")).values("d").annotate(
            pageviews=Count("id"),
            visits=Count("id", filter=Q(is_entry=True)),
            users=Count("visitor_id", distinct=True),
            seconds=Sum("duration"),
        )
    }
    daily = []
    for i in range(days):
        d = start + datetime.timedelta(days=i)
        row = by_day.get(d) or {}
        visits = row.get("visits") or 0
        daily.append({
            "date": d.isoformat(),
            "visits": visits,
            "users": row.get("users") or 0,
            "pageviews": row.get("pageviews") or 0,
            "avg_duration": round((row.get("seconds") or 0) / visits) if visits else 0,
        })

    def group(field, base=entries):
        return [
            {"key": r[field], "visits": r["visits"], "users": r["users"]}
            for r in base.values(field).annotate(visits=Count("id"), users=Count("visitor_id", distinct=True)).order_by("-visits")
        ]

    regions_raw = group("region", entries.filter(country="UZ"))
    regions = [
        {"code": r["key"], "name": UZ_REGIONS[r["key"]], "visits": r["visits"], "users": r["users"]}
        for r in regions_raw if r["key"] in UZ_REGIONS
    ]
    region_unknown = sum(r["visits"] for r in regions_raw if r["key"] not in UZ_REGIONS)
    foreign = entries.exclude(country="UZ").exclude(country="").count()
    no_country = entries.filter(country="").count()

    pages = [
        {"path": r["path"], "title": r["title"] or "", "views": r["views"]}
        for r in qs.values("path").annotate(views=Count("id"), title=Max("title")).order_by("-views")[:10]
    ]

    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "days": days,
                  "prev_from": prev_start.isoformat(), "prev_to": prev_end.isoformat()},
        "kpis": {k: {"value": cur[k], "prev": prev[k], "change": _change(cur[k], prev[k])} for k in cur},
        "daily": daily,
        "regions": regions,
        "region_other": {"unknown": region_unknown + no_country, "foreign": foreign},
        "countries": [
            {"code": r["country"], "visits": r["visits"]}
            for r in entries.exclude(country="").exclude(country="UZ").values("country")
            .annotate(visits=Count("id")).order_by("-visits")[:10]
        ],
        "devices": group("device"),
        "browsers": group("browser"),
        "os": group("os"),
        "sources": group("source"),
        "pages": pages,
        "geoip": bool(_reader()),
    }


class AnalyticsReportAPIView(AdminAPIView):
    def get(self, request):
        today = timezone.localdate() if settings.USE_TZ else datetime.date.today()
        end = _parse_day(request.GET.get("to"), today)
        start = _parse_day(request.GET.get("from"), end - datetime.timedelta(days=29))
        if start > end:
            start, end = end, start
        if (end - start).days > 366:
            return Response({"detail": "Davr 1 yildan oshmasligi kerak"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(build_report(start, end))

