"""Daily plan: pick today's topic + variant and get fresh Azerbaijani copy from an LLM.

Copy provider (env LLM_PROVIDER = anthropic | openai; default: whichever key is set,
Anthropic first):
  anthropic → ANTHROPIC_API_KEY, model CLAUDE_MODEL (default claude-opus-5-5)
  openai    → OPENAI_API_KEY,    model OPENAI_MODEL (default gpt-5.5)

Deterministic by date (Asia/Baku), so a re-run of the same day gives the same video
variant. If the LLM call fails or returns text that breaks the on-screen limits,
the topic's default texts from content/calendar.yaml are used instead.
"""
import datetime as dt
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import openai
import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
BAKU = ZoneInfo("Asia/Baku")
EPOCH = dt.date(2026, 1, 1)
PALETTE_CYCLE = ["sunset", "morning", "night"]
TRANSPOSE_CYCLE = [0, 2, -3, 5, -2]
LIMITS = {"hook": 22, "journey_1": 20, "journey_2": 24, "cover_title": 34}
FINAL_LIMIT = 26
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL") or "claude-opus-5-5"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-5.5"

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


SYSTEM = """Sən Yük.az (Azərbaycanda yükdaşıma və köçürmə şirkəti) üçün Instagram/Facebook Reels mətnləri yazan kopirayterisən.
Yalnız Azərbaycan dilində (latın əlifbası, düzgün ə, ı, ö, ü, ş, ç, ğ) yaz. Ton: isti, sakit, inamlı, qısa. Emoji az (caption-da maksimum 3).

Qaydalar:
- YALNIZ verilən faktlardan istifadə et. Rəqəm, endirim, qiymət, müddət, statistika uydurma.
- Ekran mətnləri çox qısa olmalıdır (videoda göstərilir, göz yormamalıdır):
  hook ≤ 22 simvol (sual və ya maraq oyadan qısa cümlə),
  journey_1 ≤ 20 və journey_2 ≤ 24 simvol (iki sətirlik bir fikir; journey_1 adətən "—" ilə bitir),
  final_1 + final_2 birlikdə ≤ 26 simvol (final_2 vurğulanan söz/ifadədir, nöqtə ilə bitir).
- cover_title ≤ 34 simvol, cover üçün 2-5 sözlük cəlbedici başlıq.
- caption: 3-5 qısa abzas. Birinci sətir diqqət çəkən hook. Sonda zəng/WhatsApp çağırışı, telefon nömrəsi və "Yükünüz bizə əmanət!" şüarı. Hashtag-ləri caption-a YAZMA.
- hashtags: 6-10 ədəd, # ilə, Azərbaycan dilində və yerli (#yükdaşıma #köçürmə #bakı kimi), həmişə #yukaz daxil."""


