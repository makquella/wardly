"""Localized, reviewable YouTube metadata and Shorts-only approval buttons."""

from __future__ import annotations

import hashlib
import json
from typing import Any

COPY = {
    "uk": {
        "title": "Dota 2: шукаємо бета-тестерів Wardly до 4 000 MMR",
        "description": (
            "Граєш у Dota 2? Допоможи покращити Wardly — напиши «БЕТА» в коментарях.\n\n"
            "Wardly — безкоштовний Windows-тренер для Dota 2 з підказками під час гри "
            "та розбором після матчу. Зараз разом із гравцями покращуємо точність, "
            "своєчасність і корисність порад.\n\n"
            "Шукаємо добровольців приблизно 0–4 000 MMR, особливо на Свені, "
            "Джагернауті й Терорблейді. Зіграй кілька матчів і розкажи: "
            "які підказки допомогли, які запізнилися чи відволікали, де порада була хибною.\n\n"
            "Безкоштовно для Windows: https://luhovyimvp.dev/?ref=promo-beta-uk\n\n"
            "Долучитися до бета-тесту: «БЕТА» в коментарях.\n\n"
            "#Dota2 #Wardly #Shorts"
        ),
        "tags": [
            "Dota 2",
            "dota2",
            "Wardly",
            "Dota 2 українською",
            "дота 2",
            "тренер Dota 2",
            "бета-тест",
            "низький MMR",
            "Sven",
            "Juggernaut",
            "Terrorblade",
        ],
        "button": "▶️ Опублікувати в Shorts",
        "reject": "❌ Відхилити",
        "labels": ["Назва", "Опис і хештеги", "Теги", "Мова відео", "Категорія"],
        "ready": "Готово до YouTube Shorts. Метадані — у відповіді нижче.",
        "not_connected": "YouTube ще не підключено: /connect youtube. Метадані — нижче.",
    },
    "en": {
        "title": "Dota 2 beta testers wanted: help improve Wardly | 0–4K MMR",
        "description": (
            "Play Dota 2? Help us improve Wardly — comment BETA to join the beta test.\n\n"
            "Wardly is a free Windows coach for Dota 2, with in-game tips and post-match "
            "reviews. We're working with players to make its advice more accurate, "
            "better timed and more useful.\n\n"
            "Looking for volunteers around 0–4,000 MMR, especially Sven, Juggernaut "
            "and Terrorblade players. Play a few matches and tell us what helped, "
            "what came too late or distracted you, and which advice was wrong.\n\n"
            "Free for Windows: https://luhovyimvp.dev/en/?ref=promo-beta-en\n\n"
            "Want to help shape Wardly? Comment BETA below.\n\n"
            "#Dota2 #Wardly #Shorts"
        ),
        "tags": [
            "Dota 2",
            "dota2",
            "Wardly",
            "Dota 2 coach",
            "Dota 2 beta test",
            "Dota 2 low MMR",
            "Sven",
            "Juggernaut",
            "Terrorblade",
            "Dota 2 Windows app",
        ],
        "button": "▶️ Publish to Shorts",
        "reject": "❌ Reject",
        "labels": [
            "Title",
            "Description and hashtags",
            "Tags",
            "Video language",
            "Category",
        ],
        "ready": "Ready for YouTube Shorts. Metadata is in the reply below.",
        "not_connected": "YouTube is not connected yet: /connect youtube. Metadata is below.",
    },
}

SHORTS_COPY = {
    "uk": {
        "title": "Свен до 4к MMR? Допоможи перевірити Wardly | Dota 2",
        "description": (
            "Граєш на Свені приблизно до 4к MMR? Напиши «БЕТА» — допоможи перевірити "
            "поради Wardly у своїх матчах. Шукаємо також Джагернаута й Терорблейда.\n\n"
            "Wardly — безкоштовний Windows-тренер для Dota 2: підказки під час матчу "
            "та розбір після гри. Зіграй кілька матчів і скажи чесно: що допомогло, "
            "що запізнилося чи відволікало, де порада була хибною. "
            "Твій відгук допоможе покращити точність, час і користь порад.\n\n"
            "Сайт і завантаження для Windows: https://luhovyimvp.dev/?ref=shorts-sven-uk\n\n"
            "Участь добровільна. Обіцянок приросту MMR немає.\n\n"
            "#Dota2 #ДотаУкраїнською #Sven"
        ),
        "tags": [
            "Dota 2",
            "Sven",
            "Свен",
            "Дота українською",
            "Wardly",
            "0–4k MMR",
            "бета-тест",
        ],
    },
    "en": {
        "title": "Sven under 4K MMR? Help test a free Dota 2 coach",
        "description": (
            "Play Sven around 0–4K MMR? Comment BETA to help test Wardly's advice "
            "in your matches. Juggernaut and Terrorblade players are welcome too.\n\n"
            "Wardly is a free Windows coach for Dota 2, with in-game tips and "
            "post-match reviews. Play a few matches and tell us honestly: what helped, "
            "what came too late or distracted you, and which advice was wrong. "
            "Your feedback helps improve the accuracy, timing and usefulness of the advice.\n\n"
            "Website and Windows download: https://luhovyimvp.dev/en/?ref=shorts-sven-en\n\n"
            "Voluntary beta testing. No promises of MMR gains.\n\n"
            "#Dota2 #Sven #Dota2Coach"
        ),
        "tags": [
            "Dota 2",
            "Sven",
            "Dota 2 coach",
            "Wardly",
            "low MMR",
            "Dota 2 beta test",
        ],
    },
}


