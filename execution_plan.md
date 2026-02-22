# EXECUTION PLAN: Meta Ops Agent

## A) Roadmap Macro (Hito a Hito)

| Checkpoint | Objetivo Funcional Usable | Dependencias | Tareas Atómicas | Outputs (Artefactos) | DoD (Medible) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CP0** | Persistencia Vectorial Failsafe | Ninguna | Setup Docker, ChromaDB Init, Persistence Test | `docker-compose.yml`, `db_client.py` | CRUD vectorial exitoso tras reinicio de container |
| **CP1** | BrandMap Engine v2 | CP0 | Schema Pydantic, LLM Mapping, Versioning Logic | `schemas/brand_map.py`, `engines/brand_map.py` | JSON v2 generado cumple 100% el schema |
| **CP2** | Angle Tagging Automático | CP1 | Taxonomy Specs, Embedding Comparison, Fallback UI | `specs/taxonomy.md`, `engines/tagger.py` | >90% accuracy en dataset de prueba (50 ads) |
| **CP3** | Creative Scoring (Predictor) | CP2 | Heuristic Model, LLM Scoring, Correlation Test | `engines/scoring.py`, `evals/historical_correl.py` | Correlación >0.6 con CTR real histórico |
| **CP4** | Saturation Engine (Math) | CP3 | Normalize Helpers, Formula Impl, Report Gen | `engines/saturation.py`, `utils/math_helpers.py` | Reporte genera Score 0-100 sin errores de escala |
| **CP5** | Policy Engine (Guardrails) | CP4 | Rule Registry, Lock System, Violation Logic | `core/policy_engine.py`, `core/rules.py` | 100% de violaciones inyectadas son bloqueadas |
| **CP6** | Creative Factory | CP5 | Opportunity Mapping, Prompt Factory, Asset Gen | `engines/factory.py`, `prompts/dna_visual.py` | 5 guiones generados alineados a BrandMap |
| **CP7** | Operator (Meta API) | CP6 | SDK Wrapper, OAuth2, Action Execution | `adapters/meta_api.py`, `core/operator.py` | Acción exitosa en Sandbox con Trace completo |

---

## B) Checklist Micro por Checkpoint

### CP0 — Vector Layer (Failsafe Storage)
1. **Alcance**: Setup de base de datos vectorial local con persistencia y backups.
2. **Interfaces**: `VectorDBClient.upsert(id, vector, metadata)`, `VectorDBClient.query(vector, k)`.
3. **Estructura**: `src/database/vector/`.
4. **Datos Mínimos**: 100 vectores de prueba (random) + metadatos.
5. **Steps Implementation**:
   - [ ] Configurar `docker-compose` con ChromaDB.
   - [ ] Implementar `Singleton` para cliente de DB.
   - [ ] Programar script de backup (`tar.gz` a `/backups`).
6. **Tests**: Test de persistencia (write -> kill container -> restart -> read).
7. **Logs**: `DB_CONNECTION_SUCCESS`, `STORAGE_PERSISTENCE_VERIFIED`.
8. **Checklist Aprobación Humana**:
   - [ ] ¿El container de ChromaDB reinicia automáticamente?
   - [ ] ¿El volumen de datos es visible en el host?
   - [ ] ¿Existe el script de backup manual?
   - [ ] ¿La latencia de lectura es < 50ms para 100 vectores?
   - [ ] ¿El cliente maneja errores de conexión sin caerse?

### CP1 — BrandMap Builder (The Strategy Core)
1. **Alcance**: Transformación de inputs desestructurados en objeto de estrategia BrandMap v2.
2. **Interfaces**: `BrandMapBuilder.build(raw_data) -> BrandMapJSON`.
3. **Estructura**: `src/engines/brand_map/`.
4. **Datos Mínimos**: Un PDF de branding real + 5 URLs de competencia.
5. **Steps Implementation**:
   - [ ] Definir Pydantic Models según Schema CP5 (Final Plan).
   - [ ] Implementar prompt de "Architect Analysis" para LLM.
   - [ ] Crear sistema de hashing para versionado (`hashlib.sha256`).
