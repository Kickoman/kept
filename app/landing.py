"""Landing pages rendered on the server, one URL per language: /, /ru/, /be/.

The rest of the UI is translated in the browser (static/js/i18n). The landing is
rendered here so that search engines and link previews get real text, a proper
<html lang> and hreflang links between the language versions.
"""
from __future__ import annotations

import html
import json

LANGS = ("en", "ru", "be")
PATHS = {"en": "/", "ru": "/ru/", "be": "/be/"}
OG_LOCALES = {"en": "en_US", "ru": "ru_RU", "be": "be_BY"}

TEXTS: dict[str, dict] = {
    "en": {
        "title": "Wishlist with gift reservations · Kept",
        "description": "Make a wishlist and send the link to friends. They reserve gifts so nobody buys the same thing twice, "
        "and you don't see what's been reserved.",
        "h1": "Just a wishlist.",
        "start": "Start a list",
        "signin": "Sign in",
        "mylists": "My lists",
        "how": "How it works",
        "steps": [
            ("Add what you'd like to get", "Paste a link to the product: the name, photo and description are filled in for you."),
            ("Send the list's link to friends and family", "They can open it without an account, and it won't show up in search."),
            ("Friends reserve what they'll give", "They see what's already taken. You don't."),
        ],
        "faq": "Questions",
        "questions": [
            ("Will I see who reserved what?",
             "No. You won't even see whether anything is reserved. Guests see how many are taken, but not who took them."),
            ("Do guests need an account?",
             "Not to open the list. To reserve a gift they need to sign in, so they can cancel the reservation later from any device."),
            ("Can I have several lists?",
             "Yes. For example, one for your birthday and one for New Year. Each list has its own link."),
        ],
    },
    "ru": {
        "title": "Вишлист с бронированием подарков · Kept",
        "description": "Составьте список желаний и отправьте ссылку друзьям. Они бронируют подарки, чтобы никто не купил "
        "одно и то же, а вы не видите, что уже забронировано.",
        "h1": "Просто вишлист.",
        "start": "Создать список",
        "signin": "Войти",
        "mylists": "Мои списки",
        "how": "Как это работает",
        "steps": [
            ("Добавьте, что хотели бы получить", "Вставьте ссылку на товар: название, фото и описание подтянутся сами."),
            ("Отправьте ссылку на список друзьям и родным", "Открыть его можно без регистрации, в поиске он не появится."),
            ("Друзья бронируют то, что подарят", "Они видят, что уже занято, а вы — нет."),
        ],
        "faq": "Вопросы",
        "questions": [
            ("Увижу ли я, кто что забронировал?",
             "Нет. Вы не увидите даже, забронировано ли что-нибудь. Гости видят, сколько штук уже заняли, но не видят, кто именно."),
            ("Нужна ли гостям регистрация?",
             "Открыть список можно без регистрации. Чтобы забронировать подарок, нужно войти: так бронь можно отменить с любого устройства."),
            ("Можно сделать несколько списков?",
             "Да. Например, отдельный список на день рождения и на Новый год. У каждого своя ссылка."),
        ],
    },
    "be": {
        "title": "Вішліст з браніраваннем падарункаў · Kept",
        "description": "Складзіце спіс жаданняў і адпраўце спасылку сябрам. Яны браніруюць падарункі, каб ніхто не купіў "
        "адно і тое ж, а вы не бачыце, што ўжо заброніравана.",
        "h1": "Проста вішліст.",
        "start": "Стварыць спіс",
        "signin": "Увайсці",
        "mylists": "Мае спісы",
        "how": "Як гэта працуе",
        "steps": [
            ("Дадайце тое, што хацелі б атрымаць", "Устаўце спасылку на тавар: назва, фота і апісанне падцягнуцца самі."),
            ("Адпраўце спасылку на спіс сябрам і родным", "Адкрыць яго можна без рэгістрацыі, у пошуку ён не з'явіцца."),
            ("Сябры браніруюць тое, што падораць", "Яны бачаць, што ўжо занята, а вы — не."),
        ],
        "faq": "Пытанні",
        "questions": [
            ("Ці ўбачу я, хто што забраніраваў?",
             "Не. Вы нават не ўбачыце, ці заброніравана што-небудзь. Госці бачаць, колькі ўжо занята, але не бачаць, хто менавіта."),
            ("Ці трэба гасцям рэгістравацца?",
             "Адкрыць спіс можна без рэгістрацыі. Каб забраніраваць падарунак, трэба ўвайсці: так браню можна адмяніць з любой прылады."),
            ("Ці можна зрабіць некалькі спісаў?",
             "Так. Напрыклад, асобны спіс на дзень нараджэння і на Новы год. У кожнага свая спасылка."),
        ],
    },
}

