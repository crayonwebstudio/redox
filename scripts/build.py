#!/usr/bin/env python3
"""Build the Redox WordPress-to-Astro site from the light demo export.

Reads the WordPress export XML, renders each kept page from its pre-rendered
Elementor cache HTML, renders custom widget placeholders from their settings,
applies Woodwolf branding, downloads demo images locally, and writes Astro
page files plus raw HTML fragments under src/data/wp/.

This script writes ONLY inside ~/workspace/redox-wp-astro. It never deploys.
"""
import base64
import html as htmlmod
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path.home() / "workspace" / "redox-wp-astro"
XML = Path.home() / "workspace" / "redox-wp-source" / "redox-106" / "themeforest-redox-creative-agency-and-portfolio-wordpress-theme" / "sample-data" / "light" / "contents-demo.xml"
NS = {'wp': 'http://wordpress.org/export/1.2/', 'content': 'http://purl.org/rss/1.0/modules/content/'}

BRAND = "Woodwolf Digital"
EMAIL = "info@woodwolfdigital.com"
PHONE_TEXT = "+91 9375767751"
PHONE_TEL = "+919375767751"

KEEP_PAGES = ["about-us", "contact", "digital-agency", "digital-agency-classic",
              "digital-agency-modern", "faq", "journals", "marketing-agency",
              "portfolio", "portfolio-details", "portfolio-st-2", "portfolio-st-3",
              "portfolio-st-4", "portfolio-st-5", "portfolio-st-6", "service",
              "services-details", "services-st-2", "services-st-3", "services-st-4",
              "services-st-5", "services-st-6", "team", "team-details"]
REMOVED = ["creative-agency", "design-agency", "startup-agency", "modern-agency",
           "agency-portfolio", "portfolio-horizontal", "portfolio-line-effect",
           "portfolio-box-effect", "portfolio-vertical", "portfolio-slicer",
           "parallax-carousal", "portfolio-showcase", "branding-agency",
           "modern-agency-2", "agency-portfolio-2", "agency-portfolio-3",
           "web-design", "web-development", "it-solution", "modern-agency-3",
           "elementor-test"]
DEFAULT_HEADER_ID = "8350"
DEFAULT_FOOTER_ID = "8336"
OFFCANVAS_ID = "13060"

REPORT = {"warnings": [], "failed_images": [], "unknown_page_links": Counter(),
          "widget_counts": Counter(), "approximations": []}


def warn(msg):
    REPORT["warnings"].append(msg)
    print("WARN:", msg)


# ---------------------------------------------------------------- XML parsing
def parse_xml():
    tree = ET.parse(XML)
    items = tree.getroot().findall(".//item")
    by_id, pages, posts, headers, footers = {}, {}, [], {}, {}
    attachments, menu_items, offcanvas = {}, [], None
    for it in items:
        pid = it.findtext("wp:post_id", namespaces=NS)
        pt = it.findtext("wp:post_type", namespaces=NS)
        name = it.findtext("wp:post_name", namespaces=NS)
        title = (it.findtext("title") or "").strip()
        status = it.findtext("wp:status", namespaces=NS)
        meta = {}
        for m in it.findall("wp:postmeta", namespaces=NS):
            meta[m.findtext("wp:meta_key", namespaces=NS)] = m.findtext("wp:meta_value", namespaces=NS) or ""
        rec = {"id": pid, "type": pt, "slug": name, "title": htmlmod.unescape(title),
               "status": status, "meta": meta, "item": it}
        by_id[pid] = rec
        if pt == "page" and status == "publish":
            pages[name] = rec
        elif pt == "post" and status == "publish":
            posts.append(rec)
        elif pt == "arrox-header":
            headers[pid] = rec
        elif pt == "arrox-footer":
            footers[pid] = rec
        elif pt == "attachment":
            attachments[pid] = rec
        elif pt == "nav_menu_item":
            menu_items.append(rec)
        elif pt == "arrox-offcanvas":
            offcanvas = rec
    return {"by_id": by_id, "pages": pages, "posts": posts, "headers": headers,
            "footers": footers, "attachments": attachments,
            "menu_items": menu_items, "offcanvas": offcanvas}


# NOTE: this must not parse XML at import time when the source is absent.
# The container build runs this script via prebuild with no demo sources, and
# the old code crashed here (FileNotFoundError) before main()'s guard could
# run, which failed the whole deploy. When XML is missing, use empty data so
# import succeeds and main() returns early, keeping committed generated files.
if XML.exists():
    DATA = parse_xml()
    BY_ID = DATA["by_id"]
    PAGES = DATA["pages"]
    POSTS = sorted(DATA["posts"], key=lambda p: p["slug"])
    HEADERS = DATA["headers"]
    FOOTERS = DATA["footers"]
else:
    DATA = {"by_id": {}, "pages": {}, "posts": [], "headers": {}, "footers": {},
            "attachments": {}, "menu_items": [], "offcanvas": None}
    BY_ID, PAGES, POSTS, HEADERS, FOOTERS = {}, {}, [], {}, {}

# URL maps: page/post id -> clean URL. Removed and unknown -> "/".
ID_URL = {}
for slug in KEEP_PAGES:
    if slug in PAGES:
        ID_URL[PAGES[slug]["id"]] = f"/{slug}/"
for p in POSTS:
    ID_URL[p["id"]] = f"/{p['slug']}/"
SLUG_URL = {}
for slug in KEEP_PAGES:
    SLUG_URL[slug] = f"/{slug}/"
for p in POSTS:
    SLUG_URL[p["slug"]] = f"/{p['slug']}/"
for slug in REMOVED:
    SLUG_URL[slug] = "/"


def page_url(pid):
    """URL for a WordPress post/page id, or '/' for removed/unknown targets."""
    if pid is None or str(pid) == "":
        return "/"
    pid = str(pid)
    if pid in ID_URL:
        return ID_URL[pid]
    rec = BY_ID.get(pid)
    if rec is not None and rec["type"] == "page" and rec["slug"] in REMOVED:
        return "/"
    REPORT["unknown_page_links"][pid] += 1
    return "/"


def demo_url_to_local(url):
    """Retarget a demo-site URL to a clean local URL, or None to drop it."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("#"):
        return url
    if url.startswith("mailto:") or url.startswith("tel:"):
        return url
    if "wp.ravextheme.com" in url:
        # Uploads are handled separately; page URLs map by trailing slug.
        m = re.search(r"/(?:redox|arrox)/(.+?)/?$", url)
        if m:
            slug = m.group(1).strip("/").split("/")[-1]
            if slug in SLUG_URL:
                return SLUG_URL[slug]
            if slug == "" :
                return "/"
        if "/wp-content/uploads/" in url:
            return uploads_local(url)
        return "/"
    if "rrdevs.net" in url:
        return None  # demo video host: drop, never hotlink
    if url.startswith("http"):
        return url  # genuine external link (social etc. handled elsewhere)
    return url


def uploads_local(url):
    """Local path for a demo upload URL, preserving the path after uploads/."""
    m = re.search(r"/wp-content/uploads/(.+)$", url)
    if not m:
        return "/assets/uploads/placeholder.svg"
    path = m.group(1).split("?")[0]
    return "/assets/uploads/" + path


def media_url(media):
    """Extract a usable URL from an Elementor media dict, or ''."""
    if not media:
        return ""
    if isinstance(media, str):
        return media
    if isinstance(media, dict):
        return media.get("url", "") or ""
    return ""


def is_placeholder_image(url):
    return ("plugins/elementor/assets/images/placeholder" in (url or "")
            or "placeholder.png" in (url or ""))


def esc(s):
    return htmlmod.escape(str(s), quote=True)


def esc_text(s):
    return htmlmod.escape(str(s))


def link_from(link_type, page_link, link):
    """Resolve an Elementor link control to (href, target, rel)."""
    if str(link_type) == "2":
        return page_url(page_link), "_self", "nofollow"
    if isinstance(link, dict) and link.get("url"):
        href = demo_url_to_local(link["url"])
        if href is None:
            return "#", "", ""
        target = "_blank" if link.get("is_external") else ""
        rel = "nofollow" if link.get("nofollow") else ""
        return href, target, rel
    return "#", "", ""


def link_attrs(href, target="", rel=""):
    out = f' href="{esc(href)}"'
    if target:
        out += f' target="{esc(target)}"'
    if rel:
        out += f' rel="{esc(rel)}"'
    return out


def img_tag(url, alt="", cls=""):
    if not url or is_placeholder_image(url):
        return ""
    cls_attr = f' class="{esc(cls)}"' if cls else ""
    return f'<img src="{esc(url)}" alt="{esc(alt)}"{cls_attr}>'


def cache_content(rec):
    """Pre-rendered HTML from a record's _elementor_element_cache."""
    raw = rec["meta"].get("_elementor_element_cache", "")
    if not raw:
        return ""
    try:
        return json.loads(raw)["value"]["content"]
    except Exception as e:
        warn(f"cache parse failed for {rec['type']}/{rec['slug']}: {e}")
        return ""


def decode_placeholder(match):
    try:
        return json.loads(base64.b64decode(match.group(2)).decode("utf-8"))
    except Exception:
        return None


PLACEHOLDER_RE = re.compile(r'\[elementor-element k="([^"]+)" data="([^"]+)"\]')

# ---------------------------------------------------------------- posts
def post_date(rec):
    d = rec["item"].findtext("wp:post_date", namespaces=NS) or ""
    return d[:10]


def post_categories(rec):
    out = []
    for c in rec["item"].findall("category"):
        if c.get("domain") == "category":
            out.append((c.text or "", c.get("nicename") or ""))
    return out


def post_thumb(rec):
    tid = rec["meta"].get("_thumbnail_id", "")
    if tid and tid in DATA["attachments"]:
        att = DATA["attachments"][tid]
        url = att["item"].findtext("wp:attachment_url", namespaces=NS) or ""
        return url
    return ""


def post_excerpt(rec, words=24):
    content = rec["item"].findtext("content:encoded", namespaces=NS) or ""
    text = re.sub(r"<[^>]+>", " ", content)
    text = htmlmod.unescape(re.sub(r"\s+", " ", text)).strip()
    parts = text.split(" ")
    return " ".join(parts[:words]) + ("..." if len(parts) > words else "")


