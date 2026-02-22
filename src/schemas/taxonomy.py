from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


# ── Taxonomy Definition ──────────────────────────────────────────────────────
# Three-level hierarchy: L1 Intent → L2 Driver → L3 Execution
# Used by the Tagger to classify ad creative content.

L1_TAGS = [
    "Awareness",
    "Consideration",
    "Conversion",
    "Retention",
    "Advocacy",
]

L2_TAGS = [
    # Awareness drivers
    "Brand Story",
    "Problem Agitation",
    # Consideration drivers
    "Social Proof",
    "Feature Highlight",
    "Comparison",
    # Conversion drivers
    "Urgency / Scarcity",
    "Offer / Discount",
    "Risk Reversal",
    # Retention drivers
    "Community",
    "Loyalty Reward",
]

L3_TAGS = [
    # Storytelling formats
    "Founder Story",
    "Customer Testimonial",
    "Before / After",
    "Case Study",
    # Problem-aware formats
    "Pain Point Call-Out",
    "Fear of Missing Out",
    "Negative Consequence",
    # Trust builders
    "Stats & Numbers",
    "Celebrity / Influencer",
    "User Generated Content",
    "Media Mention",
    # Feature-focused
    "Demo / How-It-Works",
    "Benefit List",
    # Conversion triggers
    "Limited Time Offer",
    "Free Trial / Sample",
    "Money-Back Guarantee",
    "Bundle Deal",
    # Retention / community
    "Community Spotlight",
    "Milestone Celebration",
    "Exclusive Member Perk",
    # Visual / creative style
    "Animated / Motion",
    "Minimalist",
    "Bold Typography",
    "Lifestyle / Aspirational",
    "Educational / Tutorial",
    "Meme / Humor",
    "User Poll / Interactive",
    "Countdown Timer",
    "Product Close-Up",
    "Unboxing",
]

ALL_TAGS: List[str] = L1_TAGS + L2_TAGS + L3_TAGS

# Richer phrases used when encoding tag centroids.
# Single-word / short labels embed poorly against full ad copy;
# these descriptions give the model enough semantic context.
TAG_DESCRIPTIONS: dict[str, str] = {
    # L1
    "Awareness": "brand awareness, introducing product to new audience, reach campaign, first-time exposure",
    "Consideration": "consideration phase, product research, comparison, audience evaluating options, learn more",
    "Conversion": "conversion, driving purchase, buy now, sign up today, checkout, sales, limited time offer",
    "Retention": "customer retention, keeping existing customers, loyalty, repeat purchase, re-engagement",
    "Advocacy": "brand advocacy, referrals, word of mouth, community champions, ambassadors, share with friends",
    # L2
    "Brand Story": "brand origin story, founder journey, company mission, why we exist, our values",
    "Problem Agitation": "problem agitation, pain point, frustration, what is not working, the real issue you face",
    "Social Proof": "social proof, customer testimonials, reviews, five star ratings, what customers say, results",
    "Feature Highlight": "product feature highlight, what it does, how it works, key capabilities, functionality showcase",
    "Comparison": "competitor comparison, versus, better than others, unlike alternatives, switching, different approach",
    "Urgency / Scarcity": "urgency scarcity, limited time, limited spots, act now, offer expires, last chance, ending soon",
    "Offer / Discount": "special offer, discount, sale price, percentage off, deal, coupon, save money today",
    "Risk Reversal": "risk reversal, money back guarantee, free trial, no risk, satisfaction guaranteed, try it free",
    "Community": "community, belonging, join others, tribe, group of like-minded people, together we",
    "Loyalty Reward": "loyalty reward, exclusive member benefit, VIP access, thank you for being a customer, members only",
    # L3
    "Founder Story": "founder started the company, personal journey, origin of the business, I built this because",
    "Customer Testimonial": "customer testimonial, success story, client results achieved, happy customer review",
    "Before / After": "before and after transformation, dramatic results comparison, progress photo, look at the change",
    "Case Study": "detailed case study, specific results achieved, step-by-step success story, client win",
    "Pain Point Call-Out": "calling out specific pain, you are frustrated with, struggling with this problem, feel this way",
    "Fear of Missing Out": "fear of missing out, FOMO, everyone is doing it, do not get left behind, join thousands",
    "Negative Consequence": "negative consequence, what happens if you do not act, warning, risk of inaction, the cost of waiting",
    "Stats & Numbers": "statistics, numbers, data proof, percentage improvement, measurable results, 10000 customers",
    "Celebrity / Influencer": "celebrity endorsement, influencer recommendation, as seen on, famous person uses this",
    "User Generated Content": "user generated content, real customer photo, authentic review, community post, real people",
    "Media Mention": "media mention, press coverage, as featured in, news coverage, award, recognized by",
    "Demo / How-It-Works": "product demo, how it works, walkthrough, tutorial, step by step explanation, watch it work",
    "Benefit List": "list of benefits, key advantages, bullet points, what you get, everything included",
    "Limited Time Offer": "limited time offer, sale ends tonight, 24 hours only, flash sale, today only, expires soon",
    "Free Trial / Sample": "free trial, free sample, try before you buy, no credit card required, risk free start",
    "Money-Back Guarantee": "money back guarantee, 30 day refund, satisfaction guaranteed, no questions asked refund",
    "Bundle Deal": "bundle deal, combo offer, save more with bundle, package deal, buy together and save",
    "Community Spotlight": "community member spotlight, customer highlight, member of the month, community success story",
    "Milestone Celebration": "milestone celebration, company anniversary, customer milestone, achievement unlocked",
    "Exclusive Member Perk": "exclusive member perk, VIP benefit, members only, subscriber exclusive, only for you",
    "Animated / Motion": "animated ad, motion graphics, video animation, moving elements, dynamic visual",
    "Minimalist": "minimalist design, clean simple layout, white space, less is more aesthetic, stripped back",
    "Bold Typography": "bold typography, large text statement, typographic design, text-focused visual, big words",
    "Lifestyle / Aspirational": "lifestyle photography, aspirational imagery, dream life, aesthetic living, you could have this",
    "Educational / Tutorial": "educational content, how to do it, tutorial, learn this skill, step by step guide, tips",
    "Meme / Humor": "meme format, humor, funny relatable, joke, viral content, laughs",
    "User Poll / Interactive": "poll, question to audience, interactive post, would you rather, vote now, tell us",
    "Countdown Timer": "countdown timer, time running out, urgency clock, expires in, hurry before it ends",
    "Product Close-Up": "product close-up photo, detail shot, macro photography, product showcase, see every detail",
    "Unboxing": "unboxing experience, opening the package, first impression, unbox reveal, what is inside",
}


# ── Result Models ────────────────────────────────────────────────────────────

class TagScore(BaseModel):
    """A single tag with its similarity confidence score."""
    tag: str
    score: float = Field(ge=0.0, le=1.0)


class TaxonomyTags(BaseModel):
    """Full classification output for one piece of ad content."""
    l1_intent: Optional[TagScore] = None
    l2_driver: Optional[TagScore] = None
    l3_execution: List[TagScore] = Field(default_factory=list)
    # Raw scores for every tag (useful for debugging / downstream reranking)
    all_scores: List[TagScore] = Field(default_factory=list)
    # Confidence threshold used during classification
    threshold: float = 0.0