# Sends visitors who land on "/" to their language version. Mirrors detectLang() in
# static/js/i18n.js: a choice made with the language switcher wins; otherwise a Russian
# or Belarusian browser decides, and a Russian one in the Minsk time zone gets Belarusian.
# Only humans are redirected: crawlers render pages with an English browser.
LANG_REDIRECT = (
    '<script>(function(){var l;try{l=localStorage.getItem("kept.lang");}catch(e){}'
    'if(!l){var n=(navigator.language||"").toLowerCase(),z="";'
    "try{z=Intl.DateTimeFormat().resolvedOptions().timeZone;}catch(e){}"
    'l=n.indexOf("be")===0?"be":n.indexOf("ru")===0?(z==="Europe/Minsk"?"be":"ru"):"en";}'
    'if(l==="ru"||l==="be")location.replace("/"+l+"/");})();</script>'
)


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def alternates(base: str) -> list[tuple[str, str]]:
    """(hreflang, absolute URL) pairs for every language version, plus x-default."""
    pairs = [(lang, base + PATHS[lang]) for lang in LANGS]
    return pairs + [("x-default", base + PATHS["en"])]


def _json_ld(base: str, lang: str, url: str, description: str) -> str:
    data = [
        {"@context": "https://schema.org", "@type": "WebSite", "name": "Kept", "url": base + "/", "inLanguage": lang},
        {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            "name": "Kept",
            "url": url,
            "description": description,
            "applicationCategory": "LifestyleApplication",
            "operatingSystem": "Any",
            "inLanguage": lang,
        },
    ]
    # "</" inside a <script> block would end it early.
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def render(template: str, lang: str, base: str, signed_in: bool) -> str:
    tx = TEXTS[lang]
    url = base + PATHS[lang]
    head = [
        f'<meta name="description" content="{_e(tx["description"])}">',
        f'<link rel="canonical" href="{_e(url)}">',
        *(f'<link rel="alternate" hreflang="{code}" href="{_e(href)}">' for code, href in alternates(base)),
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Kept">',
        f'<meta property="og:title" content="{_e(tx["title"])}">',
        f'<meta property="og:description" content="{_e(tx["description"])}">',
        f'<meta property="og:url" content="{_e(url)}">',
        f'<meta property="og:image" content="{_e(f"{base}/static/img/og-{lang}.png")}">',
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
        f'<meta property="og:locale" content="{OG_LOCALES[lang]}">',
        *(f'<meta property="og:locale:alternate" content="{OG_LOCALES[o]}">' for o in LANGS if o != lang),
        '<meta name="twitter:card" content="summary_large_image">',
        f'<script type="application/ld+json">{_json_ld(base, lang, url, tx["description"])}</script>',
    ]
    if signed_in:
        actions = f'<a class="btn btn-primary btn-lg" href="/me">{_e(tx["mylists"])}</a>'
    else:
        actions = (
            f'<a class="btn btn-primary btn-lg" href="/register">{_e(tx["start"])}</a>'
            f'<a class="btn btn-secondary btn-lg" href="/login">{_e(tx["signin"])}</a>'
        )
    steps = "".join(
        f'<li class="card elev-sm"><span class="num">{i:02d}</span><h3 class="card-title">{_e(title)}</h3>'
        f'<p class="card-body">{_e(body)}</p></li>'
        for i, (title, body) in enumerate(tx["steps"], start=1)
    )
    questions = "".join(f"<div><h3>{_e(q)}</h3><p>{_e(a)}</p></div>" for q, a in tx["questions"])
    return (
        template.replace("{{LANG}}", lang)
        .replace("{{LANG_REDIRECT}}", LANG_REDIRECT if lang == "en" else "")
        .replace("{{TITLE}}", _e(tx["title"]))
        .replace("{{HEAD}}", "".join(head))
        .replace("{{H1}}", _e(tx["h1"]))
        .replace("{{LEDE}}", _e(tx["description"]))
        .replace("{{ACTIONS}}", actions)
        .replace("{{HOW}}", _e(tx["how"]))
        .replace("{{STEPS}}", steps)
        .replace("{{FAQ}}", _e(tx["faq"]))
        .replace("{{QUESTIONS}}", questions)
    )


def sitemap(base: str) -> str:
    links = "".join(f'<xhtml:link rel="alternate" hreflang="{code}" href="{_e(href)}"/>' for code, href in alternates(base))
    urls = "".join(f"<url><loc>{_e(base + PATHS[lang])}</loc>{links}</url>" for lang in LANGS)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f"{urls}</urlset>\n"
    )


def robots(base: str) -> str:
    # Shared lists (/w/) stay crawlable for search engines on purpose: they answer with
    # X-Robots-Tag: noindex, which a crawler only sees if robots.txt lets it fetch the page.
    # Crawlers that collect AI training data are kept away from them instead.
    return (
        "User-agent: *\n"
        "Disallow: /api/\n"
        "Disallow: /media/\n"
        "\n"
        "User-agent: GPTBot\n"
        "User-agent: ClaudeBot\n"
        "User-agent: CCBot\n"
        "User-agent: Google-Extended\n"
        "User-agent: Applebot-Extended\n"
        "User-agent: meta-externalagent\n"
        "Disallow: /w/\n"
        "Disallow: /api/\n"
        "Disallow: /media/\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
