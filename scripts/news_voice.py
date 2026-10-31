"""The channel's voice: Ukrainian wording for the Telegram posts (scripts/news_cards.py).

Each kind of line has a few variants with the same placeholders, so neighbouring
weeks do not read the same. The choice is a hash of a seed (the post's date or
version), never random: a post drawn twice is the same post, and tests can name
the line they expect. Every number in a line comes from the post's data; the
wording only frames it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def pick(variants: Sequence[str], seed: str) -> str:
    """One of the variants, the same one for the same seed."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return variants[int.from_bytes(digest[:4], "big") % len(variants)]


def say(kind: str, seed: str, **values: str) -> str:
    return pick(LINES[kind], f"{kind}:{seed}").format(**values)


LINES: dict[str, tuple[str, ...]] = {
    # --- the meta of the week: one line per angle (news.meta_angles) ---------------
    "streak": (
        "{hero} — {weeks}-й тиждень поспіль на вершині: {win} перемог",
        "{hero} не віддає перше місце вже {weeks}-й тиждень: {win} перемог",
        "Знову {hero}: {weeks}-й тиждень поспіль найчастіше виграє, {win}",
    ),
    "trap": (
        "{hero} беруть у {pick} матчів, а виграє лише {win}",
        "{hero} у {pick} матчів тижня — і лише {win} перемог",
        "Популярний не означає сильний: {hero} у {pick} матчів, перемог {win}",
    ),
    "gem": (
        "{hero} виграє {win}, а беруть його лише в {pick} матчів",
        "Тихий сильний пік: {hero} — {win} перемог при {pick} матчів",
    ),
    "rise": (
        "{hero} злетів на {delta} {when}: тепер {win} перемог",
        "{hero} додав {delta} перемог {when} — уже {win}",
    ),
    "fall": (
        "{hero} просів на {delta} {when}: тепер {win} перемог",
        "{hero} втратив {delta} перемог {when} — лише {win}",
    ),
    "patch_rise": (
        "Після патча {patch} {hero} виграє більше: +{delta} {when}, тепер {win}",
        "Патч {patch} пішов на користь {hero}: +{delta} перемог {when}",
    ),
    "patch_fall": (
        "Після патча {patch} {hero} виграє менше: −{delta} {when}, тепер {win}",
        "Патч {patch} вдарив по {hero}: −{delta} перемог {when}",
    ),
    "picked_more": (
        "{hero} беруть частіше: {pick} матчів, на {delta} більше, ніж тиждень тому",
        "На {hero} підсіли: уже {pick} матчів, +{delta} за тиждень",
    ),
    "picked_less": (
        "{hero} беруть рідше: {pick} матчів, на {delta} менше, ніж тиждень тому",
        "Від {hero} відвертаються: {pick} матчів, −{delta} за тиждень",
    ),
    "quiet": (
        "Тихий тиждень: жоден герой не зрушив у перемогах більше ніж на {min}",
        "Мета застигла: за тиждень ніхто не змінився більше ніж на {min} перемог",
    ),
    "top": (
        "Найчастіше виграє {hero}: {win}",
        "{hero} — найсильніший тижня: {win} перемог",
    ),
    "meta_cta": (
        "Хто з них у вашому драфті — Wardly підкаже предмети проти нього просто в матчі.",
        "Граєте проти них? Wardly в матчі скаже, що збирати.",
        "Wardly підкаже темп і предмети просто в матчі — безкоштовно.",
    ),
    # --- the hero of the week ------------------------------------------------------
    "hero_counter": (
        "Проти {against} {hero} без {item} виграє {without}. З {item} — {with_}.",
        "{item} проти {against}: {with_} перемог проти {without} без нього.",
    ),
    "hero_skills": (
        "Першим {first}? {alt} перемог. Першим {top} — {win}.",
        "{top} першим виграє {win}, {first} першим — лише {alt}.",
    ),
    "hero_tempo": (
        "{net_worth} нетворсу на {minute}:00 — і гру виграно в {win} випадків.",
        "Є {net_worth} на {minute}:00? Такі ігри {hero} виграє у {win}.",
    ),
    "hero_plain": (
        "{hero} цього тижня у {pick} матчів і виграє {win}.",
        "{win} перемог у {pick} матчів — {hero} цього тижня в формі.",
    ),
    "hero_cta": (
        "Wardly покаже цей план у грі — проти саме ваших ворогів.",
        "У грі Wardly сам підкаже, що з цього брати проти вашого драфту.",
    ),
    "hero_cta_plain": (
        "Wardly підкаже це просто в грі — безкоштовно.",
        "У грі Wardly нагадає про це сам.",
    ),
    # --- a Dota 2 patch ------------------------------------------------------------
    "patch_head": (
        "Патч {version}: що змінили Valve",
        "Вийшов патч {version}",
        "Valve випустили {version}",
    ),
    "patch_most": (
        "Найбільше змін",
        "Під ніж пішли",
        "Кого чіпали найбільше",
    ),
}