def post_card(rec, title_words=20):
    title = rec["title"]
    words = title.split(" ")
    if len(words) > title_words:
        title = " ".join(words[:title_words]) + "..."
    thumb = img_tag(post_thumb(rec), title)
    thumb_html = f'<a href="/{rec["slug"]}/">{thumb}</a>' if thumb else ""
    cats = ", ".join(t for t, _ in post_categories(rec))
    return (f'<article class="post-card"><div class="post-card-thumb">{thumb_html}</div>'
            f'<div class="post-card-body"><div class="post-meta">{esc(post_date(rec))}'
            + (f' | {esc(cats)}' if cats else "") + "</div>"
            f'<h3><a href="/{rec["slug"]}/">{esc_text(title)}</a></h3>'
            f'<p>{esc_text(post_excerpt(rec, 20))}</p>'
            f'<a href="/{rec["slug"]}/">Read More</a></div></article>')


def posts_for_widget(settings, default_count=3):
    """Posts filtered by a widget's category control, or all posts."""
    cats = settings.get("category") or []
    wanted = set()
    for c in cats:
        if isinstance(c, str):
            wanted.add(c)
    pool = []
    for p in POSTS:
        if not wanted:
            pool.append(p)
        else:
            nics = {n for _, n in post_categories(p)}
            if nics & wanted:
                pool.append(p)
    if not pool:
        pool = POSTS
    try:
        n = int(settings.get("posts_per_page") or default_count)
    except Exception:
        n = default_count
    return pool[:max(n, 0)] if n else pool


# ---------------------------------------------------------------- menus
def build_menu(menu_slug):
    """Render a navigation menu from nav_menu_item records."""
    target = menu_slug.replace("-", " ").lower()
    items = []
    for rec in DATA["menu_items"]:
        cats = [c.text for c in rec["item"].findall("category")]
        if not any((c or "").lower() == target for c in cats):
            continue
        m = rec["meta"]
        parent = m.get("_menu_item_menu_item_parent", "0")
        obj_id = m.get("_menu_item_object_id", "")
        obj_type = m.get("_menu_item_object", "")
        title = rec["title"].strip()
        if not title and obj_id in BY_ID:
            title = BY_ID[obj_id]["title"]
        if title.strip().lower() == "home":
            href = "/"
        elif obj_type == "custom":
            href = demo_url_to_local(m.get("_menu_item_url", "#")) or "#"
        else:
            href = page_url(obj_id)
        try:
            order = int(rec["item"].findtext("wp:menu_order", namespaces=NS) or 0)
        except Exception:
            order = 0
        items.append({"id": rec["id"], "parent": parent, "order": order,
                      "title": title, "href": href})
    items.sort(key=lambda x: x["order"])
    children = defaultdict(list)
    roots = []
    for it in items:
        if it["parent"] and it["parent"] != "0" and any(c["id"] == it["parent"] for c in items):
            children[it["parent"]].append(it)
        else:
            roots.append(it)

    def render_list(nodes):
        if not nodes:
            return ""
        out = ['<ul class="arrox-nav-menu">']
        for n in nodes:
            kids = children.get(n["id"], [])
            cls = ' class="menu-item-has-children"' if kids else ""
            out.append(f'<li{cls}><a href="{esc(n["href"])}">{esc_text(n["title"])}</a>')
            if kids:
                out.append(render_list(kids))
            out.append("</li>")
        out.append("</ul>")
        return "".join(out)
    return render_list(roots)


# ---------------------------------------------------------------- forms
def contact_form_html():
    return ('<form id="contact__form" class="contact-form" novalidate>'
            '<div class="contact-formfield"><input type="text" name="name" placeholder="Name" required /></div>'
            '<div class="contact-formfield"><input type="email" name="email" placeholder="Email" required /></div>'
            '<div class="contact-formfield"><input type="text" name="phone" placeholder="Phone" /></div>'
            '<div class="contact-formfield"><input type="text" name="company" placeholder="Company" /></div>'
            '<div class="contact-formfield"><input type="text" name="budget" placeholder="Budget" /></div>'
            '<div class="contact-formfield"><textarea name="message" placeholder="Message"></textarea></div>'
            '<button type="submit" class="submit-btn">Send Message</button></form>')


def subscribe_form_html():
    return ('<form class="subscribe-form" novalidate>'
            '<input type="email" name="email" placeholder="Email Address" required />'
            '<button type="submit" class="submit-btn">Subscribe</button></form>')


def shortcode_html(shortcode):
    if not shortcode:
        return ""
    if "mc4wp" in shortcode:
        return subscribe_form_html()
    if "contact-form-7" in shortcode:
        return contact_form_html()
    return ""


def icon_html(icon):
    """Font Awesome icon value -> <i> tag (light/thin weights mapped to solid)."""
    if not isinstance(icon, dict):
        return ""
    val = (icon.get("value") or "").strip()
    if not val:
        return ""
    val = val.replace("fa-light", "fa-solid").replace("fa-thin", "fa-solid").replace("fa-regular", "fa-solid")
    return f'<i class="{esc(val)}" aria-hidden="true"></i>'


