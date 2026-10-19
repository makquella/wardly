# Wardly Marketing Engine

Short vertical videos (TikTok, Instagram Reels, YouTube Shorts) and Telegram
posts, made three times a week from the project's own data, with no gameplay
recording, editing or screen capture. Every video goes to the developer's
Telegram first; nothing is published without a button press there. Publishing
goes straight to YouTube, Instagram and TikTok through their own free APIs.

## Pipeline

```mermaid
flowchart LR
    Data[(hero profiles · weekly meta · release notes)] --> Topics[topics.py]
    Backend[real live pipeline] --> Demo[coach_demo.py]
    Topics --> Script[script.py]
    Demo --> Script
    Script --> Voice[voice.py · ElevenLabs]
    Script --> Scenes[scenes.py · HTML 1080x1920]
    Voice --> Render[render.py · Chrome frames + ffmpeg]
    Scenes --> Render
    Media[media.py · Valve animations and clips] --> Render
    Render --> QC[quality.py]
    QC --> Send[send.py]
    Send -->|video + buttons| TG[developer's Telegram]
    Send -->|package + media| Worker[Worker src/promo.js · D1 + R2]
    TG -->|button press| Worker
    Worker -->|✅| Channel[@wardlydota]
    Worker -->|✅ queue, cron */5| Direct[YouTube Data API · Instagram API · TikTok Content Posting API]
    Direct -->|daily numbers| Worker
    Worker -. optional .-> Metricool[Metricool]
    Worker -->|GET /v1/admin/promo| Weights[weights.py → data/promo/weights.json]
    Weights --> Topics
```

| Step | Where | What |
|---|---|---|
| Topic | `scripts/promo/topics.py` | A release not promoted yet first; the week's meta and its fact once per meta post; draft videos rotate the enemies the app counters with an item (none of the last 8; the highest weight, the format for TikTok first); coach and hero videos rotate the 64 heroes with a site page (popular first, none of the last 20). Formats are drawn by weight, never the same twice in a row, seeded by the date. |
| Script | `scripts/promo/script.py`, `draft_demo.py` | Six formats. **draft**: «still buying the same items every match?» → against an enemy (Phantom Lancer, Spectre…) the counter item from the app's own logic (`situational_items.py`, `draft_analysis.COUNTERS`) on the overlay's own card text (`map_hints.py`), the card hitting as the voice says «Wardly». Every number comes from a listed source: OpenDota weekly stats (`data/news/posts`), hero profiles, release notes. |
| Real cards | `scripts/promo/coach_demo.py` | «What Wardly says on X»: a synthetic match runs through the real backend (`/gsi` → rules → scheduler → `/overlay/recommendation`) with two moments built from the hero's profile, HP falling fast with an escape ready, and a stun with BKB ready. The video shows exactly what the app shows. |
| Voice | `scripts/promo/voice.py` | ElevenLabs v4 with the selected Ukrainian male Alex Nekrasov (variant A, stability 0.5, speed 1.0): the Ukrainian script with the English hero, ability and item names read as written. One continuous request for the full script, split by aligned words for the scene renderer; the character alignment gives every word its time. Percent words agree with the number. |
| Moving pictures | `scripts/promo/media.py` | Valve's own, from dota2.com's CDN: each hero's idle animation (VP9 with transparency) and in-game clips of abilities. Valve's hero data feed names the abilities, so a card that says «use Shackles» gets the Shackles clip; an item card gets the item's icon. A coach moment opens on an enemy's stun or burst. Clips are cropped to 9:16 where they move most, with the action above the overlay card, and decoded into frames once per run. |
| Picture | `scripts/promo/scenes.py`, `render.py` | One HTML page drawn frame by frame (`window.renderAt(t)`), 30 fps; frame sequences play frame-exact. Cuts punch in with a flash, a card hits with a shake, the advised ability or item follows. Site fonts and colours, the real overlay card CSS. Subtitles light up word by word with the voice. Content stays out of the platforms' button areas. |
| Check | `scripts/promo/quality.py` | 12 to 59 s, 1080x1920, a voice track, caption limits, no promises or cheat claims, no unfilled placeholders, sources present. |
| Approval | `scripts/promo/send.py` → Telegram | The video with buttons **✅ Всюди · 📣 Лише Telegram · ▶️ Лише YouTube · ❌ Відхилити** (YouTube only skips the channel and the other networks), and a reply with captions per network, the YouTube title and the data sources. |
| Publish | `services/api/src/promo.js`, `src/social.js` | On a press from `TELEGRAM_CHAT_ID`: the channel post at once (by the approval message's file id), and one delivery per connected network. The five-minute cron works the queue: YouTube (one resumable upload), Instagram (a Reel container, polled until ready, then published), TikTok (an upload to the app's inbox as a draft, or a direct post). The result comes as a reply to the approval message. Networks that are not connected go through Metricool if it is configured, else they are listed as not connected. |
| Numbers | `promo.js` cron, `scripts/promo/weights.py` | Daily: views, likes, comments and shares straight from YouTube, Instagram and TikTok (and Metricool, if used). Mondays: a note to the developer. Before each video: format multipliers (median views per format over the median of all, at least 3 videos, bounded to 0.3–3×). |

