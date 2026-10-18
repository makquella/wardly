"""
advice_i18n.py - Ukrainian wording for the advice text the player sees.

The advice pipeline (decision points, recommender, scheduler, UX policy) stays
English: logs, session history, recordings and tests keep the canonical text.
Translation happens only at the API edge, when the overlay or the launcher asks
for ``lang=uk`` (``/overlay/recommendation``, ``/advice/recent``).

Only the visible fields are translated: ``recommendation.action``,
``recommendation.reason``, ``message`` and ``last_visible_advice``. A text with
no known translation is returned unchanged (English), never half-translated.
Ability and hero names stay as the backend sends them.

When you add or change a visible advice string anywhere in the pipeline, add
its Ukrainian here too; ``tests/test_advice_i18n.py`` replays the fixtures and
fails on any visible text without a translation.
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache, partial
from hashlib import sha256
from typing import Any

from app.hero_gameplay_texts import GAMEPLAY_TRANSLATIONS
from app.last_moments import RUNES_UK

DEFAULT_LANG = "en"

_UK_EXACT: dict[str, str] = {
    "Your bounty grows with the streak: farm near your team and skip dark, unwarded areas.": (
        "За вас дають дедалі більше золота: фарміть поруч із командою й не ходіть у темні місця без вардів."
    ),
    "The enemy has items first now; trade risky farm for safe farm until your key item.": (
        "У ворогів предмети раніше: замінюйте ризикований фарм безпечним до вашого ключового предмета."
    ),
    "A kill lead fades unless it turns into towers and map control.": (
        "Перевага за вбивствами тане, якщо не перетворити її на вежі й контроль мапи."
    ),
    # --- actions -------------------------------------------------------------
    "After respawn, avoid committing forward until your escape is ready.": (
        "Після відродження не лізьте вперед, доки не готова здібність для втечі."
    ),
    "After respawn, reset earlier when HP or key resources get low.": (
        "Після відродження відходьте раніше, коли HP або ключові ресурси закінчуються."
    ),
    "After respawn, reset your route and avoid repeating the same risky path.": (
        "Після відродження змініть маршрут і не повторюйте той самий небезпечний шлях."
    ),
    "After this item pickup, reassess whether to farm safely or pressure with your team.": (
        "З новим предметом вирішіть заново: фармити безпечно чи тиснути разом із командою."
    ),
    "Avoid risky trades until your defensive tool is ready.": (
        "Уникайте ризикованих розмінів, доки не готова захисна здібність."
    ),
    "Avoid the pressured lane and farm a safer wave or nearby camp.": (
        "Підіть з лінії, де тиснуть, і фарміть безпечнішу хвилю або ближній табір."
    ),
    "Avoid this fight and reset to safer farm.": (
        "Не йдіть у цю бійку, поверніться до безпечного фарму."
    ),
    "Avoid this fight and move to safer farm.": (
        "Не йдіть у цю бійку, перейдіть на безпечніший фарм."
    ),
    "Avoid the fight and keep farming safely.": "Пропустіть бійку й продовжуйте спокійно фармити.",
    "Avoid contesting pressure and move to safer farm.": (
        "Не протистійте тиску, перейдіть на безпечніший фарм."
    ),
    "Back up and stabilize before trading again.": (
        "Відійдіть і відновіться, перш ніж знову розмінюватися."
    ),
    "Back up slightly, secure safe last hits, then reset your HP.": (
        "Відійдіть трохи, заберіть безпечні добивання, потім відновіть HP."
    ),
    "Back up, stabilize HP, then return to the wave.": (
        "Відійдіть, відновіть HP і повертайтеся до хвилі."
    ),
    "Buyback is available. Only consider it for critical defense.": (
        "Байбек доступний. Використовуйте його лише для критичного захисту."
    ),
    "Check buyback value only for base defense or a major objective.": (
        "Байбек виправданий лише для захисту бази або важливої цілі."
    ),
    "Conserve mana or reset before taking a fight.": (
        "Бережіть ману або відновіться перед бійкою."
    ),
    "Consider joining only if your team is ready and the fight is near the objective.": (
        "Приєднуйтеся, лише якщо команда готова й бійка йде біля ключової цілі."
    ),
    "Consider joining only if the fight is near the objective.": (
        "Приєднуйтеся, лише якщо бійка йде біля ключової цілі."
    ),
    "Consider joining only if your team is ready around the objective.": (
        "Приєднуйтеся, лише якщо команда вже зібралася біля ключової цілі."
    ),
    "Consider a safer, lower-risk play.": "Оберіть безпечніший варіант із меншим ризиком.",
    "Consider playing safely.": "Грайте обережніше.",
    "Consider monitoring lane — no urgent advice.": "Стежимо за лінією — термінових порад немає.",
    "Do not overstay on low HP; reset or play behind creeps.": (
        "Не затримуйтеся з низьким HP: відійдіть або грайте за кріпами."
    ),
    "Do not show deep until enemy positions are clearer.": (
        "Не заходьте вглиб мапи, доки не ясно, де вороги."
    ),
    "Farm the safer part of the lane and avoid long trades.": (
        "Фарміть на безпечній частині лінії й уникайте довгих розмінів."
    ),
    "Farm closer to a safer zone until enemy positions are clearer.": (
        "Фарміть ближче до безпечної зони, доки не ясно, де вороги."
    ),
    "Focus on safe last hits before forcing trades.": (
        "Спершу безпечні добивання, розміни — потім."
    ),
    "Focus on safe last hits before moving to nearby camps.": (
        "Заберіть безпечні добивання, потім ідіть на ближні табори."
    ),
    "Focus on safe last hits in the next wave.": (
        "У наступній хвилі зосередьтеся на безпечних добиваннях."
    ),
    "Focus on safe last hits.": "Зосередьтеся на безпечних добиваннях.",
    "Keep farming safely and reassess in 60 seconds.": (
        "Продовжуйте спокійно фармити, за хвилину оцініть ситуацію знову."
    ),
    "Keep farming safely in lane and focus on last hits.": (
        "Спокійно фарміть на лінії й стежте за добиваннями."
    ),
    "Keep farming safely in lane.": "Спокійно фарміть на лінії.",
    "Keep farming safely until the next wave.": "Спокійно фарміть до наступної хвилі.",
    "Keep farming safely.": "Продовжуйте спокійно фармити.",
    "Keep farming the safest wave-and-camp route and reassess soon.": (
        "Фарміть найбезпечнішим маршрутом із хвиль і таборів, незабаром оцініть ситуацію знову."
    ),
    "Keep your farm rhythm and avoid low-value trades.": (
        "Тримайте темп фарму й уникайте марних розмінів."
    ),
    "Leave the wave now and reset HP before rejoining.": (
        "Ідіть із хвилі зараз і відновіть HP, перш ніж повернутися."
    ),
    "Maintain steady farm.": "Тримайте рівний темп фарму.",
    "Monitoring lane — no urgent advice.": "Стежимо за лінією — термінових порад немає.",
    "Move closer to a safer farming zone before showing on the wave.": (
        "Перед виходом на хвилю змістіться ближче до безпечної зони фарму."
    ),
    "Move closer to a safer lane area before contesting the next wave.": (
        "Перед наступною хвилею змістіться в безпечнішу частину лінії."
    ),
    "No urgent action.": "Термінових дій не потрібно.",
    "No urgent decision is needed.": "Термінових рішень не потрібно.",
    "Only consider the objective if your team is already grouped nearby.": (
        "Ідіть до цілі, лише якщо команда вже зібралася поруч."
    ),
    "Go back to farming: take the nearest safe wave or camp now.": (
        "Поверніться до фарму: заберіть найближчу безпечну хвилю або табір."
    ),
    "You have taken almost no last hits lately; every minute without farm delays your next item.": (
        "Останнім часом майже немає добивань: кожна хвилина без фарму відсуває наступний предмет."
    ),
    "Medium risk if you keep walking around without farming.": (
        "Середній ризик, якщо й далі ходити мапою без фарму."
    ),
    "Farm back your buyback gold before the next purchase.": (
        "Нафарміть золото на байбек, перш ніж купувати далі."
    ),
    "After minute 30 one death without buyback can decide the game.": (
        "Після 30-ї хвилини одна смерть без байбеку може вирішити гру."
    ),
    "High risk if you die before the buyback gold is back.": (
        "Високий ризик, якщо помрете раніше, ніж повернете золото на байбек."
    ),
    "Recover farm through the safest wave-and-camp route.": (
        "Надолужуйте фарм найбезпечнішим маршрутом із хвиль і таборів."
    ),
    "A silence does not stop items: get rid of it before the next spell lands.": (
        "Німота не заважає предметам: зніміть її до наступного закляття."
    ),
    "Reset HP before showing on another lane.": (
        "Відновіть HP, перш ніж з'являтися на іншій лінії."
    ),
    "Reset mana before taking an extended fight.": "Відновіть ману перед затяжною бійкою.",
    "Reset resources before showing on another lane.": (
        "Відновіть ресурси, перш ніж з'являтися на іншій лінії."
    ),
    "Respect your hero's safety window before forcing a fight.": (
        "Не нав'язуйте бійку, доки захисні здібності героя не готові."
    ),
    "Retreat and reset before rejoining.": "Відступіть і відновіться, перш ніж повернутися.",
    "Secure the next wave first and avoid trading unless it protects last hits.": (
        "Спершу заберіть наступну хвилю; розмінюйтеся лише щоб захистити добивання."
    ),
    "Stay hidden until your team is ready to make a move.": (
        "Не показуйтеся, доки команда не готова діяти."
    ),
    "Stop re-contesting the pressured lane until you reset HP.": (
        "Не повертайтеся на лінію, де тиснуть, доки не відновите HP."
    ),
    "Take only the safe creeps and avoid extending the trade.": (
        "Добивайте лише безпечних кріпів і не затягуйте розмін."
    ),
    "Take safe creeps, then rotate to safer farm if pressure continues.": (
        "Заберіть безпечних кріпів; якщо тиснуть далі — ідіть на безпечніший фарм."
    ),
    "Use regen or play back until your HP is safer.": (
        "Використайте реген або відійдіть, доки HP не відновиться."
    ),
    "Unspent gold is partly lost on the next death; "
    "then choose a safer route than the one you died on.": (
        "Невитрачене золото частково втрачається в разі наступної смерті. Потім оберіть маршрут безпечніший за той, де вас спіймали."
    ),
    "Keep a TP scroll in its slot: buy one now, the courier can bring it.": (
        "Тримайте сувій телепортації в слоті: купіть його зараз, кур'єр принесе."
    ),
    "Without a TP scroll you cannot join a fight or save a tower in time.": (
        "Без сувою телепортації не встигнете ні в бійку, ні врятувати вежу."
    ),
    "Medium risk if a fight starts across the map while you have no TP.": (
        "Середній ризик, якщо бійка почнеться на іншому кінці мапи, а сувою телепортації немає."
    ),
    "Use the respawn time to choose a safer farming route.": (
        "Поки чекаєте відродження, оберіть безпечніший маршрут фарму."
    ),
    "Use the respawn time to plan a safer next route.": (
        "Поки чекаєте відродження, продумайте безпечніший маршрут."
    ),
    "Use the respawn time to plan your next safe farming route.": (
        "Поки чекаєте відродження, продумайте наступний безпечний маршрут фарму."
    ),
    "Wait out the disable and avoid forcing actions.": (
        "Перечекайте контроль і не робіть різких дій."
    ),
    "You reached a timing; reassess whether to pressure or keep farming safely.": (
        "Ви вийшли на таймінг: вирішіть заново, тиснути чи спокійно фармити далі."
    ),
    "You reached a damage timing; consider objective fights, not low-value skirmishes.": (
        "Таймінг за шкодою: шукайте бійки за ключові цілі, а не випадкові сутички."
    ),
    "You reached a defensive timing; consider fighting only around objectives or with team support.": (
        "Захисний таймінг: бийтеся лише біля ключових цілей або разом із командою."
    ),
    "You reached a farming timing; increase farm speed and avoid unnecessary deaths.": (
        "Таймінг за фармом: пришвидшіть фарм і не помирайте даремно."
    ),
    "You reached a late-game timing; prioritize high-value objectives and safe positioning.": (
        "Таймінг пізньої гри: у пріоритеті важливі цілі й безпечна позиція."
    ),
    "You reached a mobility timing; look for safer map movement, not random fights.": (
        "Таймінг мобільності: пересувайтеся мапою безпечніше, не шукайте випадкових бійок."
    ),
    "Your farm pace is behind; move to safer, higher-value farm.": (
        "Ви відстаєте за фармом: переходьте на безпечніший і вигідніший фарм."
    ),
    # --- reasons -------------------------------------------------------------
    "A short reset keeps the next farming route safer without forcing a fight.": (
        "Короткий відхід робить наступний маршрут фарму безпечнішим без зайвої бійки."
    ),
    "A meaningful item can change your next decision, but avoid forcing low-value fights.": (
        "Важливий предмет може змінити план, але не нав'язуйте марних бійок."
    ),
    "At this HP, one more spell or rotation can turn into a death.": (
        "З таким HP ще одна здібність або ганк можуть закінчитися смертю."
    ),
    "At this HP, one more trade or spell can kill you.": (
        "З таким HP ще один розмін або здібність можуть вас убити."
    ),
    "Avoid returning to the same risky area without vision or team support.": (
        "Не повертайтеся в ту саму небезпечну зону без огляду чи підтримки команди."
    ),
    "Avoid rushing back into the same risky area.": (
        "Не біжіть одразу назад у ту саму небезпечну зону."
    ),
    "Current lane state does not need a full coaching card.": (
        "Ситуація на лінії не потребує окремої підказки."
    ),
    "Enemy pressure is active, and a low-value fight can delay your next timing.": (
        "Вороги тиснуть, і марна бійка відсуне ваш наступний таймінг."
    ),
    "Enemy pressure is active. A low-value fight or death delays your next timing.": (
        "Вороги тиснуть. Марна бійка або смерть відсуне ваш наступний таймінг."
    ),
    "Enemy locations are not confirmed, so exposed farming is unnecessary risk.": (
        "Де вороги — невідомо, тому фарм на відкритому місці — зайвий ризик."
    ),
    "HP is critical; one more trade or spell can kill you.": (
        "HP критично низьке: ще один розмін або здібність можуть вас убити."
    ),
    "HP is low enough that another trade can become dangerous.": (
        "HP так мало, що наступний розмін може бути небезпечним."
    ),
    "HP is stable and no pressure signal is active.": "HP у нормі, ознак тиску немає.",
    "Improving farm rate is safer than forcing a low-value fight.": (
        "Пришвидшити фарм безпечніше, ніж нав'язувати марну бійку."
    ),
    "Low health makes extra action too risky.": "З низьким HP зайві дії надто ризиковані.",
    "Low lane HP makes trades and last hits risky.": (
        "З низьким HP на лінії розміни й добивання ризиковані."
    ),
    "Low mana limits escape, spell usage, and fight impact.": (
        "Мало мани: важче втекти, застосувати здібності й допомогти в бійці."
    ),
    "Multiple recent deaths can delay your next timing more than missing one wave or camp.": (
        "Кілька смертей поспіль відсунуть таймінг сильніше, ніж пропущена хвиля чи табір."
    ),
    "Objective fights can be valuable, but the replay does not confirm team readiness.": (
        "Бійки за цілі бувають вигідні, але з реплею не видно, чи готова команда."
    ),
    "Objective fights can be valuable, but avoid forcing them without team support.": (
        "Бійки за цілі бувають вигідні, але не нав'язуйте їх без підтримки команди."
    ),
    "Objectives can be worth joining, but random skirmishes are not.": (
        "За ключові цілі битися варто, за випадкові сутички — ні."
    ),
    "Objectives can be worth joining, but avoid forcing a fight without team support.": (
        "За ключові цілі битися варто, але не нав'язуйте бійку без підтримки команди."
    ),
    "Pressure is active while HP is not comfortable.": "Вороги тиснуть, а запасу HP уже немає.",
    "Pressure is active, but HP is still high enough for conservative farming.": (
        "Вороги тиснуть, але HP вистачає для обережного фарму."
    ),
    "Pressure plus reduced HP can turn the next trade into a death.": (
        "Тиск і неповне HP: наступний розмін може закінчитися смертю."
    ),
    "Reduced HP plus lane pressure can turn one more trade into a death.": (
        "Неповне HP і тиск на лінії: ще один розмін може закінчитися смертю."
    ),
    "Repeated low-HP returns can cost more than missing one wave.": (
        "Раз у раз повертатися з низьким HP дорожче, ніж пропустити одну хвилю."
    ),
    "Returning to the same pressured area can repeat the same death pattern.": (
        "Повернувшись у ту саму небезпечну зону, можна померти так само, як минулого разу."
    ),
    "Revealing on a wave can waste the smoke timing.": (
        "Якщо показатися на хвилі, смок зникне даремно."
    ),
    "Staying exposed after a bad trade often leads to a preventable death.": (
        "Якщо залишитися на видноті після невдалого розміну, легко померти даремно."
    ),
    "Staying in pressure can cost HP and slow your recovery.": (
        "Під тиском ви втрачаєте HP і довше відновлюєтеся."
    ),
    "Stabilizing farm is safer than taking low-value damage.": (
        "Вирівняти фарм безпечніше, ніж отримувати шкоду даремно."
    ),
    "The fight looks risky and may delay your next timing.": (
        "Бійка виглядає ризикованою й може відсунути ваш таймінг."
    ),
    "The item improves your options, but missing cooldown and team context means the safer choice still depends on nearby pressure.": (
        "Предмет дає більше варіантів, але без даних про кулдауни й команду безпечний вибір залежить від тиску поруч."
    ),
    "The previous fight became risky because your survivability resource was low.": (
        "Минула бійка стала небезпечною: ресурси для виживання закінчувалися."
    ),
    "There is no clear threat, objective, or timing decision right now.": (
        "Зараз немає явної загрози, цілі чи таймінгу."
    ),
    "No urgent threat or objective is forcing action. Build resources safely.": (
        "Ні загроз, ні цілей, що потребують дій. Спокійно набирайте ресурси."
    ),
    "This reduces risk while keeping your carry game stable.": (
        "Так менше ризику, а гра залишається стабільною."
    ),
    "Use it only if your team is defending a critical objective or the game could be decided now.": (
        "Лише якщо команда захищає важливу ціль або гра вирішується просто зараз."
    ),
    "You are behind on farm and under lane pressure; forcing a trade can cost both HP and last hits.": (
        "Ви відстаєте за фармом, і на лінії тиснуть: розмін може коштувати і HP, і добивань."
    ),
    "You are behind on farm, so forcing fights before stabilizing can delay your next timing.": (
        "Ви відстаєте за фармом: бійки до того, як вирівняєтеся, відсунуть таймінг."
    ),
    "You are still behind on farm, and staying in pressure can cost both HP and timing.": (
        "Ви все ще відстаєте за фармом, а під тиском втрачаєте і HP, і таймінг."
    ),
    "You are controlled; surviving the next seconds matters more than dealing damage.": (
        "Ви під контролем: вижити найближчі секунди важливіше, ніж завдати шкоди."
    ),
    "You are under pressure but still have enough HP to keep farming if you stay conservative.": (
        "На вас тиснуть, але HP вистачає, щоб обережно фармити далі."
    ),
    "You died after your key escape or defensive tool was unavailable.": (
        "Ви померли, коли здібність для втечі чи захисту була недоступна."
    ),
    "You took heavy damage recently, so another trade can turn into a death.": (
        "Ви нещодавно отримали багато шкоди: наступний розмін може закінчитися смертю."
    ),
    "Your farm pace is behind for this minute, but HP is stable, so the fastest recovery is clean last hitting.": (
        "Для цієї хвилини фарму мало, але HP у нормі — найшвидше наздогнати чистими добиваннями."
    ),
    "Your farm pace is stable now, so keep using safe routes instead of forcing uncertain fights.": (
        "Темп фарму вирівнявся: тримайтеся безпечних маршрутів і не лізьте в сумнівні бійки."
    ),
    "Your farm route is the safest low-risk choice while enemy locations are uncertain.": (
        "Поки невідомо, де вороги, ваш маршрут фарму — найбезпечніший варіант."
    ),
    "Your position is exposed and the replay does not confirm where enemies are.": (
        "Ви на відкритій позиції, а з реплею не видно, де вороги."
    ),
    "Your position is exposed and enemy locations are not confirmed.": (
        "Ви на відкритій позиції, а де вороги — невідомо."
    ),
    "Your position is risky and enemy locations are not confirmed.": (
        "Позиція небезпечна, а де вороги — невідомо."
    ),
    "Your hero is easier to punish while this safety tool is unavailable.": (
        "Поки захисна здібність недоступна, вашого героя легше покарати."
    ),
    "Your key defensive resource is unavailable, so a bad fight is harder to escape.": (
        "Ключовий захисний ресурс недоступний: з невдалої бійки буде важко вийти."
    ),
    "Your lane progress is stable, so do not break it by taking unnecessary damage.": (
        "На лінії все рівно — не псуйте це зайвою шкодою."
    ),
    "Death detected, but context is limited.": "Смерть зафіксовано, але даних мало.",
    "Death followed a low HP or key resource state.": (
        "Смерть сталася з низьким HP або браком ключових ресурсів."
    ),
    "Death followed a state where a key escape or defensive tool was unavailable.": (
        "Смерть сталася, коли здібність для втечі чи захисту була недоступна."
    ),
    "Death followed farming with limited team context; avoid repeating the same route.": (
        "Смерть сталася під час фарму далеко від команди; не повторюйте той самий маршрут."
    ),
    "Death happened around an objective context.": "Смерть сталася в бійці біля ключової цілі.",
    "Multiple recent deaths detected; reset the next route after respawn.": (
        "Кілька смертей поспіль: після відродження змініть маршрут."
    ),
    "Position is far from your safe side, and enemy locations are not confirmed.": (
        "Ви далеко від своєї безпечної сторони, а де вороги — невідомо."
    ),
    "Position is known, but team side is unknown; avoid assuming the area is safe.": (
        "Позиція відома, але сторона команди — ні; не вважайте зону безпечною."
    ),
    "Position is lane-side, but enemy locations are not confirmed.": (
        "Ви біля лінії, але де вороги — невідомо."
    ),
    "Position is near central map areas; avoid assuming the area is safe.": (
        "Ви в центрі мапи — не вважайте зону безпечною."
    ),
    "Position is on your side of the map; still avoid assuming enemies are absent.": (
        "Ви на своїй половині мапи, але вороги все одно можуть бути поруч."
    ),
    "Position is unavailable.": "Позиція невідома.",
    # --- status messages -----------------------------------------------------
    "Monitoring...": "Стежимо за грою…",
    "Waiting for live GSI...": "Чекаємо на дані з гри…",
    "Take the side lanes your team leaves and a camp between waves; "
    "join fights only for a tower or Roshan.": (
        "Забирайте бокові лінії, які залишає команда, і табір між хвилями; у бійки йдіть лише за вежу або Рошана."
    ),
    "Your HP is fine: last-hit every creep of the next waves and trade only to protect them.": (
        "Здоров'я вистачає: добивайте кожного кріпа наступних хвиль, а розміни — лише щоб їх захистити."
    ),
    "Take the safest waves and camps first: fights before that delay your next item.": (
        "Спершу найбезпечніші хвилі й табори: бійки до цього відкладуть наступний предмет."
    ),
    "Keep taking the safest waves and camps: this pace grows without risky fights.": (
        "Беріть найбезпечніші хвилі й табори: темп росте й без ризикованих бійок."
    ),
    "Current hero is not supported by carry advisor yet.": (
        "Для цього героя порад поки немає: підтримуються лише керрі."
    ),
}

# Texts with a hero or ability name inside. The name is kept as sent.
_UK_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^Keep farming: (?P<gpm>\d+) gold per minute, (?P<lh>\d+) last hits at minute "
            r"(?P<m>\d+)\.$"
        ),
        "Фарміть далі: {gpm} золота за хвилину, добивань до {m}-ї хвилини — {lh}.",
    ),
    (
        re.compile(
            r"^No TP scroll for (?P<minutes>\d+) minutes?: without it you cannot join a fight "
            r"or save a tower in time\.$"
        ),
        "Без сувою телепортації вже {minutes} хв — не встигнете ні в бійку, ні врятувати вежу.",
    ),
    (
        re.compile(
            r"^Buy parts of your next item now with your (?P<gold>\d+) gold: "
            r"they wait for you at the fountain\.$"
        ),
        "Купіть частини наступного предмета на {gold} золота зараз — заберете їх біля фонтана.",
    ),
    (
        re.compile(
            r"^Buy parts of your next item with (?P<spare>\d+) gold "
            r"and keep (?P<cost>\d+) for buyback\.$"
        ),
        "Купіть частини наступного предмета на {spare} золота, а {cost} залиште на байбек.",
    ),
    (
        re.compile(r"^Avoid committing forward until (?P<name>.+) is ready\.$"),
        "Не лізьте вперед, доки не готовий {name}.",
    ),
    (
        re.compile(r"^Avoid risky trades until (?P<name>.+) is ready\.$"),
        "Уникайте ризикованих розмінів, доки не готовий {name}.",
    ),
    (
        re.compile(r"^Without (?P<name>.+), disables and slows are harder to avoid\.$"),
        "Без {name} важче уникнути контролю й сповільнень.",
    ),
    (
        re.compile(r"^Without (?P<name>.+), escaping a bad trade or fight is harder\.$"),
        "Без {name} складніше вийти з невдалого розміну чи бійки.",
    ),
    (
        re.compile(r"^(?P<name>.+) is unavailable, so committing forward is risky\.$"),
        "Без {name} іти вперед ризиковано.",
    ),
    (
        re.compile(r"^(?P<name>.+) is unavailable, so your hero is easier to punish\.$"),
        "Без {name} вашого героя легше покарати.",
    ),
    (
        re.compile(
            r"^Only (?P<lh>\d+) last hits? in the last (?P<m>\d+) minutes; "
            r"every minute without farm delays your next item\.$"
        ),
        "Добивань за останні {m} хв: {lh}. Кожна хвилина без фарму відсуває наступний предмет.",
    ),
    (
        re.compile(
            r"^You have (?P<gold>\d+) gold and buyback costs (?P<cost>\d+); "
            r"after minute 30 one death without buyback can decide the game\.$"
        ),
        "Золота {gold}, байбек коштує {cost}. Після 30-ї хвилини одна смерть без байбеку може вирішити гру.",
    ),
    (
        re.compile(
            r"^You have (?P<gold>\d+) gold and buyback costs (?P<cost>\d+); "
            r"the enemy holds the Aegis: one death without buyback can decide the game\.$"
        ),
        "Золота {gold}, байбек коштує {cost}. Аегіс у ворогів: одна смерть без байбеку може вирішити гру.",
    ),
    (
        re.compile(
            r"^You have (?P<gold>\d+) gold and buyback costs (?P<cost>\d+); "
            r"your base is open: one death without buyback can decide the game\.$"
        ),
        "Золота {gold}, байбек коштує {cost}. Ваша база відкрита: одна смерть без байбеку може вирішити гру.",
    ),
    (
        re.compile(
            r"^Recover farm: (?P<lh>\d+) last hits at minute (?P<m>\d+), a good pace is "
            r"(?P<low>\d+)\+\.$"
        ),
        "Надолужуйте фарм: добивань до {m}-ї хвилини — {lh}, добрий темп — {low}+.",
    ),
    # live_tools.py: the hero's own abilities and their cooldowns.
    (
        re.compile(r"^Use (?P<name>.+) now: a mute blocks items, not spells\.$"),
        "Використайте {name} зараз: німота заважає предметам, а не здібностям.",
    ),
    (
        re.compile(r"^Use (?P<name>.+) now and walk out of the fight\.$"),
        "Використайте {name} зараз і виходьте з бійки.",
    ),
    (
        re.compile(r"^(?P<name>.+) is ready: it buys you the seconds to get away\.$"),
        "{name} уже можна натиснути: це дасть секунди, щоб піти.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) is back in (?P<n>\d+) s: without it, escaping a bad trade "
            r"or fight is harder\.$"
        ),
        "{name} відновиться через {n} с: без нього складніше вийти з невдалого розміну чи бійки.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) is back in (?P<n>\d+) s: until then, disables and slows "
            r"are harder to avoid\.$"
        ),
        "{name} відновиться через {n} с: до того складніше уникнути контролю й сповільнень.",
    ),
    # live_tools.py: a rune kept in the Bottle (before the generic tool texts).
    *(
        entry
        for rune, uk in RUNES_UK.items()
        for entry in (
            (
                re.compile(rf"^Use the {rune} rune from your Bottle and run\.$"),
                f"Використайте руну {uk} із пляшки й ідіть.",
            ),
            (
                re.compile(
                    rf"^The {rune} rune in your Bottle is ready: use it before the next hit, "
                    r"not after\.$"
                ),
                f"Руна {uk} у пляшці готова: використайте її до наступного удару, а не після.",
            ),
        )
    ),
    (
        re.compile(r"^Use the Water rune from your Bottle now, then step back\.$"),
        "Використайте руну води з пляшки зараз і відійдіть.",
    ),
    (
        re.compile(r"^The Water rune in your Bottle heals you at once\.$"),
        "Руна води в пляшці лікує одразу.",
    ),
    (
        re.compile(r"^Step out of enemy range and use the Regeneration rune from your Bottle\.$"),
        "Відійдіть туди, де ворог не дістане, і використайте руну регенерації з пляшки.",
    ),
    (
        re.compile(
            r"^The Regeneration rune heals fast but stops at the first hit: use it where "
            r"enemies cannot reach you\.$"
        ),
        "Руна регенерації лікує швидко, але збивається першим же ударом: використайте її там, де вас не дістануть.",
    ),
    # live_tools.py: the tool that is ready right now.
    (
        re.compile(r"^Use (?P<name>.+) now to get out, then reset HP\.$"),
        "Використайте {name} зараз, щоб піти, потім відновіть HP.",
    ),
    (
        re.compile(
            r"^Your HP is low and (?P<name>.+) is ready: use it before the next hit, not after\.$"
        ),
        "HP мало, а {name} готовий: натисніть його до наступного удару, а не після.",
    ),
    (
        re.compile(r"^Use (?P<name>.+) now, then step back\.$"),
        "Натисніть {name} зараз і відійдіть.",
    ),
    (
        re.compile(r"^Magic Wand has (?P<n>\d+) charges: that HP is yours right now\.$"),
        "У Magic Wand {n} зарядів: це HP можна отримати просто зараз.",
    ),
    (
        re.compile(r"^(?P<name>Magic Wand) is charged: that HP is yours right now\.$"),
        "{name} заряджений: це HP можна отримати просто зараз.",
    ),
    (
        re.compile(r"^(?P<name>.+) is ready and heals you at once\.$"),
        "{name} готовий і лікує одразу.",
    ),
    (
        re.compile(r"^(?P<name>.+) heals you at once\.$"),
        "{name} лікує одразу.",
    ),
    (
        re.compile(r"^Step out of enemy range and use (?P<name>.+)\.$"),
        "Відійдіть туди, де ворог не дістане, і використайте {name}.",
    ),
    (
        re.compile(r"^(?P<name>.+) heals over time: use it where enemies cannot hit you\.$"),
        "{name} лікує поступово: використовуйте там, де вас не дістануть.",
    ),
    (
        re.compile(r"^Use (?P<name>.+) now: it removes the silence\.$"),
        "Натисніть {name} зараз: він знімає німоту.",
    ),
    (
        re.compile(r"^The moment the disable ends, use (?P<name>.+)\.$"),
        "Щойно контроль закінчиться, одразу натисніть {name}.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) is ready: the second after a disable is when most kills finish\.$"
        ),
        "{name} готовий: найчастіше добивають у першу секунду після контролю.",
    ),
    *(
        (
            re.compile(
                rf"^You died with Bottle \({rune} rune\) ready: next time use it at the first "
                r"big hit\.$"
            ),
            f"Ви загинули, коли в пляшці була руна {uk}: наступного разу використайте її після першого ж сильного удару.",
        )
        for rune, uk in RUNES_UK.items()
    ),
    (
        re.compile(r"^You died with (?P<name>.+) ready: next time use it at the first big hit\.$"),
        "Ви загинули з готовим {name}: наступного разу натисніть його після першого ж сильного удару.",
    ),
    (
        re.compile(r"^Use your gold: (?P<name>.+) can be bought now\.$"),
        "Витратьте золото: {name} уже можна купити.",
    ),
    (
        re.compile(
            r"^Its missing parts cost (?P<left>\d+) gold and you have (?P<spare>\d+) "
            r"beyond your buyback\.$"
        ),
        "Відсутні частини коштують {left} золота, у вас {spare} понад байбек.",
    ),
    (
        re.compile(r"^Its missing parts cost (?P<left>\d+) gold and you have (?P<spare>\d+)\.$"),
        "Відсутні частини коштують {left} золота, у вас {spare}.",
    ),
    (
        re.compile(r"^Keep farming toward (?P<name>.+) on the safest waves and camps\.$"),
        "Фарміть на {name} на найбезпечніших хвилях і таборах.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) is next in most builds: (?P<need>\d+) gold to go, "
            r"about (?P<m>\d+) minutes? at your (?P<gpm>\d+) gold per minute\.$"
        ),
        "{name} — наступний предмет у більшості збірок: бракує {need} золота, це близько {m} хв за темпу {gpm} золота за хвилину.",
    ),
    (
        re.compile(r"^(?P<name>.+) is next in most builds: (?P<need>\d+) gold to go\.$"),
        "{name} — наступний предмет у більшості збірок: бракує {need} золота.",
    ),
    (
        re.compile(r"^Low mana reduces (?P<name>.+)'s effective survivability\.$"),
        "У {name} мало мани — живучість помітно нижча.",
    ),
    (
        re.compile(r"^(?P<name>.+) is low on mana, so effective survivability is reduced\.$"),
        "У {name} мало мани — живучість помітно нижча.",
    ),
)

# Death places (live_tools.death_copy): Ukrainian needs the zone in a case, so
# these render with a function instead of a format template.
_ZONE_FROM = {
    "top lane": "від верхньої лінії",
    "mid lane": "від центральної лінії",
    "bottom lane": "від нижньої лінії",
    "jungle": "від лісу",
}
_ZONE_IN = {
    "top lane": "на верхній лінії",
    "mid lane": "на центральній лінії",
    "bottom lane": "на нижній лінії",
    "jungle": "у лісі",
}
_ZONE_TO = {
    "top lane": "на верхню лінію",
    "mid lane": "на центральну лінію",
    "bottom lane": "на нижню лінію",
    "jungle": "до лісу",
}
_SIDE = {
    "on your side": "на своїй половині",
    "by the river": "біля річки",
    "on the enemy side": "на половині ворога",
}
_ZONE_RE = "(?P<zone>top lane|mid lane|bottom lane|jungle)"
_SIDE_RE = "(?P<side>on your side|by the river|on the enemy side)"


def _deaths_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "смерть"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "смерті"
    return "смертей"


# The situational item's reason (post_laning_coach._situational_because) and
# the gold tail after it.
_SITUATIONAL_TAILS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\.$"), "."),
    (re.compile(r"^: (?P<need>\d+) gold to go\.$"), ": бракує {need} золота."),
    (
        re.compile(
            r"^: (?P<need>\d+) gold to go, about (?P<m>\d+) minutes? at your (?P<gpm>\d+) "
            r"gold per minute\.$"
        ),
        ": бракує {need} золота, це близько {m} хв за темпу {gpm} золота за хвилину.",
    ),
    (
        re.compile(
            r"^; its missing parts cost (?P<left>\d+) gold and you have (?P<spare>\d+) "
            r"beyond your buyback\.$"
        ),
        "; відсутні частини коштують {left} золота, у вас {spare} понад байбек.",
    ),
    (
        re.compile(r"^; its missing parts cost (?P<left>\d+) gold and you have (?P<spare>\d+)\.$"),
        "; відсутні частини коштують {left} золота, у вас {spare}.",
    ),
)


def _kills_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "вбивство"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "вбивства"
    return "вбивств"


def _situational_tail(tail: str) -> str | None:
    for pattern, template in _SITUATIONAL_TAILS:
        match = pattern.match(tail)
        if match:
            return template.format(**match.groupdict())
    return None


_SITUATIONAL_TAIL_RE = r"(?P<tail>(?:\.|: \d+ gold to go.*|; its missing parts cost.*))$"


def _magic_reason(groups: dict[str, str]) -> str:
    """A lineup of magic damage (situational_items, why "magic")."""
    count = int(groups["count"])
    word = (
        "герой"
        if count % 10 == 1 and count % 100 != 11
        else ("герої" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14 else "героїв")
    )
    head = f"{count} {word} ворога б'ють магією — {groups['name']} захистить від неї"
    tail = _situational_tail(groups["tail"])
    return head + tail if tail is not None else ""


def _counter_reason(groups: dict[str, str]) -> str:
    """The counter-item reasons (situational_items: an enemy hero seen)."""
    if groups.get("spell"):
        count = int(groups["count"])
        head = f"{count} {_deaths_word(count)} під контролем проти {groups['enemy']} — {groups['name']} блокує {groups['spell']}"
    elif groups.get("kind") == "dodges your attacks":
        head = f"{groups['enemy']} ухиляється від атак — {groups['name']} пробиває ухилення більшістю атак"
    elif groups.get("kind") == "fights with illusions":
        head = f"{groups['enemy']} б'ється ілюзіями — {groups['name']} б'є їх усіх одразу"
    elif groups.get("passive"):
        head = f"{groups['enemy']} тримається на {groups['passive']} — {groups['name']} це вимикає"
    else:
        head = f"{groups['enemy']} багато лікується — {groups['name']} ріже лікування"
    tail = _situational_tail(groups["tail"])
    return head + tail if tail is not None else ""


def _situational_reason(groups: dict[str, str]) -> str:
    count = int(groups["count"])
    if groups["kind"].strip().startswith("under stuns"):
        head = f"{count} {_deaths_word(count)} під контролем без жодної вільної секунди — {groups['name']} це виправить"
    else:
        times = (
            "раз"
            if count % 10 == 1 and count % 100 != 11
            else ("рази" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14 else "разів")
        )
        head = f"{count} {times} вас убили з високого здоров'я швидше, ніж за 3 секунди — {groups['name']} дасть час це пережити"
    for pattern, tail in _SITUATIONAL_TAILS:
        match = pattern.match(groups["tail"])
        if match:
            return head + tail.format(**match.groupdict())
    return ""


_UK_FUNCTIONS: tuple[tuple[re.Pattern[str], Callable[[dict[str, str]], str]], ...] = (
    (
        re.compile(r"^After respawn, change your route: (?P<n>\d+) deaths this game\.$"),
        lambda g: (
            f"Після відродження змініть маршрут: {g['n']} {_deaths_word(int(g['n']))} за гру."
        ),
    ),
    (
        re.compile(
            r"^After respawn, change your route: (?P<n>\d+) deaths in the last (?P<m>\d+) "
            r"minutes?\.$"
        ),
        lambda g: (
            f"Після відродження змініть маршрут: {g['n']} {_deaths_word(int(g['n']))} за {g['m']} хв."
        ),
    ),
    (
        re.compile(
            r"^Your team is (?P<n>\d+) kills behind: farm your own half and fight near your "
            r"towers\.$"
        ),
        lambda g: (
            f"Команда відстає на {g['n']} {_kills_word(int(g['n']))}: фарміть на своїй половині й бийтеся лише біля своїх веж."
        ),
    ),
    (
        re.compile(
            r"^Your team is (?P<n>\d+) kills ahead: group up and take a tower instead of "
            r"farming alone\.$"
        ),
        lambda g: (
            f"Команда попереду на {g['n']} {_kills_word(int(g['n']))}: зберіться й знесіть вежу, а не фарміть поодинці."
        ),
    ),
    (
        re.compile(r"^Stay alive: you are on a (?P<n>\d+)-kill streak\.$"),
        lambda g: f"Бережіть себе: у вас серія з {g['n']} вбивств поспіль.",
    ),
    (
        re.compile(
            r"^(?P<count>\d+) deaths(?P<kind> under stuns with no free second|, each from high "
            r"health in 3 seconds or less), and (?P<name>.+?) (?:stops that|gives you time against "
            r"that)(?P<tail>(?:\.|: \d+ gold to go.*|; its missing parts cost.*))$"
        ),
        _situational_reason,
    ),
    (
        re.compile(
            r"^(?P<count>\d+) deaths under stuns against (?P<enemy>.+?), and (?P<name>.+?) "
            r"blocks (?P<spell>.+?)" + _SITUATIONAL_TAIL_RE
        ),
        _counter_reason,
    ),
    (
        re.compile(
            r"^(?P<enemy>.+?) (?P<kind>dodges your attacks|heals a lot|fights with illusions), "
            r"and (?P<name>.+?) (?:pierces it on most attacks|cuts the healing|hits them all)"
            + _SITUATIONAL_TAIL_RE
        ),
        _counter_reason,
    ),
    (
        re.compile(
            r"^(?P<enemy>.+?) relies on (?P<passive>.+?), and (?P<name>.+?) turns it off"
            + _SITUATIONAL_TAIL_RE
        ),
        _counter_reason,
    ),
    (
        re.compile(
            r"^(?P<count>\d+) enemy heroes deal magic damage, and (?P<name>.+?) protects you "
            r"from it" + _SITUATIONAL_TAIL_RE
        ),
        _magic_reason,
    ),
    (
        re.compile(
            r"^You lost (?P<n>\d+)% HP in 5 seconds: at this rate you have seconds left, "
            r"leave now\.$"
        ),
        lambda g: (
            f"За 5 секунд пішло {g['n']}% HP: у такому темпі у вас лічені секунди, ідіть зараз."
        ),
    ),
    (
        re.compile(
            r"^Your HP has dropped this low (?P<n>\d+) times this game: "
            r"heal up fully before you go back\.(?P<regen> No regen in your bag: "
            r"have the courier bring a Healing Salve\.)?$"
        ),
        lambda g: (
            f"HP падає так низько вже {g['n']}-й раз за гру: перш ніж повертатися, відновіться повністю."
            + (
                " Регенерації в сумці немає: нехай кур'єр привезе Healing Salve."
                if g["regen"]
                else ""
            )
        ),
    ),
    (
        re.compile(rf"^After respawn, stay away from the {_ZONE_RE} {_SIDE_RE}\.$"),
        lambda g: (
            f"Після відродження тримайтеся подалі {_ZONE_FROM[g['zone']]} {_SIDE[g['side']]}."
        ),
    ),
    (
        re.compile(
            rf"^(?P<count>\d+) deaths in the {_ZONE_RE} {_SIDE_RE} in (?P<m>\d+) minutes?: "
            r"farm somewhere safer until your team is there\.$"
        ),
        lambda g: (
            f"{g['count']} {_deaths_word(int(g['count']))} {_ZONE_IN[g['zone']]} {_SIDE[g['side']]} за {g['m']} хв: фарміть в іншому місці, доки там немає вашої команди."
        ),
    ),
    (
        re.compile(
            rf"^(?P<count>\d+) deaths in the {_ZONE_RE} {_SIDE_RE} this game: "
            r"farm somewhere safer until your team is there\.$"
        ),
        lambda g: (
            f"{g['count']} {_deaths_word(int(g['count']))} {_ZONE_IN[g['zone']]} {_SIDE[g['side']]} за гру: фарміть в іншому місці, доки там немає вашої команди."
        ),
    ),
    (
        re.compile(
            rf"^You died in the {_ZONE_RE} on the enemy side: "
            r"farm your own half until your team is with you\.$"
        ),
        lambda g: (
            f"Ви загинули {_ZONE_IN[g['zone']]} на половині ворога: фарміть на своїй половині, доки команда не поруч."
        ),
    ),
    (
        re.compile(
            rf"^After respawn, farm your own half: you died in the {_ZONE_RE} on the enemy side\.$"
        ),
        lambda g: (
            f"Після відродження фарміть на своїй половині: ви загинули {_ZONE_IN[g['zone']]} на половині ворога."
        ),
    ),
    (
        re.compile(
            r"^After respawn, play the (?P<zone>top lane|mid lane|bottom lane) closer to your "
            r"tower until you see the enemy heroes\.$"
        ),
        lambda g: (
            f"Після відродження грайте {_ZONE_IN[g['zone']]} ближче до своєї вежі, доки не побачите ворожих героїв."
        ),
    ),
    (
        re.compile(
            rf"^After respawn, avoid the {_ZONE_RE} {_SIDE_RE} without your team: you died there\.$"
        ),
        lambda g: (
            f"Після відродження не ходіть {_ZONE_TO[g['zone']]} {_SIDE[g['side']]} без команди: ви загинули там."
        ),
    ),
    (
        re.compile(
            r"^After respawn, stay near your towers or your team: "
            r"you went down in (?P<s>\d+) seconds? from high HP\.$"
        ),
        lambda g: (
            f"Після відродження тримайтеся біля своїх веж або поруч із командою: вас убили за {g['s']} с з високого здоров'я."
        ),
    ),
)

# Critical HP with an Aegis, a revive or a hero save ready (live_tools.INSURANCE_COPY);
# patterns, since the exact table keeps Latin words to HP only.
_UK_INSURANCE: dict[str, str] = {
    "You hold the Aegis: leave unless this fight is worth losing it.": (
        "У вас Aegis: відходьте, якщо цей бій не вартий його втрати."
    ),
    "A death now revives you on the spot, but the Aegis is gone after that.": (
        "Смерть зараз воскресить вас на місці, але після цього Aegis зникне."
    ),
    "Use Borrowed Time before the next burst: damage will heal you.": (
        "Застосуйте Borrowed Time до наступного сплеску шкоди: шкода вас лікуватиме."
    ),
    "Borrowed Time is ready: while it lasts, incoming damage heals you instead.": (
        "Borrowed Time готова: поки вона діє, вхідна шкода лікує вас."
    ),
    "If a healthy enemy hero is in range, Sunder swaps your HP with theirs.": (
        "Якщо поруч ворожий герой із високим HP, Sunder обміняє ваше HP на його."
    ),
    "Sunder is ready: at low HP it is your save; with no healthy target, leave.": (
        "Sunder готова: при низькому HP це ваш порятунок; без здорової цілі відходьте."
    ),
    "Reincarnation is ready: leave unless this fight is worth spending it.": (
        "Reincarnation готова: відходьте, якщо цей бій не вартий її витрати."
    ),
    "A death now revives you after a few seconds, but its long cooldown starts.": (
        "Смерть зараз воскресить вас за кілька секунд, але почнеться її довга перезарядка."
    ),
}
_UK_PATTERNS += tuple(
    (re.compile(r"^" + re.escape(source) + r"$"), translated)
    for source, translated in _UK_INSURANCE.items()
)

# advice_ux_policy rewords coaching-mode actions as "Consider: <action>" (older
# logs and history have "Consider <action>").
_UK_PATTERNS += tuple(
    (re.compile(r"^" + re.escape(source) + r"$"), translated)
    for source, translated in GAMEPLAY_TRANSLATIONS.items()
)

_CONSIDER_PREFIX = re.compile(r"^Consider:? (?P<rest>.+)$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z])")
_TRUNCATION = "..."


def normalize_lang(value: object) -> str:
    """Map "uk", "uk-UA", "UK" (and the country code "ua") to "uk"; anything else is English."""
    return "uk" if str(value or "").strip().lower()[:2] in {"uk", "ua"} else DEFAULT_LANG


def _normalize(text: str) -> str:
    text = " ".join(text.split())
    # Two spellings of the same status line exist in the pipeline.
    return text.replace(" - ", " — ")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _translate_sentence(text: str) -> str | None:
    exact = _UK_EXACT.get(text)
    if exact is not None:
        return exact
    for pattern, template in _UK_PATTERNS:
        match = pattern.match(text)
        if match:
            return template.format(**match.groupdict())
    for pattern, render in _UK_FUNCTIONS:
        match = pattern.match(text)
        if match:
            return render(match.groupdict())
    return None


def _translate_consider(text: str) -> str | None:
    match = _CONSIDER_PREFIX.match(text)
    if not match:
        return None
    rest = match.group("rest")
    inner = _translate_sentence(rest[:1].upper() + rest[1:])
    return f"Подумайте: {_lower_first(inner)}" if inner else None


def _translate_truncated(text: str) -> str | None:
    # scheduler.text truncates long lines to "<prefix>..."; show the full
    # Ukrainian line instead (the UI clamps long text itself).
    prefix = text[: -len(_TRUNCATION)].rstrip()
    if len(prefix) < 20:
        return None
    candidates = [source for source in _UK_EXACT if source.startswith(prefix)]
    return _UK_EXACT[candidates[0]] if len(candidates) == 1 else None


def translate_uk(text: str) -> str | None:
    """Ukrainian for one visible advice text, or None when it is not known."""
    normalized = _normalize(text)
    if not normalized:
        return None
    result = _translate_sentence(normalized) or _translate_consider(normalized)
    if result is not None:
        return result
    if normalized.endswith(_TRUNCATION) and not normalized.endswith("...."):
        truncated = _translate_truncated(normalized)
        if truncated is not None:
            return truncated
    sentences = _SENTENCE_SPLIT.split(normalized)
    if len(sentences) > 1:
        parts = [
            _translate_sentence(sentence) or _translate_consider(sentence) for sentence in sentences
        ]
        if all(parts):
            return " ".join(part for part in parts if part)
    return None


def translate_text(text: Any, lang: str) -> Any:
    """Translate one visible text; unknown text and non-strings pass through."""
    if lang != "uk" or not isinstance(text, str):
        return text
    return _render_message(_message_for_text(text)) or text


@dataclass(frozen=True)
class AdviceMessage:
    id: str
    params: tuple[tuple[str, str | None], ...] = ()
    parts: tuple[AdviceMessage, ...] = ()

    def dto(self) -> dict[str, Any]:
        params: dict[str, Any] = dict(self.params)
        if self.parts:
            params["parts"] = [part.dto() for part in self.parts]
        return {"id": self.id, "params": params}


def _message_id(kind: str, source: str) -> str:
    # Content-derived IDs stay stable when catalog entries are inserted/reordered.
    return f"live.{kind}.{sha256(source.encode('utf-8')).hexdigest()[:20]}"


_MESSAGE_RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {}
_EXACT_MESSAGE_IDS: dict[str, str] = {}


def _render_exact(_params: dict[str, Any], *, text: str) -> str:
    return text


def _render_pattern(params: dict[str, Any], *, template: str) -> str:
    return template.format(**params)


for _source, _ukrainian in _UK_EXACT.items():
    _id = _message_id("exact", _source)
    _EXACT_MESSAGE_IDS[_source] = _id
    _MESSAGE_RENDERERS[_id] = partial(_render_exact, text=_ukrainian)

_PATTERN_MESSAGE_IDS: list[tuple[re.Pattern[str], str]] = []


def _plan_reason(
    english: str, ukrainian: str
) -> tuple[re.Pattern[str], Callable[[dict[str, str]], str]]:
    """A hero plan's reason (hero_items.reason_templates) as the farm advice says
    it: the clause, then its gold tail; placeholders match any text."""
    parts: list[str] = []
    seen: set[str] = set()
    for literal, name, _, _ in string.Formatter().parse(english):
        parts.append(re.escape(literal))
        if name is not None:
            parts.append(f"(?P={name})" if name in seen else f"(?P<{name}>.+?)")
            seen.add(name)
    pattern = re.compile("^" + "".join(parts) + _SITUATIONAL_TAIL_RE)

    def render(groups: dict[str, str]) -> str:
        tail = _situational_tail(groups["tail"])
        values = {k: v for k, v in groups.items() if k != "tail"}
        return ukrainian.format(**values) + tail if tail is not None else ""

    return pattern, render


def _plan_reasons() -> tuple[tuple[re.Pattern[str], Callable[[dict[str, str]], str]], ...]:
    from app.hero_items import reason_templates

    return tuple(_plan_reason(en, uk) for en, uk in reason_templates())


_UK_FUNCTIONS += _plan_reasons()

for _pattern, _template in _UK_PATTERNS:
    _id = _message_id("pattern", f"{_pattern.flags}:{_pattern.pattern}")
    _PATTERN_MESSAGE_IDS.append((_pattern, _id))
    _MESSAGE_RENDERERS[_id] = partial(_render_pattern, template=_template)
for _pattern, _render in _UK_FUNCTIONS:
    _id = _message_id("function", f"{_pattern.flags}:{_pattern.pattern}")
    _PATTERN_MESSAGE_IDS.append((_pattern, _id))
    _MESSAGE_RENDERERS[_id] = _render


@lru_cache(maxsize=512)
def _message_for_text(text: str) -> AdviceMessage:
    normalized = _normalize(text)
    exact = _EXACT_MESSAGE_IDS.get(normalized)
    if exact:
        return AdviceMessage(exact)
    for pattern, message_id in _PATTERN_MESSAGE_IDS:
        match = pattern.match(normalized)
        if match:
            return AdviceMessage(message_id, tuple(sorted(match.groupdict().items())))
    consider = _CONSIDER_PREFIX.match(normalized)
    if consider:
        rest = consider.group("rest")
        inner = _message_for_text(rest[:1].upper() + rest[1:])
        if inner.id != "live.unknown":
            return AdviceMessage("live.consider", parts=(inner,))
    if normalized.endswith(_TRUNCATION) and not normalized.endswith("...."):
        prefix = normalized[: -len(_TRUNCATION)].rstrip()
        if len(prefix) >= 20:
            candidates = [source for source in _EXACT_MESSAGE_IDS if source.startswith(prefix)]
            if len(candidates) == 1:
                return AdviceMessage(_EXACT_MESSAGE_IDS[candidates[0]])
    sentences = _SENTENCE_SPLIT.split(normalized)
    if len(sentences) > 1:
        parts = tuple(_message_for_text(sentence) for sentence in sentences)
        if all(part.id != "live.unknown" for part in parts):
            return AdviceMessage("live.sentences", parts=parts)
    return AdviceMessage("live.unknown", params=(("text", text),))


@lru_cache(maxsize=512)
def _render_message(message: AdviceMessage) -> str | None:
    if message.id == "live.consider" and len(message.parts) == 1:
        inner = _render_message(message.parts[0])
        return f"Подумайте: {_lower_first(inner)}" if inner else None
    if message.id == "live.sentences" and message.parts:
        parts = [_render_message(part) for part in message.parts]
        return " ".join(part for part in parts if part) if all(parts) else None
    renderer = _MESSAGE_RENDERERS.get(message.id)
    return renderer(dict(message.params)) if renderer else None


def _message_from_dto(value: Any, *, depth: int = 0) -> AdviceMessage | None:
    if not isinstance(value, dict) or depth > 4:
        return None
    message_id, params = value.get("id"), value.get("params")
    if (
        not isinstance(message_id, str)
        or len(message_id) > 100
        or not isinstance(params, dict)
        or len(params) > 20
    ):
        return None
    parts = params.get("parts", [])
    if not isinstance(parts, list) or len(parts) > 16:
        return None
    children = tuple(_message_from_dto(part, depth=depth + 1) for part in parts)
    if any(child is None for child in children):
        return None
    scalar = {k: v for k, v in params.items() if k != "parts"}
    if any(
        not isinstance(k, str) or (v is not None and (not isinstance(v, str) or len(v) > 2048))
        for k, v in scalar.items()
    ):
        return None
    return AdviceMessage(message_id, tuple(sorted(scalar.items())), tuple(c for c in children if c))


def advice_messages(item: Any) -> Any:
    """Attach additive IDs/params once; canonical English fields stay unchanged."""
    if not isinstance(item, dict):
        return item
    result = dict(item)
    for field in ("action", "reason"):
        if isinstance(result.get(field), str):
            result[field + "_message"] = _message_for_text(result[field]).dto()
    return result


def _localize_advice_fields(item: Any, lang: str) -> Any:
    if not isinstance(item, dict):
        return item
    localized = dict(item)
    if isinstance(item.get("action"), str):
        # Spoken in English when Windows has no Ukrainian voice.
        localized["action_en"] = item["action"]
    for key in ("action", "reason"):
        if key in localized:
            message = _message_from_dto(item.get(key + "_message"))
            if message is not None:
                try:
                    localized[key] = _render_message(message) or localized[key]
                except (KeyError, ValueError, TypeError):
                    localized[key] = translate_text(localized[key], lang)
            else:
                localized[key] = translate_text(localized[key], lang)
    return localized


def localize_overlay_response(response: dict[str, Any], lang: str) -> dict[str, Any]:
    """Copy of an /overlay/recommendation payload with visible text localized."""
    if lang != "uk":
        return response
    localized = dict(response)
    for key in ("recommendation", "last_visible_advice"):
        if key in localized:
            localized[key] = _localize_advice_fields(localized[key], lang)
    if "message" in localized:
        localized["message"] = translate_text(localized["message"], lang)
    localized["lang"] = lang
    return localized


def localize_advice_items(items: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """Localize the action/reason of /advice/recent items."""
    if lang != "uk":
        return items
    return [_localize_advice_fields(item, lang) for item in items]
