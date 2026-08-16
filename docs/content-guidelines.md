# Content Guidelines

Sources: YouTube Help — [Made for Kids](https://support.google.com/youtube/answer/9528076) and [YPP monetization policies](https://support.google.com/youtube/answer/1311392). Verified against the primary sources on 13 August 2026.

---

## 1. "Made for Kids" classification — not negotiable

YouTube's definition:

> Content is considered "made for kids" if **children are the primary audience**, or if it targets children through characters, activities, **songs, stories**, or other subject matter that reflects an intent to reach a young audience.

In the US, **"child" means under 13**.

Factors that count: subject matter, intended and actual audience, child actors, characters that appeal to children, child-oriented language, educational activities, advertising aimed at children.

### What is *not* MFK

> Content does not have to be labelled MFK merely because it is **safe or appropriate for everyone** to watch, because it includes activities traditionally associated with children, or because it **incidentally** reaches child viewers. **General-audience content — aimed at teens or older — should be marked "not made for kids".**

### What this means for this project

⚠️ **Phase 0 correction.** Channel B was originally designed as "story narration for ages 5–10, not MFK". That is a **misclassification**:

- Ages 5–10 are under 13 → children
- The content targets children through stories and characters → the exact centre of the definition
- Children are the primary audience → MFK

Liability sits with the channel owner:

> Creators bear legal responsibility for accurate categorization... Failure to set content appropriately may result in YouTube consequences or legal liability.

**Rule: all content aimed at children is marked Made for Kids. It is never mislabelled for the RPM advantage.** This is not an optimization opportunity; it is an FTC/COPPA obligation.

This rule is enforced in code, not just in this document: [`core/config.py`](../core/config.py) hard-codes `made_for_kids=True` for every channel whose upper age bound is under 13, and `config.validate()` returns a problem if any channel violates it.

If a genuinely non-MFK channel is ever wanted, the *content* has to change — adult sleep stories, folklore or mythology narration. Changing the label alone is not an option.

### What MFK turns off

Super Chat / Super Stickers / Super Thanks, channel memberships, end screens, cards, comments, the notification bell, personalized ads.

What stays available: **Shorts revenue sharing** — one of the few native monetization paths left on an MFK channel. This is why the Shorts cadence is not treated as optional.

---

## 2. Inauthentic content — the pipeline's design constraint

On 15 July 2025, "repetitious content" became **"inauthentic content"**. Categories that cannot be monetized, from the primary source:

| Prohibited | Our countermeasure |
|---|---|
| Content that looks "mass-produced from a template", with minimal variation | `variation_guard` — structure axis |
| "AI content made with generic or unoriginal templates", lacking the creator's own perspective | `variation_guard` — script axis + character personality |
| Videos where characters repeat the same scenarios with the same outcomes | `variation_guard` — script + structure |
| Image slideshows, or template stories with negligible narrative or educational substance | Every episode carries a real narrative arc; the slideshow format is banned |
| Highly repetitive content where "each video does not offer creative, educational or other value to the viewer" | The approval gate — human judgment |

**On performance feedback.** `core/analytics.py` weights idea generation by measured retention, and that mechanism is deliberately bounded (minimum 3 samples, weights clamped to 0.5–2.0, no value ever pruned). The reason belongs in this document rather than only in the code: an unbounded "do more of what performed" loop converges on a single setting and companion, which produces exactly the template-stamped output this policy prohibits. Optimizing hard against retention is, here, the same thing as optimizing toward demonetization.

**AI persona rule:** AI personas that give information about health, law, finance or politics cannot be monetized. Children's stories do not touch those subjects — they are on the banned-topic list below.

> Note: this policy page does **not** state an explicit disclosure requirement for AI content. Separately, YouTube Studio has an "altered or synthetic content" toggle for realistic-looking synthetic material. Animation and cartoon styles generally do not require it, but it is evaluated on every upload.

---

## 3. Banned topics (both channels)

Never appear in children's content:

- Health, medical advice, illness
- Finance, money, investment
- Law, politics, religion
- Violence, fear, danger, death, separation trauma
- Eating or weight themes
- Brands, product placement, calls to purchase
- Impersonation of real people

## 4. Channel A — Bedtime (ages 2–5, MFK)

### Protagonist: Fen

In 2026 the fastest-growing children's channels are built around a **character**, not a concept. Channel A's constant is Fen:

| | |
|---|---|
| Species | Otter |
| Home | A mossy stream bed |
| Temperament | Calm, helpful, unhurried |
| Role | Notices what others miss; helps without being asked |

Fen is a small animal, not a hero who solves everything. Sometimes Fen simply keeps someone company.

**Fen stays constant, the guest changes.** In every episode Fen meets a different animal — this delivers brand continuity and variation at the same time. The variation gate's visual axis deliberately **excludes** the protagonist (`storyboard.variation_asset_ids`); penalising an asset that is *supposed* to recur would turn the gate against our own brand.

Scripts refer to Fen by name, never "the otter". Fen's appearance is **not described in text** — the animation carries it, and written descriptions drift away from the visuals over time.

### Visual language

Code-based vector art (SVG/React). Character consistency is guaranteed **by construction**: the same component produces the same character in every episode. No image model required, cost $0.

- Round silhouettes, no sharp corners — sharpness signals alertness
- Eyes half-closed; fully closed at rest
- Low saturation, low contrast; the palette darkens noticeably toward the end of an episode
- Very slow motion: a single breathing cycle, 1.5% zoom
- The moon and stars are a fixed celestial anchor

This is a first version. The art direction will be upgraded later; because `remotion/src/SceneView.tsx` is isolated, the rest stays untouched.

- Slow pacing, warm palette, calm music
- Characters model calm and curious behaviour
- Conflict is gentle and resolves quickly; no tension arc
- Audio: slow narration (`speech_rate` 0.82), no loud sounds or abrupt transitions
- Every episode ends on a settling-down beat

## 5. Channel B — Story Time (ages 5–10, **MFK**)

- More complex narrative arc, curiosity and discovery
- Character personality in the foreground — the shared trait of fast-growing channels in 2026
- Learning arrives as a by-product, not as a lesson
- Audio: normal pace (`speech_rate` 1.0)

## 6. The minimum value test every episode must pass

These are the questions asked at the approval gate. A single "no" means the video is not published:

1. Does this episode have a story of its own, rather than being a rearrangement of another one?
2. Do the characters *do* something in this episode, or do they only change scenery?
3. Is there anything a child could retell after watching it?
4. Do the visuals carry the narrative, or are they wallpaper?
5. Can I say in one sentence what separates this video from the last 10 episodes?
