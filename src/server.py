#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Apr 19 16:27:37 2025

@author: legalchain
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur MCP pour l'accès à Legifrance
-------------------------------------
Facilite l'accès aux ressources juridiques françaises via l'API Legifrance
en utilisant le protocole Model Context (MCP).

Auteur: Raphaël d'Assignies (dassignies.law)
Date de création: Avril 2025
"""

import os
import json
import logging
import asyncio
from typing import Any, Dict, Optional, List, Sequence
from functools import wraps
from datetime import datetime

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent

from pylegifrance import ApiConfig, LegifranceClient
from pylegifrance.fonds.code import Code
from pylegifrance.fonds.judilibre import JudilibreAPI, JudilibreClient
from pylegifrance.fonds.juri import JuriAPI
from pylegifrance.fonds.loda import Loda
from pylegifrance.models.code.enum import NomCode, TypeChampCode
from pylegifrance.models.juri.search import SearchRequest as JuriSearchRequest
from pylegifrance.models.loda.search import SearchRequest as LodaSearchRequest

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legifrance_mcp")

# Chargement des variables d'environnement
load_dotenv()


def get_legifrance_client() -> LegifranceClient:
    """Construit un client Légifrance authentifié directement via PISTE.

    Lit LEGIFRANCE_CLIENT_ID/LEGIFRANCE_CLIENT_SECRET (et, optionnellement,
    PISTE_ENV pour basculer sandbox/production) depuis l'environnement.
    """
    return LegifranceClient(ApiConfig.from_env())


def get_judilibre_client() -> JudilibreClient:
    """Construit un client Judilibre authentifié via PISTE.

    Réutilise les identifiants PISTE de LEGIFRANCE_CLIENT_ID/SECRET et lit
    en plus JUDILIBRE_KEY_ID (en-tête KeyId requis par Judilibre), qui doit
    être défini avant même de tenter de construire un ApiConfig.
    """
    key_id = os.getenv("JUDILIBRE_KEY_ID")
    if not key_id:
        raise ValueError(
            "La variable d'environnement JUDILIBRE_KEY_ID doit être définie"
        )
    return JudilibreClient(ApiConfig.from_env(), key_id=key_id)


def _resolve_code_name(raw: str) -> NomCode | None:
    """Résout un nom de code saisi par l'appelant vers un membre de NomCode.

    Comparaison insensible à la casse sur la valeur officielle (ex: "code
    civil" -> NomCode.CC). Retourne None si aucun code ne correspond.
    """
    normalized = raw.strip().casefold()
    for member in NomCode:
        if member.value.casefold() == normalized:
            return member
    return None


_CHAMP_TO_TYPE_CHAMP_CODE = {
    "ALL": TypeChampCode.ALL,
    "TITLE": TypeChampCode.TITLE,
    "TABLE": TypeChampCode.TABLE,
    "ARTICLE": TypeChampCode.ARTICLE,
}


async def call_rechercher_code(arguments: dict) -> list[TextContent]:
    """Implémente le tool rechercher_code via pylegifrance.fonds.code.Code."""
    code_name_raw = arguments.get("code_name", "")
    resolved = _resolve_code_name(code_name_raw)
    if resolved is None:
        examples = ", ".join(member.value for member in list(NomCode)[:5])
        message = (
            f"Code juridique inconnu: {code_name_raw!r}. "
            f"Exemples de codes valides: {examples}, ..."
        )
        return [TextContent(type="text", text=message)]

    builder = Code(get_legifrance_client()).search().in_code(resolved).with_formatter()

    search_text = arguments.get("search")
    champ = arguments.get("champ")
    if champ == "NUM_ARTICLE":
        builder = builder.article_number(search_text)
    elif search_text:
        field = _CHAMP_TO_TYPE_CHAMP_CODE.get(champ, TypeChampCode.ALL)
        builder = builder.text(search_text, in_field=field)

    page_size = 100 if arguments.get("fetch_all") else arguments.get("page_size")
    if page_size:
        builder = builder.paginate(page_size=page_size)

    results = builder.execute()

    if not results:
        return [TextContent(type="text", text="Aucun résultat.")]

    parts = []
    for article in results:
        lines = [f"## {article.code_name or ''} — art. {article.number}".strip()]
        if article.title:
            lines.append(f"**Titre**: {article.title}")
        if article.legal_status:
            lines.append(f"**État**: {article.legal_status}")
        if article.url:
            lines.append(f"**URL**: {article.url}")
        lines.append("")
        if article.content:
            lines.append(article.content)
        parts.append("\n".join(lines))

    return [TextContent(type="text", text="\n\n---\n\n".join(parts))]


async def call_rechercher_texte_legal(arguments: dict) -> list[TextContent]:
    """Implémente le tool rechercher_dans_texte_legal via pylegifrance.fonds.loda.Loda."""
    kwargs = {
        key: arguments.get(key)
        for key in ("search", "text_id", "champ", "type_recherche", "page_size")
        if arguments.get(key) is not None
    }
    query = LodaSearchRequest(**kwargs)

    results = Loda(get_legifrance_client()).search(query)

    if not results:
        return [TextContent(type="text", text="Aucun résultat.")]

    parts = [texte.to_markdown() for texte in results]
    return [TextContent(type="text", text="\n\n---\n\n".join(parts))]


# Les noms de paramètres historiques du tool diffèrent des noms de champs
# de pylegifrance.models.juri.search.SearchRequest.
_JURI_ARG_MAP = {
    "search": "search",
    "publication_bulletin": "publication_bulletin",
    "sort": "sort",
    "champ": "field",
    "type_recherche": "search_type",
    "juridiction_judiciaire": "juridiction_judiciaire",
    "page_size": "page_size",
    "fetch_all": "fetch_all",
    "juri_keys": "keys",
}


async def call_rechercher_jurisprudence(arguments: dict) -> list[TextContent]:
    """Implémente le tool rechercher_jurisprudence_judiciaire via pylegifrance.fonds.juri.JuriAPI."""
    kwargs = {
        new_key: arguments[old_key]
        for old_key, new_key in _JURI_ARG_MAP.items()
        if arguments.get(old_key) is not None
    }
    query = JuriSearchRequest(**kwargs)

    results = JuriAPI(get_legifrance_client()).search(query)

    if not results:
        return [TextContent(type="text", text="Aucun résultat.")]

    parts = [decision.to_markdown() for decision in results]
    return [TextContent(type="text", text="\n\n---\n\n".join(parts))]


async def call_rechercher_judilibre(arguments: dict) -> list[TextContent]:
    """Implémente le tool rechercher_jurisprudence_judilibre via pylegifrance.fonds.judilibre.JudilibreAPI."""
    try:
        client = get_judilibre_client()
    except ValueError as e:
        return [TextContent(type="text", text=str(e))]

    kwargs = {
        key: arguments[key]
        for key in ("jurisdiction", "chamber", "date_start", "date_end", "page_size")
        if arguments.get(key) is not None
    }
    results = JudilibreAPI(client).search(arguments.get("search", ""), **kwargs)

    if not results:
        return [TextContent(type="text", text="Aucun résultat.")]

    parts = [decision.to_markdown() for decision in results]
    return [TextContent(type="text", text="\n\n---\n\n".join(parts))]


# Création du serveur MCP
server = Server("legifrance")


def rate_limit(calls: int, period: float):
    """
    Décorateur pour limiter le nombre d'appels API dans une période donnée.
    
    Args:
        calls (int): Nombre maximum d'appels autorisés
        period (float): Période en secondes
    """
    def decorator(func):
        last_reset = datetime.now()
        calls_made = 0

        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal last_reset, calls_made
            now = datetime.now()

            # Réinitialisation du compteur si la période est écoulée
            if (now - last_reset).total_seconds() > period:
                calls_made = 0
                last_reset = now

            # Si la limite est atteinte, attendre la fin de la période
            if calls_made >= calls:
                wait_time = period - (now - last_reset).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    last_reset = datetime.now()
                    calls_made = 0

            calls_made += 1
            return await func(*args, **kwargs)
        return wrapper
    return decorator

@server.list_tools()
async def list_tools() -> List[Tool]:
    """Liste tous les outils disponibles dans ce serveur MCP."""
    return [
        Tool(
            name="rechercher_dans_texte_legal",
            description="""
            Recherche un article dans un texte légal (loi, ordonnance, décret, arrêté)
            par le numéro du texte et le numéro de l'article. On peut également rechercher 
            des mots clés ("mots clés" séparés par des espaces) dans une loi précise (n° de loi)
            
            Paramètres:
                - text_id: Le numéro du texte (format AAAA-NUMERO)
                - search: Mots-clés de recherche ou numéro d'article
                - champ: Champ de recherche ("ALL", "TITLE", "TABLE", "NUM_ARTICLE", "ARTICLE")
                - type_recherche: Type de recherche ("TOUS_LES_MOTS_DANS_UN_CHAMP", "EXPRESSION_EXACTE", "AU_MOINS_UN_MOT")
                - page_size: Nombre de résultats (max 100)
                
            Exemples:
                - Pour l'article 7 de la loi 78-17: {text_id="78-17", search="7", champ="NUM_ARTICLE"}
                - On cherche les conditions de validité de la signature électronique : {search="signature électronique validité conditions"}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "text_id": {"type": "string"},
                    "champ": {"type": "string", "enum": ["ALL", "TITLE", "TABLE", "NUM_ARTICLE", "ARTICLE"]},
                    "type_recherche": {"type": "string", "enum": ["TOUS_LES_MOTS_DANS_UN_CHAMP", "EXPRESSION_EXACTE", "AU_MOINS_UN_MOT"]},
                    "page_size": {"type": "integer", "maximum": 100}
                }
            }
        ),
        Tool(
            name="rechercher_code",
            description="""
            Recherche des articles juridiques dans les codes de loi français.
            
            Paramètres:
                - search: Termes de recherche (ex: "contrat de travail", "légitime défense")
                - code_name: Nom du code juridique (ex: "Code civil", "Code du travail")
                - champ: Champ de recherche ("ALL", "TITLE", "TABLE", "NUM_ARTICLE", "ARTICLE")
                - sort: Tri des résultats ("PERTINENCE", "DATE_ASC", "DATE_DESC")
                - type_recherche: Type de recherche
                - page_size: Nombre de résultats (max 100)
                - fetch_all: Récupérer tous les résultats
                
            Exemples:
                - Pour le PACS dans le Code civil: {search="pacte civil de solidarité", code_name="Code civil"}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "code_name": {"type": "string"},
                    "champ": {"type": "string"},
                    "sort": {"type": "string", "enum": ["PERTINENCE", "DATE_ASC", "DATE_DESC"]},
                    "type_recherche": {"type": "string"},
                    "page_size": {"type": "integer", "maximum": 100},
                    "fetch_all": {"type": "boolean"}
                },
                "required": ["search", "code_name"]
            }
        ),
        Tool(
            name="rechercher_jurisprudence_judiciaire",
            description="""
            Recherche des jurisprudences judiciaires dans la base JURI de Legifrance.
            
            Paramètres:
                - search: Termes ou numéros d'affaires à rechercher
                - publication_bulletin: Si publiée au bulletin ['T'] sinon ['F']
                - sort: Tri des résultats ("PERTINENCE", "DATE_DESC", "DATE_ASC")
                - champ: Champ de recherche ("ALL", "TITLE", "ABSTRATS", "TEXTE", "RESUMES", "NUM_AFFAIRE")
                - type_recherche: Type de recherche
                - page_size: Nombre de résultats (max. 100)
                - fetch_all: Récupérer tous les résultats
                - juri_keys: Mots-clés pour extraire des champs comme 'titre'. Par défaut, le titre, le texte et les résumés sont extraits
                - juridiction_judiciaire: Liste des juridictions à inclure parmi ['Cour de cassation', 'Juridictions d'appel', ]
            
            Exemples : 
                - Obtenir un panorama de la jurisprudence par mots clés : 
                    search = "tierce opposition salarié société liquidation", page_size=100, juri_keys=['titre']
                - Obtenir toutes les jurisprudences sur la signature électronique : 
                    search = "signature électronique", fetch_all=True, juri_keys=['titre', 'sommaire']
                - Obtenir les 20 dernières jurisprudences sur la signature électronique des juridictions d'appel
                 search = "signature électronique", page_size, sort='DATE_DESC', juridiction_judiciaire=['Juridictions d'appel']]
            
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "publication_bulletin": {"type": "array", "items": {"type": "string", "enum": ["T", "F"]}},
                    "sort": {"type": "string", "enum": ["PERTINENCE", "DATE_DESC", "DATE_ASC"]},
                    "champ": {"type": "string"},
                    "type_recherche": {"type": "string"},
                    "page_size": {"type": "integer", "maximum": 100},
                    "fetch_all": {"type": "boolean"},
                    "juri_keys": {"type": "array", "items": {"type": "string"}},
                    "juridiction_judiciaire": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["search"]
            }
        ),
        Tool(
            name="rechercher_jurisprudence_judilibre",
            description="""
            Recherche des décisions de justice via l'API Judilibre (Cour de cassation
            et juridictions du fond), en complément de rechercher_jurisprudence_judiciaire.

            Paramètres:
                - search: Termes de recherche
                - jurisdiction: Juridiction(s) à filtrer
                - chamber: Chambre(s) à filtrer
                - date_start: Date de début (YYYY-MM-DD)
                - date_end: Date de fin (YYYY-MM-DD)
                - page_size: Nombre de résultats (max 100)

            Exemples:
                - Recherche sur le licenciement: {search="licenciement sans cause réelle et sérieuse"}
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "jurisdiction": {"type": "array", "items": {"type": "string"}},
                    "chamber": {"type": "array", "items": {"type": "string"}},
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "page_size": {"type": "integer", "maximum": 100}
                },
                "required": ["search"]
            }
        )
    ]

@server.call_tool()
@rate_limit(calls=5, period=1.0)  # Limite à 5 appels par seconde
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    """
    Gère les appels aux outils juridiques.
    
    Args:
        name (str): Nom de l'outil à appeler
        arguments (Any): Arguments à passer à l'outil
    
    Returns:
        Sequence[TextContent]: Résultat de l'appel
    """
    try:
        logger.info(f"Appel de l'outil: {name} avec arguments: {json.dumps(arguments)}")
        
        if name == "rechercher_dans_texte_legal":
            return await call_rechercher_texte_legal(arguments)

        elif name == "rechercher_code":
            return await call_rechercher_code(arguments)

        elif name == "rechercher_jurisprudence_judiciaire":
            return await call_rechercher_jurisprudence(arguments)

        elif name == "rechercher_jurisprudence_judilibre":
            return await call_rechercher_judilibre(arguments)

        else:
            raise ValueError(f"Outil inconnu: {name}")

    except Exception as e:
        error_message = f"Erreur lors de l'exécution de {name}: {str(e)}"
        logger.error(error_message)
        return [TextContent(type="text", text=error_message)]

@server.list_prompts()
async def list_prompts():
    """Liste tous les prompts disponibles dans ce serveur MCP."""
    from mcp.types import Prompt, PromptArgument
    
    return [
        Prompt(
            name="agent_juridique_expert",
            description="Utilise un agent juridique expert pour répondre à des questions de droit français",
            arguments=[
                PromptArgument(
                    name="question",
                    description="La question juridique",
                    required=True
                )
            ]
        )
    ]

@server.get_prompt()
async def get_prompt(prompt_name: str, inputs: dict) -> Dict:
    """
    Retourne un prompt prédéfini pour une utilisation spécifique.
    
    Args:
        prompt_name (str): Nom du prompt à récupérer
        inputs (dict): Entrées pour le prompt
    
    Returns:
        Dict: Structure du prompt
    """
    if prompt_name == "agent_juridique_expert":
        question = inputs.get("question", "")
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Tu es un agent juridique expert qui cite toujours ses sources dans le corps du texte.\n"
                                "Lorsque tu effectues une recherche et que des références sont citées (article d'un code, numéro de décision de justice), "
                                "tu dois systématiquement utiliser les outils à ta disposition pour aller chercher leur contenu et l'analyser. "
                                "Tu peux utiliser tous les outils disponibles pour rechercher des informations dans les textes de loi français ou la jurisprudence.\n"
                                "Tu dois :\n"
                                "- Expliquer ton raisonnement étape par étape\n"
                                "- Utiliser les outils pertinents\n"
                                "- Fournir une synthèse claire, sourcée, avec des liens vers les articles. "
                                "Tu dois impérativement récupérer les liens officiels et les citer."
                            )
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Voici ma question juridique : {question}"
                        }
                    ]
                }
            ]
        }
    else:
        raise ValueError(f"Prompt inconnu: {prompt_name}")

async def main():
    """Point d'entrée principal du serveur MCP."""
    import mcp.server.stdio
    try:
        logger.info("Démarrage du serveur MCP Legifrance...")
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    except Exception as e:
        logger.error(f"Erreur fatale lors de l'exécution du serveur: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())