6. **Tests**: Validación de schema sobre 5 generaciones distintas.
7. **Logs**: `BRANDMAP_GEN_STARTED`, `BRANDMAP_VERSION_HASH`.
8. **Checklist Aprobación Humana**:
   - [ ] ¿El JSON refleja fielmente el tono de voz de la marca?
   - [ ] ¿Se identifican correctamente los "Pains" de la audiencia?
   - [ ] ¿El versionado cambia cuando el input cambia?
   - [ ] ¿El objecto es "Statically Typed"?
   - [ ] ¿Maneja correctamente inputs contradictorios?

### CP2 — Angle Tagging (Classification)
1. **Alcance**: Clasificación jerárquica de anuncios en la taxonomía L1/L2/L3.
2. **Interfaces**: `Tagger.classify(ad_content) -> TaxonomyTags`.
3. **Estructura**: `src/engines/tagger/`.
4. **Datos Mínimos**: 50 copies de anuncios de Facebook Ads Library.
5. **Steps Implementation**:
   - [ ] Insertar centroides de taxonomía en CP0.
   - [ ] Implementar búsqueda semántica para asignación de tags.
   - [ ] Crear mecanismo de "Confidence Score" basado en distancia coseno.
6. **Tests**: F1-Score sobre dataset etiquetado manualmente.
7. **Checklist Aprobación Humana**:
   - [ ] ¿Los tags L1 (Intent) son precisos?
   - [ ] ¿El fallback manual se activa si el score es bajo?
   - [ ] ¿Se pueden agregar nuevos tags sin romper el sistema?
   - [ ] ¿El tagger ignora ruido visual (emojis, etc)?
   - [ ] ¿La clasificación toma < 2 segundos?

### CP3 — Creative Scoring (The Predictor)
1. **Alcance**: Evaluar la probabilidad de éxito de un creativo contra el BrandMap.
2. **Interfaces**: `Scorer.evaluate(asset, brand_map) -> EvaluationScore`.
3. **Estructura**: `src/engines/scoring/`.
4. **Steps Implementation**:
   - [ ] Definir rúbrica de evaluación (Hook, Clarity, etc).
   - [ ] Implementar LLM Scoring con Chain-of-Thought.
   - [ ] Normalizar score final a 0-10.
5. **Checklist Aprobación Humana**:
   - [ ] ¿El razonamiento (Reasoning) del score es lógico?
   - [ ] ¿Los anuncios ganadores históricos reciben scores altos?
   - [ ] ¿Detecta falta de alineación con el BrandMap?
   - [ ] ¿El output es puramente estructurado (sin charla)?
   - [ ] ¿Es capaz de procesar imágenes y texto?

### CP4 — Saturation Engine (The Efficiency Guard)
1. **Alcance**: Cálculo matemático de fatiga y saturación de ángulos.
2. **Interfaces**: `SaturationEngine.analyze(meta_stats) -> SaturationReport`.
3. **Steps Implementation**:
   - [ ] Implementar fórmulas de CP5 (Architect Correction Pass).
   - [ ] Crear pipeline de normalización de datos.
   - [ ] Generar OpportunityMap (ángulos no saturados).
4. **Checklist Aprobación Humana**:
   - [ ] ¿El SaturationScore es consistente con la realidad (CTR bajo)?
   - [ ] ¿El Heatmap visual (mock) es intuitivo?
   - [ ] ¿Identifica correctamente "Emerging Angles"?
   - [ ] ¿El CPM Inflation se calcula correctamente?
   - [ ] ¿El reporte es exportable a CSV/JSON?

### CP5 — Policy Engine (The Failsafe)
1. **Alcance**: Motor de validación pre-ejecución con reglas de seguridad.
2. **Interfaces**: `PolicyEngine.validate(action_request) -> ValidationResult`.
3. **Steps Implementation**:
   - [ ] Implementar registro de reglas (Rules Registry).
   - [ ] Crear sistema de estados (Locks) en Redis/DB.
   - [ ] Implementar validación de Cooldown.
4. **Checklist Aprobación Humana**:
   - [ ] ¿Bloquea cambios de presupuesto del 50%?
   - [ ] ¿Respeta el cooldown de 24 horas?
   - [ ] ¿El log de violación es claro y accionable?
   - [ ] ¿El sistema de Lock funciona en entornos multi-thread?
   - [ ] ¿Es fácil agregar una nueva regla de negocio?

