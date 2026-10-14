"""Daily plan: pick today's topic + variant and get fresh Azerbaijani copy from an LLM.

Deterministic by date (Asia/Baku), so a re-run of the same day gives the same topic and
creative direction. If the LLM call fails or returns text that breaks the on-screen limits,
the topic's default texts from content/calendar.yaml are used instead.
"""
import datetime as dt
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel

from . import llm

ROOT = Path(__file__).resolve().parents[1]
BAKU = ZoneInfo("Asia/Baku")
EPOCH = dt.date(2026, 1, 1)
PALETTE_CYCLE = ["sunset", "morning", "night"]
TRANSPOSE_CYCLE = [0, 2, -3, 5, -2]
LIMITS = {"hook": 22, "journey_1": 20, "journey_2": 24, "cover_title": 34}
FINAL_LIMIT = 26

log = logging.getLogger(__name__)


class DailyCopy(BaseModel):
    hook: str
    journey_1: str
    journey_2: str
    final_1: str
    final_2: str
    cover_title: str
    caption: str
    hashtags: list[str]


CAPTION_EXAMPLE = """Köçmək düşündüyündən daha rahat ola bilər. 🚚✨

Yük.az ilə əşyaların sökülməsi, paketlənməsi, daşınması və yeni ünvanda yerləşdirilməsi bir prosesdə tamamlanır. 📦🏠

Yeni ünvana keçidi stresə çevirmə, qalanını biz həll edək. ❤️📍

Sifariş üçün bizə yaz və köçürüləcək ünvanı qeyd et. 📲"""

SYSTEM = f"""Sən Yük.az (Azərbaycanda yükdaşıma və köçürmə şirkəti) üçün Instagram/Facebook Reels mətnləri yazan kopirayterisən.
Yalnız Azərbaycan dilində (latın əlifbası, düzgün ə, ı, ö, ü, ş, ç, ğ) yaz. Ton: isti, sakit, inamlı, səmimi ("sən" müraciəti).

Qaydalar:
- YALNIZ verilən faktlardan istifadə et. Rəqəm, endirim, qiymət, müddət, statistika uydurma.
- Ekran mətnləri çox qısa olmalıdır (videoda göstərilir, göz yormamalıdır):
  hook ≤ 22 simvol (sual və ya maraq oyadan qısa cümlə),
  journey_1 ≤ 20 və journey_2 ≤ 24 simvol (iki sətirlik bir fikir; journey_1 adətən "—" ilə bitir),
  final_1 + final_2 birlikdə ≤ 26 simvol (final_2 vurğulanan söz/ifadədir, nöqtə ilə bitir).
- cover_title ≤ 34 simvol, cover üçün 2-5 sözlük cəlbedici başlıq.

caption — DƏQİQ bu üslubda yaz (struktur, uzunluq, boşluqlar, emoji istifadəsi eyni olsun, mətn isə bugünkü mövzuya uyğun TƏZƏ olsun):
---
{CAPTION_EXAMPLE}
---
caption qaydaları:
- 4 qısa abzas, aralarında BİR boş sətir.
- 1-ci abzas: bir cümləlik hook. 2-ci: xidmətin faydası (1-2 cümlə). 3-cü: emosional rahatlıq cümləsi. 4-cü: sifariş çağırışı (yaz / zəng et).
- Hər abzasın sonunda mətnin mənasına uyğun 1-2 emoji (🚚 📦 🏠 ✨ ❤️ 📍 📲 🛋️ 🔑 🧰 ⏰ 🛡️ 💬 kimi). Emoji abzasın ortasında olmasın.
- Hashtag-ləri caption-a YAZMA (ayrıca verilir).
hashtags: 5-6 ədəd, kiçik hərflə, Azərbaycan dilində, mövzuya uyğun; həmişə #yükaz və #yükdaşıma daxil (məs. #yükaz #yükdaşıma #evköçürmə #bakı #köçürülmə)."""


