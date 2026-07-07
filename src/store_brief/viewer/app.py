"""Parse result viewer — FastAPI local web app."""
from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from store_brief.viewer.loader import ParseViewerLoader
from store_brief.kg.export import cards_by_product, cards_for_post
from store_brief.kg.load import default_graph_path, load_knowledge_graph
from store_brief.kg.viz import graph_for_viz
from store_brief.llmwiki.grouping import load_rnr_damdang_roster
from store_brief.qa.schemas import QAAskBody, QASearchBody, SuggestQuestionBody, SuggestQuestionResponse

_PKG = Path(__file__).resolve().parent

# Parsed files change on disk while the viewer runs; avoid stale browser caches.
_NO_CACHE = {"Cache-Control": "no-store"}


def _to_json(obj):
    if is_dataclass(obj):
        return {k: _to_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_json(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    return obj


def create_app(
    data_dir: str | Path,
    *,
    as_of: str | None = None,
    openai_model: str = "gpt-4o-mini",
) -> FastAPI:
    data_dir = Path(data_dir)
    loader = ParseViewerLoader(data_dir, as_of=as_of)
    app = FastAPI(title="Store Brief — Parse Viewer")
    templates = Jinja2Templates(directory=str(_PKG / "templates"))
    app.mount("/static", StaticFiles(directory=str(_PKG / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        q: str | None = None,
        kind: str | None = None,
        needs_review: bool | None = None,
    ):
        posts = loader.list_posts(query=q, kind=kind, needs_review=needs_review)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "posts": posts,
                "q": q or "",
                "kind": kind or "",
                "needs_review": needs_review,
            },
            headers=_NO_CACHE,
        )

    @app.get("/post/{post_id}", response_class=HTMLResponse)
    async def post_detail(request: Request, post_id: str):
        detail = loader.load_post_detail(post_id)
        if detail is None:
            raise HTTPException(404, "post not found")
        return templates.TemplateResponse(
            request,
            "post.html",
            {"post": detail},
            headers=_NO_CACHE,
        )

    @app.get("/api/posts")
    async def api_posts(
        q: str | None = None,
        kind: str | None = None,
        needs_review: bool | None = None,
    ):
        posts = loader.list_posts(query=q, kind=kind, needs_review=needs_review)
        return JSONResponse(_to_json(posts), headers=_NO_CACHE)

    @app.get("/api/posts/{post_id}")
    async def api_post_detail(post_id: str):
        detail = loader.load_post_detail(post_id)
        if detail is None:
            raise HTTPException(404, "post not found")
        return JSONResponse(_to_json(detail), headers=_NO_CACHE)

    def _quality_report(refresh: bool) -> dict:
        """Serve the cached report unless a refresh is requested.

        Rebuilding re-parses the whole corpus (incl. OCR on scanned PDFs),
        so the cached scripts/parse_quality_report.py output is preferred.
        """
        import json as _json

        from store_brief.ingestion.quality import build_quality_report

        cache = data_dir / "parsed" / "_quality" / "report.json"
        if not refresh and cache.is_file():
            try:
                report = _json.loads(cache.read_text(encoding="utf-8"))
                report["cached"] = True
                return report
            except Exception:
                pass
        report = build_quality_report(data_dir)
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                _json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except Exception:
            pass
        report["cached"] = False
        return report

    @app.get("/quality", response_class=HTMLResponse)
    async def quality_page(request: Request, refresh: bool = False):
        import anyio

        report = await anyio.to_thread.run_sync(_quality_report, refresh)
        return templates.TemplateResponse(
            request,
            "quality.html",
            {"report": report},
            headers=_NO_CACHE,
        )

    @app.get("/api/quality")
    async def api_quality(refresh: bool = False):
        import anyio

        report = await anyio.to_thread.run_sync(_quality_report, refresh)
        return JSONResponse(report, headers=_NO_CACHE)

    @app.get("/media/parsed/{post_id}/{rel_path:path}")
    async def media_parsed(post_id: str, rel_path: str):
        path = loader.resolve_media_path(post_id, rel_path)
        if path is None:
            raise HTTPException(404, "file not found")
        return FileResponse(path, headers=_NO_CACHE)

    @app.get("/kg", response_class=HTMLResponse)
    async def kg_graph_page(request: Request):
        if as_of is None:
            raise HTTPException(
                400,
                "as_of required — run with: python scripts/serve_parse_viewer.py --as-of YYYY-MM-DD",
            )
        gp = default_graph_path(data_dir, as_of)
        stats = None
        if gp.is_file():
            stats = load_knowledge_graph(gp).stats()
        damdangs = [
            d for d in load_rnr_damdang_roster(str(data_dir / "rnr.txt"))
            if d != "점장"
        ]
        return templates.TemplateResponse(
            request,
            "kg.html",
            {
                "as_of": as_of,
                "stats": stats,
                "damdangs": damdangs,
            },
            headers=_NO_CACHE,
        )

    @app.get("/api/kg/graph")
    async def api_kg_graph(
        mode: str = "spine",
        damdang: str | None = None,
        include_products: bool = False,
        include_co_occurs: bool = False,
    ):
        if as_of is None:
            raise HTTPException(400, "as_of required for KG API")
        gp = default_graph_path(data_dir, as_of)
        if not gp.is_file():
            raise HTTPException(404, "knowledge graph not built — run build_knowledge_graph.py")
        graph = load_knowledge_graph(gp)
        payload = graph_for_viz(
            graph,
            mode=mode,
            damdang=damdang or None,
            include_products=include_products,
            include_co_occurs=include_co_occurs,
        )
        return JSONResponse(payload, headers=_NO_CACHE)

    @app.get("/api/kg/nodes/{node_id:path}")
    async def api_kg_node(node_id: str):
        if as_of is None:
            raise HTTPException(400, "as_of required for KG API")
        gp = default_graph_path(data_dir, as_of)
        if not gp.is_file():
            raise HTTPException(404, "knowledge graph not built")
        graph = load_knowledge_graph(gp)
        node = graph.node_by_id().get(node_id)
        if node is None:
            raise HTTPException(404, "node not found")
        return JSONResponse(node.model_dump(mode="json"), headers=_NO_CACHE)

    @app.get("/api/kg")
    async def api_kg_stats():
        if as_of is None:
            raise HTTPException(400, "as_of required for KG API")
        gp = default_graph_path(data_dir, as_of)
        if not gp.is_file():
            raise HTTPException(404, "knowledge graph not built")
        graph = load_knowledge_graph(gp)
        return JSONResponse(graph.stats(), headers=_NO_CACHE)

    @app.get("/api/kg/posts/{post_id}")
    async def api_kg_post(post_id: str):
        if as_of is None:
            raise HTTPException(400, "as_of required for KG API")
        gp = default_graph_path(data_dir, as_of)
        if not gp.is_file():
            raise HTTPException(404, "knowledge graph not built")
        graph = load_knowledge_graph(gp)
        cards = cards_for_post(graph, post_id)
        return JSONResponse({"post_id": post_id, "cards": cards}, headers=_NO_CACHE)

    @app.get("/api/kg/products/{prd_cd}")
    async def api_kg_product(prd_cd: str):
        if as_of is None:
            raise HTTPException(400, "as_of required for KG API")
        gp = default_graph_path(data_dir, as_of)
        if not gp.is_file():
            raise HTTPException(404, "knowledge graph not built")
        graph = load_knowledge_graph(gp)
        cards = cards_by_product(graph, prd_cd)
        return JSONResponse({"prd_cd": prd_cd.upper(), "cards": cards}, headers=_NO_CACHE)

    @app.get("/qa", response_class=HTMLResponse)
    async def qa_page(request: Request):
        if as_of is None:
            raise HTTPException(
                400,
                "as_of required — run with: python scripts/serve_parse_viewer.py --as-of YYYY-MM-DD",
            )
        damdangs = [
            d for d in load_rnr_damdang_roster(str(data_dir / "rnr.txt"))
            if d != "점장"
        ]
        has_key = bool(os.environ.get("OPENAI_API_KEY"))
        return templates.TemplateResponse(
            request,
            "qa.html",
            {
                "as_of": as_of,
                "damdangs": damdangs,
                "openai_configured": has_key,
                "openai_model": openai_model,
            },
            headers=_NO_CACHE,
        )

    @app.get("/api/qa/damdangs")
    async def api_qa_damdangs():
        damdangs = [
            d for d in load_rnr_damdang_roster(str(data_dir / "rnr.txt"))
            if d != "점장"
        ]
        return JSONResponse({"damdangs": damdangs}, headers=_NO_CACHE)

    @app.get("/api/qa/status")
    async def api_qa_status():
        use_as_of = as_of
        index_loaded = False
        index_card_count = 0
        index_path = None
        corpus_card_count = 0
        if use_as_of:
            try:
                from store_brief.qa.corpus import load_corpus

                corpus = load_corpus(data_dir, use_as_of)
                corpus_card_count = len(corpus.cards)
                if corpus.search_index:
                    index_loaded = True
                    index_card_count = corpus.search_index.card_count
                if corpus.search_index_path:
                    index_path = corpus.search_index_path
            except FileNotFoundError:
                pass
        return JSONResponse(
            {
                "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
                "openai_model": openai_model,
                "as_of": as_of,
                "index_loaded": index_loaded,
                "index_card_count": index_card_count,
                "index_path": index_path,
                "corpus_card_count": corpus_card_count,
                "search_pipeline": "v2-soft-boost",
            },
            headers=_NO_CACHE,
        )

    @app.post("/api/qa/search")
    async def api_qa_search(body: QASearchBody):
        use_as_of = body.as_of or as_of
        if not use_as_of:
            raise HTTPException(400, "as_of required")

        from datetime import date as date_cls

        from store_brief.qa.search import (
            load_search_corpus,
            resolve_search_damdangs,
            search_wiki_cards,
        )

        qd = None
        if body.query_date:
            qd = date_cls.fromisoformat(body.query_date)
        elif use_as_of:
            try:
                qd = date_cls.fromisoformat(use_as_of)
            except ValueError:
                qd = None

        try:
            corpus = load_search_corpus(str(data_dir), use_as_of)
            damdangs = resolve_search_damdangs(
                damdang=body.damdang,
                rnr_path=str(data_dir / "rnr.txt"),
            )
            resp = search_wiki_cards(
                corpus,
                question=body.question,
                damdangs=damdangs,
                keywords=body.keywords,
                query_date=qd,
                limit=body.limit,
            )
            return JSONResponse(resp.model_dump(mode="json"), headers=_NO_CACHE)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/qa/ask")
    async def api_qa_ask(body: QAAskBody):
        if not os.environ.get("OPENAI_API_KEY"):
            raise HTTPException(
                503,
                "OPENAI_API_KEY not set — copy .env.example to .env or export the variable",
            )
        use_as_of = body.as_of or as_of
        if not use_as_of:
            raise HTTPException(400, "as_of required")

        from datetime import date as date_cls

        from store_brief.llm.client import LLMClient
        from store_brief.qa.orchestrator import QAOrchestrator
        from store_brief.qa.schemas import QAAskRequest

        qd = None
        if body.query_date:
            qd = date_cls.fromisoformat(body.query_date)

        try:
            llm = LLMClient.openai(model=openai_model)
            orch = QAOrchestrator(
                llm=llm,
                data_dir=str(data_dir),
                as_of=use_as_of,
            )
            resp = orch.ask(
                QAAskRequest(
                    question=body.question,
                    as_of=use_as_of,
                    damdang=body.damdang,
                    query_date=qd,
                    anchor_post_id=body.anchor_post_id,
                    anchor_source_ref=body.anchor_source_ref,
                ),
            )
            return JSONResponse(resp.model_dump(mode="json"), headers=_NO_CACHE)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:
            from pydantic import ValidationError

            if isinstance(exc, ValidationError):
                raise HTTPException(422, str(exc)) from exc
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/qa/suggest-question")
    async def api_qa_suggest_question(body: SuggestQuestionBody | None = None):
        if not os.environ.get("OPENAI_API_KEY"):
            raise HTTPException(
                503,
                "OPENAI_API_KEY not set — copy .env.example to .env or export the variable",
            )
        use_as_of = as_of
        if not use_as_of:
            raise HTTPException(400, "as_of required")

        from store_brief.llm.client import LLMClient
        from store_brief.qa.tools.suggest_question import suggest_question

        req_body = body or SuggestQuestionBody()
        try:
            llm = LLMClient.openai(model=openai_model)
            question, snippet, use_seed = suggest_question(
                llm, data_dir=data_dir, as_of=use_as_of, seed=req_body.seed,
            )
            resp = SuggestQuestionResponse(
                question=question,
                post_id=snippet.post_id,
                post_title=snippet.post_title,
                posted_date=snippet.posted_date,
                source_type=snippet.source_type,
                source_label=snippet.source_label,
                source_ref=snippet.source_ref,
                excerpt_preview=snippet.excerpt_preview,
                excerpt_full=snippet.text,
                seed=use_seed,
                post_url=f"/post/{snippet.post_id}",
            )
            return JSONResponse(resp.model_dump(mode="json"), headers=_NO_CACHE)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    return app