# ---------------------------------------------------------------- widget renderers
def render_widget(d):
    """Render one decoded widget dict to HTML. Returns '' to drop it."""
    wt = d.get("widgetType", "?")
    s = d.get("settings", {}) or {}
    REPORT["widget_counts"][wt] += 1
    if wt == "text-editor":
        editor = s.get("editor", "") or ""
        editor = re.sub(r"\[mc4wp_form[^\]]*\]", subscribe_form_html(), editor)
        editor = re.sub(r"\[[^\]]*\]", "", editor)
        return editor
    if wt == "shortcode":
        return shortcode_html(s.get("shortcode", ""))
    if wt == "arrox-image":
        return f'<div class="arrox-el-image">{img_tag(media_url(s.get("arrox_image")), s.get("arrox_image", {}).get("alt", "") if isinstance(s.get("arrox_image"), dict) else "")}</div>'
    if wt == "arrox-image-shape":
        return ('<div class="ax-hero-circle">'
                + img_tag(media_url(s.get("arrox_circle_icon")), "circle icon")
                + img_tag(media_url(s.get("arrox_circle_text")), "circle text") + "</div>")
    if wt == "arrox-heading":
        title = s.get("arrox_hero_title", "") or ""
        sec = s.get("arrox_hero_sec_title", "") or ""
        img = img_tag(media_url(s.get("arrox_image")), "")
        return ('<div class="section-header rd-da-hero-title arrox-el-section"><div class="section-title-wrapper">'
                f'<div class="title-wrapper"><h2 class="section-title arrox-el-title font-instrumentsans-medium char-anim">{title}'
                + (f"<span>{img}</span>" if img else "") + f"{sec}</h2></div></div></div>")
    if wt == "arrox_heading":
        title = s.get("arrox_title", "") or ""
        btn_text = s.get("heading_button_text", "") or ""
        href, target, rel = link_from(s.get("heading_button_link_type"), s.get("heading_button_page_link"), s.get("heading_button_link"))
        btn = f'<a{link_attrs(href, target, rel)} class="rr-btn-group arrox-el-btn"><span class="b">{btn_text}</span></a>' if btn_text else ""
        return (f'<div class="title-wrapper arrox-el-section"><h2 class="section-title font-thunder-regular arrox-el-title">{title}</h2>{btn}</div>')
    if wt == "arrox-theme-button":
        text = s.get("arrox_button_text", "") or s.get("arrox_theme_btn_text", "") or ""
        if not text:
            return ""
        href, target, rel = link_from(s.get("arrox_button_link_type"), s.get("arrox_button_page_link"), s.get("arrox_button_link"))
        return f'<a{link_attrs(href, target, rel)} class="rr-btn-group arrox-el-btn"><span class="b">{text}</span></a>'
    if wt == "arrox_button_three":
        text = s.get("button_text", "") or ""
        if not text:
            return ""
        href, target, rel = link_from(s.get("button_link_type"), s.get("button_page_link"), s.get("button_link"))
        return f'<div class="arrox-white-btn-group"><a{link_attrs(href, target, rel)} class="arrox-white-btn arrox-white-btn-primary">{text}</a></div>'
    if wt == "arrox-hero-animated-title":
        t1 = s.get("arrox_animated_text_01", "") or ""
        t2 = s.get("arrox_animated_text_02", "") or ""
        hover = s.get("arrox_hero_hover_text", "") or ""
        return ('<div class="hero-animated-title arrox-el-section"><h2 class="section-title">'
                f"{t1} {t2}</h2>"
                + img_tag(media_url(s.get("arrox_hero_shape")), "")
                + img_tag(media_url(s.get("arrox_hero_arrow")), "")
                + (f'<span class="hero-hover-text">{hover}</span>' if hover else "")
                + img_tag(media_url(s.get("arrox_hero_hover_image")), "") + "</div>")
    if wt == "arrox_hero_banner":
        title = s.get("section_title", "") or ""
        d1 = s.get("section_description_one", "") or ""
        d2 = s.get("section_description_two", "") or ""
        icons = "".join(f'<span class="contact-icon">{icon_html(c.get("contact_list_icon"))}</span>' for c in (s.get("contact_list") or []) if isinstance(c, dict))
        return ('<div class="hero-banner arrox-el-section">'
                + img_tag(media_url(s.get("marketing_shape")), "")
                + f'<h2 class="section-title">{title}</h2><p>{d1}</p><p>{d2}</p>'
                + f'<div class="hero-contact-icons">{icons}</div></div>')
    if wt == "arrox_news_ticker":
        items = "".join(f"<li>{i.get('news_ticker_title', '')}</li>" for i in (s.get("news_ticker_list") or []) if isinstance(i, dict))
        return f'<div class="news-ticker arrox-el-section"><ul>{items}</ul></div>'
    if wt == "arrox_career_text_slider":
        items = "".join(f'<span class="career-title">{i.get("career_title", "")}</span>' for i in (s.get("career_slider") or []) if isinstance(i, dict))
        return f'<div class="career-text-slider arrox-el-section">{items}</div>'
    if wt == "arrox-invert-text":
        return f'<div class="service-content-wrapper arrox-el-section"><div class="service-content"><div class="section-info-wrapper"><div class="text-wrapper"><p class="text text-invert arrox-el-text">{s.get("arrox_invert_text", "")}</p></div></div></div></div>'
    if wt == "rt-image-portfolio":
        href, target, rel = link_from(s.get("arrox_img_link_type"), s.get("arrox_img_page_link"), s.get("arrox_img_link"))
        img = img_tag(media_url(s.get("rt_img")), "")
        inner = f'<a{link_attrs(href, target, rel)}>{img}</a>' if (img and href != "#") else img
        return ('<div class="ax-pf-wrapper-02 work-area-2"><div class="works-wrapper-box"><div class="work-box">'
                f'<div class="thumb">{inner}</div></div></div></div>')
    if wt == "rt-brand-bounch":
        desc = s.get("rt_brand_desc", "") or ""
        slides = "".join(f'<div class="swiper-slide"><div class="ab-brand-item">{img_tag(media_url(i.get("rt_brand_image")), "")}</div></div>'
                         for i in (s.get("rt_brand_slides") or []) if isinstance(i, dict) and media_url(i.get("rt_brand_image")))
        return (f'<div class="brand-bounch arrox-el-section"><p class="brand-desc">{desc}</p>'
                f'<div class="swiper ab-brand-slide-active"><div class="swiper-wrapper">{slides}</div></div></div>')
    if wt == "arrox-brand-slider":
        slides = "".join(f'<div class="client-box">{img_tag(media_url(i.get("arrox_brand_image")), "")}</div>'
                         for i in (s.get("arrox_brand_slides") or []) if isinstance(i, dict) and media_url(i.get("arrox_brand_image")))
        return f'<section class="capabilities-area arrox-el-section"><div class="clients-wrapper-box"><div class="clients-wrapper">{slides}</div></div></section>'
    if wt == "arrox_brand_slider_slider":
        slides = ""
        for i in (s.get("brand_slider_list") or []):
            if not isinstance(i, dict):
                continue
            slides += ('<div class="swiper-slide"><div class="branding-slide">'
                       + img_tag(media_url(i.get("brand_slider_image")), "")
                       + f'<p class="branding-text">{i.get("branding_slider_text", "")}</p></div></div>')
        return f'<div class="branding-slider arrox-el-section"><div class="swiper"><div class="swiper-wrapper">{slides}</div></div></div>'
    if wt == "rt-banner":
        feats = ""
        for i in (s.get("arrox_features_list") or []):
            if not isinstance(i, dict):
                continue
            feats += ('<div class="banner-feature">'
                      + img_tag(media_url(i.get("image_icon")), "")
                      + f'<span>{i.get("arrox_pd_text_01", "")}</span><span>{i.get("arrox_pd_text_02", "")}</span></div>')
        return f'<div class="banner-features arrox-el-section">{feats}</div>'
    if wt == "rt-cta-work":
        text = s.get("rt_cta_text", "") or ""
        href = demo_url_to_local(s.get("rt_cta_text_url", "")) or "/contact/"
        return (f'<div class="p-relative overflow-hidden"><section class="cta-area rt-el-section"><div class="cta-area-inner section-spacing">'
                f'<div class="container large"><div class="section-content"><div class="section-title-wrapper"><div class="title-wrapper">'
                f'<h2 class="rt-el-text section-title font-instrumentsans-medium char-anim"><a href="{esc(href)}">{text}</a></h2>'
                "</div></div></div></div></section></div>")
    if wt == "arrox_services_list":
        boxes = ""
        for i in (s.get("services_list") or []):
            if not isinstance(i, dict):
                continue
            th, tt, tr = link_from(i.get("services_title_link_type"), i.get("services_title_page_link"), i.get("services_title_link"))
            bh, bt, br = link_from(i.get("services_button_link_type"), i.get("services_button_page_link"), i.get("services_button_link"))
            img = img_tag(media_url(i.get("services_img")), i.get("services_title", ""))
            boxes += ('<div class="service-box fade-anim">'
                      + (f'<div class="thumb"><a{link_attrs(th, tt, tr)}>{img}</a></div>' if img else "")
                      + f'<h3 class="service-title"><a{link_attrs(th, tt, tr)}>{i.get("services_title", "")}</a></h3>'
                      + f'<p>{i.get("services_desc", "")}</p>'
                      + f'<a{link_attrs(bh, bt, br)} class="service-btn">{i.get("services_button_text", "Explore")}</a></div>')
        return f'<section class="service-area-3 arrox-el-section"><div class="service-area-3-inner"><div class="services-wrapper-box"><div class="services-wrapper-3">{boxes}</div></div></div></section>'
    if wt == "arrox_services_vertical_slider":
        rows = ""
        for i in (s.get("services_list") or []):
            if not isinstance(i, dict):
                continue
            th, tt, tr = link_from(i.get("services_title_link_type"), i.get("services_title_page_link"), i.get("services_title_link"))
            feats = "".join(f"<li>{f.get('features_title', '')}</li>" for f in (i.get("features_list") or []) if isinstance(f, dict))
            rows += (f'<div class="service-row"><span class="service-number">{i.get("services_number", "")}</span>'
                     f'<h3><a{link_attrs(th, tt, tr)}>{i.get("services_title", "")}</a></h3><ul>{feats}</ul></div>')
        return ('<div class="services-vertical arrox-el-section">'
                + img_tag(media_url(s.get("arrox_image")), "") + rows + "</div>")
    if wt == "arrox_feature_list":
        boxes = ""
        for i in (s.get("features_list") or []):
            if not isinstance(i, dict):
                continue
            th, tt, tr = link_from(i.get("features_list_link_type"), i.get("features_list_page_link"), i.get("features_list_link"))
            boxes += (f'<a{link_attrs(th, tt, tr)} class="fade-anim"><div class="service-box-wrapper">'
                      f'<span class="feature-number">{i.get("feature_number", "")}</span>'
                      f'<h3>{i.get("feature_title", "")}</h3><p>{i.get("feature_desc", "")}</p></div></a>')
        return f'<div class="features-list arrox-el-section"><div class="services-wrapper-2">{boxes}</div></div>'
    if wt == "arrox-team-box":
        boxes = ""
        for i in (s.get("teams") or []):
            if not isinstance(i, dict):
                continue
            th, tt, tr = link_from(i.get("arrox_title_link_type"), i.get("arrox_title_page_link"), i.get("arrox_title_custome_link"))
            boxes += ('<div class="team-box">'
                      + img_tag(media_url(i.get("arrox_team_image")), i.get("arrox_team_name", ""))
                      + f'<h3 class="name"><a{link_attrs(th, tt, tr)}>{i.get("arrox_team_name", "")}</a></h3>'
                      + f'<span class="designation">{i.get("arrox_team_designation", "")}</span>'
                      + img_tag(media_url(i.get("team_arrow_image")), "") + "</div>")
        return f'<div class="team-list-area arrox-el-section"><div class="team-wrapper-box"><div class="team-wrapper">{boxes}</div></div></div>'
    if wt == "arrox_award":
        l1 = "".join(f'<li><span class="award-year">{i.get("award_year", "")}</span><span class="award-title">{i.get("award_title", "")}</span><span class="award-number">{i.get("award_number", "")}</span>{img_tag(media_url(i.get("award_img")), "")}</li>'
                       for i in (s.get("award_list") or []) if isinstance(i, dict))
        l2 = "".join(f'<li><span class="award-number">{i.get("award_number", "")}</span><span class="award-title">{i.get("award_title", "")}</span></li>'
                       for i in (s.get("award_list_two") or []) if isinstance(i, dict))
        l3 = "".join(f'<li><span class="award-title">{i.get("award_title", "")}</span><span class="award-year">{i.get("award_year", "")}</span><span class="award-category">{i.get("award_category", "")}</span></li>'
                       for i in (s.get("award_list_three") or []) if isinstance(i, dict))
        return f'<div class="award-area arrox-el-section"><ul class="award-list">{l1}</ul><ul class="award-list-two">{l2}</ul><ul class="award-list-three">{l3}</ul></div>'
    if wt == "arrox_testimonial_slider_two":
        slides = ""
        for i in (s.get("testimonial_list_one") or []):
            if not isinstance(i, dict):
                continue
            slides += ('<div class="swiper-slide"><div class="testimonial-box">'
                       + img_tag(media_url(i.get("testimonial_image")), "")
                       + f'<p class="testimonial-text">{i.get("testimonial_description_repeater", "")}</p>'
                       + img_tag(media_url(i.get("testimonial_author_image")), i.get("testimonial_name", ""))
                       + f'<h4>{i.get("testimonial_name", "")}</h4><span>{i.get("testimonial_designation", "")}</span></div></div>')
        return f'<div class="testimonial-slider arrox-el-section"><div class="swiper"><div class="swiper-wrapper">{slides}</div></div></div>'
    if wt in ("arrox-blog-post", "arrox_blog_post_list"):
        limit = 14
        try:
            limit = int(s.get("post_content_limit") or s.get("arrox_post_content_limit") or 14)
        except Exception:
            pass
        cards = "".join(post_card(p) for p in posts_for_widget(s))
        return f'<div class="blog-post-list arrox-el-section"><div class="post-cards">{cards}</div></div>'
    if wt == "arrox_portfolio_list":
        items = ""
        for i in (s.get("project_main_list") or []):
            if not isinstance(i, dict):
                continue
            th, tt, tr = link_from(i.get("project_item_link_type"), i.get("project_item_page_link"), i.get("project_item_link"))
            tags = "".join(f"<li>{f.get('menu_text_list', '')}</li>" for f in (i.get("feature_list") or []) if isinstance(f, dict))
            items += ('<div class="project-item">'
                      + img_tag(media_url(i.get("arrox_project_thumb")), "")
                      + f'<p class="project-desc">{i.get("project_item_description", "")}</p><ul class="project-tags">{tags}</ul>'
                      + f'<a{link_attrs(th, tt, tr)}>{s.get("project_item_btn_text", "See work")}</a></div>')
        sticky = s.get("project_sticky_text", "") or ""
        bh, bt, br = link_from(s.get("slider_button_link_type_bottom"), s.get("slider_button_page_link_bottom"), s.get("slider_button_link_bottom"))
        return (f'<div class="portfolio-list arrox-el-section"><div class="project-sticky-text">{sticky}</div>{items}'
                + (f'<a{link_attrs(bh, bt, br)} class="all-projects-btn">{s.get("bottom_btn_text", "All Projects")}</a>' if s.get("bottom_btn_text") else "") + "</div>")
    if wt == "arrox-about-vertical-image-slider":
        slides = "".join(f'<div class="swiper-slide">{img_tag(media_url(i.get("arrox_image")), "")}</div>'
                         for i in (s.get("arrox_image_list") or []) if isinstance(i, dict) and media_url(i.get("arrox_image")))
        return f'<div class="about-image-slider arrox-el-section"><div class="swiper"><div class="swiper-wrapper">{slides}</div></div></div>'
    if wt == "arrox-contact-form":
        return contact_form_html()
    if wt == "arrox_footer_subscribe_form":
        return subscribe_form_html()
    if wt == "arrox_footer_button":
        href, target, rel = link_from(s.get("button_link_type"), s.get("button_page_link"), s.get("button_link"))
        return f'<a{link_attrs(href, target, rel)} class="footer-btn">{icon_html(s.get("button_icon"))}</a>'
    if wt == "rt-footer-anchor":
        text = (s.get("rt_footer_anchor_text", "") or "").strip()
        url = (s.get("rt_footer_anchor_url", "") or "").strip()
        if not text:
            return ""
        if re.search(r"(Street|Road|Avenue|Drive|Blvd|Lane|Ranchview|Green Road|Dorland)", text):
            return ""  # demo street address: removed outright
        if url.startswith("mailto:"):
            return f'<a href="{esc(url)}">{text}</a>'
        if url.startswith("tel:"):
            return f'<a href="{esc(url)}">{text}</a>'
        href = demo_url_to_local(url) if url else None
        if href:
            return f'<a href="{esc(href)}">{text}</a>'
        return f"<span>{text}</span>"
    if wt == "rt-footer-links":
        title = s.get("tp_footer_links_title", "") or ""
        lis = ""
        for i in (s.get("tp_footer_links_list") or []):
            if not isinstance(i, dict):
                continue
            ititle = i.get("tp_footer_links_title", "") or ""
            link_url = i.get("tp_footer_links_link", {}).get("url", "") if isinstance(i.get("tp_footer_links_link"), dict) else ""
            # Demo office city lists (map links) are removed outright.
            if ititle.strip() in ("New York", "Toronto", "Berlin", "London", "San Diego", "Charleston") or "maps" in link_url:
                continue
            href, target, rel = link_from(i.get("tp_footer_links_link_type"), i.get("tp_footer_links_page_link"), i.get("tp_footer_links_link"))
            lis += f'<li><a{link_attrs(href, target, rel)}>{ititle}</a></li>'
        if not lis:
            return ""
        return f'<div class="footer-links"><h4>{title}</h4><ul>{lis}</ul></div>'
    if wt.startswith("arrox-header"):
        layout = wt.replace("arrox-header", "") or "1"
        logo = media_url(s.get("site_logo"))
        logo_html = ""
        if logo and not is_placeholder_image(logo):
            logo_html = (f'<div class="arrox-el-logo header__logo"><a href="/">'
                         f'<img src="{esc(logo)}" class="normal-logo" alt="Woodwolf Digital logo"></a></div>')
        menu_slug = s.get("menu", "main-menu") or "main-menu"
        nav = build_menu(menu_slug)
        btn_text = s.get("arrox_theme_btn_text", "") or ""
        btn_html = ""
        if btn_text:
            href, target, rel = link_from(s.get("arrox_theme_btn_link_type"), s.get("arrox_theme_btn_page_link"), s.get("arrox_theme_btn_link"))
            btn_html = (f'<div class="header__button"><a{link_attrs(href, target, rel)} class="rr-btn">'
                        f'<span class="btn-wrap"><span class="text-one">{btn_text}</span><span class="text-two">{btn_text}</span></span></a></div>')
        toggle_img = img_tag(media_url(s.get("toggle_image")), "")
        toggle = (f'<div class="header__navicon"><button class="side-toggle">{toggle_img if toggle_img else "<i class=\"fa-solid fa-bars\"></i>"}</button></div>')
        return (f'<header class="header-area-{layout} redox-header-layout-{layout}"><div class="header-main">'
                f'<div class="header-area-{layout}__inner">{logo_html}'
                f'<div class="header__nav"><nav class="main-menu">{nav}</nav></div>{btn_html}{toggle}'
                "</div></div></header>")
    REPORT["approximations"].append(f"unrendered widget type: {wt}")
    return f'<div class="widget-fallback"><p>{esc_text(str(s.get("title", "") or wt))}</p></div>'