def load_calendar():
    with open(ROOT / "content" / "calendar.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def today_baku() -> dt.date:
    return dt.datetime.now(BAKU).date()


def _default_copy(brand, topic):
    t = topic["texts"]
    caption = (
        f"{t['hook']}\n\n{topic['brief']}\n\n"
        f"📞 {brand['phone']} — zəng edin və ya WhatsApp-a yazın.\n\n{brand['slogan']}"
    )
    return {
        **t,
        "cover_title": t["hook"],
        "caption": caption,
        "hashtags": ["#yukaz", "#yükdaşıma", "#köçürmə", "#evköçürmə", "#bakı", "#azərbaycan"],
    }


def _valid(copy: dict) -> list[str]:
    bad = [k for k, n in LIMITS.items() if not copy.get(k) or len(copy[k]) > n]
    if not copy.get("final_1") or not copy.get("final_2") or len(copy["final_1"]) + len(copy["final_2"]) + 1 > FINAL_LIMIT:
        bad.append("final")
    if not copy.get("caption") or len(copy["caption"]) > 1800:
        bad.append("caption")
    return bad


def provider() -> str | None:
    choice = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if choice in ("anthropic", "openai"):
        return choice
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _user_prompt(brand, topic, date: dt.date) -> str:
    facts = "\n".join(f"- {f}" for f in brand["facts"])
    user = (
        f"Tarix: {date.isoformat()}\n"
        f"Bugünkü mövzu: {topic['brief']}\n"
        f"Videoda göstərilən otaq: {topic['room_set']}\n"
        f"Telefon: {brand['phone']} · WhatsApp: {brand['whatsapp']} · Sayt: {brand['website']}\n"
        f"Brend faktları:\n{facts}\n\n"
        f"Nümunə ekran mətnləri (eyni ruhda, amma təzə yaz): {topic['texts']}\n"
        "Videonun hekayəsi: köhnə evdə əşyalar qutuya uçur → qutu Yük.az kubuna çevrilib yolda hoppanır "
        "(journey mətnləri burada görünür) → yeni evdə hər şey yerinə düşür (final mətni) → loqo."
    )


def ask_claude(user: str) -> dict | None:
    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=DailyCopy,
        )
    except anthropic.APIStatusError as e:
        log.error("Claude API error %s: %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError as e:
        log.error("Claude connection error: %s", e)
        return None
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.error("Claude returned no usable output (stop_reason=%s)", response.stop_reason)
        return None
    return response.parsed_output.model_dump()


def ask_openai(user: str) -> dict | None:
    client = openai.OpenAI()
    try:
        completion = client.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            response_format=DailyCopy,
        )
    except openai.APIStatusError as e:
        log.error("OpenAI API error %s: %s", e.status_code, e.message)
        return None
    except openai.APIConnectionError as e:
        log.error("OpenAI connection error: %s", e)
        return None
    msg = completion.choices[0].message
    if msg.refusal or msg.parsed is None:
        log.error("OpenAI returned no usable output (refusal=%s)", msg.refusal)
        return None
    return msg.parsed.model_dump()


def ask_llm(brand, topic, date: dt.date) -> tuple[dict | None, str | None]:
    prov = provider()
    if prov is None:
        log.warning("no LLM key set (ANTHROPIC_API_KEY / OPENAI_API_KEY) — using calendar defaults")
        return None, None
    user = _user_prompt(brand, topic, date)
    if prov == "anthropic":
        return ask_claude(user), CLAUDE_MODEL
    return ask_openai(user), OPENAI_MODEL


def make_plan(date: dt.date | None = None) -> dict:
    date = date or today_baku()
    cal = load_calendar()
    brand, topics = cal["brand"], cal["topics"]
    day = (date - EPOCH).days
    topic = topics[day % len(topics)]

    default = _default_copy(brand, topic)
    copy, model = ask_llm(brand, topic, date)
    source = provider() or "calendar"
    if copy is None:
        copy, source = default, "calendar"
    else:
        bad = _valid(copy)
        if bad:
            log.warning("LLM copy broke limits %s — falling back for those fields", bad)
            for k in bad:
                if k == "final":
                    copy["final_1"], copy["final_2"] = default["final_1"], default["final_2"]
                else:
                    copy[k] = default[k]
            source += "+defaults"
    tags = [t if t.startswith("#") else f"#{t}" for t in copy["hashtags"]][:10]
    if "#yukaz" not in tags:
        tags.insert(0, "#yukaz")

    return {
        "date": date.isoformat(),
        "topic": topic["id"],
        "room_set": topic["room_set"],
        "palette": PALETTE_CYCLE[day % len(PALETTE_CYCLE)],
        "transpose": TRANSPOSE_CYCLE[day % len(TRANSPOSE_CYCLE)],
        "seed": int(date.strftime("%Y%m%d")),
        "phone": brand["phone"],
        "texts": {k: copy[k] for k in ("hook", "journey_1", "journey_2", "final_1", "final_2")},
        "cover_title": copy["cover_title"],
        "caption": copy["caption"].strip() + "\n\n" + " ".join(tags),
        "copy_source": source,
        "model": model if source != "calendar" else None,
    }
