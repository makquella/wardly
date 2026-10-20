# Wardly: запуск набора бета-тестеров, UK + EN

**С 20.10.2026 набор — «керрі до 4к MMR»** вместо трёх героев: в 0.57 у 20 керри свой план. Все ссылки ведут на страницу беты [beta.html](https://luhovyimvp.dev/beta.html) / [en/beta.html](https://luhovyimvp.dev/en/beta.html) с путём «скачай → настрой → сыграй 3 матча → оставь отзыв»; закреплённое сообщение группы тестеров — [beta-pinned.md](beta-pinned.md).

Основная работа сейчас — [улучшенная серия Shorts и конкретный план публикаций](shorts-plan.md). Сообщества — дополнительный бесплатный канал. Новая пара v4 заменяет приведённый ниже ранний черновик следующего Shorts; состояние готовых файлов фиксируется в плане и PR.

## Что проверено 15 октября 2026

[Снимок публикаций](https://github.com/makquella/wardly/actions/runs/38762411614) получен в 18:40 по Киеву.

| Ролик | Публикация, Киев | Язык текста / аудио | Доступ / обработка | Просмотры API |
|---|---|---|---|---|
| [UK](https://www.youtube.com/shorts/Q8etsMs4470) | 15.10, 13:41:23 | uk / uk | public / succeeded | 2 |
| [EN](https://www.youtube.com/shorts/KAwwovVUuMI) | 15.10, 13:41:25 | en / en | public / succeeded | 1 |

Канал создан 13 октября в 01:43 по Киеву. На момент проверки — 0 подписчиков и 2 видео. Видимых запретов доступа или ошибок обработки API не вернул. Это не проверка всех внутренних факторов рекомендаций YouTube.

Позже владелец прислал данные Studio для UK: 3 просмотра, 66,7% из поиска и 33,3% со страницы канала. В этом срезе нет просмотров, отнесённых к ленте Shorts. Количество показов в ленте, доля пролистываний и удержание остаются неизвестными. Нельзя утверждать ни «показов не было», ни «зрители плохо удерживаются».

YouTube Analytics API вернул `403 accessNotConfigured`: API не включён для проекта. Для будущего автоматического чтения понадобится включить YouTube Analytics API и авторизовать `yt-analytics.readonly`. Текущий доступ даёт чтение публикаций и счётчиков, а не эти показатели Studio.

[Официальная справка о тегах](https://support.google.com/youtube/answer/146402?hl=en) прямо говорит, что теги играют небольшую роль в обнаружении видео, кроме исправления частых опечаток. [Справка о рекомендациях](https://support.google.com/youtube/answer/11914225?hl=en) описывает персонализацию и поведение зрителей. Изменение тегов не даёт возможности назначить аудиторию или гарантировать показы.

## Цель и последовательность

Владелец выбрал **бесплатные согласованные размещения в сообществах**. Платные предложения не принимаем; рекламный бюджет не используется.

[Готовая очередь обращений](beta-outreach.md): проверенные Telegram/Discord-ссылки, публичный адрес Maincast и шесть персонализированных текстов. Личных сообщений авторам ещё не отправлено: подключён только бот доставки владельцу, без личного Telegram/Discord/почты. Режим `outreach` в Promo передаёт один документ владельцу и не публикует его в сообществах.

Рабочая цель пилота: найти по 10 активных тестеров на каждом языке. Это цель эксперимента, а не прогноз результата. Считать отдельно охват, переходы, загрузки, согласившихся игроков, сыгранные матчи и полученный полезный фидбек.

1. Сохранить текущие публикации и их исходные показатели. Не удалять и не перезаливать их ради «сброса алгоритма».
2. Начать с адресного согласования одного прозрачного поста разработчика в подходящих сообществах. Внешние сообщения и посты пока **не отправлены**; доступ к чужим сообществам и разрешение модераторов не предполагаются.
3. Вести игроков на страницу беты их языка (`beta.html` / `en/beta.html`) с инструкцией участия. Отвечать на «БЕТА» / BETA с этой инструкцией в день обращения.
4. Подготовить следующий Shorts с ролью (керри) и MMR уже в первом кадре. После появления данных сравнивать поведение зрителей, а не менять сразу язык, озвучку, монтаж и призыв.
5. Через 24 и 72 часа после каждого размещения записывать результат. При малой выборке фиксировать «данных мало», без выводов о победителе.

Сам по себе внешний переход не гарантирует дальнейших рекомендаций Shorts. Польза размещения — доступ к подходящим игрокам и возможность получить реальных участников теста.

## Проверенный список для адресного обращения

Источники: [публичный поиск и данные каналов через API](https://github.com/makquella/wardly/actions/runs/38762959310). Число подписчиков — снимок на 15.10.2026, не обещание охвата размещения. Согласие, стоимость, доступность контакта и правила размещения ещё не подтверждены. Название канала в результатах поиска само по себе не подтверждает язык; примеры ниже проверены по заголовкам публикаций.

| Приоритет | Аудитория / канал | Почему подходит | Подтверждение тематики | Ссылка кампании |
|---|---|---|---|---|
| 1 UK | [Krauch_V](https://www.youtube.com/channel/UCQut_NvqjmTcYjlAI6es80w), 9 530 | Украиноязычные Dota-стримы, небольшой тематический канал | [UA DOTA 2, 30.08](https://www.youtube.com/watch?v=hFHKjO-j6h0) | https://luhovyimvp.dev/beta.html?ref=beta-uk-krauch |
| 1 UK | [Типовий Лс з Харди](https://www.youtube.com/channel/UCkei_sEPZde5SRYUxPWQ97Q), 3 900 | Украиноязычные игроки и обсуждение решений | [Dota 2 Українською, 28.07](https://www.youtube.com/watch?v=YYOCJgFf3Q8) | https://luhovyimvp.dev/beta.html?ref=beta-uk-hardy |
| 2 UK | [Ghostik](https://www.youtube.com/channel/UCwqbubdeglCU60ntcz7A-7w), 41 400 | Украиноязычные разборы решений, можно запросить экспертный фидбек | [Разбор решений на Axe, 14.10](https://www.youtube.com/watch?v=QL_4xrLzPRc) | https://luhovyimvp.dev/beta.html?ref=beta-uk-ghostik |
| 3 UK | [Dota 2 Maincast](https://www.youtube.com/channel/UCXjZjHhyrkODi2PBNvHrRvw), 35 300 | Украиноязычная Dota-аудитория; возможное партнёрское размещение | [UA трансляция, 23.08](https://www.youtube.com/watch?v=ggG8BLsFvV0) | https://luhovyimvp.dev/beta.html?ref=beta-uk-maincast |
| 1 EN | [Qubi_Dota_Coaching](https://www.youtube.com/channel/UC4GP0zkMKGbXicHNx3UckSw), 428 | Очень узкое совпадение: Sven carry и 2–4k MMR | [Sven, 2–4k MMR, 06.09](https://www.youtube.com/watch?v=CvaGSR9ZfWw) | https://luhovyimvp.dev/en/beta.html?ref=beta-en-qubi |
| 2 EN | [BalloonDota](https://www.youtube.com/channel/UCYldE7tGQHjNwIVHQ7bDNoA), 33 900 | Англоязычные carry/low-MMR разборы | [Low MMR Carry Guide, 05.08](https://www.youtube.com/watch?v=J6m5LDaP_B0) | https://luhovyimvp.dev/en/beta.html?ref=beta-en-balloon |

Цифры/обещания побед из названий чужих видео не являются обещаниями Wardly и не используются в объявлениях.

Для r/learndota2 и r/DotA2 проверка правил через Reddit вернула HTTP 403. Эти площадки **не считаются разрешёнными для рекламы**. До поста нужны ручная проверка актуальных правил и согласование модераторов. Также не размещать рекламу в комментариях чужих видео и в стрим-чатах без разрешения.

## Обращение к украинским модераторам / автору

> Привіт! Розвиваємо Wardly — безкоштовний Windows-тренер для Dota 2 з підказками в матчі та розбором після гри. Шукаємо невелику групу керрі-гравців приблизно до 4к MMR: у версії 0.57 у 20 керрі свій план — предмети проти ворожого драфту, збірка й прокачка з лігових матчів. Хочемо перевірити, чи поради точні й вчасні.
>
> Чи можна погодити один безкоштовний допис від розробника у вашій спільноті? Потрібні три матчі на керрі й чесний відгук: що допомогло, що відволікало, де порада була хибною. Будемо вдячні й за критику. Як долучитися: https://luhovyimvp.dev/beta.html. Публічний приклад: https://www.youtube.com/shorts/Q8etsMs4470
>
> Обіцянок приросту MMR немає. Можемо надіслати текст допису на перевірку й підлаштувати його під правила спільноти. Чи прийнятний у вас такий формат?

Для Ghostik добавить одно конкретное предложение перед описанием: «У вашому каналі є розбір рішень на Axe від 14 жовтня; саме чесна оцінка корисності порад дуже допомогла б цьому тесту». Это ссылка на проверенный заголовок, а не утверждение, что автор уже знаком с продуктом или рекомендует его.

## Message to English-speaking moderators / creator

> Hi! We're developing Wardly, a free Windows coach for Dota 2 with in-game tips and post-match reviews. We're looking for a small group of carry players under about 4k MMR: in version 0.57, 20 carries have a plan of their own, with items against the enemy draft, builds and skills from league matches. We want to check whether the advice is accurate and on time.
>
> Would your moderators allow one transparent developer post in the community at no cost? Participation means three carry matches and honest feedback: what helped, what distracted you, and which advice was wrong. Criticism is useful. How to join: https://luhovyimvp.dev/en/beta.html. Public demo: https://www.youtube.com/shorts/KAwwovVUuMI
>
> We're not promising MMR gains or asking you to endorse the advice. We can send the post for review and follow your community rules. Would this format be appropriate?

For Qubi, the optional opening is: “Your channel has a Sven carry analysis for 2–4k MMR players; that's exactly one of the groups we're looking for.” For BalloonDota: “Your carry and low-MMR guides reach the kind of players we're hoping to hear from.” Neither implies an existing relationship or an endorsement.

## Готовый украинский пост после согласования

**Граєте керрі до 4к MMR? Допоможіть перевірити Wardly**

Wardly — безкоштовний Windows-тренер для Dota 2: підказки під час гри та розбір після матчу. У версії 0.57 у 20 керрі свій план: предмети проти ворожого драфту під вашого героя, звичайна й темпова збірка, прокачка з талантами — з лігових матчів поточного патча.

Шукаємо керрі-гравців приблизно до 4к MMR. Шлях простий:

1. Завантажте й налаштуйте — у застосунку є список «Перший запуск».
2. Зіграйте три матчі на керрі.
3. Позначте поради в розборі («Корисно», «Не до речі», «Повторювалося») і напишіть, що допомогло, що запізнилося чи відволікало, де порада була хибною.

Усі кроки: https://luhovyimvp.dev/beta.html?ref=beta-uk-community

Хочете долучитися? Напишіть «БЕТА» й основного керрі у відповіді. Обіцянок приросту MMR немає — потрібна чесна оцінка.

## English post after moderator approval

**Carry player under 4k MMR? Help us test Wardly**

Wardly is a free Windows coach for Dota 2: in-game tips and post-match reviews. In version 0.57, 20 carries have a plan of their own: items against the enemy draft for your hero, a usual and a tempo build, skills and talents, all from league matches of the current patch.

We're looking for carry players under about 4k MMR. The path is short:

1. Download and set up: the app has a “Getting started” list.
2. Play three matches as a carry.
3. Mark the advice in the review (“Useful”, “Not to the point”, “Repeated”) and tell us what helped, what came too late or distracted you, and which advice was wrong.

Every step: https://luhovyimvp.dev/en/beta.html?ref=beta-en-community

Want to join? Reply BETA with your main carry. No MMR promises: we need an honest verdict.

## Ответ участнику

UK:

> Дякую! Усі кроки тут: https://luhovyimvp.dev/beta.html?ref=beta-uk-reply. Зіграйте три матчі на керрі, позначте поради в розборі й напишіть, що допомогло, що запізнилося чи відволікало, де порада була хибною. Для помилки в застосунку є «Повідомити про проблему». Будь ласка, вкажіть героя й приблизну хвилину. І якщо не проти — увімкніть «Допомогти покращити підказки» в «Налаштування → Застосунок».

EN:

> Thanks! Every step is here: https://luhovyimvp.dev/en/beta.html?ref=beta-en-reply. Play three carry matches, mark the advice in the review and tell us what helped, what came too late or distracted you, and which advice was wrong. The app also has “Report a problem” for bugs. Please add the hero and the rough minute. And if you don't mind, turn on “Help improve the advice” in Settings → App.

## Следующий Shorts: роль и MMR с первого кадра

Статус: заменён парой «керрі до 4к» из [shorts-plan.md](shorts-plan.md) (отложенная публикация в 17:00 по Киеву). Прежний черновик с тремя героями больше не используется.

Первая проверяемая гипотеза прежняя: роль и диапазон рейтинга в первом кадре раньше объясняют подходящему игроку, зачем смотреть дальше. Второй тест менять только после данных первого; не объявлять победу по единичным просмотрам.

## Учёт и решение после пилота

Ссылки `ref` используют уже существующие агрегированные счётчики сайта: посещения и переходы на загрузку. Никакой новой формы и персонального трекинга не добавлено. Счётчик загрузок отражает переход на установщик, а не подтверждённую установку.

| Площадка | Язык | Дата и разрешение модератора | Переходы | Загрузки | Ответы БЕТА/BETA | Сыграли несколько матчей | Полезные отзывы |
|---|---|---|---|---|---|---|---|
| Первый слот UK | uk | ещё не согласовано | — | — | — | — | — |
| Первый слот EN | en | ещё не согласовано | — | — | — | — | — |

Проверять данные каждой площадки через 24 и 72 часа после фактического поста. Сравнивать результаты с учётом размера и правил сообщества. Для Shorts отдельно фиксировать «Показано в ленте», долю просмотра/пролистывания, среднее время и процент просмотра. Если этих данных мало, не объяснять результат удержанием. Решение о продолжении принимать по качеству пришедших игроков и фидбека вместе с охватом.

Выбран бесплатный запуск. Если автор предлагает только платное размещение, пропустить его и продолжить с другими сообществами. Никаких сообщений авторам или модераторам этот документ и диагностический скрипт не отправляют.