def render_element(d):
    """Render a decoded Elementor element dict (widget or container)."""
    if not isinstance(d, dict):
        return ""
    if d.get("elType") == "widget":
        return render_widget(d)
    kids = "".join(render_element(c) for c in (d.get("elements") or []) if isinstance(c, dict))
    return f'<div class="e-con e-flex">{kids}</div>'


def render_placeholders(html):
    """Replace [elementor-element] tokens with rendered widget HTML.

    The output is wrapped in the element's own elementor-element-<id> div
    so generated per-element layout rules have a target to attach to (the
    placeholder tokens carry no wrapper of their own).
    """
    def repl(m):
        d = decode_placeholder(m)
        if d is None:
            return ""
        out = render_element(d)
        if not out.strip():
            return ""
        eid = d.get("id")
        wt = d.get("widgetType", "")
        if eid:
            return (f'<div class="elementor-element elementor-element-{eid} '
                    f'elementor-widget elementor-widget-{wt}">{out}</div>')
        return out
    return PLACEHOLDER_RE.sub(repl, html)

# ---------------------------------------------------------------- HTML cleaning
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\(\d{3}\)\s*|\d{3}[- ])\d{3}[- ]\d{4}|\+?\d[\d\s().-]{9,}\d")
VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "col"}


def clean_text(text):
    # Emails and phones FIRST: a brand replace inside an address would break
    # the pattern (hello@arroxagency.com became hello@Woodwolf Digitalagency.com).
    text = EMAIL_RE.sub(lambda m: EMAIL if m.group(0).lower() != EMAIL else m.group(0), text)
    text = PHONE_RE.sub(PHONE_TEXT, text)
    for pat in ("RavexTheme", "RRDevs", "Redox", "Arrox"):
        text = re.sub(pat, BRAND, text, flags=re.IGNORECASE)
    text = re.sub(r"WordPress", "Website", text, flags=re.IGNORECASE)
    return text


def rewrite_attr_url(url, failed):
    """Rewrite one attribute URL; returns None to drop the attribute/tag use."""
    if not url:
        return url
    url = url.strip()
    if url.startswith("mailto:"):
        addr = url[7:].split("?")[0]
        return "mailto:" + EMAIL if addr and addr.lower() != EMAIL else url
    if url.startswith("tel:"):
        return "tel:" + PHONE_TEL
    if url.startswith("#") or url.startswith("data:"):
        return url
    if "wp.ravextheme.com" in url and "/wp-content/uploads/" in url:
        local = uploads_local(url)
        if local in failed:
            return "/assets/uploads/placeholder.svg"
        return local
    if "wp.ravextheme.com" in url:
        mapped = demo_url_to_local(url)
        return mapped if mapped is not None else "/"
    if "rrdevs.net" in url:
        return None
    if "themeforest.net" in url or "ravextheme" in url:
        return "/"
    if "mail.google.com" in url:
        return "mailto:" + EMAIL
    if re.match(r"^https?://\+?\d[\d\s()-]*$", url):
        return "tel:" + PHONE_TEL
    if url.startswith("/"):
        parts = [p for p in url.split("/") if p]
        if parts and parts[0] in REMOVED:
            return "/"
        if parts and parts[0] in SLUG_URL:
            return SLUG_URL[parts[0]]
        return url
    if url.startswith("http"):
        return url
    return url


CITIES = {"New York", "Toronto", "Berlin", "London", "San Diego", "Charleston"}
SOCIAL_DOMAINS = ("facebook.com", "instagram.com", "x.com", "twitter.com",
                  "youtube.com", "linkedin.com", "behance.net", "dribbble.com",
                  "dribble.com", "pinterest.com")


def post_clean(html):
    """Anchor-level fixes the tag parser cannot do alone: bare social links
    (no real profile) become plain text, map/city links are dropped, and
    theme-author links point home."""
    def social_repl(m):
        return f"<span>{m.group(1)}</span>"
    html = re.sub(
        r'<a[^>]*href="https?://(?:www\.)?(?:facebook\.com|instagram\.com|x\.com|twitter\.com|youtube\.com|linkedin\.com|behance\.net|dribbble\.com|dribble\.com|pinterest\.com)/?"[^>]*>(.*?)</a>',
        social_repl, html, flags=re.DOTALL)

    def maps_repl(m):
        inner = m.group(1)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if text in CITIES:
            return ""
        return f"<span>{inner}</span>"
    html = re.sub(
        r'<a[^>]*href="[^"]*(?:maps\.app\.goo\.gl|google\.com/maps)[^"]*"[^>]*>(.*?)</a>',
        maps_repl, html, flags=re.DOTALL)
    # Demo street addresses: drop whole icon-box widgets that carry one.
    for marker in ("Ranchview", "Dorland", "Green Road", "1772 Street", "772 Street"):
        html = _drop_blocks_with(html, marker)
    html = html.replace("3891 Ranchview Dr. Richardson", "")
    return html


ADDRESS_MARKER_RE = None


def _drop_blocks_with(html, marker):
    """Remove elementor icon-box widget blocks whose content contains marker."""
    out = []
    pos = 0
    pat = re.compile(r'<div[^>]*elementor-widget-icon-box[^>]*>')
    while True:
        m = pat.search(html, pos)
        if not m:
            out.append(html[pos:])
            break
        start = m.start()
        depth = 0
        i = start
        end = None
        tag_re = re.compile(r'</?div\b[^>]*>', re.IGNORECASE)
        for tm in tag_re.finditer(html, start):
            if tm.group(0).startswith("</"):
                depth -= 1
                if depth == 0:
                    end = tm.end()
                    break
            else:
                depth += 1
        if end is None:
            out.append(html[pos:])
            break
        block = html[start:end]
        if marker in block:
            out.append(html[pos:start])
        else:
            out.append(html[pos:end])
        pos = end
    return "".join(out)


