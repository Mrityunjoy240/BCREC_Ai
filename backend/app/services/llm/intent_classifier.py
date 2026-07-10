"""
Intent Classifier for BCREC Voice Agent

Maps user queries to structured intents using embedding similarity.
Falls back to keyword-based matching when the embedding model is unavailable.

Intents with a structured handler (exact data from canonical KB):
  fee, admission, hostel, principal, contact, hod, cutoff, seats, placement

Intents routed directly to RAG + LLM (natural language understanding):
  departments, scholarship, eligibility, timings, library, safety,
  id_card, bonafide, campus_visit, handoff, help, placement_eligibility

When confidence is below threshold, route to RAG + LLM.
"""

import logging
import re
import time
import numpy as np

logger = logging.getLogger(__name__)

# Threshold for high-confidence intent classification
# Above this → use structured handler (exact data)
# Below this → route to RAG + LLM (natural understanding)
HIGH_CONFIDENCE_THRESHOLD = 0.70

# Reference phrases per intent — each is a list of example queries
# covering English, Hindi, Banglish, and Bengali as appropriate
INTENT_REFERENCES = {
    "fee": [
        "CSE fee",
        "kinta kharcha parega",
        "total fees for ECE",
        "fees structure",
        "semester fee koto",
        "course fee",
        "kitna fee hai",
        "admission fee",
        "tuition fee",
        "fee for IT department",
        "fee kitna he",
        "kitna fee lagega",
        "4 sal ka fee",
        "per year fee",
        "fees bahut hai",
        "fee reasonable hai",
        "fee samanya hai",
    ],
    "admission": [
        "admission process",
        "kivabe admit hobo",
        "how to apply",
        "admission eligibility",
        "apply for btech",
        "admission documents required",
        "kya documents chahiye admission ke liye",
        "admission counseling",
        "WBJEE admission",
        "management quota",
        "spot admission",
        "direct admission",
        "mujhe admission lena hai",
    ],
    "why_bcrec": [
        "why bcrec",
        "why choose bcrec",
        "BCREC kyun join karein",
        "BCREC ke fayde",
        "dusre college se behtar",
        "convince kar do mujhe",
        "mujhe bcrec kyun join karna chahiye",
        "bcrec kyun behtar hai",
        "bcrec kyun accha hai",
        "bcrec ke fayde kya hai",
        "kya acha hai bcrec mein",
        "mughe convinse koro",
        "bcrec se accha college hai",
        "kya khas hai",
        "kya fayda hai",
        "kya acha hai is college mein",
        "why should I take admission",
        "why should I take admission in this college",
        "me idar hi q admission lu",
        "ami akahane keno admission nebo",
        "why admission",
        "kyu admission lu",
        "keno admission nebo",
        "tell me why i should take admission",
        "mujhe yaha kyu admission lena chahiye",
    ],
    "branch_recommendation": [
        "which branch should I choose",
        "kon si branch acchi hai",
        "best branch in bcrec",
        "mujhe konsa branch lena chahiye",
        "mughe kon si branch me admission lena chyea",
        "branch recommendation",
        "kaun si branch choose karu",
        "which branch has best placement",
        "sabse accha branch kaunsa hai",
        "konsa subject choose karu",
        "konsa department choose karun",
        "kon department choose korbo",
        "mujhe branch chuni hai",
        "coding ke liye kaunsa branch",
        "AI ML ke liye kaunsa branch",
    ],
    "hostel": [
        "hostel available",
        "hostel fee",
        "room rent",
        "how to apply for hostel",
        "hostel facilities",
        "boys hostel",
        "girls hostel",
        "mess food",
        "hostel accommodation",
        "hostel application",
        "kya hostel compulsory hai",
        "hostel mandatory",
        "hostel me non veg",
        "hostel food quality",
    ],
    "principal": [
        "principal name",
        "who is principal",
        "principal phone number",
        "principal contact",
        "principal email",
        "principal er number",
        "principal er name ki",
        "princepal name",
        "princepal er name",
        "princepal r vice princepal ar nam ki",
        "principal and vice principal name",
        "principal r vice principal ar nam ki",
        "principal r vice principal name",
        "vice principal name",
        "vice principal er name",
    ],
    "contact": [
        "college phone number",
        "college contact",
        "helpline number",
        "college email",
        "college address",
        "phone number of BCREC",
        "contact the college",
        "office phone",
        "kivabe contact korbo",
        "his contact info number",
        "contact number",
        "phone number mil",
        "contact info",
        "contact number kya hai",
        "contact number ki",
    ],
    "hod": [
        "HOD of CSE",
        "department head",
        "who is HOD",
        "faculty in charge",
        "HOD name",
        "CSE department head",
        "department chairman",
    ],
    "cutoff": [
        "cutoff rank for CSE",
        "WBJEE cutoff",
        "closing rank",
        "cutoff 2025",
        "rank required for admission",
        "kitna rank chahiye",
    ],
    "seats": [
        "seats available",
        "intake capacity",
        "CSE seat count",
        "how many seats",
        "total seats in ECE",
        "kitni seats hain",
    ],
    "placement": [
        "placement rate",
        "placement record",
        "placement statistics",
        "average package",
        "placement company",
        "highest package",
        "CSE placement",
        "placement percentage",
        "koto percent placement",
        "recruiters in BCREC",
        "placement kaisa hai",
        "kitna placement hai",
        "placement bahut accha hai",
        "company list",
        "TCS",
    ],
    "departments": [
        "kon department ache",
        "what departments",
        "courses offered",
        "branches available",
        "B.Tech programs",
        "ki ki department ache",
        "kon kon course ache",
        "what subjects are taught",
        "how many branches",
        "AI ka naam sunne me aa raha hai",
        "trending branch",
        "future branch",
        "branch change",
        "stream change",
        "branch transfer",
    ],
    "scholarship": [
        "scholarship available",
        "scholarship eligibility",
        "financial aid",
        "scholarship for btech",
        "how to get scholarship",
        "scholarship scheme",
        "TFW",
        "education loan",
        "loan facility",
        "kanyashree",
    ],
    "eligibility": [
        "eligible for admission",
        "minimum marks required",
        "eligibility criteria",
        "qualified for btech",
        "percentage required",
        "marks needed",
    ],
    "timings": [
        "college timings",
        "office hours",
        "working hours",
        "college kobe khole",
        "when is college open",
        "college schedule",
        "timing of college",
    ],
    "library": [
        "library timings",
        "library hours",
        "reading room",
        "library book",
        "library e resources",
        "library facilities",
    ],
    "safety": [
        "campus safety",
        "anti ragging",
        "women safety",
        "ragging policy",
        "safety helpline",
        "security on campus",
        "ragging",
        "ladkiyon ke liye safe hai",
    ],
    "id_card": [
        "duplicate id card",
        "identity card replacement",
        "how to get id card",
        "id card application",
        "new ID card",
        "id card process",
    ],
    "bonafide": [
        "bonafide certificate",
        "character certificate",
        "custom certificate",
        "college certificate",
        "certificate application",
        "bonafide process",
        "kivabe bonafide nite hobe",
        "প্রমাণপত্র",
    ],
    "campus_visit": [
        "visit campus",
        "college tour",
        "campus visit appointment",
        "college ghurte chai",
        "can I visit the college",
        "campus kaisa hai",
        "campus facility",
        "sports",
        "cultural activities",
        "canteen",
        "transport",
        "bus facility",
        "medical facility",
        "bank ATM",
        "alumni network",
        "kya kya facilities hai",
    ],
    "help": [
        "help",
        "help lagbe",
        "amake help lagbe",
        "ekta help chai",
        "sahayya chahiye",
        "help me",
        "can you help me",
        "I need help",
        "problem ache",
        "help koro",
    ],
    "handoff": [
        "speak to human",
        "connect to operator",
        "talk to counselor",
        "transfer to reception",
        "real person",
        "call me back",
        "connect me to principal",
        "transfer to accounts",
        "human operator",
    ],
    "establishment": [
        "established year",
        "when was college founded",
        "college established",
        "college history",
        "kobe college ta shuru hoyeche",
        "how old is BCREC",
    ],
    "backlog": [
        "backlog",
        "arrear",
        "fail subject",
        "fail exam",
        "supplementary exam",
        "semester fail",
        "backlog exam",
        "failed in exam",
        "compartment",
        "backlog clear",
        "backlog kivabe clear korbo",
        "fail korle ki hobe",
        "fell in exam",
    ],
}

