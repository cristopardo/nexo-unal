import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

STOPWORDS = set(
    "a al algo alguna algunas alguno algunos ante bajo como con cual cuales cuando de del "
    "desde donde el ella ellas ellos en entre era es esa esas ese esos esta estas este esto "
    "estos ha hasta hay la las le les lo los me mi mis mucho muy o para pero por porque que "
    "quiero se ser si sin sobre son su sus tengo tiene toda todas todo todos tu tus un una "
    "unas unos y ya yo hacer hago puedo necesito saber favor hola buenos dias tardes noches "
    "universidad nacional unal colombia".split()
)
ALIASES = {
    "solicito": "solicitud",
    "solicitar": "solicitud",
    "solicitudes": "solicitud",
    "cancelo": "cancelar",
    "cancela": "cancelar",
    "cancelacion": "cancelar",
    "renuevo": "renovar",
    "renueva": "renovar",
    "renovacion": "renovar",
    "inscribo": "inscripcion",
    "inscribirme": "inscripcion",
    "inscribir": "inscripcion",
    "psicologica": "psicologia",
    "psicologico": "psicologia",
}
DISTINCTIVE = {
    "bienestar",
    "biblioteca",
    "sia",
    "sinsu",
    "psicologia",
    "computacion",
    "pensum",
    "malla",
    "matricula",
    "certificado",
}
FALLBACK = (
    "Aún no tengo una fuente verificada para responder esa consulta. "
    "Puedo orientarte sobre Ciencias de la Computación, trámites académicos, bienestar y "
    "bibliotecas. Consulta el directorio de la UNAL para contactar la dependencia responsable."
)


def normalize(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c)
    )


OTHER_CAMPUSES = (
    "medellin",
    "manizales",
    "palmira",
    "amazonia",
    "orinoquia",
    "caribe",
    "tumaco",
    "la paz",
    "leticia",
    "arauca",
    "san andres",
)
CAMPUS_FALLBACK = (
    "Actualmente mi catálogo verificado cubre la Sede Bogotá. Aún no tengo fuentes "
    "verificadas para otras sedes; confirma el trámite en los canales oficiales de tu sede."
)


def unsupported_campus(question: str) -> bool:
    value = normalize(question)
    return any(
        re.search(r"\b" + re.escape(campus) + r"\b", value) for campus in OTHER_CAMPUSES
    ) or bool(re.search(r"\b(otra sede|otras sedes|todas las sedes|fuera de bogota)\b", value))


def fallback_for(question: str) -> str:
    return CAMPUS_FALLBACK if unsupported_campus(question) else FALLBACK


def tokens(value: str) -> set[str]:
    result = set()
    for word in re.findall(r"[a-z0-9]+", normalize(value)):
        if len(word) <= 2 or word in STOPWORDS:
            continue
        word = ALIASES.get(word, word)
        # Match common Spanish singular/plural forms without a language-model call.
        if len(word) > 4 and word.endswith("s"):
            word = word[:-1]
        result.add(word)
    return result


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    url: str
    category: str
    keywords: list[str]
    content: str
    reviewed_at: str

    def public(self):
        return {"title": self.title, "url": self.url}


class KnowledgeBase:
    def __init__(self, path: str):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("sources", [])
        self.sources = [Source(**item) for item in raw]
        if not self.sources:
            raise ValueError("Knowledge catalogue must contain at least one source")
        for source in self.sources:
            url = urlparse(source.url)
            if url.scheme != "https" or not (
                url.hostname == "unal.edu.co" or (url.hostname or "").endswith(".unal.edu.co")
            ):
                raise ValueError("Knowledge catalogue requires HTTPS official UNAL URLs")

    def search(self, question: str) -> list[Source]:
        query = tokens(question)
        if unsupported_campus(question) or not query:
            return []
        ranked = []
        for source in self.sources:
            keywords = " ".join(source.keywords)
            title_terms = tokens(source.title + " " + keywords)
            all_terms = title_terms | tokens(source.content)
            matches = query & all_terms
            score = 2 * len(query & title_terms) + len(matches)
            # A single broad word in a long question should not invent confidence.
            if score >= 3 and (len(matches) >= 2 or len(query) == 1 or bool(matches & DISTINCTIVE)):
                ranked.append((score, source))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if not ranked:
            return []
        best = ranked[0][0]
        return [source for score, source in ranked if score >= best * 0.65][:3]

    @staticmethod
    def extract(sources: list[Source]) -> str:
        return "\n\n".join(f"{source.title}: {source.content}" for source in sources)