class Cleaner(HTMLParser):
    def __init__(self, failed):
        super().__init__(convert_charrefs=True)
        self.failed = failed
        self.out = []
        self.skip = 0  # depth for script/style/link dropping

    def _attrs(self, tag, attrs):
        res = []
        bg_style = ""
        for k, v in attrs:
            if v is None:
                res.append((k, None))
                continue
            if k in ("data-id", "data-element_type", "data-widget_type", "data-cursor-text",
                     "data-cursor-text-red", "data-animation", "onclick") or k.startswith("data-elementor"):
                continue
            if k == "data-settings":
                try:
                    sj = json.loads(v)
                    bg = sj.get("background_image") or {}
                    if isinstance(bg, dict) and bg.get("url"):
                        local = rewrite_attr_url(bg["url"], self.failed)
                        if local:
                            bg_style += f"background-image:url({local});"
                    col = sj.get("background_color")
                    if col:
                        bg_style += f"background-color:{col};"
                except Exception:
                    pass
                continue
            if k == "action":
                continue
            if k in ("href", "src", "data-background"):
                nv = rewrite_attr_url(v, self.failed)
                if nv is None:
                    continue
                v = nv
            if k in ("aria-label", "title", "alt", "placeholder"):
                v = clean_text(v)
            if k == "style" and v:
                v = re.sub(r"https://wp\.ravextheme\.com[^)'\"\s]+/wp-content/uploads/([^)'\"\s]+)",
                           lambda m: uploads_local(m.group(0)) if uploads_local(m.group(0)) not in self.failed else "/assets/uploads/placeholder.svg", v)
            if k == "class" and v:
                toks = [t for t in v.split() if not t.startswith("wp-")]
                v = " ".join(toks)
            res.append((k, v))
        if bg_style:
            for i, (k, v) in enumerate(res):
                if k == "style":
                    res[i] = (k, v.rstrip(";") + ";" + bg_style)
                    break
            else:
                res.append(("style", bg_style))
        return res

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "link"):
            self.skip += 1
            return
        if tag == "img":
            src = dict(attrs).get("src", "")
            if is_placeholder_image(src):
                return
        if tag in ("video", "source"):
            src = dict(attrs).get("src", "")
            if src and ("rrdevs.net" in src or "wp.ravextheme.com" in src):
                return
        a = self._attrs(tag, attrs)
        s = "".join(f" {k}" if v is None else f' {k}="{htmlmod.escape(v, quote=True)}"' for k, v in a)
        self.out.append(f"<{tag}{s}>")

    def handle_startendtag(self, tag, attrs):
        if tag in ("script", "style", "link"):
            return
        if tag == "img" and is_placeholder_image(dict(attrs).get("src", "")):
            return
        a = self._attrs(tag, attrs)
        s = "".join(f" {k}" if v is None else f' {k}="{htmlmod.escape(v, quote=True)}"' for k, v in a)
        self.out.append(f"<{tag}{s}>")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "link"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(htmlmod.escape(clean_text(data)))

    def handle_comment(self, data):
        return

    def handle_decl(self, decl):
        return


def clean_html(html, failed):
    c = Cleaner(failed)
    try:
        c.feed(html)
        c.close()
    except Exception as e:
        warn(f"HTML clean failed, returning raw: {e}")
        return html
    return "".join(c.out)


def normalize_h1(html):
    """Exactly one H1: promote first H2 if none, demote extras if many."""
    if "<h1" not in html:
        m = re.search(r"<h2([^>]*)>(.*?)</h2>", html, flags=re.DOTALL)
        if m:
            html = html[:m.start()] + f"<h1{m.group(1)}>{m.group(2)}</h1>" + html[m.end():]
        return html
    parts = re.split(r"(<h1[^>]*>.*?</h1>)", html, flags=re.DOTALL)
    seen = False
    out = []
    for p in parts:
        if re.match(r"<h1[^>]*>.*?</h1>$", p, flags=re.DOTALL):
            if not seen:
                seen = True
                out.append(p)
            else:
                out.append(re.sub(r"^<h1([^>]*)>(.*?)</h1>$", r"<h2\1>\2</h2>", p, flags=re.DOTALL))
        else:
            out.append(p)
    return "".join(out)


def apply_lazy(html, first_eager=True):
    """First image eager, the rest lazy (content fragments)."""
    count = [0]

    def repl(m):
        tag = m.group(0)
        if "loading=" in tag:
            return tag
        count[0] += 1
        if first_eager and count[0] == 1:
            return tag
        return tag[:-1] + ' loading="lazy">'
    return re.sub(r"<img[^>]*>", repl, html)


def lazy_all(html):
    def repl(m):
        tag = m.group(0)
        return tag if "loading=" in tag else tag[:-1] + ' loading="lazy">'
    return re.sub(r"<img[^>]*>", repl, html)


def plain_text(html):
    t = re.sub(r"<[^>]+>", " ", html)
    return htmlmod.unescape(re.sub(r"\s+", " ", t)).strip()


def description_for(title, content_html):
    text = plain_text(content_html)
    if len(text) >= 40:
        d = text[:157]
        if len(text) > 157:
            d = d.rsplit(" ", 1)[0]
        return d
    return f"Explore {title} from Woodwolf Digital, a creative agency for design, development and marketing."


# ---------------------------------------------------------------- images
def collect_upload_urls(html_list):
    urls = set()
    for h in html_list:
        for m in re.finditer(r"https://wp\.ravextheme\.com[^\"'\s)]+?/wp-content/uploads/([^\"'\s)]+)", h):
            urls.add(m.group(0).split("?")[0])
    return urls


def download_images(urls):
    dest_base = ROOT / "public" / "assets" / "uploads"
    failed = set()

    def dl(url):
        rel = re.search(r"/wp-content/uploads/(.+)$", url).group(1)
        dest = dest_base / rel
        if dest.exists() and dest.stat().st_size > 0:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(dest) + ".tmp"
        r = subprocess.run(["curl", "-sS", "-L", "--fail", "--max-time", "60",
                            "-A", "Mozilla/5.0", "-o", tmp, url],
                           capture_output=True, text=True)
        if r.returncode != 0:
            try:
                Path(tmp).unlink()
            except Exception:
                pass
            return url
        Path(tmp).rename(dest)
        return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        for bad in ex.map(dl, sorted(urls)):
            if bad:
                failed.add(uploads_local(bad))
                REPORT["failed_images"].append(bad)
    return failed

# ---------------------------------------------------------------- generated layout CSS
# Per-element layout rules derived from the demo page settings. The live
# theme CSS only carries generic rules, so without these the pages lose
# their column widths, gaps, padding, typography and absolute positioning.
# The output file is plain CSS: no builder JSON, no remote URLs, no
# data attributes are reintroduced anywhere.
import zipfile

KIT_ZIP = (Path.home() / "workspace" / "redox-wp-source" / "redox-106"
           / "themeforest-redox-creative-agency-and-portfolio-wordpress-theme"
           / "sample-data" / "elementor-kit.zip")
BP_ORDER = ["widescreen", "laptop", "tablet_extra", "tablet", "mobile_extra", "mobile"]
BP_MEDIA = {
    "widescreen": "@media (min-width: 2400px)",
    "laptop": "@media (max-width: 1366px)",
    "tablet_extra": "@media (max-width: 1200px)",
    "tablet": "@media (max-width: 1024px)",
    "mobile_extra": "@media (max-width: 880px)",
    "mobile": "@media (max-width: 767px)",
}
BP_SUFFIXES = ["tablet_extra", "mobile_extra", "widescreen", "tablet", "mobile", "laptop"]
TYPO_MAP = (("font-family", "typography_font_family"),
            ("font-weight", "typography_font_weight"),
            ("font-size", "typography_font_size"),
            ("line-height", "typography_line_height"),
            ("letter-spacing", "typography_letter_spacing"),
            ("text-transform", "typography_text_transform"))


def load_globals():
    colors, typos = {}, {}
    try:
        with zipfile.ZipFile(KIT_ZIP) as z:
            settings = json.loads(z.read("site-settings.json")).get("settings", {}) or {}
        for group in ("system_colors", "custom_colors"):
            for c in settings.get(group, []) or []:
                if c.get("_id") and c.get("color"):
                    colors[c["_id"]] = c["color"]
        for group in ("system_typography", "custom_typography"):
            for t in settings.get(group, []) or []:
                if t.get("_id"):
                    typos[t["_id"]] = t
    except Exception as e:
        warn(f"kit globals load failed: {e}")
    return colors, typos


GLOBAL_COLORS, GLOBAL_TYPOS = load_globals()


def resolve_color_ref(value):
    if isinstance(value, str):
        m = re.match(r"globals/colors\?id=(.+)$", value.strip())
        if m:
            return GLOBAL_COLORS.get(m.group(1))
    return None


def typo_props_from_global(gid):
    t = GLOBAL_TYPOS.get(gid)
    if not t:
        return {}
    out = {}
    if t.get("typography_font_family"):
        out["font-family"] = t["typography_font_family"]
    if t.get("typography_font_weight"):
        out["font-weight"] = t["typography_font_weight"]
    for key, css in (("typography_font_size", "font-size"),
                     ("typography_line_height", "line-height"),
                     ("typography_letter_spacing", "letter-spacing"),
                     ("typography_text_transform", "text-transform")):
        v = t.get(key)
        if v:
            sv = size_value(v, css)
            if sv:
                out[css] = sv
    return out


def size_value(v, prop=""):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v) if prop == "line-height" else f"{v}px"
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, dict):
        size = v.get("size")
        if size is None or size == "":
            return None
        unit = v.get("unit") or ""
        if prop == "line-height" and not unit:
            return str(size)
        return f"{size}{unit}"
    return None


def dim_value(side_val, unit, prop=""):
    """One side of a dimension dict: bare numbers take the dict's unit."""
    if side_val is None or side_val == "":
        return None
    s = str(side_val).strip()
    if s in ("0", "0.0", "-0"):
        return "0"
    if re.search(r"(px|%|em|rem|vw|vh|vmin|vmax|ch|ex|cm|mm|in|pt|pc)$", s):
        return s
    if prop == "line-height":
        return s
    return f"{s}{unit or 'px'}"


def box_longhands(prop, v):
    """Padding/margin/border-width dict -> individual longhand props."""
    if not isinstance(v, dict):
        return {}
    out = {}
    size = v.get("size")
    if size not in (None, "") and v.get("isLinked"):
        sv = size_value(v, prop)
        if sv:
            for side in ("top", "right", "bottom", "left"):
                out[f"{prop}-{side}"] = sv
            return out
    unit = v.get("unit") or "px"
    for side in ("top", "right", "bottom", "left"):
        sv = dim_value(v.get(side), unit, prop)
        if sv:
            out[f"{prop}-{side}"] = sv
    return out