def package(language: str, video: dict[str, Any]) -> dict[str, Any]:
    copy = COPY[language]
    if video["visual_revision"] >= 4:
        copy = {**copy, **SHORTS_COPY[language]}
    if video.get("creative") in {"juggernaut-review", "terrorblade-feedback"}:
        from .beta_followups import metadata

        copy = {**copy, **metadata(video["creative"], language)}
    topic = f"beta-testers-{language}-v{video['visual_revision']}"
    if video.get("creative") == "carry-plans-0.57":
        from .release_carry import metadata as release_metadata

        copy = {**copy, **release_metadata(language)}
        topic = f"release-0.57-carries-{language}"
    publish_at = None
    if video.get("creative") in {"carry-match-review", "carry-decisive-moments"}:
        from . import carry_beta

        copy = {**copy, **carry_beta.metadata(video["creative"], language)}
        topic = f"{video['creative']}-{language}"
        publish_at = carry_beta.PUBLISH_AT[video["creative"]]
    identity = {"video_sha256": video["sha256"], "language": language, "copy": copy}
    if publish_at:
        identity["publish_at"] = publish_at
    package_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return {
        "id": package_id,
        "format": "release",
        "topic": topic,
        "hook": 0,
        "title": copy["title"],
        "youtube_title": copy["title"],
        "caption": copy["description"],
        "telegram_caption": copy["title"],
        "youtube_tags": copy["tags"],
        "youtube_language": language,
        # YouTube publishes the video itself at this time (private until then).
        **({"youtube_publish_at": publish_at} if publish_at else {}),
    }


def keyboard(language: str, package_id: str) -> dict[str, Any]:
    copy = COPY[language]
    return {
        "inline_keyboard": [
            [
                {"text": copy["button"], "callback_data": f"promo:yt:{package_id}"},
                {"text": copy["reject"], "callback_data": f"promo:no:{package_id}"},
            ]
        ]
    }


def details(language: str, metadata: dict[str, Any]) -> str:
    title, description, tags, locale, category = COPY[language]["labels"]
    message = (
        f"YouTube Shorts\n\n{title}: {metadata['youtube_title']}\n\n"
        f"{description}:\n{metadata['caption']}\n\n"
        f"{tags}: {', '.join(metadata['youtube_tags'])}\n"
        f"{locale}: {language}\n{category}: Gaming (20)"
    )
    if metadata.get("youtube_publish_at"):
        from .carry_beta import kyiv

        when = kyiv(metadata["youtube_publish_at"])
        message += (
            f"\n\nПублікація: {when} за Києвом. Кнопка «Опублікувати в Shorts» "
            "завантажує відео в YouTube як приватне з розкладом, і YouTube відкриває "
            "його сам у цей час. Натисніть до нього; після цього часу відео вийде одразу."
            if language == "uk"
            else f"\n\nPublication: {when} Kyiv time. The Shorts button uploads the video "
            "to YouTube as private with this schedule, and YouTube opens it itself at "
            "that time. Press it before then; after that time the video goes out at once."
        )
    if metadata.get("topic", "").endswith("-v4"):
        message += (
            "\n\nКнопка «Лише YouTube» одразу ставить відео в чергу на публікацію "
            "в YouTube через Worker: окремого розкладу немає, тож натискайте її тоді, "
            "коли відео має вийти.\n"
            "Перевірка результату: 24 години, 72 години й 7 днів після публікації."
            if language == "uk"
            else "\n\nThe YouTube-only button queues the video for publication on YouTube "
            "through the Worker right away: there is no separate schedule, so press it "
            "when the video should go out.\n"
            "Review results 24 hours, 72 hours and 7 days after publication."
        )
        message += "\nhttps://github.com/makquella/wardly/blob/main/docs/marketing/shorts-plan.md"
    return message