### CP6 — Creative Factory (The Generator)
1. **Alcance**: Generación de nuevos activos basados en el OpportunityMap y BrandMap.
2. **Interfaces**: `Factory.generate_scripts(opportunity_map) -> List[Script]`.
3. **Checklist Aprobación Humana**:
   - [ ] ¿Los guiones tienen el CTA correcto?
   - [ ] ¿El Hook usa el "Unfair Advantage" del BrandMap?
   - [ ] ¿La estructura sigue el modelo AIDA/PAS?
   - [ ] ¿Se generan múltiples variaciones para testing?
   - [ ] ¿El DNA Visual se respeta en los briefs?

### CP7 — Operator (The Executor)
1. **Alcance**: Integración final con Meta API para ejecución controlada.
2. **Interfaces**: `Operator.execute(decision_pack) -> ExecutionLog`.
3. **Checklist Aprobación Humana**:
   - [ ] ¿La conexión con Meta API es estable?
   - [ ] ¿Se registra cada cambio en DecisionMemory?
   - [ ] ¿El Kill Switch global funciona instantáneamente?
   - [ ] ¿El Rollback system restaura el estado previo?
   - [ ] ¿Se envían notificaciones tras ejecución exitosa?

---

## C) Definition of Ready (DoR) Global

Antes de iniciar **CP0**, se debe cumplir:
1.  **Repo Init**: Carpeta `meta-ops-agent` creada con estructura base.
2.  **Env Setup**: Archivo `.env` con `OPENAI_API_KEY`, `PYTHONPATH` y `LOG_LEVEL=INFO`.
3.  **Requirements**: `requirements.txt` con FastAPI, LangChain, ChromaDB, Pydantic v2 y Python-dotenv.
4.  **Meta Sandbox**: Credenciales de Meta App (Test Mode) obtenidas.
5.  **Data Seed**: Dataset mínimo de 10 ejemplos de anuncios y 1 documento de marca listo.
6.  **Traceability Setup**: Utilidad de generación de `trace_id` universal lista.

---

## D) Política de Cambios (Causalidad Meta)

Para proteger el aprendizaje algorítmico y la estabilidad de la cuenta:
1.  **Límite de cambios**: Máximo **1 cambio estructural** (presupuesto, puja, creativo) por AdSet en un periodo de **24 horas**.
2.  **Protección de Learning Phase**: Prohibido tocar AdSets en estado `LEARNING` a menos que el CPA sea > 3x Target.
3.  **Cooldown Period**: Tras un cambio del Operador, la entidad entra en `LOCK_MODE` por 24h.
4.  **No Edición Directa**: Nunca editar un anuncio activo. Siempre duplicar, editar y pausar el anterior (preservar ID histórico).
5.  **Budget Delta**: Cambios de presupuesto limitados a **+/- 20%** por iteración.

---

## E) Políticas Transversales (Mandatory)

### 1. Global Traceability
- Todos los logs, registros de decisión, outputs de módulos y eventos de ejecución DEBEN incluir un campo `trace_id`.
- El `trace_id` debe generarse en el punto de entrada (API o Trigger) y propagarse a través de todos los módulos.

### 2. Dataset Versioning
- Estructura de archivos obligatoria:
  ```
  datasets/
    v1/
    v2/
  ```
- Todos los tests y procesos de entrenamiento/evaluación deben referenciar explícitamente la versión del dataset.

### 3. LLM Failsafe Policy
- **Timeout**: 15 segundos máximo por llamada.
- **Retries**: 2 reintentos con backoff exponencial.
- **Fallback Mode**: Si falla el LLM tras reintentos o timeout, se activa el `heuristic_engine` (reglas estáticas basadas en datos previos).
- Ningún módulo puede bloquear el pipeline si falla el LLM.

---
**Justificación del Arquitecto:**
Este plan incremental permite que el sistema empiece a dar valor desde el **CP1**. La inclusión de **Global Traceability** y el **LLM Failsafe** garantiza que el sistema sea auditable y resiliente en producción.