Run locally, from the repository root (the backend venv plus `scripts/promo/requirements.txt`, `python -m playwright install chromium`):

```bash
ELEVENLABS_API_KEY=... \
  python -m scripts.promo.package --out promo-out --format coach   # video.mp4, cover.jpg, package.json
python -m scripts.promo.package --out promo-out --format coach --allow-silent  # no key: a silent draft
python -m scripts.promo.package --out promo-out --format meta --no-video  # script and captions only
```

The video needs the network (Valve's animations and clips, ElevenLabs); keep the key out of shell history and files.

## Private beta recruitment pair

The manual **Promo** input `beta_campaign=build` makes two 1080×1920,
20–27-second recruitment Shorts, Ukrainian and English. It does not send or
publish, regardless of `send`. The copy asks voluntary 0–4k MMR players,
especially Sven/Juggernaut/Terrorblade players, for a few matches and honest
feedback about helpful, late, distracting or incorrect advice. It promises no
MMR gains and teaches no universal item/HP rules. `scripts/promo/beta_scenes.py`
uses the site's own Montserrat/Inter fonts, branding and localized screenshots.

`scripts/promo/beta.py` verifies the live site, reads the authenticated
ElevenLabs model catalog (prefers the actual `eleven_v4` ID, otherwise explicitly
records supported `eleven_v3`), and keeps Alex Nekrasov
`9Sj8ugvpK1DmcAXyvi3a`, stability 0.5, speed 1.0. Each script is one continuous
take. Its character alignment supplies scene cuts and every burned-in subtitle;
the master recording is never split or sped up. The final card shows the local
site URL, Free for Windows and the БЕТА/BETA comment call to action.

Visual revision 2 uses one brand mark, no progress bar, and short editorial
caption phrases that preserve every word and its alignment. The opening caption
becomes the headline; the final invitation and comment card replace duplicate
subtitles. `beta_style.css` and `beta_motion.js` control deterministic motion,
including Valve's official animated hero renders from the existing media source.
Hero emphasis, the in-game/review cut and feedback highlights follow spoken words.
Review screenshots are cropped past the sidebar logo. The artifact retains
source URLs/hashes, frame sequences and self-contained storyboards for review.

Build artifacts include MP4s, covers, scripts, SRTs, word alignment, seven sample
frames per language, source verification and layout/audio/decode reports.
An independent CPU Whisper pass checks the actual rendered language and spoken
text. Text bounds stay within x=78–910/y=196–1450, away from Shorts controls.
To recheck an existing artifact without TTS or rendering, use
`beta_campaign=validate` with its `beta_run_id`. A build can also use this ID
to reuse an exact matching cached narration. Recognition reports include the
MP4 hash, so delivery cannot use a report from a different render.

After inspecting the build artifact, dispatch the same workflow with
`beta_campaign=deliver`, `beta_run_id=<build run ID>` and `send=true`. This
downloads the exact existing artifact and checks both videos and their hashes
before sending either. It requires the configured Telegram chat to be private,
sends no publication buttons, writes no Worker publishing queue and changes no
rotation history. Sanitized `telegram-receipt.json` files retain Telegram's
actual `ok`, message IDs and video metadata without bot credentials or chat IDs.
The delivery run's artifact contains the receipts. Do not blindly redispatch
an upload whose response was lost: inspect the previous run/private chat first.

For the explicitly enabled **YouTube Shorts** handoff, dispatch
`beta_campaign=shorts`, `beta_run_id=<reviewed build>` and `send=true`.
`beta_shorts.py` supplies separate UK/EN titles, descriptions, three relevant
hashtags, search tags, language and campaign URLs. The category is Gaming (20),
with the existing public visibility and not-made-for-kids setting. Metadata is
also sent as a reply to each Telegram video. The only publishing callback is
`promo:yt:<id>`; the other button rejects the package. The existing Worker queues
YouTube after the owner's press. It does not queue Instagram/TikTok or forward
the video to the Telegram channel.

Deploy the API revision that accepts `youtube_tags` and `youtube_language` first.
Registration echoes the saved values; the sender checks them before attaching
buttons, and displays whether a direct YouTube connection exists. Optional
metadata retains the legacy defaults for standard promos. Shorts approval IDs
include the video hash and metadata, and `shorts-approval-receipt.json` prevents
duplicate uploads while allowing an interrupted metadata reply to resume.
Visual revision 3 centres Sven's body independently of his off-centre sword.

Revision 4 opens on Sven and 0–4,000 MMR immediately, then shows the enlarged
real in-game hint and review fields. It shortens the continuous scripts and
uses stable phrase captions with emphasis on key words. Layout checks also
reject overlapping text blocks. The renderer caps the new take at 27 seconds;
delivery still accepts the reviewed 30–35-second v3 files, and v3 publishing
metadata/approval IDs remain stable. New source codes are `shorts-sven-uk/en`.
See the [six-post Shorts plan](marketing/shorts-plan.md) for localized follow-up
scripts, titles, descriptions, authorized Kyiv schedule and measurement rules.

### Six-film series

`beta_campaign=series`, `beta_run_id=<reviewed Sven run>`, `send=false` reuses the
reviewed Sven pair and builds four distinct Juggernaut/Terrorblade follow-ups.
Each has continuous Alex narration, timestamped phrase captions, actual site
materials and independent language/speech checks. The hash-bound manifest
(`series-manifest.json`) requires all six finished, fully decoded, verified MP4s.

The first six (Sven, Juggernaut, Terrorblade; UK and EN) were released once,
with the owner's explicit approval on 2026-10-15, through YouTube's native
schedule (`privacyStatus=private` + `publishAt`, 16/17/18 October at 17:00
Kyiv). Receipts: Actions run 38781318750. That one-off tool was removed after
it ran; the Worker keeps the generic `publish_at` support in `src/social.js`.
Every other release goes through the Telegram buttons as above.

### Release pair 0.57 (20 carries)

`beta_campaign=release`, `send=false` builds a Ukrainian/English pair about the
0.57 carry plans with the same engine (`scripts/promo/release_carry.py`, creative
`carry-plans-0.57`, visual revision 7): one continuous Alex take per language,
phrase captions, the layout and Whisper speech checks, Valve's idle renders of
Phantom Assassin, Naga Siren and Terrorblade and Valve item icons. Before
building, `release_carry.verify()` checks every claim against the shipped data:
20 carry plans, over 10,000 league games, Naga Siren's Bloodthorn rule, Drow
Ranger without Monkey King Bar (Marksmanship), Terrorblade's 12,000 at 20:00.
After reviewing its artifact, `beta_campaign=shorts` with that run's ID sends both
videos to the private chat with the YouTube-only button; the titles and
descriptions (`release_carry.metadata`) link the release news post.

### Reach audit and acquisition materials

`beta_campaign=audit`, `send=false` runs `youtube_audit.mjs` with the existing
Actions secrets. It reads the campaign's D1 rows and aggregate site counters,
decrypts the existing YouTube connection only in memory, and reads actual video
privacy, processing state, language, counters and channel age. The artifact
contains a whitelist of non-secret fields, public outreach candidates and
[the acquisition plan](marketing/beta-acquisition.md). It does not publish,
upload videos, contact creators or write to D1. The only OAuth operation is
refreshing the access token when needed; no credentials are written to artifacts.

Detailed Analytics may need both the enabled YouTube Analytics API and a new
`yt-analytics.readonly` consent; a failure is recorded with its actual reason.
Missing analytics are never treated as zero retention or zero feed impressions.
Public creator search uses language hints, which do not guarantee the creator's
language; outreach candidates need manual filtering and permission before use.

`beta_campaign=outreach`, `send=true` sends one [free outreach document](marketing/beta-outreach.md)
to the existing owner's private Telegram chat, with links to the selected
communities. It verifies the chat type first and saves a sanitized `sendDocument`
receipt. `send=false` only prepares the artifact. This mode does not join servers,
message creators, register publishing packages or create public posts. The
document includes six personalized UK/EN moderator requests; source links and
Discord invite availability are checked in the read-only audit. Community rules
and moderator consent must still be checked before placement. Optional reference
or Reddit timeouts do not discard the core publication audit.

Local storyboard preview (no credentials and no paid API calls):

```bash
source /workspace/.local/share/dota-ai-coach/headless-env.sh
CHROME=/usr/bin/chromium python -m scripts.promo.beta --out promo-out/beta-draft --draft
```

These draft frames have estimated timings; they are not finished voiced videos.
An application release/version bump is unnecessary for this campaign.

## Safety

- **Approval is the only way out.** A package is `pending` until a callback whose sender *and* chat are `TELEGRAM_CHAT_ID`. One conditional `UPDATE … WHERE status = 'pending'` moves it, so a double press or a Telegram redelivery publishes once (tested on real D1).
- **The webhook is signed.** Telegram sends `X-Telegram-Bot-Api-Secret-Token`, derived from the bot token (`sha256("wardly-promo-webhook:" + token)`), set by `api.yml`. Other requests get 404.
- **Accounts.** Only `TELEGRAM_CHAT_ID` gets `/connect` links. The OAuth `state` is random, lives 15 minutes and works once. Tokens are stored in D1 sealed with AES-GCM under a key derived from `ADMIN_TOKEN`; changing `ADMIN_TOKEN` means connecting again. `/disconnect <network>` deletes them.
- **Publishing once.** Each delivery keeps the network's id after the first call and only polls after that; a lease stops two cron runs from working the same delivery. Failed calls retry with back-off (2, 5, 15, 30, 60 minutes), six times at most.
- **Metricool (optional) starts as drafts.** `PROMO_METRICOOL_MODE = "draft"` (wrangler.toml).
- **Media.** R2 `promo/<random 128-bit key>/`, public only while the post is not rejected or expired (Instagram and Metricool fetch the video from there). Rejected media are deleted at once, undecided ones after 7 days, published ones after 30 days.
- **No personal data.** Videos use public aggregate statistics, the app's own rules and Valve's art; nothing from players' matches or reports.
- **Secrets** live only in GitHub and Worker secrets and are never printed.

## Setup

Everything is in place: the only thing left is each network's app keys. For
each network: create the app (below), put its two keys into the repository
secrets, run the **API** workflow (it copies them to the Worker), then send the
bot `/connect youtube` (or `instagram`, `tiktok`) and allow access on the page it
links. `/accounts` shows what is connected. Redirect URI for every app:
`https://api.luhovyimvp.dev/oauth/<network>/callback`.

### Voice → `ELEVENLABS_API_KEY`

1. An ElevenLabs Starter plan (or higher: the free plan forbids commercial use and wants attribution). Profile → API keys → a new key; repository secret `ELEVENLABS_API_KEY`.
2. Scheduled/default narration uses the developer-selected **A**: **Alex Nekrasov — Confident and Clear** (`9Sj8ugvpK1DmcAXyvi3a`), `eleven_v4`, Ukrainian, stability `0.5`, speed `1.0`, one continuous take. The account already has this voice, verified by the live comparison. Older repository variables do not override this preset. For a deliberate alternative, dispatch with `voice_preset=custom`: it uses `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`, `ELEVENLABS_LANGUAGE`, `ELEVENLABS_STABILITY`, `ELEVENLABS_SPEED` and `ELEVENLABS_CONTINUOUS` variables. Packages and approval captions show the effective voice/model. Branch validation builds do not record or push rotation history to main.
3. The Promo workflow stops with an annotation when the key is missing; it never sends a silent video.

### YouTube Shorts → `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`

1. [console.cloud.google.com](https://console.cloud.google.com): a new project, *APIs & Services → Library → YouTube Data API v3 → Enable*.
2. *OAuth consent screen*: External, app name Wardly, your e-mail. Scopes `youtube.upload` and `youtube.readonly`. Then **Publish app** (status *In production*): in *Testing* the refresh token dies after 7 days. The «unverified app» warning on sign-in is fine for your own channel.
3. *Credentials → Create credentials → OAuth client ID → Web application*, redirect URI `https://api.luhovyimvp.dev/oauth/youtube/callback`.
4. Until the project passes YouTube's API audit (*YouTube API Services — Audit and Quota Extension* form, free), uploads are locked as private; the bot says so after each upload. One upload uses 1,600 of the 10,000 daily quota units.

### Instagram Reels → `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`

1. The Instagram account must be professional (*Settings → Account type → Creator* or *Business*).
2. [developers.facebook.com](https://developers.facebook.com) → *Create app* → use case *Manage messaging & content on Instagram* (Instagram API with Instagram login).
3. *API setup with Instagram login*: add the account under *Roles → Instagram testers* and accept the invite in Instagram (*Settings → Website permissions → Apps and websites → Tester invites*); *Business login settings*: redirect URI `https://api.luhovyimvp.dev/oauth/instagram/callback`.
4. The *Instagram app ID* and *Instagram app secret* from the same page are the two secrets. The app can stay in development mode: it publishes to accounts that have a role in it.

### TikTok → `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`

1. [developers.tiktok.com](https://developers.tiktok.com) → *Manage apps → Connect an app*. Platform *Web*, terms and privacy URL `https://luhovyimvp.dev/privacy.html`.
2. Products *Login Kit* (redirect URI `https://api.luhovyimvp.dev/oauth/tiktok/callback`) and *Content Posting API*; scopes `user.info.basic`, `video.list`, `video.upload` (and `video.publish` for direct posts).
3. Until TikTok reviews the app, use its *Sandbox* with your account as a target user. `TIKTOK_MODE = "inbox"` (wrangler.toml) sends each video to the TikTok app as a draft: open the notification and press *Post*. After TikTok's audit, `"direct"` posts at once.

### The rest

- `TELEGRAM_CHAT_ID` must be your chat with the bot: `/id` answers it.
- Metricool is optional (`METRICOOL_TOKEN`, `METRICOOL_USER_ID`, `METRICOOL_BLOG_ID`, the Advanced plan): it only takes the networks that are not connected directly.
- Without any network the buttons still publish to the Telegram channel, and the approval message carries the video and the captions for posting by hand.

## Costs

GitHub Actions (about 8 minutes per video on the free runners), the existing Cloudflare free tier (R2, D1 rows, two cron triggers), the networks' own free APIs and ElevenLabs Starter (commercial use; a video is about 700 characters, three a week fit the plan's monthly credits). Metricool is optional.

## Extending

- A new format: a builder in `script.py`, a branch in `topics.choose` and `package.build_script`, a weight in `topics.WEIGHTS`, a pill in `scenes.PILLS`, tests in `backend/tests/test_promo.py`.
- A word said wrong: rewrite it in the script (`script.py`) the way it should sound, or try another voice (`ELEVENLABS_VOICE_ID`).
- A new network: a client in `services/api/src/social.js` with `authUrl`, `exchange`, `fresh`, `step` and `stats`, its secrets in `NETWORK_SECRETS` and `api.yml`, a route in `index.js`.
- Tests: `backend/tests/test_promo.py`; `services/api/test/promo.test.js`, `test/social.test.js`, `test/integration/promo.test.js` and `test/integration/social.test.js` (real D1 and R2).
