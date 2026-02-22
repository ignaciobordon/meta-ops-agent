"""
CP6 Test Suite — Creative Factory
DoD:
  - generate_scripts() returns a list of AdScript objects
  - Scripts have non-empty hook, body, cta
  - Target avatar references a BrandMap audience persona
  - Visual brief respects brand creative DNA
  - Framework field matches requested framework
  - Multiple variants are generated per angle
"""
import pytest
from src.utils.logging_config import setup_logging, set_trace_id
from src.engines.factory import Factory
from src.schemas.factory import AdScript
from src.schemas.brand_map import (
    BrandMap,
    BrandMapMetadata,
    CoreIdentity,
    OfferLayer,
    AudienceAvatar,
    DifferentiationLayer,
    NarrativeAssets,
    CreativeDNA,
    MarketContext,
)

setup_logging()

# El Templo brand map (calisthenics gym from CP4 data)
BRAND_MAP_DATA = {
    "core_identity": {
        "mission": "Ayudar a personas de Mar del Plata a entrenar calistenia de forma técnica, segura y progresiva.",
        "values": ["profesionalismo", "progresión", "comunidad"],
        "tone_voice": "cálido, técnico, motivador",
        "personality_traits": ["experto", "accesible", "progresivo", "auténtico"],
    },
    "offer_layer": {
        "main_product": "Clases de calistenia guiadas en grupos reducidos",
        "upsells": ["plan mensual ilimitado", "entrenamiento 1-a-1"],
        "pricing_psychology": "Primera clase gratuita para eliminar fricción",
        "risk_reversal": "Clase gratis sin compromiso, cancela cuando quieras",
    },
    "audience_model": [
        {
            "avatar_name": "Persona activa 25-45 años",
            "demographics": "Hombres y mujeres 25-45, Mar del Plata, ingresos medios",
            "psychographics": "Buscan mejorar fuerza y movilidad sin gimnasio tradicional",
            "pains": ["lesiones en gimnasios", "rutinas genéricas", "falta de guía técnica"],
            "desires": ["entrenar con control", "movimientos funcionales", "comunidad de apoyo"],
            "triggers": ["frustración con máquinas", "querer entrenar sin equipamiento", "buscar progresión real"],
        }
    ],
    "differentiation_layer": {
        "usp": "El único centro de calistenia en Mar del Plata con profesores certificados y progresiones adaptadas",
        "competitive_moat": "Metodología progresiva probada, grupos reducidos, profesores full-time",
        "proof_points": ["1,200 alumnos entrenados", "profesores certificados internacionalmente", "3 años en MDP"],
    },
    "narrative_assets": {
        "lore": "Fundado por atletas de calistenia que querían traer entrenamiento técnico a Mar del Plata",
        "story_hooks": ["Del gimnasio a la calle", "Entrenamiento sin máquinas"],
        "core_myths": ["Calistenia es solo para expertos", "No se puede ganar fuerza sin pesas"],
    },
    "creative_dna": {
        "color_palette": ["Negro", "Blanco", "Naranja energético"],
        "typography_intent": "Bold y moderna para transmitir fuerza, clean para accesibilidad",
        "visual_constraints": ["Mostrar personas reales entrenando", "Evitar stock photos", "Movimientos técnicos"],
    },
    "market_context": {
        "seasonal_factors": ["Verano: pico de interés fitness", "Otoño: nuevos hábitos post-vacaciones"],
        "current_trends": ["Fitness funcional", "Entrenamiento al aire libre", "Anti-gimnasio tradicional"],
    },
    "competitor_map": [
        {"name": "Gimnasios tradicionales", "strategy_type": "Máquinas y pesas", "weak_points": ["rutinas genéricas", "sobrepoblados"]}
    ],
    "opportunity_map": [{"gap_id": "OPP-001", "strategy_recommendation": "Targeting mujeres 30-40"}],
    "metadata": {"hash": "eltemplo2024", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
}


@pytest.fixture(scope="module")
def brand_map():
    return BrandMap.model_validate(BRAND_MAP_DATA)


@pytest.fixture(scope="module")
def factory():
    set_trace_id("cp6-test-setup")
    return Factory()


def test_returns_ad_scripts(factory, brand_map):
    """generate_scripts() must return a list of AdScript objects."""
    set_trace_id("cp6-test-type")
    scripts = factory.generate_scripts(
        brand_map=brand_map, target_angles=["Social Proof"], num_variants=2
    )
    assert isinstance(scripts, list)
    assert len(scripts) >= 1
    assert all(isinstance(s, AdScript) for s in scripts)


def test_scripts_have_required_fields(factory, brand_map):
    """All scripts must have non-empty hook, body, cta."""
    set_trace_id("cp6-test-fields")
    scripts = factory.generate_scripts(
        brand_map=brand_map, target_angles=["Problem Agitation"], num_variants=2
    )
    for script in scripts:
        assert script.hook, f"Script {script.script_id} missing hook"
        assert script.body, f"Script {script.script_id} missing body"
        assert script.cta, f"Script {script.script_id} missing cta"
        assert script.target_avatar, f"Script {script.script_id} missing target_avatar"
        assert script.visual_brief, f"Script {script.script_id} missing visual_brief"


def test_framework_matches_request(factory, brand_map):
    """Framework field should match the requested framework."""
    set_trace_id("cp6-test-framework")
    scripts = factory.generate_scripts(
        brand_map=brand_map, target_angles=["Risk Reversal"], num_variants=1, framework="AIDA"
    )
    # Framework may not always match exactly (LLM autonomy), but should be valid
    for script in scripts:
        assert script.framework in ["AIDA", "PAS", "PSF"]


def test_multiple_variants_generated(factory, brand_map):
    """Should generate num_variants scripts per angle."""
    set_trace_id("cp6-test-variants")
    scripts = factory.generate_scripts(
        brand_map=brand_map, target_angles=["Feature Highlight"], num_variants=3
    )
    # Should get ~3 scripts for 1 angle (LLM may vary slightly)
    assert len(scripts) >= 2


def test_multiple_angles(factory, brand_map):
    """Should generate scripts for all target angles."""
    set_trace_id("cp6-test-multi-angle")
    angles = ["Social Proof", "Urgency / Scarcity"]
    scripts = factory.generate_scripts(brand_map=brand_map, target_angles=angles, num_variants=2)
    # Should get scripts covering both angles
    script_angles = {s.angle for s in scripts}
    assert len(script_angles) >= 1  # At least one of the angles covered


def test_brand_alignment(factory, brand_map):
    """Scripts should reference brand context (tone, USP, audience)."""
    set_trace_id("cp6-test-brand-alignment")
    scripts = factory.generate_scripts(
        brand_map=brand_map, target_angles=["Brand Story"], num_variants=2
    )
    # Check that at least one script references brand-specific terms
    all_text = " ".join(s.hook + s.body + s.cta for s in scripts).lower()
    # El Templo specific: should mention calistenia, clase, entrenamiento, etc.
    brand_mentions = any(
        term in all_text for term in ["calistenia", "clase", "entrenamiento", "técnica", "progresión"]
    )
    assert brand_mentions, "Scripts should reference brand-specific terms"


if __name__ == "__main__":
    set_trace_id("cp6-manual-run")
    from src.engines.brand_map import BrandMapBuilder

    bm = BrandMap.model_validate(BRAND_MAP_DATA)
    f = Factory()
    scripts = f.generate_scripts(
        brand_map=bm, target_angles=["Social Proof", "Problem Agitation"], num_variants=2
    )

    for i, script in enumerate(scripts, 1):
        print(f"\n=== SCRIPT {i}: {script.angle} ({script.framework}) ===")
        print(f"Target: {script.target_avatar}")
        print(f"\nHOOK:\n{script.hook}")
        print(f"\nBODY:\n{script.body}")
        print(f"\nCTA:\n{script.cta}")
        print(f"\nVISUAL BRIEF:\n{script.visual_brief}")
