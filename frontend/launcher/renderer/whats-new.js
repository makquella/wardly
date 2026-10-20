// Update history and numeric version selection, shared by the panel and checks.
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WardlyWhatsNew = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const TEXT = {
    en: {
      "0.58.0": [
        "Mids and offlaners get their own plan from high-rank games: Ember Spirit, Shadow Fiend, Queen of Pain, Storm Spirit, Puck, Outworld Destroyer, Templar Assassin, Void Spirit, Dragon Knight, Axe, Bristleback, Centaur Warrunner, Legion Commander, Mars, Pangolier, Primal Beast, Slardar, Tidehunter and Timbersaw. Each has a usual and a tempo build, a skill build with talents and a net worth line, from 15,268 league games of patch 7.41.",
        "Counters that fit the hero: Axe, Legion Commander, Mars, Primal Beast, Slardar and Timbersaw take their own BKB earlier against 3+ magic damage heroes instead of Pipe; Centaur keeps Pipe; Pangolier needs neither (Rolling Thunder). Queen of Pain, Puck, Void Spirit and Storm Spirit take Linken's against Phantom Assassin and Spirit Breaker, whose jumps it blocks (not Slark's Pounce). Shadow Fiend and Templar Assassin take Monkey King Bar against evasion, Dragon Knight Orchid against escapes and Bloodthorn against evasion, Ember Spirit and Void Spirit finish Spirit Vessel early against heavy healing. Caster mids are no longer told to buy Silver Edge.",
        "Spirit Vessel is no longer suggested to offlaners against heavy healing: high-rank offlaners leave it to the support."
      ],
      "0.57.0": [
        "Items for the enemy draft now depend on your hero, starting with Terrorblade. Against Phantom Assassin or Windranger he gets Monkey King Bar, but if the enemies also have an escape a silence stops (Queen of Pain's Blink, Storm Spirit's Ball Lightning, Puck, Ember Spirit and others), Bloodthorn: its silence stops the escape, and his attacks and illusions never miss the silenced target.",
        "Terrorblade against heavy healing (Huskar, Alchemist, Necrophos…) keeps his own Eye of Skadi after Manta; against illusion heroes Butterfly, with the Dragon Lance going into Hydra's Breath instead of Hurricane Pike; against Slark, Phantom Assassin or Spirit Breaker, Hurricane Pike. With 12k net worth by minute 20 (17k by 25, 21k by 30), where high-rank Terrorblades win about 85%, the counters wait for the tempo build (Manta, Shard, Dragon Lance, Skadi, Butterfly, Daedalus), the Aegis and the throne. His usual build also follows high-rank won games now: Power Treads, Falcon Blade, Manta, Shard, Dragon Lance, Skadi, Pike, Butterfly, BKB, Daedalus. The skill tips (order, first point, talents) come from 634 of his high-rank games instead of a handful of pro games, and level 20 turns to +10 All Attributes when the enemies clear illusions fast. Heroes without a plan keep the usual counters.",
        "Five more carries get their own plan from high-rank games: Juggernaut, Phantom Lancer, Luna, Lifestealer and Slark. Juggernaut and Lifestealer are not told to buy BKB against magic (Blade Fury and Rage give debuff immunity), Juggernaut, Luna, Slark and Lifestealer get no Maelstrom against illusions (Battle Fury, Moon Glaives, Diffusal, Radiance), Phantom Lancer gets Bloodthorn and Butterfly. Slark against evasion takes Eye of Skadi first, then Silver Edge against Phantom Assassin or Bloodthorn against Windranger; against illusions he is told to find the real hero, stack Essence Shift and call the team. Luna and Slark have their own tempo line (where high-rank players win about 80%).",
        "Five more carries with their own plan: Anti-Mage (Skadi against Huskar, no BKB against magic until control kills you), Medusa (Maelstrom, Mjollnir, Aghanim's against illusions; Mana Shield instead of BKB), Phantom Assassin (Aghanim's for Fan of Knives against Bristleback or Spectre, Nullifier against save items, Stifling Dagger first), Spectre (Skadi, then Bloodthorn or Monkey King Bar) and Sven (Blink over Silver Edge).",
        "Nine more carries with their own plan, every carry but Ember Spirit now: Drow Ranger (Silver Edge and Hurricane Pike, no Monkey King Bar: Marksmanship procs never miss), Gyrocopter, Monkey King, Morphling and Muerta (Monkey King Bar, Silver Edge; Morphling takes Butterfly, then Hydra's Breath against illusions), Kez (skill build from Yatoro's and Satanic's games), Naga Siren (Bloodthorn: her illusions never miss the silenced target), Sniper (Hydra's Breath instead of Hurricane Pike against illusions) and Ursa (Monkey King Bar earlier, Abyssal instead of Silver Edge).",
        "Against heavy healing (Huskar, Alchemist, Necrophos…) every carry with Eye of Skadi in the build is told to keep it from minute 20; Naga Siren and Spectre no longer get BKB for a magic lineup alone.",
        "When the game is on the line: «Enemy Aegis until 30:03» when they take Roshan (do not fight the Aegis, keep your buyback gold), buyback kept from minute 20 with their Aegis or your base open, the death screen says how much the buyback was short, Linken's or BKB by whether you were held in a Hex or in stuns, «5 enemies together in the bottom lane: do not go there alone», and a fight where you are not: «Fight at your T2: 3 allies, 2 enemies — TP ready, Metamorphosis in 49 s», the facts only, the call is yours.",
        "Monkey King Bar no longer «never misses» in the explanations: in the current patch it goes through evasion on 80% of attacks."
      ],
      "0.56.6": [
        "Items for the enemy draft now answer the real enemies. Before the horn, Dota also lists every picked hero, yours and your allies' included, on the minimap data; Wardly took some of them for enemies (in one match: your own hero and three allies) and could suggest, for example, Silver Edge against an allied Bristleback. Only the heroes shown as enemies on the minimap count now.",
        "The same fix applies to «Your lane opponent is missing»: it no longer names a hero who is not in the enemy team."
      ],
      "0.56.5": [
        "Critical HP no longer always means «leave now». With the Aegis or a ready Reincarnation, the card says a death here revives you and asks whether the fight is worth it; with Borrowed Time ready it says to cast it before the next burst; Terrorblade at low HP with Sunder ready is reminded of the swap with a healthy enemy hero.",
        "The Sven, Juggernaut and Terrorblade preparation tips are shown at most twice a match each, and a lane farm tip comes before them."
      ],
      "0.56.4": [
        "15 gameplay preparation tips for Sven, Juggernaut and Terrorblade: ultimate windows, Omnislash setup, Healing Ward recovery, Sunder target checks and upgraded Hammer. They use your observed abilities and upgrades; they never choose an unseen target or guarantee an escape.",
        "The new tips use the main card and normal advice voice. If you enable weekly match recordings, the saved file also identifies the rule and its observed own resources for playtest feedback."
      ],
      "0.56.3": [
        "Refreshed starting items and builds for 127 heroes using STRATZ Divine–Immortal data from October 13: used by the starting card, game plan and quick-buy tips.",
        "Prepared 73 contextual gameplay advice candidates for Ember Spirit, Juggernaut, Terrorblade, Dazzle and Sven, with conditions and exceptions. This is research for upcoming improvements; these tips are not enabled in matches yet."
      ],
      "0.56.2": [
        "No more «avoid risky trades until Sunder is ready» before you have even learned Sunder: an ability you have not learned is nothing to wait for.",
        "Low HP while stunned or hexed: the card now says what to press the moment it ends, instead of «Leave the wave now», which you cannot do while stunned."
      ],
      "0.56.1": [
        "«Save file» for a recorded match (Settings → Keep match recordings for a week) works again: the file goes to Downloads instead of «Could not save the file».",
        "Problem reports no longer carry your Steam id inside the service job names."
      ],
      "0.56.0": [
        "A faster first run: «Start Dota 2» on Home opens the game through Steam in one click, and «Show» puts a sample advice card over the screen while you wait.",
        "If you share anonymous statistics, they now also count app starts and crashes, your marks on the advice and the first-run steps done, so we see what to fix first. Advice texts, heroes, matches and keys are never sent."
      ],
      "0.55.0": [
        "Lane: against an opponent you have laned against before, the overlay says when you are behind their usual last hits at 5:00 and 7:00.",
        "Items for the enemy draft: once four enemy heroes are seen, a core gets the counter item to plan for (Monkey King Bar, Maelstrom, Spirit Vessel, BKB or Pipe, and now Silver Edge against Bristleback, Spectre and Huskar).",
        "Skills for the lane: in a hard lane (a death, low health, an opponent you usually lose to) the skill tip puts an early point in your escape or defensive ability before the pro order.",
        "Your marks matter: advice you mostly mark «Not to the point» or «Repeated» now comes half as often, and Progress shows a table of your marks per kind of advice. Safety advice never gets quieter.",
        "Home asks once whether to share anonymous statistics that show which tips to fix first; «No, thanks» turns nothing on. News with the weekly meta are on the website and in our Telegram channel."
      ],
      "0.54.1": [
        "No Ukrainian voice in Windows? Advice is now read in English instead of staying silent, and Settings → Voice shows «Add a voice» with the way to install the Ukrainian one.",
        "Clearer Ukrainian wording in the in-game tips, reviews and settings."
      ],
      "0.54.0": [
        "Wardly now speaks Ukrainian instead of Russian: the panel, the overlay, the voice, reviews, the AI coach, the website and shared pages. If you had picked Russian, the app switches to Ukrainian by itself; a Ukrainian, Russian or Belarusian Windows starts in Ukrainian.",
        "Old AI coach answers written in Russian are kept in your history but no longer shown; ask again to get them in Ukrainian."
      ],
      "0.53.62": [
        "Wardly 0.53 in short: Ctrl+K finds anything, keys are encrypted on disk, history is copied automatically, you can rate the coach's advice, and every review says what it is based on. Restart Dota once after updating.",
        "Rate the coach's advice under each card in a review, and open «What is this review based on?» for the rules and data behind it.",
        "The AI coach checks K/D/A, GPM/XPM and last hits against the match data; websites can no longer reach the coach's settings."
      ],
      "0.53.61": [
        "Under the hood: overlay status answers come from one builder, and the optional replay parser build checks what it downloads."
      ],
      "0.53.60": [
        "Live advice is steadier: a game packet, an overlay poll and a session reset no longer interleave, so the overlay never shows advice built from half-updated match state."
      ],
      "0.53.59": [
        "A long match history opens faster: the match table, filters and Progress read through new indexes, and the Profile reads only what it needs."
      ],
      "0.53.58": [
        "For developers: a one-command check that replays a carry, a mid, an offlaner and a support match through the live coach and shows exactly which advice changed."
      ],
      "0.53.57": [
        "«What is this review based on?»: every review shows its rules version, the data it read and when and why it was rebuilt, and Progress says whether its averages compare like with like."
      ],
      "0.53.56": [
        "Rate the coach's advice after a match: under each card of «Advice during the match» mark it «Useful», «Not to the point» or «Repeated». The marks stay on your computer."
      ],
      "0.53.55": [
        "Automatic copies of your history: once a week and before each update Wardly keeps a copy on this computer, and you can check exactly what a copy would add before restoring it."
      ],
      "0.53.54": [
        "Only you can delete your data on the server: uploads now carry a device key whose hash the server keeps, and a history transfer can be cancelled only by someone who has the whole code."
      ],
      "0.53.53": [
        "Your keys are now encrypted on disk: the AI and OpenDota keys, the Discord link and the share and profile tokens are sealed for your Windows user, and keys saved by older versions are sealed automatically."
      ],
      "0.53.52": [
        "Ask the coach is sturdier: a question costs one AI request even after a lost answer or a double click, the wait is bounded, and an answer that arrives late still shows up."
      ],
      "0.53.51": [
        "For developers: Settings → For developers now shows operations health — background queues, whether the finished match was saved, live GSI timings and how fresh the data are, with plain warnings when something is off."
      ],
      "0.53.50": [
        "One hero table behind every hero name: the live game, the supported list, profiles, share pages and the launcher's pictures all resolve through it, and a test keeps them in step. The public profile page wears every look exactly as the app draws it."
      ],
      "0.53.49": [
        "The old browser pages are developer-only now: served at /debug/ from a source checkout, never by the installed app, and the backend no longer serves the rest of the frontend folder."
      ],
      "0.53.48": [
        "Malformed game-phase containers no longer crash dead-hero GSI packets. Invalid event fields remain unknown, while valid pre-spawn behavior is preserved; the nightly fuzz regression is covered by real HTTP cases."
      ],
      "0.53.47": [
        "Generated game-data and Python dependency updates validate their immutable PR head directly, including Windows packaging. Shared Node/Python version files, scheduled dependency PRs and separate all-profile audit reports keep maintenance reviewable."
      ],
      "0.53.46": [
        "Advice history handles duplicate appends and reset safely, and recent requests copy only selected records. Live messages include stable IDs and parameters so unchanged translations reuse bounded caches, preserving English originals and unknown-text fallback."
      ],
      "0.53.45": [
        "Local Markdown knowledge is cached at startup and refreshed on file changes during development. Repeated advice skips context retrieval after early scheduler checks, preserving advice rules and owned-item filtering."
      ],
      "0.53.44": [
        "Failed local writes now retain diagnostics and remain unacknowledged. Optional debug recording stops on write failure, while live advice and settings in memory keep working."
      ],
      "0.53.43": [
        "GSI and skill tips share a pure ability normalizer, removing the reverse import cycle while preserving names, cooldowns and missing values. Unused-variable lint is enabled across the backend."
      ],
      "0.53.42": [
        "Development checks now have a portable runner that selects consumer profiles from all changed files. CI verifies matching backend, launcher, lock and Ukrainian/English release versions."
      ],
      "0.53.41": [
        "Live game packets and demo replay no longer run filesystem and game processing on the API event loop. Local diagnostics retain bounded timing observations for preparation, rules and persistence."
      ],
      "0.53.40": [
        "File/code history transfer, control-panel language catalogs and match-review composition have their own modules. File roundtrip, complete reviews and missing-match screens are checked through actual UI and IPC in both languages."
      ],
      "0.53.39": [
        "Normalized game data and match facts have typed core contracts. Finding sources, counts and recording coverage are validated at the review API without dropping legacy fields or unknown values."
      ],
      "0.53.38": [
        "Ward, last-hit-at-10 and early-death findings show their measurement source. Partial recordings stay unknown, inventory counts are labeled estimates, and AI checks these claims against their own data."
      ],
      "0.53.37": [
        "Profile API preserves unknown rating and winrate, zero totals, signed estimates and complete shop/achievement data through a validated core contract."
      ],
      "0.53.36": [
        "Delayed profile, rating, shop and friends responses cannot replace the current account, tab or language; linking from Profile reloads that screen."
      ],
      "0.53.35": [
        "Invalid farm samples stay unknown without crashing AI fact preparation or reappearing through older compact fields."
      ],
      "0.53.34": [
        "Older status responses cannot undo linking or unlinking in the interface; simultaneous player-status reads share one request."
      ],
      "0.53.33": [
        "Delayed Progress responses cannot replace a newer hero or language selection, including leaving and returning to the tab."
      ],
      "0.53.32": [
        "Progress preserves unknown results and missing averages when selecting heroes; both interface languages are checked against stored match history."
      ],
      "0.53.31": [
        "AI match reviews and saved answers check last hits and denies against their own totals, with separate data for samples at 10:00 and opponent comparisons."
      ],
      "0.53.30": [
        "Delayed history responses cannot replace a newer filter or sort; repeated More clicks cannot duplicate a page."
      ],
      "0.53.29": [
        "Delayed review responses cannot replace a newer selection or update a review after changing tabs or language."
      ],
      "0.53.28": [
        "Returning from a review keeps the match row focused through the table refresh; back/forward history is checked in both languages."
      ],
      "0.53.27": [
        "The match table preserves partial K/D/A, notes and unknown results when paging, sorting and filtering; these flows are checked in both interface languages."
      ],
      "0.53.26": [
        "AI match reviews and answers check GPM and XPM against their own player metrics and show the data used for verification."
      ],
      "0.53.25": [
        "Player polling preserves idle, queued, running, completed and failed sync states, with zero counts kept distinct from missing data."
      ],
      "0.53.24": [
        "The update history keeps its Ukrainian and English summaries, including versions skipped during an update."
      ],
      "0.53.23": [
        "A delayed demo frame cannot restore the overlay after session reset or replace a newer demo frame."
      ],
      "0.53.22": [
        "Map, skill and shop tips update together; hints prepared before a session reset are discarded."
      ],
      "0.53.21": [
        "Enemy, lane, teleport and objective tracker reads stay consistent during game updates and session resets."
      ],
      "0.53.20": [
        "Roshan and Aegis timer settings load before game-state updates, keeping the first timer event and reset responsive."
      ],
      "0.53.19": [
        "Session reset no longer waits for role-history lookup; game state updates use the prepared role data."
      ],
      "0.53.18": [
        "Match-memory summaries stay consistent while game data, demo replay and resets update the session."
      ],
      "0.53.17": [
        "Match K/D/A keeps known values, including zero, and shows a dash for each missing counter."
      ],
      "0.53.16": [
        "Match-screen translations now have their own module, with the same copy and number formatting checked in both languages."
      ],
      "0.53.15": [
        "GSI packet, state and timestamp now update together. Reset clears the old packet and waits for fresh Dota data."
      ],
      "0.53.14": [
        "Background tasks now have an independent checked executor, preserving delayed retries and safe shutdown."
      ],
      "0.53.13": [
        "The AI checks match kills, deaths and assists against their own counters. Open the review’s data disclosure to see the reported totals."
      ],
      "0.53.12": [
        "Documentation and site checks are faster while app changes retain the required Windows installer validation."
      ],
      "0.53.11": [
        "History transfer now handles simultaneous downloads and code collisions safely. Late cleanup preserves a fresh transfer that reused a code."
      ],
      "0.53.10": [
        "Installer releases now require the same source version to pass the shared checks before publishing."
      ],
      "0.53.9": [
        "Improved automated update checks to detect new code errors earlier."
      ],
      "0.53.8": [
        "Protected the app’s windows: privileged actions only accept their own local interface, and unexpected navigation or popups are blocked."
      ],
      "0.53.7": [
        "Websites can no longer change the coach’s local settings or send game data. Dota uses a separate protected connection; restart Dota once after updating."
      ],
      "0.53.6": [
        "History backups are checked before loading and restored as one operation. A damaged cache no longer interrupts opening a review."
      ],
      "0.53.5": [
        "Repeated background requests are deduplicated while running. Shutdown cancels waiting jobs and gives active jobs limited time to finish."
      ],
      "0.53.4": [
        "Finished matches are kept for retry if saving fails, including after a restart. Recording continues for the next match."
      ],
      "0.53.3": [
        "The packaged coach now uses the same pinned library versions as its automated checks."
      ],
      "0.53.2": [
        "Updated the app engine and dependencies with security fixes."
      ],
      "0.53.1": [
        "Advice keeps working when its diagnostic log cannot be saved. The error is included in a problem report."
      ],
      "0.53.0": [
        "Ctrl+K finds anything: a tab, a match by hero or your note, Progress on a hero, a setting or an action.",
        "Notes show on Home's last matches too."
      ],
      "0.52.0": [
        "Find a setting: a search field on top of Settings (Ctrl+F) keeps only the rows with your words.",
        "Interface size in Settings → App (90–125 %), or Ctrl + plus / minus.",
        "Notes on matches: your own line in the review header, marked in the match table too.",
        "The mouse's back / forward buttons and Alt+←/→ walk the pages you opened; ↑/↓ move through the match table."
      ],
      "0.51.0": [
        "Open any match by its number: paste it, or an OpenDota, Dotabuff or STRATZ link, next to the match filters — older games than your synced history get a full review too.",
        "The review's chart shows your items under the minutes: when each finished item came.",
        "While you wait to respawn, the overlay's card shows the icon of the item to buy."
      ],
      "0.50.0": [
        "Items everywhere: the match table shows what you ended each game with, the review's header too, and the scoreboard shows every player's items.",
        "Home's last matches carry their items as well; hover an item for its name."
      ],
      "0.49.0": [
        "Skill tips show the ability's own icon, and the pros' skill order as icons with the one to level now outlined; the review's skill card has the icons too.",
        "Long pages have section links: the review's top bar and Progress list their parts, jump to one with a click and mark the part you are reading.",
        "Press ? on any tab for the list of hotkeys; the match table remembers how you sorted it."
      ],
      "0.48.0": [
        "Sort your matches: click a column in the table (score, gold, last hits, duration, KDA, date); click again to flip the order.",
        "Profile shows the award you are closest to next, and the deaths list draws the last 20 seconds of HP more clearly.",
        "Small fixes: tables in the side column line up with the card text, «What does this mean?» no longer covers a table row, the review header reads more calmly."
      ],
      "0.47.0": [
        "The in-game card has a coloured stripe on its left: red urgent, yellow a tip, green a calm note, cream the map and the plan.",
        "While Dota runs, Home shows the current match first.",
        "Calmer details: achievement progress and sparks in cream, a dash instead of an empty ring for matches without a review, “More settings” as a folded row."
      ],
      "0.46.0": [
        "Scroll down a review and its top bar stays with you: the hero, the result, the score and ‹ Newer · Older ›.",
        "Progress tiles show your last 20 matches: wins and losses, and how gold, last hits and the score went.",
        "Match scores on the charts are coloured like the score rings; the first start shows its progress and a real advice card."
      ],
      "0.45.0": [
        "A new look: Wardly's red, warmer colours and bolder headings, the same as on the site.",
        "The review header and the current match show your hero large; win and loss are coloured tags.",
        "Your Steam name and picture at the bottom of the side menu open your profile.",
        "Clearer English texts in the in-game tips and the reviews."
      ],
      "0.44.2": [
        "A review saved as a PDF keeps every hero and item picture, charts at their real size and no cards over each other.",
        "Clearer in-game and review texts in Ukrainian."
      ],
      "0.44.1": [
        "When the coach is starting or stopped, Matches, Progress and Profile say so (with a button to start it) instead of loading forever or asking to link your account again.",
        "A narrow window uses its whole width; reviews write numbers the way your language does."
      ],
      "0.44.0": [
        "Reviews in a row: “‹ Newer · Older ›” next to “Matches”, or the ← and → keys. Every review also links the match on OpenDota, Dotabuff and STRATZ.",
        "Hotkeys: Ctrl+1…5 open the tabs, Esc goes back to the match list; the whole list is in Settings → “Hotkeys”. The tray menu opens your latest review.",
        "Urgent advice on the card is red now, and while you move the card it shows a sample advice of the real size.",
        "Numbers as you read them, chart tooltips that close, a tidier Progress and Profile, and tabs that say what they will show before your account is linked."
      ],
      "0.43.2": [
        "Skill arrows find the ability icons by themselves (Full HD, 2K, 4K) and point at the “+” button to press; a hero with more abilities, or a new one from Aghanim's or the Shard, needs nothing. “Fine-tune” stays for another HUD.",
        "No more “plan a safer route” card before the horn: the moment the hero appears on the map is no death."
      ],
      "0.43.1": [
        "Role chosen by accident: if “Your role” says support but you play mid or carry, the card and Home say so once, with a button to switch back to Auto."
      ],
      "0.43.0": [
        "Arrows over your abilities: when a skill point is due, an arrow and the ability's name appear right over its icon on Dota's bar. Lay the frame over your ability icons once: Settings → “Arrows over your abilities” → “Set up the frame”."
      ],
      "0.42.0": [
        "Your starting items as icons: the card shows what Divine and Immortal players buy on your hero in your role — already during strategy time.",
        "The game plan draws the build as icons with the usual minute of each item.",
        "Gold piling up: the card names the part of your next item you can buy right now."
      ],
      "0.41.0": [
        "The first skill point stays on the card until you level it; the game plan comes 20 seconds before the horn.",
        "No starting items or gold piling up: the card says so for every role, even with map timers off.",
        "A card that stays the same for 20 seconds fades into the background; the next new one comes back bright."
      ],
      "0.40.3": [
        "A new first-run tour: real advice cards with what each line means, map calls, the game plan, the profile, the AI coach and help. Open it in Settings → Help → “Show”."
      ],
      "0.40.2": [
        "Mid: when the next power rune is coming and your Bottle still holds the last one, the card tells you to use it first.",
        "Fewer repeats: the farm pace card and the support's “No observer wards” come less often once you have seen them three times, and the ward reminder waits after you place your last ward."
      ],
      "0.40.1": [
        "The rating graph on the Profile tab is now a smooth line through your games instead of a zigzag.",
        "Your profile page for friends looks the way it does in the app: the same frame, banner and name colour, and your Steam avatar.",
        "Long titles in the shop sit in the middle of their card."
      ],
      "0.40.0": [
        "The first skill point: before the horn the card names the skill pros on your hero start with (when most of their games agree)."
      ],
      "0.39.0": [
        "“Hard lane” and “Your lane”: when the hero in your lane has beaten you (or lost to you) in the lane before, the card says so in the first minutes, with your record against them."
      ],
      "0.38.0": [
        "“Missing” calls in the laning stage: when the enemy mid or your lane opponent has not been seen for 20 seconds, the card warns you (and the voice says it when it reads every advice)."
      ],
      "0.37.0": [
        "A “Lane” card in the match review: last hits, denies, gold and XP at 3, 5, 7 and 10 minutes against the enemy core of your lane, and whether the lane was won.",
        "“Your lanes” on Progress: how many of your last lanes you won, and the heroes you lose the lane to."
      ],
      "0.36.0": [
        "Lane tips for cores in the first ten minutes: no regen on the way to lane, half HP with nothing to heal, no Magic Stick yet, too few denies.",
        "Items against the enemy lineup: Pipe of Insight or Black King Bar against magic damage, Glimmer Cape or Ghost Scepter for a support."
      ],
      "0.35.0": [
        "Friends on the “Profile” tab: show your profile by a friend code, add friends by theirs and see who is on top — level, rating, looks.",
        "Your profile as a page to send to a chat: api.luhovyimvp.dev/p/<code>."
      ],
      "0.34.0": [
        "New tab “Profile”: your rating graph like on FACEIT — enter your MMR once and every ranked game moves it.",
        "Levels, achievements and sparks for playing with Wardly.",
        "Spend sparks in the profile shop: avatar frames, banners, name colours and titles; the rare ones need a level or an achievement."
      ],
      "0.32.0": [
        "New in “More settings”: keep match recordings for a week. Save any match as a file and send it to the developer, the next day too.",
        "The problem report says which match the app recorded last and whether its review is ready."
      ],
      "0.31.2": [
        "A problem report sent after restarting the app still shows what the game sent during your last match."
      ],
      "0.31.1": [
        "The death review names a Haste, Invisibility, Shield or Illusion rune left unused in the Bottle.",
        "Fixed: the review showed a dash instead of the hero's ability when you died with it ready."
      ],
      "0.31.0": [
        "Low HP with a Haste, Invisibility, Shield or Illusion rune in the Bottle: the coach tells you to use it and run.",
        "A Regeneration or Water rune in the Bottle counts as healing, and a Bottle holding another rune no longer does.",
        "A power rune kept in the Bottle for 30 seconds: a reminder to use it for a kill."
      ],
      "0.30.3": [
        "Checked on real games: the enemies on the minimap, item readiness and the Roshan events reach the coach.",
        "The Roshan timer no longer loses the kill among chat messages and other game events."
      ],
      "0.30.2": [
        "The Roshan and Aegis timers now get their data from the game: restart Dota once after this update.",
        "Items in the backpack no longer count as ready to press.",
        "The problem report shows which data the game really sends: play a match and send one."
      ],
      "0.30.1": [
        "More heroes in the item advice: Linken's Sphere against Reaper's Scythe, Charge of Darkness and Winter's Curse, Maelstrom for a carry against illusion heroes, Dust against Mirana, Templar Assassin and Invoker."
      ],
      "0.30.0": [
        "Losing 30% HP or more in 5 seconds brings the urgent card at once, before HP is critical.",
        "The low-HP card shows what to press, how fast HP is falling and how many times it happened this game.",
        "A third death in one place this game is named after the death and on the respawn screen."
      ],
      "0.29.2": [
        "Items against the enemy heroes: dying under Beastmaster's Primal Roar, Doom or Duel brings a Linken's Sphere tip that says why; Monkey King Bar against evasion, Spirit Vessel against healing, Dust for a support against invisible heroes.",
        "An unlearned Blink no longer counts as on cooldown, and “you died with Blink ready” needs two free seconds to press it.",
        "Repeated low-HP cards say how many times it happened and ask to heal up fully."
      ],
      "0.29.1": [
        "A mid gets the power rune timer until minute 20, not all game, and before level 6 with a Bottle the hint says to keep the rune in it for a kill."
      ],
      "0.29.0": [
        "The match review is shorter: past the three main points, the other remarks and the long list of deaths open with “Show more”.",
        "The health line under each death says what it is, and “Net worth” is named plainly."
      ],
      "0.28.0": [
        "The first advice after a death names the lane or part of the map where you died, or how fast the kill came, instead of “plan a safer route”.",
        "Supports: the “no save item” tip names the save item most bought on your hero and how much gold it still needs; the ward tip says where to put it (your lane's river, Roshan's pit, your own or the enemy jungle by the score).",
        "A lane under a good farm pace gets the numbers: “Recover farm: 12 last hits at minute 5, a good pace is 18+”."
      ],
      "0.27.0": [
        "The advice after a death says how many times you have died, lately or this game, instead of the same “change your route” line."
      ],
      "0.26.0": [
        "The match review has a “Skill order” card: which skill you maxed first and how pro players level your hero."
      ],
      "0.25.0": [
        "The farm cards put the numbers on the main line: your gold per minute and last hits, or how far behind a good pace you are.",
        "Advice that only changed its numbers no longer repeats every two minutes."
      ],
      "0.24.0": [
        "Which talent to take: when a talent row opens, the coach names the one pro players take on your hero."
      ],
      "0.23.0": [
        "Where the point goes: after a level-up the coach names the skill pro players level on your hero, with the whole order.",
        "The game plan shows the pro skill order, and the review says when you maxed a different skill first."
      ],
      "0.22.0": [
        "Skill points: the coach names your ultimate at 6/12/18 and the talent at 10/15/20/25 when a point is left unspent.",
        "A situational item: two deaths under stuns → Black King Bar, two burst deaths → Aeon Disk, with the reason and the gold still needed.",
        "Less banal advice: a kill streak, the kill score gap or your pace in numbers instead of the same “farm safely”."
      ],
      "0.21.0": [
        "Settings are rebuilt: five clear groups, bigger text, fewer buttons, and a plain line under every setting. Moving to another computer now explains itself step by step.",
        "“Why this advice?” under every advice on Home and in the review: what the coach saw.",
        "“What does this mean?” for the match score, the rank comparison and the focus, and no more technical words across the app."
      ],
      "0.20.0": [
        "Full advice for 25 supports (positions 4 and 5) with their own saves, reminders to place the wards in your bag and to get a save item, and a support review: your save item's timing and the wards you placed.",
        "Overlay 2.0: a timer strip under the card (runes, stacks, Roshan, Aegis for your role), a compact card and a soft fade-in — Settings → Overlay.",
        "A new Home: one card with your last match, today, streaks and focus. Progress gets a Goals zone."
      ],
      "0.19.0": [
        "Your evening: after two or more matches, Home sums up the sitting once Dota is closed, with a text to copy for friends.",
        "Progress shows where you die over the last 20 matches, and your hero's key item timing game by game.",
        "A short tour of the app (Settings → App), and the status line says plainly whether Dota's data reaches the coach."
      ],
      "0.18.0": [
        "Full advice for 18 more heroes: 8 mids (Shadow Fiend, Storm Spirit, Queen of Pain, Puck and others) and 10 offlaners (Axe, Mars, Legion Commander, Centaur and others).",
        "The coach knows their own saves (Blink, Ball Lightning, Refraction, Guardian Sprint…), and an offlaner's farm is measured against an offlaner's pace, not a carry's."
      ],
      "0.17.0": [
        "Optional anonymous statistics (Settings → App, off by default): which advice was shown and which warnings came before a death, to make the advice better. “What is sent” shows the exact text.",
        "“Delete my data on the server” removes your problem reports, shared links and statistics in one press."
      ],
      "0.16.0": [
        "In a review, “Watch” next to a death or a key moment copies the replay command that jumps 10 s before it.",
        "The match chart shows your best match on this hero as a dashed line.",
        "Home: streak goals (5 matches in a row with 5 deaths or fewer) and a gentle note after 3 losses in a row.",
        "Progress: heroes to play more and heroes to park, against your rank."
      ],
      "0.15.0": [
        "Roshan and Aegis timers: the respawn window after a kill, and your Aegis warns a minute before it expires.",
        "While you wait to respawn: how you died, what was left unpressed, what to buy now.",
        "No more “wait out the disable” when there is nothing to press after the stun."
      ],
      "0.14.0": [
        "Advice knows your hero: Blink to get out, Blade Fury to walk out of a fight, and how many seconds until your escape is back.",
        "The match map rings the places where you keep dying, with a route tip."
      ],
      "0.13.0": [
        "Advice names what to press right now: Force Staff to get out, Magic Wand with its charges, Black King Bar the moment a stun ends.",
        "After a death: the rescue item you left unpressed and the place where you keep dying."
      ],
      "0.12.0": [
        "Every tab is split into clear areas: what to look at first, then the details.",
        "Your week on Home: the score against the week before and a chart of every match.",
        "Farm advice for carries names your next item, the gold it needs and how long to farm it.",
        "Fixed: some reviews stayed on “Loading the match” forever."
      ],
      "0.11.0": [
        "The app uses the whole window: side navigation, two columns, both teams side by side.",
        "Last matches on Home, score rings in reviews and the match table.",
        "More in-game tips for every role: mid rotations and last hits, offlane hard lanes, support pulls, your key item's timing.",
        "Hard matchups in the game plan."
      ],
      "0.10.0": [
        "The week in Discord: every Monday your matches, score and heroes of the week go to your server's channel. Settings → App → The week in Discord.",
        "The Week card on Home shows the heroes you played.",
        "Problem reports no longer include the delete tokens of your shared links."
      ],
      "0.9.0": [
        "Status in Discord: your friends see “Playing <hero> · with the Wardly coach”. Switch it off in Settings → App.",
        "Links to reviews and progress are shorter now: luhovyimvp.dev/r/…",
        "The website in the logo's colours."
      ],
      "0.8.0": [
        "Death reviews: HP in the last 20 seconds and the saving item that was ready but not pressed.",
        "Progress: your build on the hero — when items come in your wins and in your losses.",
        "After a match the overlay shows the summary right on the score screen.",
        "Move your history to another computer with a one-time code."
      ],
      "0.7.0": [
        "Progress → Share: a link to a page with your progress — matches, wins, averages, top heroes, what goes well and what to work on.",
        "A new start-up splash: the logo comes alive while the service starts."
      ],
      "0.6.1": [
        "Offlaner reviews: stuns and building damage against the enemy offlaner of the same match.",
        "The plan for the game shows your record on the hero next to its name.",
        "All versions and their changes are on the website: luhovyimvp.dev/changelog.html."
      ],
      "0.6.0": [
        "Role reviews: runes for a mid against the enemy mid, stacks and sentries for a support.",
        "Progress: your record against each enemy hero — who is hardest for you and whom you beat most.",
        "Ask the AI coach about your recent matches, not only one game.",
        "In game: a level-6 tip for a mid (rotation) and an offlaner (pressure)."
      ],
      "0.5.0": [
        "Dota AI Coach is now Wardly, with a new logo. Your history and settings stay.",
        "Progress → Compare with a friend: their public matches next to yours, with the heroes you both play.",
        "Share a review by link — with a preview in Discord and Telegram, no Steam ID or nickname.",
        "Settings → App → Match history: save everything to a file and load it back on any computer.",
        "The path on the match map no longer runs from a death to the fountain."
      ],
      "0.4.0": [
        "The match map is drawn on the real Dota minimap: your path, lane position, wards and deaths.",
        "Good-pace lines for gold and XP on the “Over the match” chart.",
        "A “Deaths” card: where, who killed you, unspent gold and the advice shown before each death.",
        "Mistakes that keep coming back are marked: “3 matches in a row”.",
        "This week on Home: matches, score change, best match, the most frequent mistake and a 3-match plan for your focus."
      ],
      "0.3.0": [
        "Map timers on the overlay 20 s ahead: runes, wisdom shrines, lotuses, the Tormentor, neutral item tiers — only the ones your role needs.",
        "Your role is found from your lane in the first minutes (or chosen in Settings → Advice) and shown on Home.",
        "Support tips: stack a camp, take wards, leave the last hits to your carry. No carry farm advice on a support; the TP reminder works on every hero.",
        "“Send to developer” in the problem report: one click, with a note and a preview; keys, nickname and Steam ID are removed.",
        "Draft advice suggests only heroes of the position you played."
      ],
      "0.2.1": [
        "Match history no longer fails to sync when OpenDota answers slowly.",
        "The app asks OpenDota to parse your latest matches, so reviews get last hits at 10:00, the build and the chart.",
        "Draft advice suggests a hero of your role; the same-role opponent and counter items are right even without a parsed replay.",
        "Progress shows all five tiles in one row, and Home no longer cuts the hero's name."
      ],
      "0.2.0": [
        "A plan at the start of each match, and a focus: pick one mistake to work on — every review says whether you avoided it.",
        "“Ask the coach”: your own question about a match, answered from its data.",
        "Spoken advice, advice frequency, survival advice for every hero, reminders to carry a TP scroll and to spend gold while dead.",
        "Match map, this match against your usual numbers, match filters and PDF export.",
        "A check for Dota's -gamestateintegration launch option, without which no game data arrives."
      ]
    },
    uk: {
      "0.58.0": [
        "Свій план з ігор сильних гравців тепер мають мідери й хардлайнери: Ember Spirit, Shadow Fiend, Queen of Pain, Storm Spirit, Puck, Outworld Destroyer, Templar Assassin, Void Spirit, Dragon Knight, Axe, Bristleback, Centaur Warrunner, Legion Commander, Mars, Pangolier, Primal Beast, Slardar, Tidehunter і Timbersaw. У кожного — звичайна й темпова збірки, прокачка з талантами й поріг нетворсу з 15 268 лігових ігор патча 7.41.",
        "Предмети проти драфту під героя: Axe, Legion Commander, Mars, Primal Beast, Slardar і Timbersaw проти 3+ героїв з магічною шкодою беруть раніше свій BKB замість Pipe; Centaur лишає Pipe; Pangolier не потребує ні того, ні іншого (Rolling Thunder). Queen of Pain, Puck, Void Spirit і Storm Spirit беруть Linken's проти Phantom Assassin і Spirit Breaker — він блокує їхні стрибки (але не Pounce у Slark). Shadow Fiend і Templar Assassin проти ухилення — Monkey King Bar, Dragon Knight — Orchid проти втеч і Bloodthorn проти ухилення, Ember Spirit і Void Spirit проти сильного лікування збирають Spirit Vessel раніше. Мідерам-магам більше не радиться Silver Edge.",
        "Spirit Vessel проти сильного лікування більше не радиться хардлайнерам: сильні гравці лишають його саппорту."
      ],
      "0.57.0": [
        "Предмети проти ворожого драфту тепер залежать від вашого героя, почнімо з Terrorblade. Проти Phantom Assassin чи Windranger він отримує Monkey King Bar, а якщо у ворогів є ще й втеча, яку зупиняє тиша (Blink у Queen of Pain, Ball Lightning у Storm Spirit, Puck, Ember Spirit та інші), — Bloodthorn: його тиша не дає втекти, а по цілі під тишею атаки героя та його ілюзій не промахуються.",
        "Terrorblade проти сильного лікування (Huskar, Alchemist, Necrophos…) отримує пораду брати свій Eye of Skadi після Manta; проти героїв з ілюзіями — Butterfly, а Dragon Lance збирати в Hydra's Breath замість Hurricane Pike; проти Slark, Phantom Assassin чи Spirit Breaker — Hurricane Pike. З нетворсом 12 тис. до 20-ї хвилини (17 тис. до 25-ї, 21 тис. до 30-ї), коли сильні гравці на Terrorblade виграють близько 85 %, поради проти драфту чекають на темпову збірку (Manta, Shard, Dragon Lance, Skadi, Butterfly, Daedalus), Aegis і трон. Його звичайна збірка тепер теж з виграних ігор сильних гравців: Power Treads, Falcon Blade, Manta, Shard, Dragon Lance, Skadi, Pike, Butterfly, BKB, Daedalus. Поради з прокачки (порядок, перше очко, таланти) — з 634 його ігор сильних гравців замість кількох про-ігор, а на 20-му рівні — +10 до атрибутів, коли вороги швидко вбивають ілюзії. Герої без плану зберігають звичайні поради.",
        "Ще п'ять керрі отримали свій план з ігор сильних гравців: Juggernaut, Phantom Lancer, Luna, Lifestealer і Slark. Juggernaut і Lifestealer більше не отримують пораду брати BKB проти магії (Blade Fury і Rage дають імунітет до дебафів), Juggernaut, Luna, Slark і Lifestealer — Maelstrom проти ілюзій (Battle Fury, Moon Glaives, Diffusal, Radiance), Phantom Lancer отримує Bloodthorn і Butterfly. Slark проти ухилення спершу бере Eye of Skadi, далі Silver Edge проти Phantom Assassin або Bloodthorn проти Windranger; проти ілюзій — порада знайти справжнього героя, накопичувати Essence Shift і кликати команду. У Luna і Slark свій поріг темпу (де сильні гравці виграють близько 80 %).",
        "Ще п'ять керрі зі своїм планом: Anti-Mage (Skadi проти Huskar, без BKB проти магії, доки контроль вас не вбиває), Medusa (Maelstrom, Mjollnir, Aghanim's проти ілюзій; Mana Shield замість BKB), Phantom Assassin (Aghanim's заради Fan of Knives проти Bristleback чи Spectre, Nullifier проти рятівних предметів, першим Stifling Dagger), Spectre (Skadi, далі Bloodthorn або Monkey King Bar) і Sven (Blink замість Silver Edge).",
        "Ще дев'ять керрі зі своїм планом, тепер усі керрі, крім Ember Spirit: Drow Ranger (Silver Edge і Hurricane Pike, без Monkey King Bar: спрацювання Marksmanship не промахуються), Gyrocopter, Monkey King, Morphling і Muerta (Monkey King Bar, Silver Edge; Morphling проти ілюзій — Butterfly, потім Hydra's Breath), Kez (прокачка з ігор Yatoro і Satanic), Naga Siren (Bloodthorn: по цілі під тишею не промахуються і її ілюзії), Sniper (Hydra's Breath замість Hurricane Pike проти ілюзій) і Ursa (Monkey King Bar раніше, Abyssal замість Silver Edge).",
        "Проти сильного лікування (Huskar, Alchemist, Necrophos…) усі керрі, у чиїй збірці є Eye of Skadi, отримують пораду не пропускати його з 20-ї хвилини; Naga Siren і Spectre більше не отримують BKB лише за магічний драфт.",
        "Коли гра вирішується: «Аегіс у ворогів до 30:03», коли вони забрали Рошана (не бийтеся проти Аегіса, тримайте золото на байбек), байбек зберігається з 20-ї хвилини з ворожим Аегісом чи відкритою базою, екран смерті каже, скільки не вистачило на байбек, Linken's чи BKB — за тим, чи вас тримали в Hex, чи в оглушеннях, «Ворогів разом — 5, на нижній лінії: туди один не йдіть» і бійка там, де вас немає: «Бійка біля вашої T2: союзників 3, ворогів 2 — ТП — готово, Metamorphosis — через 49 с», лише факти, рішення за вами.",
        "Monkey King Bar у поясненнях більше не «б'є без промаху»: у поточному патчі він пробиває ухилення 80 % атак."
      ],
      "0.56.6": [
        "Предмети проти ворожого драфту тепер відповідають справжнім ворогам. До горну Dota також передає в даних мінікарти всіх обраних героїв, ваших і союзних теж; Wardly вважав частину з них ворогами (в одному матчі — вашого героя і трьох союзників) і міг порадити, наприклад, Silver Edge проти союзного Bristleback. Тепер враховуються лише герої, яких мінікарта показує як ворогів.",
        "Те саме виправлення стосується «Суперник з вашої лінії зник»: картка більше не називає героя, якого немає у ворожій команді."
      ],
      "0.56.5": [
        "Критично мало HP більше не завжди означає «відходьте». З Aegis або готовою Reincarnation картка нагадує, що смерть тут вас воскресить, і питає, чи вартий цього бій; з готовою Borrowed Time — застосувати її до наступного сплеску шкоди; Terrorblade з малим HP і готовою Sunder отримує нагадування про обмін зі здоровим ворожим героєм.",
        "Поради підготовки для Sven, Juggernaut і Terrorblade звучать щонайбільше двічі за матч кожна, а порада про фарм у лінії йде перед ними."
      ],
      "0.56.4": [
        "15 порад підготовки для Sven, Juggernaut і Terrorblade: вікна ультимейтів, підготовка Omnislash, відновлення через Healing Ward, перевірка цілі Sunder і покращений Hammer. Враховують ваші здібності й покращення, не обирають невидиму ціль і не гарантують утечу.",
        "Нові поради працюють на основній картці зі звичайною озвучкою. Якщо ввімкнути тижневі записи матчів, збережений файл також міститиме правило та власні ресурси, на яких воно спрацювало, для відгуку після тесту."
      ],
      "0.56.3": [
        "Оновлено стартові предмети та білди для 127 героїв за даними STRATZ Divine–Immortal від 13 жовтня: для стартової картки, плану гри та підказок швидкої покупки.",
        "Підготовлено 73 кандидати на контекстні поради для Ember Spirit, Juggernaut, Terrorblade, Dazzle та Sven з умовами й винятками. Це дослідження для наступних покращень; ці поради ще не ввімкнено в матчах."
      ],
      "0.56.2": [
        "Більше немає «Не ризикуйте, поки Sunder не готовий», коли Sunder ще навіть не вивчено: на невивчену здібність нема чого чекати.",
        "Мало HP під оглушенням чи хексом: картка тепер каже, що натиснути, щойно контроль мине, замість «Залиште хвилю зараз», чого під оглушенням не зробиш."
      ],
      "0.56.1": [
        "«Зберегти файл» для записаного матчу («Налаштування» → «Зберігати записи матчів тиждень») знову працює: файл потрапляє в «Завантаження», а не «Не вдалося зберегти файл».",
        "Звіт про проблему більше не містить вашого Steam id у назвах службових задач."
      ],
      "0.56.0": [
        "Швидший перший запуск: «Запустити Dota 2» на «Головній» відкриває гру через Steam одним натиском, а «Показати» виводить приклад картки поверх екрана, поки ви чекаєте.",
        "Якщо ви ділитеся анонімною статистикою, тепер вона рахує ще запуски й падіння застосунку, ваші відмітки на порадах і пройдені кроки першого запуску — так видно, що виправляти першим. Тексти порад, герої, матчі й ключі не надсилаються."
      ],
      "0.55.0": [
        "Лінія: проти суперника, з яким ви вже стояли на лінії, оверлей скаже, коли ви відстаєте від його звичних добивань на 5:00 і 7:00.",
        "Предмети під вражеський драфт: щойно видно чотирьох героїв ворога, кор отримує предмет, який варто запланувати (Monkey King Bar, Maelstrom, Spirit Vessel, BKB чи Pipe, а тепер і Silver Edge проти Bristleback, Spectre та Huskar).",
        "Прокачка під лінію: на важкій лінії (смерть, мало здоров'я, суперник, якому ви зазвичай програєте) підказка радить раннє очко у втечу чи захисну здібність, а вже потім порядок про-гравців.",
        "Ваші відмітки враховуються: поради, які ви здебільшого позначаєте «Не до речі» або «Повторювалося», тепер з'являються вдвічі рідше, а в «Прогресі» є таблиця ваших відміток за видами порад. Поради про безпеку тихішими не стають.",
        "На «Головній» один раз з'явиться пропозиція ділитися анонімною статистикою, щоб бачити, які підказки виправляти першими; «Ні, дякую» нічого не вмикає. Новини з метою тижня — на сайті й у нашому Telegram-каналі."
      ],
      "0.54.1": [
        "Немає українського голосу в Windows? Тепер поради читаються англійською, а не мовчки, а в «Налаштування → Голос» з'явилася кнопка «Додати голос» з поясненням, як встановити український.",
        "Природніші українські формулювання в підказках, розборах і налаштуваннях."
      ],
      "0.54.0": [
        "Wardly тепер українською замість російської: панель, оверлей, голос, розбори, ШІ-тренер, сайт і сторінки «Поділитися». Якщо ви вибирали російську, застосунок сам перейде на українську; на українській, російській чи білоруській Windows він одразу запускається українською.",
        "Старі відповіді ШІ-тренера російською зберігаються в історії, але більше не показуються; запитайте ще раз, щоб отримати їх українською."
      ],
      "0.53.62": [
        "Wardly 0.53 коротко: Ctrl+K знаходить будь-що, ключі зашифровано на диску, історія копіюється сама, поради тренера можна оцінювати, а кожен розбір показує, на чому він ґрунтується. Після оновлення один раз перезапустіть Доту.",
        "Оцінюйте поради тренера під кожною карткою розбору й відкривайте «На чому ґрунтується розбір?», щоб побачити правила й дані.",
        "ШІ-тренер звіряє В/С/Д, золото й досвід за хвилину та добивання з даними матчу; сайти більше не можуть дістатися до налаштувань тренера."
      ],
      "0.53.61": [
        "Під капотом: службові відповіді оверлея збираються в одному місці, а збірка необов'язкового парсера записів перевіряє те, що завантажує."
      ],
      "0.53.60": [
        "Живі поради стабільніші: пакет гри, опитування оверлея й скидання сесії більше не перемішуються, і оверлей не покаже пораду, зібрану з наполовину оновленого стану матчу."
      ],
      "0.53.59": [
        "Велика історія матчів відкривається швидше: таблиця матчів, фільтри й «Прогрес» читаються за новими індексами, а «Профіль» читає лише потрібне."
      ],
      "0.53.58": [
        "Для розробника: одна команда проганяє матчі керрі, міда, офлейнера й саппорта через живого тренера й показує, які саме поради змінилися."
      ],
      "0.53.57": [
        "«На чому ґрунтується розбір?»: кожен розбір показує версію правил, дані, на яких побудований, і коли й чому перерахований, а «Прогрес» підказує, чи можна напряму порівнювати середні."
      ],
      "0.53.56": [
        "Оцінка порад після матчу: під кожною карткою «Підказок під час матчу» можна позначити «Корисно», «Не до речі» або «Повторювалося». Позначки лишаються на вашому комп'ютері."
      ],
      "0.53.55": [
        "Автоматичні копії історії: раз на тиждень і перед кожним оновленням Wardly зберігає копію на цьому комп'ютері, а перед відновленням можна точно перевірити, що копія додасть."
      ],
      "0.53.54": [
        "Видалити ваші дані на сервері можете лише ви: надсилання тепер несуть ключ пристрою, а сервер зберігає лише його хеш; перенесення історії за кодом може скасувати лише той, у кого є весь код."
      ],
      "0.53.53": [
        "Ключі тепер зашифровано на диску: ключі ШІ й OpenDota, посилання Discord і токени посилань і профілю захищено для вашого облікового запису Windows, а ключі з минулих версій шифруються автоматично."
      ],
      "0.53.52": [
        "«Запитати тренера» надійніше: запитання витрачає один запит до ШІ навіть після втраченої відповіді чи подвійного натискання, очікування обмежене, а відповідь, що прийшла пізніше, однаково з'явиться."
      ],
      "0.53.51": [
        "Для розробника: у «Налаштування → Для розробників» з'явився «Стан операцій» — фонові черги, чи збережено зіграний матч, затримки живого GSI і свіжість даних, зі зрозумілими попередженнями, якщо щось не так."
      ],
      "0.53.50": [
        "Одна таблиця героїв для всіх імен: жива гра, список підтримуваних героїв, профілі, сторінки «Поділитися» й картинки лаунчера спираються на неї, а тест стежить за збігом. Публічна сторінка профілю показує образи точно так, як застосунок."
      ],
      "0.53.49": [
        "Старі браузерні сторінки тепер лише для розробника: /debug/ з вихідного коду, ніколи у встановленому застосунку; решту теки frontend бекенд більше не віддає."
      ],
      "0.53.48": [
        "Словник або список замість фази гри більше не ламає GSI-пакет загиблого героя. Некоректні поля події лишаються невідомими, а звичайна поведінка pre-spawn збережена; збій nightly fuzz покрито справжніми HTTP-перевірками."
      ],
      "0.53.47": [
        "Автоматичні оновлення даних гри й Python-залежностей перевіряють свій SHA напряму, включно з Windows-збіркою. Спільні версії Node/Python, регулярні PR оновлень і окремі звіти аудиту зберігають змогу перевіряти зміни."
      ],
      "0.53.46": [
        "Історія захищає додавання повторів і reset, а останні поради копіюють лише обрані записи. Live-тексти отримують стабільні ID і параметри для обмеженого кешу перекладу; англійський оригінал і невідомі фрази зберігаються."
      ],
      "0.53.45": [
        "Локальна Markdown-база кешується під час запуску й оновлюється під час зміни файлів у розробці. Повторні поради пропускають пошук контексту після ранніх перевірок scheduler; правила й фільтрацію куплених предметів збережено."
      ],
      "0.53.44": [
        "Збої локального запису зберігаються в діагностиці й не підтверджуються як успішне збереження. Налагоджувальний запис зупиняється в разі помилки, а live-поради й налаштування в пам'яті продовжують працювати."
      ],
      "0.53.43": [
        "GSI й підказки прокачки використовують чисту нормалізацію здібностей без зворотного циклу імпорту. Назви, кулдауни й невідомі значення збережено; перевірку невикористаних змінних увімкнено для всього backend."
      ],
      "0.53.42": [
        "Перевірки розробки запускаються через переносний runner із вибором профілів за всіма зміненими файлами. CI перевіряє збіг версій backend, launcher, lock і описів випуску обома мовами."
      ],
      "0.53.41": [
        "Обробка ігрових пакетів і demo більше не виконує файлові операції й розрахунки в event loop API. Локальна діагностика зберігає обмежені заміри підготовки, правил і збереження даних."
      ],
      "0.53.40": [
        "Перенесення історії файлом і кодом, мовні каталоги панелі й збірку екрана розбору винесено у власні модулі. Файлове перенесення, повний розбір і екран відсутнього матчу перевіряються через справжній UI та IPC обома мовами."
      ],
      "0.53.39": [
        "Нормалізовані ігрові дані й факти матчу отримали типізовані контракти. Джерела, числа й покриття findings перевіряються на межі API розбору; старі поля й невідомі значення зберігаються."
      ],
      "0.53.38": [
        "Висновки про варди, добивання до 10:00 і ранні смерті показують джерело вимірювання. Пропуски запису лишаються невідомими, підрахунок за інвентарем позначено як оцінку, а ШІ перевіряє ці твердження за своїми даними."
      ],
      "0.53.37": [
        "API профілю зберігає невідомий рейтинг і відсоток перемог, нульові лічильники, оцінки зі знаком і повні дані крамниці/нагород через перевірюваний контракт основних полів."
      ],
      "0.53.36": [
        "Запізнілі відповіді профілю, рейтингу, крамниці й друзів не замінюють поточний акаунт, вкладку чи мову; прив'язка з профілю перезавантажує його екран."
      ],
      "0.53.35": [
        "Некоректні показники фарму лишаються невідомими без збою підготовки ШІ-фактів і повернення через старі поля."
      ],
      "0.53.34": [
        "Стара відповідь статусу не скасовує прив'язку чи відв'язку в інтерфейсі; одночасні читання статусу використовують один запит."
      ],
      "0.53.33": [
        "Запізнілі відповіді Прогресу не замінюють новий вибір героя чи мови, включно з виходом із вкладки й поверненням."
      ],
      "0.53.32": [
        "Прогрес зберігає невідомі результати й відсутні середні під час вибору героя; обидві мови перевіряються на збереженій історії."
      ],
      "0.53.31": [
        "ШІ-розбори й збережені відповіді перевіряють добивання й денаї за власними підсумками матчу, окремо — дані до 10:00 і порівняння із суперником."
      ],
      "0.53.30": [
        "Запізнілі відповіді історії не замінюють новий фільтр чи сортування; повторні натискання «Ще» не дублюють сторінку."
      ],
      "0.53.29": [
        "Затримана відповідь розбору не замінює новий вибір і не оновлює розбір після зміни вкладки чи мови."
      ],
      "0.53.28": [
        "Повернення з розбору зберігає фокус рядка під час оновлення таблиці; історія переходів назад/вперед перевіряється обома мовами."
      ],
      "0.53.27": [
        "Таблиця матчів зберігає частковий K/D/A, нотатки й невідомий результат під час завантаження сторінок, сортування й фільтрації; ці дії перевіряються обома мовами."
      ],
      "0.53.26": [
        "ШІ-розбір і відповіді перевіряють GPM і XPM за відповідними показниками гравця й показують дані для перевірки."
      ],
      "0.53.25": [
        "Статус гравця зберігає стани очікування, черги, виконання, завершення й помилки синхронізації; нульові лічильники відрізняються від відсутніх даних."
      ],
      "0.53.24": [
        "Історія оновлень зберігає описи обома мовами, включно з пропущеними під час оновлення версіями."
      ],
      "0.53.23": [
        "Затриманий демо-кадр не повертає оверлей після скидання сесії й не замінює новіший кадр."
      ],
      "0.53.22": [
        "Підказки мапи, прокачки й покупок оновлюються разом; підготовлені до скидання сесії підказки відкидаються."
      ],
      "0.53.21": [
        "Відомості про ворогів, лінії, телепортацію й об'єкти читаються узгоджено під час оновлення гри та скидання сесії."
      ],
      "0.53.20": [
        "Налаштування таймерів Рошана й Аегіса завантажуються перед оновленням стану, зберігаючи чуйність першої події й скидання."
      ],
      "0.53.19": [
        "Скидання сесії не чекає читання історії для визначення ролі; ігровий стан використовує заздалегідь підготовлені дані."
      ],
      "0.53.18": [
        "Зведення пам'яті матчу оновлюється узгоджено під час надходження ігрових і демо-даних і під час скидання сесії."
      ],
      "0.53.17": [
        "K/D/A матчу зберігає відомі значення, включно з нулем, і показує прочерк для кожного відсутнього лічильника."
      ],
      "0.53.16": [
        "Переклади екранів матчів винесено в окремий модуль; попередні тексти й форматування чисел перевіряються обома мовами."
      ],
      "0.53.15": [
        "GSI-пакет, стан і час отримання оновлюються разом. Скидання очищує попередній пакет і чекає свіжі дані Dota."
      ],
      "0.53.14": [
        "Фонові завдання винесено в самостійну перевірювану чергу з попередніми відкладеними повторними спробами й безпечною зупинкою."
      ],
      "0.53.13": [
        "ШІ перевіряє вбивства, смерті й асисти за їхніми власними лічильниками матчу. У розборі можна розгорнути дані, на яких ґрунтується перевірка."
      ],
      "0.53.12": [
        "Документація й сайт перевіряються швидше, а зміни застосунку зберігають обов'язкову перевірку Windows-інсталятора."
      ],
      "0.53.11": [
        "Перенесення історії тепер надійно обробляє одночасні завантаження й збіги кодів. Пізнє очищення зберігає нове перенесення з повторно зайнятим кодом."
      ],
      "0.53.10": [
        "Для випуску інсталятора тепер потрібні спільні перевірки тієї самої версії вихідного коду перед публікацією."
      ],
      "0.53.9": [
        "Покращено автоматичні перевірки оновлень, щоб раніше знаходити нові помилки в коді."
      ],
      "0.53.8": [
        "Захищено вікна застосунку: дії приймаються лише від свого локального інтерфейсу, а сторонні переходи й спливні вікна блокуються."
      ],
      "0.53.7": [
        "Сайти більше не можуть змінювати локальні налаштування тренера чи надсилати ігрові дані. Дота використовує окреме захищене підключення; після оновлення перезапустіть Доту один раз."
      ],
      "0.53.6": [
        "Файл історії перевіряється до завантаження й відновлюється цілком однією операцією. Пошкоджений кеш більше не заважає відкрити розбір."
      ],
      "0.53.5": [
        "Повторні фонові запити не дублюють завдання, що виконується. Під час закриття тренер скасовує завдання в очікуванні й обмежено чекає активні."
      ],
      "0.53.4": [
        "Якщо завершений матч не вдається зберегти, тренер повторить спробу, зокрема після перезапуску. Наступний матч продовжує записуватися."
      ],
      "0.53.3": [
        "Готовий тренер тепер використовує ті самі закріплені версії бібліотек, що й автоматичні перевірки."
      ],
      "0.53.2": [
        "Оновлено рушій застосунку й залежності з виправленнями безпеки."
      ],
      "0.53.1": [
        "Поради продовжують працювати, якщо журнал не вдається зберегти. Помилка потрапить у звіт про проблему."
      ],
      "0.53.0": [
        "Ctrl+K знаходить усе: вкладку, матч за героєм або вашою нотаткою, «Прогрес на герої», налаштування чи дію.",
        "Значок нотатки тепер і в «Останніх матчах» на Головній."
      ],
      "0.52.0": [
        "Пошук у налаштуваннях: поле вгорі «Налаштувань» (Ctrl+F) залишає лише рядки з вашими словами.",
        "Розмір інтерфейсу в «Налаштування» → «Застосунок» (90–125 %) або Ctrl + плюс / мінус.",
        "Нотатки до матчів: ваш рядок у шапці розбору, значком — і в таблиці матчів.",
        "Бічні кнопки миші й Alt+←/→ ходять відкритими сторінками; ↑/↓ — рядками таблиці матчів."
      ],
      "0.51.0": [
        "Будь-який матч за номером: вставте номер або посилання OpenDota, Dotabuff чи STRATZ поруч із фільтрами матчів — повний розбір отримають і ігри, старші за вашу історію.",
        "На графіку розбору під хвилинами — ваші предмети: коли з'явився кожен зібраний предмет.",
        "Поки ви чекаєте відродження, картка оверлея показує іконку предмета, який варто купити."
      ],
      "0.50.0": [
        "Предмети всюди: у таблиці матчів видно, з чим ви закінчили кожну гру, те саме — у шапці розбору, а в «Підсумках матчу» — предмети всіх десяти гравців.",
        "В «Останніх матчах» на Головній теж є предмети; наведіть на іконку — з'явиться назва."
      ],
      "0.49.0": [
        "Підказки щодо прокачки показують іконку здібності, а порядок прокачки в про — іконками, потрібна зараз обведена; у картці «Прокачка» розбору теж іконки.",
        "Довгі сторінки мають розділи: у верхній смузі розбору й у «Прогресі» — посилання на частини сторінки, перехід в один клік, поточна частина підсвічена.",
        "Клавіша ? на будь-якій вкладці показує гарячі клавіші; таблиця матчів пам'ятає, як ви її відсортували."
      ],
      "0.48.0": [
        "Матчі можна сортувати: натисніть на стовпець таблиці (оцінка, золото, добивання, тривалість, В/С/Д, дата), ще раз — у зворотному порядку.",
        "У профілі видно найближчу нагороду, а в списку смертей зрозуміліший графік здоров'я за останні 20 секунд.",
        "Дрібниці: таблиці у вузькій колонці рівно по краю тексту, «Що це означає?» більше не налазить на рядок таблиці, шапка розбору спокійніша."
      ],
      "0.47.0": [
        "Картка в грі має кольорову смужку ліворуч: червона — терміново, жовта — порада, зелена — спокійна підказка, кремова — мапа й план.",
        "Поки Дота запущена, «Головна» показує поточний матч першим.",
        "Спокійніші дрібниці: прогрес нагород і іскри кремові, у матчу без розбору — прочерк замість порожнього кільця, «Ще налаштування» — розгортний рядок."
      ],
      "0.46.0": [
        "Під час прокручування розбору верхня смуга лишається на місці: герой, підсумок, оцінка й «‹ Новіший · Старіший ›».",
        "Плитки «Прогресу» показують останні 20 матчів: перемоги й поразки, як змінювалися золото, добивання й оцінка.",
        "Оцінки матчів на графіках пофарбовано як кільця оцінок; перший запуск показує, скільки лишилося, і приклад справжньої підказки."
      ],
      "0.45.0": [
        "Новий вигляд: фірмовий червоний Wardly, теплі кольори й виразні заголовки — як на сайті.",
        "У шапці розбору й у поточному матчі — ваш герой великим планом, перемога й поразка — кольорові позначки.",
        "Ваш нік і аватар Steam унизу бічного меню відкривають профіль.",
        "Зрозуміліші англійські тексти підказок і розборів."
      ],
      "0.44.2": [
        "Розбір у PDF: на місці всі портрети героїв та іконки предметів, графіки нормального розміру, картки не налазять одна на одну.",
        "Зрозуміліші тексти підказок у грі й розборів: «Смерть від Axe», «Денаїв до 4:00», «Пул о 2:15» та інші дрібниці."
      ],
      "0.44.1": [
        "Коли тренер запускається або зупинений, «Матчі», «Прогрес» і «Профіль» так і кажуть (із кнопкою запуску), а не вантажаться нескінченно й не просять заново прив'язати акаунт.",
        "Вузьке вікно використовує всю ширину; у розборах дробові числа записано через кому."
      ],
      "0.44.0": [
        "Розбори поспіль: «‹ Новіший · Старіший ›» поруч із «Матчі» або клавіші ← і →. У кожному розборі є посилання на цей матч на OpenDota, Dotabuff і STRATZ.",
        "Гарячі клавіші: Ctrl+1…5 відкривають вкладки, Esc повертає до списку матчів; увесь список — у «Налаштування → Гарячі клавіші». У меню в треї — розбір останнього матчу.",
        "Термінова порада на картці тепер червона, а поки ви переміщуєте картку, на ній видно приклад поради справжнього розміру.",
        "Числа записано як заведено (7,5), підказки на графіках закриваються, «Прогрес» і «Профіль» охайніші, а вкладки до прив'язки акаунта розповідають, що на них буде."
      ],
      "0.43.2": [
        "Стрілки над навичками самі знаходять іконки здібностей (Full HD, 2K, 4K) і вказують на кнопку «+», яку треба натиснути. Для героя з іншою кількістю здібностей і після нової здібності від аганіма чи шарда нічого налаштовувати не потрібно. «Підправити» лишилося на випадок іншого інтерфейсу.",
        "Більше немає картки «сплануйте безпечний маршрут» до горна: поява героя на мапі — не смерть."
      ],
      "0.43.1": [
        "Роль обрано помилково: якщо в «Ваша роль» стоїть саппорт, а ви граєте мід чи керрі, картка й Головна один раз скажуть про це — з кнопкою, щоб повернути «Авто»."
      ],
      "0.43.0": [
        "Стрілки над навичками: коли є очко навички, над потрібною іконкою на панелі Доти з'являється стрілка з назвою здібності. Один раз сумістіть рамку з іконками: «Налаштування → Стрілки над навичками → Налаштувати рамку»."
      ],
      "0.42.0": [
        "Стартові предмети іконками: картка показує, що купують на вашому герої й вашій ролі гравці Divine та Immortal, — уже на стадії стратегії.",
        "План на гру малює збірку іконками зі звичайною хвилиною кожного предмета.",
        "Накопичується золото — картка називає частину наступного предмета, яку можна купити просто зараз."
      ],
      "0.41.0": [
        "Перше очко навички тримається на картці, поки ви його не вкладете; план на гру з'являється за 20 секунд до горна.",
        "Порожній інвентар на початку чи золото, що накопичується: картка скаже про це на будь-якій ролі, навіть із вимкненими таймерами мапи.",
        "Картка, що не змінюється 20 секунд, стає напівпрозорою; нова знову яскрава — її одразу помітно."
      ],
      "0.40.3": [
        "Нове навчання: справжні картки порад із поясненням, що означає кожен рядок, підказки по мапі, план на гру, профіль, ШІ-тренер і допомога. Відкрити: «Налаштування → Допомога → Показати»."
      ],
      "0.40.2": [
        "Мід: якщо наближається руна сили, а в пляшці ще лежить минула, картка нагадає спершу використати її.",
        "Менше повторів: картка про темп фарму й «Немає вардів» у саппорта приходять рідше після трьох разів, а нагадування про варди чекає, якщо ви щойно поставили останній."
      ],
      "0.40.1": [
        "Графік рейтингу у вкладці «Профіль» тепер плавна лінія, а не ламана.",
        "Сторінка вашого профілю для друзів виглядає як у застосунку: та сама рамка, банер і колір ніка, і ваша аватарка зі Steam.",
        "Довгі титули в крамниці стоять по центру картки."
      ],
      "0.40.0": [
        "Перше очко навички: ще до початку гри картка підкаже, з якої навички починають про-гравці на вашому герої (якщо більшість їхніх ігор збігається)."
      ],
      "0.39.0": [
        "«Важка лінія» й «Зручна лінія»: якщо герой на вашій лінії вже не раз обігрував вас на лінії (або програвав вам), картка скаже про це в перші хвилини — з рахунком ваших минулих ліній проти нього."
      ],
      "0.38.0": [
        "Підказка «суперник зник» на лінії: якщо міда суперника чи вашого суперника на лінії не видно 20 секунд, картка попередить (а голос скаже, якщо він читає всі поради)."
      ],
      "0.37.0": [
        "Картка «Лінія» в розборі матчу: добивання, денаї, золото й досвід на 3, 5, 7 і 10-й хвилинах проти кора суперника на вашій лінії й підсумок лінії.",
        "«Ваші лінії» в «Прогресі»: скільки останніх ліній ви виграли й проти яких героїв програєте лінію."
      ],
      "0.36.0": [
        "Поради на лінії для корів у перші десять хвилин: немає регенерації дорогою на лінію, половина HP і нічим лікуватися, ще немає Magic Stick, мало добитих своїх кріпів.",
        "Предмети проти складу ворога: Pipe of Insight або Black King Bar проти магічної шкоди, Glimmer Cape або Ghost Scepter для саппорта."
      ],
      "0.35.0": [
        "Друзі на вкладці «Профіль»: покажіть профіль за кодом друга, додайте друзів за їхніми кодами й дивіться, хто вище — рівень, рейтинг, оформлення.",
        "Ваш профіль сторінкою, яку можна скинути в чат: api.luhovyimvp.dev/p/<код>."
      ],
      "0.34.0": [
        "Нова вкладка «Профіль»: графік рейтингу як на FACEIT — введіть свій MMR один раз, і кожна рейтингова гра його рухатиме.",
        "Рівні, нагороди й іскри за гру з Wardly.",
        "Витрачайте іскри в крамниці профілю: рамки аватара, банери, колір ніка й титули; рідкісні відкриваються з рівнем або за нагороду."
      ],
      "0.32.0": [
        "Нове в «Ще налаштуваннях»: записи матчів зберігаються тиждень. Будь-який матч можна зберегти файлом і надіслати розробникові — хоч наступного дня.",
        "Звіт про проблему показує, який матч застосунок записав останнім і чи готовий його розбір."
      ],
      "0.31.2": [
        "Звіт про проблему, надісланий після перезапуску застосунку, однаково показує, що гра надсилала в останньому матчі."
      ],
      "0.31.1": [
        "Розбір смерті каже, якщо в пляшці лишилася невикористана руна прискорення, невидимості, щита чи ілюзій.",
        "Виправлено: у розборі стояв прочерк замість здібності героя, з якою ви загинули, не натиснувши її."
      ],
      "0.31.0": [
        "Мало HP, а в пляшці руна прискорення, невидимості, щита чи ілюзій — тренер підкаже натиснути її й іти.",
        "Руна регенерації чи води в пляшці вважається лікуванням, а пляшка з іншою руною — більше ні.",
        "Руна сили лежить у пляшці 30 секунд — підказка використати її для вбивства."
      ],
      "0.30.3": [
        "Перевірено на справжніх іграх: вороги на мінімапі, готовність предметів і події Рошана доходять до тренера.",
        "Таймер Рошана більше не губить убивство серед повідомлень чату й інших подій гри."
      ],
      "0.30.2": [
        "Таймер Рошана й Аегіса тепер отримує дані з гри: один раз перезапустіть Доту після оновлення.",
        "Предмети в рюкзаку більше не вважаються готовими до натискання.",
        "Звіт про проблему показує, які дані гра надсилає насправді: зіграйте матч і надішліть його."
      ],
      "0.30.1": [
        "Більше героїв у порадах щодо предметів: Linken's Sphere проти Reaper's Scythe, Charge of Darkness і Winter's Curse, Maelstrom керрі проти героїв з ілюзіями, Dust проти Mirana, Templar Assassin і Invoker."
      ],
      "0.30.0": [
        "Якщо за 5 секунд пішло 30 % здоров'я й більше, термінова картка з'являється одразу, до критичного HP.",
        "Картка низького HP показує, що натиснути, як швидко падає здоров'я і який це раз за гру.",
        "Третя смерть в одному місці за гру називається в пораді після смерті й на екрані відродження."
      ],
      "0.29.2": [
        "Предмети проти ворогів: смерті під Primal Roar від Beastmaster, Doom чи Duel — порада купити Linken's Sphere з поясненням; проти ухилення — Monkey King Bar, проти лікування — Spirit Vessel, саппортові проти невидимих — Dust.",
        "Невивчений Blink більше не вважається «на перезарядці», а «померли з готовим Blink» — лише якщо на натискання були дві вільні секунди.",
        "Повторні картки про низьке HP кажуть, який це раз за гру, і радять відновитися повністю."
      ],
      "0.29.1": [
        "Мідерові таймер руни сили показується до 20-ї хвилини, а не всю гру, а до 6-го рівня з Bottle підказка радить покласти руну в нього й приберегти для вбивства."
      ],
      "0.29.0": [
        "Розбір матчу став коротшим: крім трьох головних пунктів, решта зауважень і довгий список смертей відкриваються кнопкою «Показати ще».",
        "Під кожною смертю підписано, що це за лінія здоров'я, а «Цінність» тепер називається «Вартість героя»."
      ],
      "0.28.0": [
        "Перша порада після смерті називає лінію чи частину мапи, де ви загинули, або як швидко вас убили — а не «продумайте безпечніший маршрут».",
        "Саппортам: підказка «Немає рятівного предмета» називає предмет, який найчастіше беруть на вашому герої, і скільки золота на нього лишилося; підказка про вард каже, куди його поставити (річка біля вашої лінії, лігво Рошана, свій чи ворожий ліс за рахунком).",
        "Якщо на лінії бракує добивань, порада показує цифри: «Надолужуйте фарм: добивань до 5-ї хвилини — 12, добрий темп — 18+»."
      ],
      "0.27.0": [
        "Порада після смерті каже, скільки разів ви вже загинули — за останні хвилини чи за гру, — а не повторює те саме «змініть маршрут»."
      ],
      "0.26.0": [
        "У розборі матчу з'явилася картка «Прокачка»: яке вміння ви прокачали першим і як прокачують вашого героя про-гравці."
      ],
      "0.25.0": [
        "Картки про фарм показують цифри в головному рядку: золото за хвилину й добивання або наскільки ви відстали від доброго темпу.",
        "Порада, у якій змінилися лише цифри, більше не повторюється кожні дві хвилини."
      ],
      "0.24.0": [
        "Який талант узяти: коли відкривається ряд талантів, тренер називає той, що беруть про-гравці на вашому герої."
      ],
      "0.23.0": [
        "Куди вкласти очко: після нового рівня тренер називає вміння, яке прокачують про-гравці на вашому герої, і весь порядок прокачки.",
        "План на гру показує прокачку в про, а розбір — якщо першим ви прокачали інше вміння."
      ],
      "0.22.0": [
        "Прокачка: тренер підкаже ультимейт на 6/12/18-му рівні й талант на 10/15/20/25-му, якщо очко лишилося невкладеним.",
        "Предмет під ситуацію: дві смерті під контролем — Black King Bar, дві швидкі смерті — Aeon Disk, із причиною й золотом, якого бракує.",
        "Менше банальних порад: серія вбивств, розрив у рахунку чи ваш темп у цифрах замість того самого «фарміть безпечно»."
      ],
      "0.21.0": [
        "Налаштування зібрано заново: п'ять зрозумілих груп, більший шрифт, менше кнопок і пояснення простими словами біля кожного рядка. Перенесення на інший комп'ютер — покроково.",
        "«Чому ця порада?» під кожною підказкою на Головній і в розборі: що побачив тренер.",
        "«Що це означає?» біля оцінки матчу, порівняння з рангом і фокусу — і жодних технічних слів у всьому застосунку."
      ],
      "0.20.0": [
        "Повні підказки для 25 саппортів (четвірки й п'ятірки): їхні порятунки, нагадування поставити варди з інвентарю й зібрати рятівний предмет, а в розборі — таймінг цього предмета й скільки вардів ви поставили.",
        "Оверлей 2.0: смужка таймерів під карткою (руни, стаки, Рошан, Аегіс для вашої ролі), компактна картка й плавна поява — «Налаштування → Оверлей».",
        "Нова Головна: одна картка з останнім матчем, сьогоднішнім днем, серіями й фокусом. У «Прогресі» — зона «Цілі»."
      ],
      "0.19.0": [
        "Підсумок вечора: після двох і більше матчів, коли Дота закрита, на Головній — зведення вечора й текст, який можна скопіювати друзям.",
        "У «Прогресі» — мапа ваших смертей за останні 20 матчів і таймінг ключового предмета героя за іграми.",
        "Коротке навчання застосунком (Налаштування → Застосунок), а рядок стану прямо пише, чи є зв'язок із Дотою."
      ],
      "0.18.0": [
        "Повні підказки ще для 18 героїв: 8 мідерів (Shadow Fiend, Storm Spirit, Queen of Pain, Puck та інші) і 10 хардлайнерів (Axe, Mars, Legion Commander, Centaur та інші).",
        "Тренер знає їхні власні порятунки (Blink, Ball Lightning, Refraction, Guardian Sprint…), а фарм хардлайнера порівнюється з темпом хардлайнера, а не керрі."
      ],
      "0.17.0": [
        "Анонімна статистика за бажанням («Налаштування → Застосунок», типово вимкнена): які підказки показано й після яких попереджень була смерть — щоб зробити підказки кращими. «Що надсилається» показує точний текст.",
        "«Видалити мої дані на сервері» одним натисканням стирає ваші звіти про проблеми, посилання «Поділитися» й статистику."
      ],
      "0.16.0": [
        "У розборі кнопка «Дивитися» біля смерті й ключового моменту копіює команду повтору, яка переносить за 10 с до нього.",
        "На графіку матчу пунктиром — ваш найкращий матч на цьому герої.",
        "На головній — цілі-серії (5 матчів поспіль не більше 5 смертей) і м'яке попередження після 3 поразок поспіль.",
        "У «Прогресі» — на яких героях грати частіше, а яких краще відкласти, порівняно з вашим званням."
      ],
      "0.15.0": [
        "Таймери Рошана й Аегіса: вікно появи після вбивства й попередження за хвилину до того, як згорить ваш Аегіс.",
        "Поки чекаєте відродження: як вас убили, що лишилося не натиснуто й що купити зараз.",
        "Більше немає «Перечекайте контроль», якщо після оглушення нічого натиснути."
      ],
      "0.14.0": [
        "Підказки знають вашого героя: Blink, щоб піти, Blade Fury, щоб вийти з бійки, і за скільки секунд відновиться втеча.",
        "Мапа матчу обводить місця, де ви помираєте раз у раз, і підказує маршрут."
      ],
      "0.13.0": [
        "Підказки називають, що натиснути просто зараз: Force Staff, щоб піти, Magic Wand із зарядами, Black King Bar одразу після оглушення.",
        "Після смерті: який рятівний предмет лишився не натиснутим і де ви помираєте раз у раз."
      ],
      "0.12.0": [
        "Кожну вкладку розбито на зрозумілі зони: спершу головне, потім подробиці.",
        "«Ваш тиждень» на Головній: оцінка проти минулого тижня й графік кожного матчу.",
        "Порада щодо фарму для керрі називає наступний предмет, скільки золота бракує і скільки його фармити.",
        "Виправлено: деякі розбори нескінченно показували «Завантажуємо матч…»."
      ],
      "0.11.0": [
        "Застосунок на весь екран: навігація ліворуч, дві колонки, обидві команди поруч.",
        "«Останні матчі» на Головній, оцінка кільцем у розборі й таблиці матчів.",
        "Більше підказок у грі для кожної ролі: ротації й добивання міда, важка лінія хардлайну, пули саппорта, таймінг ключового предмета.",
        "«Важко проти» в плані на гру."
      ],
      "0.10.0": [
        "Тиждень у Discord: щопонеділка матчі, оцінка й герої тижня приходять у канал вашого сервера. «Налаштування → Застосунок → Тиждень у Discord».",
        "У картці «Тиждень» на Головній видно, на яких героях ви грали.",
        "У «Звіт про проблему» більше не потрапляють ключі видалення ваших посилань «Поділитися»."
      ],
      "0.9.0": [
        "Статус у Discord: друзі бачать «Матч на <герой> · з тренером Wardly». Вимикається в «Налаштуваннях → Застосунок».",
        "Посилання на розбори й прогрес тепер коротші: luhovyimvp.dev/r/…",
        "Сайт у кольорах логотипа."
      ],
      "0.8.0": [
        "Розбір смертей: здоров'я за останні 20 секунд і рятівний предмет, який був готовий, але не натиснутий.",
        "«Прогрес»: ваш білд на герої — коли предмети з'являються в перемогах і в поразках.",
        "Після матчу оверлей показує підсумок просто на екрані з рахунком.",
        "Перенесення історії на інший комп'ютер за одноразовим кодом."
      ],
      "0.7.0": [
        "«Прогрес» → «Поділитися»: посилання на сторінку з вашим прогресом — матчі, перемоги, середні цифри, головні герої, що вдається й над чим працювати.",
        "Нова заставка під час запуску: логотип оживає, поки запускається служба."
      ],
      "0.6.1": [
        "Розбір хардлайнера: оглушення й шкода будівлям проти ворожого хардлайнера того самого матчу.",
        "У плані на гру поруч із героєм — ваш рахунок на ньому.",
        "Усі версії й що в них змінилося — на сайті: luhovyimvp.dev/changelog.html."
      ],
      "0.6.0": [
        "Розбір під роль: руни міда проти ворожого міда, стаки й сентрі саппорта.",
        "«Прогрес»: ваш рахунок проти кожного ворожого героя — хто незручний і кого ви обігруєте.",
        "ШІ-тренерові можна поставити запитання про всі останні матчі, а не лише про один.",
        "У грі: підказка на 6-му рівні для міда (ротація) й офлейну (тиск)."
      ],
      "0.5.0": [
        "Dota AI Coach тепер називається Wardly, у нього новий логотип. Історія й налаштування на місці.",
        "«Прогрес» → «Порівняння з другом»: його відкриті матчі поруч із вашими й спільні герої.",
        "Розбір можна надіслати посиланням — із прев'ю в Discord і Telegram, без Steam ID і ніка.",
        "«Налаштування → Застосунок → Історія матчів»: зберегти все у файл і завантажити на будь-якому комп'ютері.",
        "Шлях на мапі матчу більше не тягнеться від місця смерті до фонтана."
      ],
      "0.4.0": [
        "Мапу матчу намальовано на справжній мінімапі Доти: ваш шлях, позиція на лінії, варди й смерті.",
        "На графіку «Протягом матчу» — добрий темп за золотом і досвідом.",
        "Картка «Смерті»: де, хто вбив, скільки золота не витрачено й яка була підказка перед смертю.",
        "Повторювані помилки позначено: «3-й матч поспіль».",
        "Тиждень на головній: матчі, зміна оцінки, найкращий матч, часта помилка й план на 3 матчі за фокусом."
      ],
      "0.3.0": [
        "Таймери мапи на оверлеї за 20 секунд: руни, святилища мудрості, лотоси, Торментор, рівні нейтральних предметів — лише потрібні вашій ролі.",
        "Роль визначається за лінією в перші хвилини (або обирається в «Налаштування → Поради») і видна на головній.",
        "Підказки саппортові: застакати табір, узяти варди, залишити добивання керрі. Поради щодо фарму на саппорті вимкнено; щодо ТП — на будь-якому герої.",
        "«Надіслати розробникові» у звіті про проблему: одна кнопка, коментар і попередній перегляд; ключі, нік і Steam ID вирізаються.",
        "Драфт пропонує лише героїв тієї позиції, на якій ви грали."
      ],
      "0.2.1": [
        "Історія матчів більше не зривається, коли OpenDota відповідає повільно.",
        "Застосунок сам просить OpenDota розібрати останні матчі — у розборі з'являються добивання до 10:00, збірка й графік.",
        "Драфт радить героя вашої ролі; суперник за роллю й предмети проти ворогів визначаються правильно й без розбору реплею.",
        "На «Прогресі» всі п'ять плиток в один рядок, на головній не обрізається ім'я героя."
      ],
      "0.2.0": [
        "План на гру на початку матчу й фокус: оберіть одну помилку — у кожному розборі видно, чи вдалося її уникнути.",
        "«Запитати тренера»: своє запитання про матч, відповідь за його даними.",
        "Голос, частота порад, поради щодо виживання на будь-якому герої, нагадування носити TP і витрачати золото після смерті.",
        "Мапа матчу, порівняння з вашими звичайними цифрами, фільтри матчів і збереження в PDF.",
        "Перевірка параметра запуску -gamestateintegration, без якого Дота не передає дані."
      ]
    }
  };

  // "0.51.0" > "0.50.2": the parts as numbers.
  function newerVersion(a, b) {
    const x = String(a).split(".").map((part) => Number.parseInt(part, 10) || 0);
    const y = String(b).split(".").map((part) => Number.parseInt(part, 10) || 0);
    for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
      if ((x[i] || 0) !== (y[i] || 0)) {
        return (x[i] || 0) > (y[i] || 0);
      }
    }
    return false;
  }

  // The new version's bullets, then those of the versions an update skipped
  // (0.49 → 0.51 also lists 0.50), newest first, four versions at most.
  function whatsNewVersions(table, current, from) {
    return Object.keys(table)
      .filter((version) => Array.isArray(table[version]) && table[version].length)
      .filter((version) => version === current || (from && newerVersion(version, from) && newerVersion(current, version)))
      .sort((a, b) => (newerVersion(a, b) ? -1 : newerVersion(b, a) ? 1 : 0))
      .slice(0, 4);
  }


  // Copies keep callers from mutating the module's static history.
  function texts(language) {
    const table = TEXT[language === "uk" ? "uk" : "en"];
    return Object.fromEntries(Object.entries(table).map(([version, bullets]) => [version, [...bullets]]));
  }

  return { texts, versions: whatsNewVersions };
});