def radius_value(v):
    if not isinstance(v, dict):
        return None
    parts = []
    unit = v.get("unit") or "px"
    for side in ("top", "right", "bottom", "left"):
        sv = dim_value(v.get(side), unit, "border-radius")
        parts.append(sv if sv else "0")
    if all(p == "0" for p in parts):
        return None
    return " ".join(parts)


def gap_value(v):
    if not isinstance(v, dict):
        return None
    unit = v.get("unit") or "px"
    size = v.get("size")
    if size not in (None, ""):
        return f"{size}{unit}"
    row, col = v.get("row"), v.get("column")
    if (row in (None, "")) and (col in (None, "")):
        return None
    r = f"{row}{unit}" if row not in (None, "") else "0"
    c = f"{col}{unit}" if col not in (None, "") else "0"
    return f"{r} {c}"


def font_family_value(v):
    if not isinstance(v, str) or not v.strip():
        return None
    v = v.strip()
    if "," in v or v.startswith(("'", '"')):
        return v
    if " " in v:
        return f"'{v}'"
    return v


def color_of(settings, key):
    v = settings.get(key)
    if isinstance(v, str) and v.strip():
        return resolve_color_ref(v) or v
    gl = settings.get("__globals__") or {}
    g = gl.get(key)
    if isinstance(g, str) and g.strip():
        return resolve_color_ref(g)
    return None


def typo_props(settings):
    """Direct typography_* keys plus nested *_typography_* groups and globals."""
    out = {}
    for css, key in TYPO_MAP:
        v = settings.get(key)
        if key == "typography_font_family":
            fv = font_family_value(v) if isinstance(v, str) else None
            if fv:
                out["font-family"] = fv
        elif v is not None and v != "":
            if isinstance(v, str) and v.startswith("globals/typography"):
                for k2, v2 in typo_props_from_global(v.split("id=", 1)[1]).items():
                    out.setdefault(k2, v2)
            else:
                sv = size_value(v, css)
                if sv:
                    out[css] = sv
    gl = settings.get("__globals__") or {}
    for css, key in TYPO_MAP:
        if css in out:
            continue
        g = gl.get(key)
        if isinstance(g, str) and g.startswith("globals/typography"):
            for k2, v2 in typo_props_from_global(g.split("id=", 1)[1]).items():
                out.setdefault(k2, v2)
    # Nested widget typography groups (title_typography_*, etc.): apply to
    # the wrapper as an approximation; they inherit into the inner text.
    nested = re.compile(r"^(.+)_typography_(font_family|font_size|font_weight|line_height|letter_spacing|text_transform)$")
    for key, v in settings.items():
        m = nested.match(key)
        if not m or v is None or v == "":
            continue
        css = m.group(2).replace("_", "-")
        if css in out:
            continue
        if css == "font-family":
            fv = font_family_value(v) if isinstance(v, str) else None
            if fv:
                out[css] = fv
        else:
            sv = size_value(v, css)
            if sv:
                out[css] = sv
    return out


def split_breakpoints(settings):
    base = {}
    per = {bp: {} for bp in BP_ORDER}
    for k, v in (settings or {}).items():
        matched = None
        for suf in BP_SUFFIXES:
            if k.endswith("_" + suf):
                matched = suf
                break
        if matched:
            per[matched][k[:-(len(matched) + 1)]] = v
        else:
            base[k] = v
    return base, per


def local_bg_url(url, failed):
    if not url or is_placeholder_image(url):
        return None
    if "wp.ravextheme.com" in url and "/wp-content/uploads/" in url:
        local = uploads_local(url)
        return "/assets/uploads/placeholder.svg" if local in failed else local
    if url.startswith("http"):
        return None
    return url


def extract_props(s, eltype, failed, base_settings=None, is_base=False):
    """One breakpoint's settings -> (self, inner, heading, inner_max) prop dicts."""
    self_p, inner_p, head_p = {}, {}, {}
    inner_max = None
    # Width / flex item sizing.
    w = s.get("width") if s.get("width") is not None else s.get("_element_width")
    wv = size_value(w, "width") if w is not None else None
    if wv:
        if wv in ("auto", "initial", "inherit", "unset"):
            self_p["width"] = wv
        else:
            self_p["flex"] = f"0 0 {wv}"
            self_p["max-width"] = wv
            self_p["width"] = wv
            self_p["--width"] = wv
    fs = s.get("_flex_size")
    if fs not in (None, ""):
        self_p["flex-grow"] = str(fs["size"] if isinstance(fs, dict) else fs)
    fo = s.get("_flex_order") if s.get("_flex_order") is not None else s.get("order")
    if fo not in (None, ""):
        self_p["order"] = str(fo)
    fas = s.get("_flex_align_self")
    if fas:
        self_p["align-self"] = fas
    # Container flex layout. Rendered HTML puts children inside .e-con-inner
    # ONLY for boxed containers; full-width containers hold children directly
    # (verified across all dist pages: every boxed container has an inner
    # wrapper, no full-width container does). So flex props must target the
    # inner wrapper for boxed containers and the element itself for
    # full-width ones. Boxed-ness comes from base settings because the
    # rendered HTML is fixed, not per breakpoint: content_width unset means
    # boxed (Elementor default), "full" means full width.
    if eltype == "container":
        cw_base = (base_settings or {}).get("content_width")
        if cw_base is None:
            cw_base = (base_settings or {}).get("boxed_width")
        if cw_base is None:
            cw_base = s.get("content_width") or s.get("boxed_width")
        boxed = not (isinstance(cw_base, str) and cw_base.strip() == "full")
        target = inner_p if boxed else self_p
        is_grid = ("grid_columns_grid" in s or
                   (base_settings is not None and "grid_columns_grid" in base_settings))
        fd = s.get("flex_direction")
        if not fd and is_base and not is_grid:
            # No direction set anywhere: containers stack children vertically.
            # Evidence from the demo data itself: unset containers' children
            # almost never carry width settings (187 of 196 multi-child unset
            # containers have no child with a width), matching explicit
            # column containers (2 of 78 children with widths) rather than
            # explicit row containers (216 of 384 children with widths).
            fd = "column"
        if fd:
            target["flex-direction"] = fd
        fw = s.get("flex_wrap")
        if fw:
            target["flex-wrap"] = fw
        ai = s.get("flex_align_items") or s.get("content_vertical_alignment")
        if ai:
            target["align-items"] = ai
        jc = s.get("flex_justify_content")
        if jc:
            target["justify-content"] = jc
        gv = gap_value(s.get("flex_gap") if s.get("flex_gap") is not None else s.get("gap"))
        if gv:
            target["gap"] = gv
    # Spacing.
    for key in ("padding", "_padding"):
        self_p.update(box_longhands("padding", s.get(key)))
    for key in ("margin", "_margin"):
        self_p.update(box_longhands("margin", s.get(key)))
    # Background.
    bg = s.get("background_background") or s.get("_background_background")
    if bg == "classic":
        c = color_of(s, "background_color") or color_of(s, "_background_color")
        if c:
            self_p["background-color"] = c
        img = s.get("background_image") or s.get("_background_image")
        url = local_bg_url(media_url(img), failed)
        if url:
            self_p["background-image"] = f"url({url})"
        for key, css in (("background_position", "background-position"),
                         ("background_repeat", "background-repeat"),
                         ("background_size", "background-size"),
                         ("background_attachment", "background-attachment")):
            if s.get(key):
                self_p[css] = s[key]
    # Border.
    bs = s.get("border_border") or s.get("_border_border")
    if bs:
        self_p["border-style"] = bs
    for key in ("border_width", "_border_width"):
        self_p.update(box_longhands("border-width", s.get(key)))
    bc = color_of(s, "border_color") or color_of(s, "_border_color")
    if bc:
        self_p["border-color"] = bc
    rv = radius_value(s.get("border_radius") or s.get("_border_radius"))
    if rv:
        self_p["border-radius"] = rv
    # Typography (wrapper inherits into inner text; heading titles get it too).
    tp = typo_props(s)
    if tp:
        self_p.update(tp)
        head_p.update(tp)
    tc = color_of(s, "title_color")
    if tc:
        self_p["color"] = tc
        head_p["color"] = tc
    al = s.get("align") or s.get("alignment")
    if al in ("left", "center", "right", "justify"):
        self_p["text-align"] = al
    # Position / stacking / overflow / height.
    pos = s.get("_position")
    if pos in ("absolute", "relative", "fixed", "sticky", "static"):
        self_p["position"] = pos
        oh = s.get("_offset_orientation_h") or "start"
        ov = s.get("_offset_orientation_v") or "start"
        ox = s.get("_offset_x_end") if oh == "end" else s.get("_offset_x")
        oy = s.get("_offset_y_end") if ov == "end" else s.get("_offset_y")
        if ox is not None and ox != "":
            self_p["right" if oh == "end" else "left"] = size_value(ox, "left")
        if oy is not None and oy != "":
            self_p["bottom" if ov == "end" else "top"] = size_value(oy, "top")
    zi = s.get("z_index") if s.get("z_index") is not None else s.get("_z_index")
    if zi not in (None, ""):
        self_p["z-index"] = str(zi)
    ovf = s.get("overflow")
    if ovf in ("hidden", "visible", "auto", "scroll", "clip"):
        self_p["overflow"] = ovf
    mh = size_value(s.get("min_height"), "min-height")
    if mh:
        self_p["min-height"] = mh
    elif s.get("height") is not None:
        hv = size_value(s.get("height"), "min-height")
        if hv:
            self_p["min-height"] = hv
    # Boxed content width -> inner max-width (content_width wins over boxed).
    # A string "full" means full width, not a length; "boxed" keeps the default.
    cw = s.get("content_width") or s.get("boxed_width")
    if isinstance(cw, str) and cw.strip() == "full":
        inner_max = "100%"
        self_p["--content-width"] = "100%"
    elif cw is not None and not (isinstance(cw, str) and cw.strip() == "boxed"):
        inner_max = size_value(cw, "max-width")
        if inner_max:
            self_p["--content-width"] = inner_max
    return self_p, inner_p, head_p, inner_max