def load_calendar():
    with open(ROOT / "content" / "calendar.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def today_baku() -> dt.date:
    return dt.datetime.now(BAKU).date()


def _default_copy(brand, topic):
    t = topic["texts"]
    caption = (
        f"{t['hook']} 🚚✨\n\n{topic['brief']} 📦🏠\n\n"
        f"Yeni ünvana keçidi stresə çevirmə, qalanını biz həll edək. ❤️📍\n\n"
        f"Sifariş üçün bizə yaz və ya zəng et: {brand['phone']} 📲"
    )
    return {**t, "cover_title": t["hook"], "caption": caption,
            "hashtags": ["#yükaz", "#yükdaşıma", "#evköçürmə", "#bakı", "#köçürülmə"]}


def _valid(copy: dict) -> list[str]:
    bad = [k for k, n in LIMITS.items() if not copy.get(k) or len(copy[k]) > n]
    if not copy.get("final_1") or not copy.get("final_2") or len(copy["final_1"]) + len(copy["final_2"]) + 1 > FINAL_LIMIT:
        bad.append("final")
    if not copy.get("caption") or len(copy["caption"]) > 1500:
        bad.append("caption")
    return bad


def _user_prompt(brand, topic, date: dt.date) -> str:
    facts = "\n".join(f"- {f}" for f in brand["facts"])
    return (
        f"Tarix: {date.isoformat()}\n"
        f"Bugünkü mövzu: {topic['brief']}\n"
        f"Telefon: {brand['phone']} · WhatsApp: {brand['whatsapp']} · Sayt: {brand['website']}\n"
        f"Brend faktları:\n{facts}\n\n"
        f"Nümunə ekran mətnləri (eyni ruhda, amma təzə yaz): {topic['texts']}\n"
        "Videonun quruluşu: hook (ilk saniyələr) → mövzunun vizual hekayəsi (journey mətnləri) → "
        "nəticə anı (final mətni) → loqo və şüar."
    )


def make_plan(date: dt.date | None = None) -> dict:
    date = date or today_baku()
    cal = load_calendar()
    brand, topics = cal["brand"], cal["topics"]
    day = (date - EPOCH).days
    topic = topics[day % len(topics)]

    default = _default_copy(brand, topic)
    parsed = llm.structured(SYSTEM, _user_prompt(brand, topic, date), DailyCopy, max_tokens=4000)
    if parsed is None:
        copy, source, model = default, "calendar", None
    else:
        copy, source, model = parsed.model_dump(), llm.provider(), llm.model_name()
        bad = _valid(copy)
        if bad:
            log.warning("LLM copy broke limits %s — falling back for those fields", bad)
            for k in bad:
                if k == "final":
                    copy["final_1"], copy["final_2"] = default["final_1"], default["final_2"]
                else:
                    copy[k] = default[k]
            source += "+defaults"

    tags = []
    for t in copy["hashtags"]:
        t = "#" + t.lstrip("#").strip().lower().replace(" ", "")
        if t != "#" and t not in tags:
            tags.append(t)
    for must in ("#yükdaşıma", "#yükaz"):
        if must not in tags:
            tags.insert(0, must)
    caption = "\n\n".join(p.strip() for p in copy["caption"].strip().split("\n\n") if p.strip())

    return {
        "date": date.isoformat(),
        "day": day,
        "topic": topic["id"],
        "topic_brief": topic["brief"],
        "room_set": topic["room_set"],
        "palette": PALETTE_CYCLE[day % len(PALETTE_CYCLE)],
        "transpose": TRANSPOSE_CYCLE[day % len(TRANSPOSE_CYCLE)],
        "seed": int(date.strftime("%Y%m%d")),
        "phone": brand["phone"],
        "slogan": brand["slogan"],
        "texts": {k: copy[k] for k in ("hook", "journey_1", "journey_2", "final_1", "final_2")},
        "cover_title": copy["cover_title"],
        "caption": caption + "\n\n" + " ".join(tags[:7]),
        "copy_source": source,
        "model": model,
    }
