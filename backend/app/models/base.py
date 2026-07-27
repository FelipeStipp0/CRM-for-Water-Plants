"""
Documento multi-tenant: a mesma classe atende várias orgs no mesmo processo.

O problema que isto resolve
---------------------------
`init_beanie` guarda a coleção do Mongo em `cls._document_settings`, que é
estado **de classe**. Com um processo servindo várias orgs, a última org
inicializada passava a valer para todas: um usuário da junta A lia os dados da
junta B. O `ContextVar` com o slug do request existia, mas nada ligava a query
a ele.

Como funciona agora
-------------------
Tudo que é ligado ao banco no Beanie passa por `cls.get_settings()`
(`get_pymongo_collection`, `get_collection_name`, `get_bson_encoders`). Então
guardamos um `DocumentSettings` **por org** e resolvemos qual usar na hora da
query, pelo slug do request. Nenhuma query precisa saber disso.

`registrar_settings_da_org()` é chamado pelo `database.ensure_org_db()` logo
depois do `init_beanie` de cada org, quando `_document_settings` ainda aponta
para aquela org.

Ordem de resolução em `get_settings()`:
  1. settings registrados para o slug do request  → caminho normal;
  2. `_document_settings` cru                     → org em inicialização,
     scripts e testes de org única (sem ContextVar).
"""

from typing import ClassVar, Dict, Optional, Type

from beanie import Document
from beanie.odm.settings.document import DocumentSettings


# {classe do modelo: {slug: settings daquela org}}
_SETTINGS_POR_ORG: Dict[type, Dict[str, DocumentSettings]] = {}


class OrgDocument(Document):
    """Base de todo documento que vive DENTRO do banco de uma org (`wmapp_{slug}`).

    Documentos do `wmapp_admin` (ex.: `Organization`) continuam com `Document`
    puro — são de um banco só e não passam por este roteamento.
    """

    _document_settings: ClassVar[Optional[DocumentSettings]] = None

    @classmethod
    def get_settings(cls) -> DocumentSettings:
        from app.middleware.org_context import get_org_slug

        slug = get_org_slug()
        if slug:
            por_slug = _SETTINGS_POR_ORG.get(cls)
            if por_slug is not None:
                settings = por_slug.get(slug)
                if settings is not None:
                    return settings
        return super().get_settings()


def registrar_settings_da_org(slug: str, models: list) -> None:
    """
    Congela, para `slug`, os settings que o `init_beanie` acabou de montar.

    Cada `init_beanie` cria um `DocumentSettings` novo por classe, então o
    objeto guardado aqui não é mexido pelas inicializações seguintes.
    """
    for model in models:
        if not (isinstance(model, type) and issubclass(model, OrgDocument)):
            continue
        settings = model.__dict__.get("_document_settings")
        if settings is None:
            continue
        _SETTINGS_POR_ORG.setdefault(model, {})[slug] = settings


def orgs_registradas(model: Type[OrgDocument]) -> list:
    """Slugs com settings registrados para um modelo (diagnóstico/testes)."""
    return sorted(_SETTINGS_POR_ORG.get(model, {}))


def limpar_registro() -> None:
    """Esquece o roteamento por org (usado por testes)."""
    _SETTINGS_POR_ORG.clear()