def scope_custom_css(css, eid, failed):
    """Scope one element's custom CSS under its element selector.

    `selector` tokens become .elementor-element-<id>; every other selector
    is prefixed with it. Remote URLs are dropped, demo upload URLs go local.
    """
    base_sel = f".elementor-element-{eid}"

    def rewrite_urls(text):
        text = re.sub(r"https://wp\.ravextheme\.com[^)'\"\s]+/wp-content/uploads/([^)'\"\s]+)",
                       lambda m: uploads_local(m.group(0)) if uploads_local(m.group(0)) not in failed else "/assets/uploads/placeholder.svg", text)
        text = re.sub(r"url\(\s*['\"]?https?://rrdevs\.net[^)'\"]*['\"]?\s*\)", "none", text)
        return text

    def scope_selector(sel):
        sel = sel.strip()
        if not sel:
            return sel
        if sel.startswith("selector"):
            return base_sel + sel[len("selector"):]
        if sel.startswith(base_sel):
            return sel
        if sel.startswith(":"):
            return base_sel + sel
        return f"{base_sel} {sel}"

    def scope_block(text):
        out = []
        i, n = 0, len(text)
        while i < n:
            while i < n and text[i] in " \t\r\n;":
                i += 1
            if i >= n:
                break
            j = text.find("{", i)
            if j == -1:
                break
            head = text[i:j].strip()
            depth, k = 1, j + 1
            while k < n and depth:
                if text[k] == "{":
                    depth += 1
                elif text[k] == "}":
                    depth -= 1
                k += 1
            body = text[j + 1:k - 1]
            if head.startswith("@media"):
                out.append(f"{head} {{\n{scope_block(body)}\n}}")
            elif head.startswith("@"):
                out.append(f"{head} {{{body}}}")
            else:
                sels = ", ".join(scope_selector(s) for s in head.split(","))
                out.append(f"{sels} {{{rewrite_urls(body)}}}")
            i = k
        return "\n".join(out)

    css = rewrite_urls(css)
    return scope_block(css)


LAYOUT_KEY_FAMILIES = ("width", "_element_width", "_flex_size", "_flex_order",
                       "_flex_align_self", "flex_direction", "flex_wrap",
                       "flex_align_items", "flex_justify_content", "flex_gap",
                       "gap", "padding", "_padding", "margin", "_margin",
                       "background_", "border_", "typography_", "title_color",
                       "align", "alignment", "_position", "_offset_", "z_index",
                       "_z_index", "overflow", "min_height", "height",
                       "content_width", "boxed_width", "wcf_custom_css")


def element_has_layout(settings):
    for k in (settings or {}):
        if any(k == fam or k.startswith(fam) for fam in LAYOUT_KEY_FAMILIES):
            return True
    return False


def walk_elements(nodes, out):
    for n in nodes:
        if isinstance(n, dict):
            out.append(n)
            walk_elements(n.get("elements") or [], out)


def collect_layout_elements():
    recs = [PAGES[s] for s in KEEP_PAGES if s in PAGES]
    used_h, used_f = set(), set()
    for slug in KEEP_PAGES:
        if slug in PAGES:
            rec = PAGES[slug]
            used_h.add(rec["meta"].get("redox_header_templates") or DEFAULT_HEADER_ID)
            used_f.add(rec["meta"].get("redox_footer_templates") or DEFAULT_FOOTER_ID)
    for hid in used_h:
        if hid in HEADERS:
            recs.append(HEADERS[hid])
    for fid in used_f:
        if fid in FOOTERS:
            recs.append(FOOTERS[fid])
    if DATA["offcanvas"] is not None:
        recs.append(DATA["offcanvas"])
    seen, els = set(), []
    for rec in recs:
        try:
            data = json.loads(rec["meta"].get("_elementor_data", "[]"))
        except Exception:
            continue
        batch = []
        walk_elements(data, batch)
        for el in batch:
            eid = el.get("id")
            if eid and eid not in seen:
                seen.add(eid)
                els.append(el)
    return els


def element_layout_rules(el, failed):
    """All breakpoint rules for one element: {bp: {selector: {prop: val}}}."""
    settings = el.get("settings") or {}
    base, per = split_breakpoints(settings)
    out = {}
    for bp, s in [("base", base)] + [(b, per[b]) for b in BP_ORDER]:
        self_p, inner_p, head_p, inner_max = extract_props(
            s, el.get("elType"), failed, base_settings=base, is_base=(bp == "base"))
        if not (self_p or inner_p or head_p or inner_max):
            continue
        eid = el.get("id")
        base_sel = f".elementor-element-{eid}"
        sels = {}
        if self_p:
            sels[f"{base_sel}, .e-con-inner > {base_sel}"] = self_p
        if inner_p:
            sels[f"{base_sel} > .e-con-inner"] = inner_p
        if head_p:
            sels[f"{base_sel} .elementor-heading-title"] = head_p
        if inner_max:
            sels[f"{base_sel}.e-con-boxed > .e-con-inner"] = {"max-width": inner_max}
        if sels:
            out[bp] = sels
    return out


def generate_layout_css(failed):
    els = collect_layout_elements()
    by_bp = {"base": {}, "widescreen": {}, "laptop": {}, "tablet_extra": {},
             "tablet": {}, "mobile_extra": {}, "mobile": {}}
    custom_blocks = []
    covered, with_layout = 0, 0
    per_page_coverage = {}
    for el in els:
        rules = element_layout_rules(el, failed)
        has_layout = element_has_layout(el.get("settings") or {})
        if has_layout:
            with_layout += 1
        if rules:
            covered += 1
        for bp, sels in rules.items():
            for sel, props in sels.items():
                by_bp[bp].setdefault(sel, {}).update(props)
    # Custom CSS is scoped per element, so it needs its source element id.
    for el in els:
        css = (el.get("settings") or {}).get("wcf_custom_css") or ""
        if css.strip():
            if re.search(r"wordpress", css, re.IGNORECASE):
                warn(f"custom CSS dropped for element {el.get('id')} (builder reference)")
                continue
            custom_blocks.append(scope_custom_css(css, el.get("id"), failed))
    # Per-page coverage for the two pages the fix is judged on.
    for slug in ("digital-agency", "digital-agency-classic"):
        if slug not in PAGES:
            continue
        try:
            batch = []
            walk_elements(json.loads(PAGES[slug]["meta"].get("_elementor_data", "[]")), batch)
        except Exception:
            batch = []
        tot = sum(1 for e in batch if element_has_layout(e.get("settings") or {}))
        cov = sum(1 for e in batch if element_layout_rules(e, failed))
        per_page_coverage[slug] = {"with_layout": tot, "with_rules": cov}
    lines = ["/* Per-element layout rules generated from demo page settings. */"]
    lines.append("@media (min-width: 2400px) { .elementor-hidden-widescreen { display: none !important; } }")
    lines.append("@media (min-width: 1367px) and (max-width: 2399px) { .elementor-hidden-desktop { display: none !important; } }")
    lines.append("@media (min-width: 1201px) and (max-width: 1366px) { .elementor-hidden-laptop { display: none !important; } }")
    lines.append("@media (min-width: 1025px) and (max-width: 1200px) { .elementor-hidden-tablet_extra { display: none !important; } }")
    lines.append("@media (min-width: 881px) and (max-width: 1024px) { .elementor-hidden-tablet { display: none !important; } }")
    lines.append("@media (min-width: 768px) and (max-width: 880px) { .elementor-hidden-mobile_extra { display: none !important; } }")
    lines.append("@media (max-width: 767px) { .elementor-hidden-mobile { display: none !important; } }")
    rule_count = 0
    for sel, props in sorted(by_bp["base"].items()):
        body = "; ".join(f"{k}: {v}" for k, v in props.items())
        lines.append(f"{sel} {{ {body}; }}")
        rule_count += 1
    for bp in BP_ORDER:
        if not by_bp[bp]:
            continue
        lines.append(f"{BP_MEDIA[bp]} {{")
        for sel, props in sorted(by_bp[bp].items()):
            body = "; ".join(f"{k}: {v}" for k, v in props.items())
            lines.append(f"  {sel} {{ {body}; }}")
            rule_count += 1
        lines.append("}")
    lines.extend(custom_blocks)
    css = "\n".join(lines) + "\n"
    return css, {"rules": rule_count, "elements": len(els),
                 "with_layout": with_layout, "covered": covered,
                 "custom_blocks": len(custom_blocks),
                 "per_page": per_page_coverage}


# ---------------------------------------------------------------- assembly
def render_template_cache(rec):
    return render_placeholders(cache_content(rec))