# Structured handler eligible intents — these have exact data in canonical_kb.json
STRUCTURED_INTENTS = frozenset({
    "fee", "admission", "hostel", "principal", "contact",
    "hod", "cutoff", "seats", "placement", "safety",
    "departments", "scholarship", "eligibility", "timings",
    "library", "campus_visit", "establishment",
    "why_bcrec", "branch_recommendation",
})

# Out-of-domain / unrecognized intents
UNSTRUCTURED_INTENTS = frozenset({
    "id_card", "bonafide", "help", "handoff",
    "placement_eligibility", "backlog",
})

# All known intents
ALL_INTENTS = frozenset(STRUCTURED_INTENTS | UNSTRUCTURED_INTENTS)


class IntentClassifier:
    """Embedding-based intent classifier with keyword fallback.
    Thread-safe after initialization (read-only reference embeddings)."""

    def __init__(self):
        self._reference_embeddings = None
        self._intent_names = []
        self._reference_texts = []
        self._embedder = None
        self._fallback_only = False

    def _get_embedder(self):
        """Lazy-load the embedding model from VectorStoreService singleton.
        Returns None if vector store is unavailable."""
        if self._embedder is not None or self._fallback_only:
            return self._embedder
        try:
            from app.services.vector_store import VectorStoreService
            vs = VectorStoreService()
            if hasattr(vs, "embeddings") and vs.embeddings is not None:
                self._embedder = vs.embeddings
                logger.info("IntentClassifier: using BGE-M3 embeddings from VectorStoreService")
            else:
                self._fallback_only = True
                logger.warning("IntentClassifier: vector store embeddings unavailable, using keyword fallback")
        except Exception as e:
            self._fallback_only = True
            logger.warning(f"IntentClassifier: failed to load embedder: {e}")
        return self._embedder

    def _ensure_reference_embeddings(self):
        """Compute and cache reference embeddings for all intents."""
        if self._reference_embeddings is not None:
            return
        logger.info("IntentClassifier: computing reference embeddings...")
        t0 = time.time()

        self._intent_names = []
        self._reference_texts = []
        for intent, phrases in INTENT_REFERENCES.items():
            for phrase in phrases:
                self._intent_names.append(intent)
                self._reference_texts.append(phrase.lower())

        embedder = self._get_embedder()
        if embedder and not self._fallback_only:
            try:
                embeddings = embedder.embed_documents(self._reference_texts)
                self._reference_embeddings = np.array(embeddings, dtype=np.float32)
                logger.info(
                    f"IntentClassifier: computed {len(self._reference_texts)} reference "
                    f"embeddings in {time.time() - t0:.2f}s"
                )
                return
            except Exception as e:
                logger.warning(f"IntentClassifier: embedding computation failed: {e}")

        self._fallback_only = True
        self._reference_embeddings = None
        logger.info("IntentClassifier: using keyword fallback only")

    def classify(self, query: str) -> tuple[str | None, float]:
        """Classify a user query into an intent.
        Returns (intent_name, confidence), e.g. ("fee", 0.85).
        If confidence is below threshold, intent_name may be None."""
        self._ensure_reference_embeddings()
        q_lower = query.lower().strip()
        if not q_lower:
            return None, 0.0

        if self._fallback_only or self._reference_embeddings is None:
            return self._keyword_classify(query)

        embedder = self._get_embedder()
        if embedder is None:
            return self._keyword_classify(query)

        try:
            query_vec = np.array(embedder.embed_query(q_lower), dtype=np.float32)
            # Normalize query vector
            query_norm = np.linalg.norm(query_vec)
            if query_norm > 0:
                query_vec = query_vec / query_norm

            # Cosine similarity (embeddings are already normalized)
            sims = self._reference_embeddings @ query_vec

            best_idx = int(np.argmax(sims))
            best_intent = self._intent_names[best_idx]
            best_score = float(sims[best_idx])

            logger.debug(
                f"IntentClassifier: '{q_lower[:50]}' -> {best_intent} ({best_score:.3f})"
            )
            return best_intent, best_score

        except Exception as e:
            logger.warning(f"IntentClassifier: embedding classify failed: {e}")
            return self._keyword_classify(query)

    def _keyword_classify(self, query: str) -> tuple[str | None, float]:
        """Fallback keyword-based intent classification.
        Returns (intent, confidence) where confidence is 0-1 based on match ratio."""
        q_lower = query.lower()
        q_words = set(re.sub(r"[^\w\s]", " ", q_lower).split())

        best_intent = None
        best_score = 0.0

        for intent, phrases in INTENT_REFERENCES.items():
            match_count = 0
            total_words = 0
            for phrase in phrases:
                phrase_lower = phrase.lower()
                phrase_words = set(re.sub(r"[^\w\s]", " ", phrase_lower).split())
                total_words += len(phrase_words)
                if phrase_lower in q_lower:
                    match_count += len(phrase_words)
                else:
                    common = q_words & phrase_words
                    match_count += len(common)
            if total_words > 0:
                score = match_count / total_words
                if score > best_score:
                    best_score = score
                    best_intent = intent

        logger.debug(
            f"IntentClassifier (keyword): '{q_lower[:50]}' -> {best_intent} ({best_score:.3f})"
        )
        return best_intent, best_score


# Singleton
_instance = None


def get_intent_classifier() -> IntentClassifier:
    global _instance
    if _instance is None:
        _instance = IntentClassifier()
    return _instance
