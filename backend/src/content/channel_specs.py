"""
Content Studio — Channel Specifications.
Defines all supported channels with their formats, fields, and best practices.
"""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class ChannelSpec:
    key: str
    display_name: str
    platform: str
    default_format: str
    format_options: List[str]
    required_fields: List[str]
    field_guidance: str = ""  # Per-channel instructions for LLM on output structure
    variants_count: int = 3
    best_practices: List[str] = field(default_factory=list)


CHANNEL_SPECS: Dict[str, ChannelSpec] = {
    "ig_reel": ChannelSpec(
        key="ig_reel",
        display_name="Instagram Reel",
        platform="instagram",
        default_format="9x16_30s",
        format_options=["9x16_15s", "9x16_30s", "9x16_60s"],
        required_fields=["hook", "script", "cta", "hashtags", "music_suggestion", "shot_list"],
        field_guidance="""OUTPUT FIELDS for Instagram Reel:
- "hook": string — First 1-3 seconds spoken/displayed text that stops the scroll. Short, punchy, provocative.
- "script": string — Full voiceover/on-screen script for the entire reel. Written as spoken word, with natural cadence. Include timing cues in brackets like [0-3s], [3-8s], etc.
- "cta": string — Call to action at the end (e.g., "Link en bio", "Seguime para mas").
- "hashtags": array of strings — 15-25 relevant hashtags WITHOUT the # symbol.
- "music_suggestion": string — Specific music/audio suggestion with genre, mood, BPM.
- "shot_list": array of strings — Video scene/shot descriptions in sequence. Each string is ONE camera shot description (e.g., "Close-up of hands gripping bar, slow motion", "Wide shot: person completing movement, camera tracking"). These are VIDEO SHOTS for filming, NOT carousel slides.""",
        variants_count=3,
        best_practices=[
            "First 3 seconds must hook the viewer",
            "Use trending audio when possible",
            "Include captions for accessibility",
            "End with clear CTA",
            "Keep text overlays short and impactful",
        ],
    ),
    "ig_post": ChannelSpec(
        key="ig_post",
        display_name="Instagram Post",
        platform="instagram",
        default_format="1x1",
        format_options=["1x1", "4x5"],
        required_fields=["caption", "cta", "hashtags", "visual_description"],
        field_guidance="""OUTPUT FIELDS for Instagram Post (single image):
- "caption": string — Full Instagram caption. First line is the hook (visible before "more"). Use line breaks for readability. Max 2200 chars.
- "cta": string — Call to action (e.g., "Link en bio", "Comenta tu experiencia").
- "hashtags": array of strings — 20-30 relevant hashtags WITHOUT the # symbol.
- "visual_description": string — Detailed description of the single image/photo to produce. Include: composition, subject, lighting, color palette, text overlay if any, mood/aesthetic.""",
        variants_count=3,
        best_practices=[
            "Caption under 2200 chars, first line is crucial",
            "Use 20-30 relevant hashtags",
            "Include call-to-action in caption",
            "Use emotive or curiosity-driven first line",
        ],
    ),
    "ig_carousel": ChannelSpec(
        key="ig_carousel",
        display_name="Instagram Carousel",
        platform="instagram",
        default_format="carousel_10",
        format_options=["carousel_5", "carousel_10"],
        required_fields=["slides", "caption", "cta", "hashtags"],
        field_guidance="""OUTPUT FIELDS for Instagram Carousel:
- "slides": array of objects — Each object represents one carousel slide with:
  - "slide_number": integer (1, 2, 3...)
  - "copy": string — Text content displayed ON the slide image
  - "visual_direction": string — Art direction for the slide (colors, layout, imagery)
  Use 5-10 slides. First slide = scroll-stopping hook. Last slide = CTA.
- "caption": string — Carousel caption for below the images. First line hooks, then summarize value.
- "cta": string — Call to action.
- "hashtags": array of strings — 20-30 relevant hashtags WITHOUT # symbol.""",
        variants_count=3,
        best_practices=[
            "First slide must stop the scroll",
            "Each slide should add value",
            "Last slide has strong CTA",
            "Mix text-heavy and visual slides",
            "Use swipe-worthy transitions between slides",
        ],
    ),
    "ig_story": ChannelSpec(
        key="ig_story",
        display_name="Instagram Story",
        platform="instagram",
        default_format="9x16_story",
        format_options=["9x16_story"],
        required_fields=["frames", "cta", "sticker_suggestions"],
        field_guidance="""OUTPUT FIELDS for Instagram Story (multi-frame):
- "frames": array of strings — Each string describes one story frame. Include text overlay, background visual, and any interactive elements. 3-5 frames typical.
- "cta": string — Final frame CTA (e.g., "Swipe up", "Link en bio", "Responde esta encuesta").
- "sticker_suggestions": array of strings — Instagram sticker ideas (polls, questions, sliders, quizzes, countdowns).""",
        variants_count=3,
        best_practices=[
            "Use polls, questions, or sliders for engagement",
            "Keep text minimal per frame",
            "Include swipe-up or link sticker CTA",
            "Design for tap-through rhythm",
        ],
    ),
    "tiktok_short": ChannelSpec(
        key="tiktok_short",
        display_name="TikTok Short",
        platform="tiktok",
        default_format="9x16_30s",
        format_options=["9x16_15s", "9x16_30s", "9x16_60s"],
        required_fields=["hook", "script", "cta", "hashtags", "sound_suggestion", "text_overlays"],
        field_guidance="""OUTPUT FIELDS for TikTok Short (video):
- "hook": string — First 1-2 seconds spoken/displayed. Must create curiosity or pattern interrupt.
- "script": string — Full spoken script for the video. Conversational, authentic TikTok tone. Include timing cues.
- "cta": string — End CTA (e.g., "Seguime para la parte 2", "Link en bio").
- "hashtags": array of strings — 5-10 relevant hashtags WITHOUT # (TikTok uses fewer).
- "sound_suggestion": string — Trending sound or original audio suggestion.
- "text_overlays": array of strings — Key text overlays that appear on screen during the video (for silent viewers). Each string = one overlay moment.""",
        variants_count=3,
        best_practices=[
            "Hook in first 1-2 seconds is critical",
            "Use native TikTok trends and formats",
            "Pattern interrupts boost retention",
            "Include text overlays for silent viewers",
            "Authentic tone outperforms polished",
        ],
    ),
    "yt_short": ChannelSpec(
        key="yt_short",
        display_name="YouTube Short",
        platform="youtube",
        default_format="9x16_60s",
        format_options=["9x16_30s", "9x16_60s"],
        required_fields=["hook", "script", "cta", "title", "description"],
        field_guidance="""OUTPUT FIELDS for YouTube Short (vertical video):
- "hook": string — First 2 seconds spoken text. Must stop scrolling.
- "script": string — Full voiceover script. More informative than TikTok, slightly more polished.
- "cta": string — Subscribe/channel CTA.
- "title": string — SEO-optimized Short title (under 100 chars).
- "description": string — YouTube description with keywords, links placeholder, and brief context.""",
        variants_count=3,
        best_practices=[
            "Strong hook in first 2 seconds",
            "Optimize title for search",
            "Include subscribe CTA",
            "Loop-friendly endings boost replays",
        ],
    ),
    "yt_long": ChannelSpec(
        key="yt_long",
        display_name="YouTube Long-Form",
        platform="youtube",
        default_format="16x9_long",
        format_options=["16x9_long"],
        required_fields=["title", "description", "script_outline", "hook", "cta", "tags", "chapters"],
        field_guidance="""OUTPUT FIELDS for YouTube Long-Form video:
- "title": string — SEO-optimized video title (under 70 chars, include primary keyword).
- "description": string — Full YouTube description: summary, timestamps placeholder, links, keywords.
- "script_outline": string — Detailed video script outline with sections: intro, main points, transitions, conclusion. Include approximate timing.
- "hook": string — First 15 seconds spoken script that prevents click-away.
- "cta": string — Subscribe + engagement CTA text.
- "tags": array of strings — YouTube tags for SEO (15-20 tags).
- "chapters": array of strings — Chapter titles with timestamps (e.g., "0:00 Intro", "1:30 Problem", "4:00 Solution").""",
        variants_count=2,
        best_practices=[
            "SEO-optimized title and description",
            "Pattern interrupt every 30-60 seconds",
            "Include chapters for navigation",
            "Strong thumbnail concept in description",
            "End screen with subscribe + related video CTA",
        ],
    ),
    "fb_feed": ChannelSpec(
        key="fb_feed",
        display_name="Facebook Feed Post",
        platform="facebook",
        default_format="feed_post",
        format_options=["feed_post", "feed_video"],
        required_fields=["copy", "headline", "cta", "visual_description"],
        field_guidance="""OUTPUT FIELDS for Facebook Feed Post:
- "copy": string — Main post text. Scannable with line breaks. Lead with value or question.
- "headline": string — Bold headline (if using link preview format). Under 40 chars.
- "cta": string — Call to action text or button label.
- "visual_description": string — Image/video description for the post creative.""",
        variants_count=3,
        best_practices=[
            "Lead with value or curiosity",
            "Keep copy concise and scannable",
            "Use line breaks for readability",
            "Include clear CTA button text",
        ],
    ),
    "fb_ad_copy": ChannelSpec(
        key="fb_ad_copy",
        display_name="Facebook Ad Copy",
        platform="facebook",
        default_format="ad_copy",
        format_options=["ad_copy", "lead_ad"],
        required_fields=["primary_text", "headline", "description", "cta_button", "link_description"],
        field_guidance="""OUTPUT FIELDS for Facebook Ad Copy:
- "primary_text": string — Main ad text above the image. Problem-agitate-solve or benefit-led. Can be long (125+ chars shown, rest behind "See more").
- "headline": string — Bold headline below image. Under 40 chars for mobile. Benefit or curiosity driven.
- "description": string — Link description text below headline. Supporting info, under 30 chars.
- "cta_button": string — Button label: "Learn More", "Sign Up", "Get Offer", "Shop Now", etc.
- "link_description": string — URL preview description text.""",
        variants_count=4,
        best_practices=[
            "Primary text: problem-agitate-solve structure",
            "Headline under 40 chars for mobile",
            "Test multiple headline angles",
            "Include social proof when possible",
            "Match ad copy to landing page messaging",
        ],
    ),
    "x_post": ChannelSpec(
        key="x_post",
        display_name="X (Twitter) Post",
        platform="x",
        default_format="single_tweet",
        format_options=["single_tweet"],
        required_fields=["text", "cta", "hashtags"],
        field_guidance="""OUTPUT FIELDS for X (Twitter) Post:
- "text": string — Tweet text. Max 280 characters. Concise, punchy, shareable. Can include line breaks.
- "cta": string — Engagement CTA (e.g., "RT si estas de acuerdo", "Comenta tu opinion").
- "hashtags": array of strings — 1-2 hashtags max WITHOUT # symbol.""",
        variants_count=4,
        best_practices=[
            "280 chars max, shorter is better",
            "Use 1-2 hashtags max",
            "Ask questions for engagement",
            "Include media when possible",
        ],
    ),
    "x_thread": ChannelSpec(
        key="x_thread",
        display_name="X (Twitter) Thread",
        platform="x",
        default_format="thread",
        format_options=["thread"],
        required_fields=["tweets", "hook_tweet", "cta_tweet"],
        field_guidance="""OUTPUT FIELDS for X Thread:
- "tweets": array of strings — Each string is one tweet in the thread (max 280 chars each). 5-10 tweets. Number them.
- "hook_tweet": string — The first tweet that must stand alone and hook. This IS tweets[0] but written separately for emphasis.
- "cta_tweet": string — The last tweet with CTA and retweet request.""",
        variants_count=2,
        best_practices=[
            "First tweet must stand alone and hook",
            "Number tweets for readability",
            "Each tweet adds one key point",
            "End with CTA and retweet request",
            "5-10 tweets is optimal length",
        ],
    ),
    "linkedin_post": ChannelSpec(
        key="linkedin_post",
        display_name="LinkedIn Post",
        platform="linkedin",
        default_format="text_post",
        format_options=["text_post", "article"],
        required_fields=["text", "hook", "cta", "hashtags"],
        field_guidance="""OUTPUT FIELDS for LinkedIn Post:
- "text": string — Full post text. Professional but personal. Use line breaks and white space. The hook line must be visible without clicking "see more" (first ~210 chars).
- "hook": string — The first 1-2 lines that appear before "see more". Must create curiosity.
- "cta": string — Engagement CTA (e.g., "Que opinan? Comenten", "Repostea si te identificas").
- "hashtags": array of strings — 3-5 professional hashtags WITHOUT # symbol.""",
        variants_count=3,
        best_practices=[
            "First line visible without 'see more' is crucial",
            "Use line breaks and white space",
            "Professional but personal tone",
            "3-5 hashtags max",
            "Ask for engagement in CTA",
        ],
    ),
    "email_newsletter": ChannelSpec(
        key="email_newsletter",
        display_name="Email Newsletter",
        platform="email",
        default_format="newsletter",
        format_options=["newsletter", "drip_email", "promo_email"],
        required_fields=["subject_line", "preview_text", "body_html", "cta_text", "cta_url_placeholder"],
        field_guidance="""OUTPUT FIELDS for Email Newsletter:
- "subject_line": string — Email subject. Under 50 chars. Create curiosity or urgency.
- "preview_text": string — Preview text shown after subject in inbox. Complements subject, under 90 chars.
- "body_html": string — Email body as simple HTML. Use <h2>, <p>, <strong>, <a> tags. Single column layout. Keep it scannable.
- "cta_text": string — Main CTA button text (e.g., "Accede ahora", "Reserva tu lugar").
- "cta_url_placeholder": string — URL placeholder (e.g., "{{cta_link}}").""",
        variants_count=3,
        best_practices=[
            "Subject line under 50 chars, create curiosity",
            "Preview text complements subject line",
            "Single clear CTA per email",
            "Mobile-first design",
            "Personalize when possible",
        ],
    ),
}


def get_channel_spec(key: str) -> ChannelSpec | None:
    """Get a channel spec by key."""
    return CHANNEL_SPECS.get(key)


def get_all_channels() -> list[ChannelSpec]:
    """Return all channel specs."""
    return list(CHANNEL_SPECS.values())