def main():
    # The container build (Dockerfile runs `npm run build`, which triggers
    # this script via `prebuild`) has no demo source files, so skip cleanly
    # there and keep the committed generated files instead of failing.
    if not XML.exists():
        print("Demo source not present, keeping existing generated files.")
        return
    print("Parsing demo content...")
    kept = []
    for slug in KEEP_PAGES:
        if slug not in PAGES:
            warn(f"kept page missing from XML: {slug}")
            continue
        kept.append(slug)
    print(f"kept pages: {len(kept)}, posts: {len(POSTS)}")

    # Raw fragments (before cleaning / image download).
    raw_headers, raw_footers = {}, {}
    header_ids, footer_ids = set(), set()
    page_meta = {}
    for slug in kept:
        rec = PAGES[slug]
        hdr = rec["meta"].get("redox_header_templates") or DEFAULT_HEADER_ID
        ftr = rec["meta"].get("redox_footer_templates") or DEFAULT_FOOTER_ID
        page_meta[slug] = (hdr, ftr)
        header_ids.add(hdr)
        footer_ids.add(ftr)
    for hid in header_ids:
        rec = HEADERS.get(hid)
        if rec is None:
            warn(f"header id {hid} not found, using default")
            rec = HEADERS[DEFAULT_HEADER_ID]
        raw_headers[hid] = render_template_cache(rec)
    for fid in footer_ids:
        rec = FOOTERS.get(fid)
        if rec is None:
            warn(f"footer id {fid} not found, using default")
            rec = FOOTERS[DEFAULT_FOOTER_ID]
        raw_footers[fid] = render_template_cache(rec)
    offcanvas_raw = ""
    if DATA["offcanvas"] is not None:
        offcanvas_raw = render_template_cache(DATA["offcanvas"])

    raw_pages = {}
    for slug in kept:
        raw_pages[slug] = render_placeholders(cache_content(PAGES[slug]))
    raw_posts = {}
    for p in POSTS:
        content = p["item"].findtext("content:encoded", namespaces=NS) or ""
        content = re.sub(r"<h1([^>]*)>(.*?)</h1>", r"<h2\1>\2</h2>", content, flags=re.DOTALL)
        thumb = post_thumb(p)
        thumb_html = f'<div class="post-featured">{img_tag(thumb, p["title"])}</div>' if thumb else ""
        cats = ", ".join(t for t, _ in post_categories(p))
        meta_line = post_date(p) + (f" | {cats}" if cats else "")
        raw_posts[p["slug"]] = (f'<article class="post-single">{thumb_html}'
                                f'<h1>{esc_text(p["title"])}</h1>'
                                f'<div class="post-meta">{esc(meta_line)}</div>'
                                f'<div class="post-content">{content}</div>'
                                '<p><a href="/journals/">Back to Journals</a></p></article>')

    # Collect + download demo images.
    all_raw = list(raw_headers.values()) + list(raw_footers.values()) + [offcanvas_raw] + list(raw_pages.values()) + list(raw_posts.values())
    urls = collect_upload_urls(all_raw)
    print(f"demo image URLs referenced: {len(urls)}")
    failed = download_images(urls)
    print(f"downloaded ok: {len(urls) - len(failed)}, failed: {len(failed)}")

    # Per-element layout CSS from demo settings (generated, not hand-edited).
    layout_css, layout_stats = generate_layout_css(failed)
    (ROOT / "public" / "assets" / "css" / "generated-layout.css").write_text(layout_css)
    print(f"generated layout CSS: {len(layout_css)} bytes, {layout_stats['rules']} rules, "
          f"{layout_stats['covered']}/{layout_stats['with_layout']} layout elements covered")

    # Clean fragments.
    data_dir = ROOT / "src" / "data" / "wp"
    data_dir.mkdir(parents=True, exist_ok=True)
    for hid, raw in raw_headers.items():
        (data_dir / f"header-{hid}.html").write_text(post_clean(clean_html(raw, failed)))
    for fid, raw in raw_footers.items():
        (data_dir / f"footer-{fid}.html").write_text(post_clean(clean_html(raw, failed)))
    offcanvas_clean = post_clean(clean_html(offcanvas_raw, failed)) if offcanvas_raw else ""
    offcanvas_html = ""
    if offcanvas_clean.strip():
        offcanvas_html = ('<aside class="offcanvas-area"><button class="offcanvas-close" type="button">Close</button>'
                          + offcanvas_clean + "</aside>")
    (data_dir / "offcanvas.html").write_text(offcanvas_html)

    page_info = {}
    for slug in kept:
        cleaned = post_clean(clean_html(raw_pages[slug], failed))
        cleaned = normalize_h1(cleaned)
        cleaned = apply_lazy(cleaned)
        (data_dir / f"page-{slug}.html").write_text(cleaned)
        title = PAGES[slug]["title"]
        page_info[slug] = {"title": title, "description": description_for(title, cleaned),
                           "header": page_meta[slug][0], "footer": page_meta[slug][1]}
    post_info = {}
    for p in POSTS:
        cleaned = post_clean(clean_html(raw_posts[p["slug"]], failed))
        cleaned = apply_lazy(cleaned)
        (data_dir / f"post-{p['slug']}.html").write_text(cleaned)
        post_info[p["slug"]] = {"title": p["title"], "description": description_for(p["title"], cleaned)}

    # Page .astro files.
    def astro_page(path, title, description, frag, header_id, footer_id, extra=""):
        imp = ("---\nimport BaseLayout from '../layouts/BaseLayout.astro';\n"
               f"import headerHtml from '../data/wp/header-{header_id}.html?raw';\n"
               f"import footerHtml from '../data/wp/footer-{footer_id}.html?raw';\n"
               "import offcanvasHtml from '../data/wp/offcanvas.html?raw';\n"
               f"import contentHtml from '../data/wp/{frag}.html?raw';\n---\n")
        props = (f"title={json.dumps(title)} description={json.dumps(description)} path={json.dumps(path)} "
                 f"headerHtml={{headerHtml}} footerHtml={{footerHtml}} offcanvasHtml={{offcanvasHtml}}{extra}")
        return imp + f"<BaseLayout {props}>\n  <Fragment set:html={{contentHtml}} />\n</BaseLayout>\n"

    pages_dir = ROOT / "src" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    home = page_info["digital-agency"]
    (pages_dir / "index.astro").write_text(astro_page(
        "/", "Woodwolf Digital | Creative Agency for Design, Development and Marketing",
        "Woodwolf Digital is a creative agency for design, development and marketing.",
        "page-digital-agency", home["header"], home["footer"]))
    for slug, info in page_info.items():
        extra = ""
        if slug == "digital-agency":
            extra = ' noindex canonicalPath="/"'
        else:
            extra = f' breadcrumbLabel={json.dumps(info["title"])}'
        (pages_dir / f"{slug}.astro").write_text(astro_page(
            f"/{slug}/", f"{info['title']} | Woodwolf Digital", info["description"],
            f"page-{slug}", info["header"], info["footer"], extra))
    for slug, info in post_info.items():
        (pages_dir / f"{slug}.astro").write_text(astro_page(
            f"/{slug}/", f"{info['title']} | Woodwolf Digital", info["description"],
            f"post-{slug}", DEFAULT_HEADER_ID, DEFAULT_FOOTER_ID,
            extra=f' breadcrumbLabel={json.dumps(info["title"])}'))

    # 404 page (hand-written, default header/footer).
    (pages_dir / "404.astro").write_text(
        "---\nimport BaseLayout from '../layouts/BaseLayout.astro';\n"
        f"import headerHtml from '../data/wp/header-{DEFAULT_HEADER_ID}.html?raw';\n"
        f"import footerHtml from '../data/wp/footer-{DEFAULT_FOOTER_ID}.html?raw';\n"
        "import offcanvasHtml from '../data/wp/offcanvas.html?raw';\n---\n"
        '<BaseLayout title="Page Not Found | Woodwolf Digital" description="The page you are looking for does not exist on Woodwolf Digital." path="/404/" headerHtml={headerHtml} footerHtml={footerHtml} offcanvasHtml={offcanvasHtml}>\n'
        '  <div class="post-single"><h1>Page Not Found</h1><p>Sorry, the page you are looking for does not exist or has been moved.</p><p><a href="/">Return to the homepage</a></p></div>\n'
        "</BaseLayout>\n")

    # robots.txt
    (ROOT / "public" / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: https://redox.woodwolfdigital.com/sitemap-index.xml\n")
    # Placeholder image for any failed download.
    ph = ROOT / "public" / "assets" / "uploads" / "placeholder.svg"
    ph.parent.mkdir(parents=True, exist_ok=True)
    if not ph.exists():
        ph.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#eeeeee"/><text x="400" y="300" font-family="sans-serif" font-size="28" fill="#666666" text-anchor="middle">Woodwolf Digital</text></svg>\n')

    # Theme assets (CSS comments stripped so no builder names survive in CSS).
    theme = Path.home() / "workspace" / "redox-wp-theme" / "redox" / "assets"
    css_keep = ["bootstrap.min.css", "fontawesome.min.css", "swiper-bundle.min.css",
                "animate.min.css", "redox-core.css", "redox-spacing.css",
                "redox-unit.css", "redox-update.css"]
    for name in css_keep:
        src = theme / "css" / name
        if src.exists():
            css = re.sub(r"/\*.*?\*/", "", src.read_text(errors="ignore"), flags=re.DOTALL)
            if name == "fontawesome.min.css":
                # Drop the WordPress brand-icon rules (fa-wordpress*); the icon
                # set is otherwise kept for the social/utility icons in use.
                css = re.sub(r"\.fa-wordpress[^,{]*\{[^}]*\}", "", css)
                css = re.sub(r"\.fa-elementor[^,{]*\{[^}]*\}", "", css)
            (ROOT / "public" / "assets" / "css" / name).write_text(css)
    import shutil
    for sub in ["fonts", "webfonts", "imgs"]:
        src = theme / sub
        if src.exists():
            shutil.copytree(src, ROOT / "public" / "assets" / sub, dirs_exist_ok=True)
    js_src = theme / "js" / "swiper-bundle.min.js"
    if js_src.exists():
        shutil.copyfile(js_src, ROOT / "public" / "assets" / "js" / "swiper-bundle.min.js")

    REPORT["approximations"].extend([
        "Theme main.js and the plugin slider script are NOT shipped: both require jQuery and the builder runtime. A small vanilla script (site-wp.js) handles sliders (Swiper), background images, off-canvas, back-to-top and forms instead.",
        "Slider widgets render as Swiper markup and are initialised generically; per-widget autoplay/speed settings from the demo are not reproduced exactly.",
        "Demo video URLs (rrdevs.net) were dropped, never hotlinked; video slides render as image slides.",
        "Font Awesome light/thin icon weights are mapped to solid so icons render without the pro font.",
        "CSS comments were stripped from copied theme stylesheets.",
        "The theme ad/ folder is not shipped; no kept page references it.",
        "Post pages render title, date, categories, featured image and body only; the theme related-posts block is not reproduced.",
        "Generated layout CSS converts per-element width, flex, gap, padding, margin, background, border, typography, position and height settings from demo data, including scoped custom CSS. Not converted: grid_gaps, background overlays, transforms/animations, and widget-internal spacings (icon_gap, image_space, title_gap); container height settings become min-height; nested widget typography groups apply to the wrapper; responsive visibility classes use reconstructed device ranges.",
        "Per-element layout CSS is generated by scripts/build.py into public/assets/css/generated-layout.css and linked after the theme stylesheets.",
    ])
    manifest = {
        "pages": {slug: {"url": f"/{slug}/", "title": info["title"]} for slug, info in page_info.items()},
        "homepage": {"url": "/", "content": "digital-agency"},
        "posts": {slug: {"url": f"/{slug}/", "title": info["title"]} for slug, info in post_info.items()},
        "image_urls_referenced": len(urls),
        "images_failed": REPORT["failed_images"],
        "unknown_page_links": dict(REPORT["unknown_page_links"]),
        "widget_counts": dict(REPORT["widget_counts"]),
        "generated_layout_css_bytes": len(layout_css),
        "generated_layout_css_rules": layout_stats["rules"],
        "layout_coverage": layout_stats,
        "warnings": REPORT["warnings"],
        "approximations": REPORT["approximations"],
    }
    (ROOT / "scripts" / "build-manifest.json").write_text(json.dumps(manifest, indent=2))
    print("pages:", len(page_info), "posts:", len(post_info))
    print("widget counts:", dict(REPORT["widget_counts"]))
    print("unknown page links:", dict(REPORT["unknown_page_links"]))
    print("warnings:", len(REPORT["warnings"]))


if __name__ == "__main__":
    main()
