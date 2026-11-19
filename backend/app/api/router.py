from fastapi import APIRouter

from app.api import advice, analysis, bits, documents, external, generation, imports, materials, net, papers, questions, subjective, subjects, system

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(subjects.router)
api_router.include_router(documents.router)
api_router.include_router(questions.router)
api_router.include_router(analysis.router)
api_router.include_router(generation.router)
api_router.include_router(papers.router)
api_router.include_router(advice.router)
api_router.include_router(imports.router)
api_router.include_router(net.router)
api_router.include_router(bits.router)
api_router.include_router(subjective.router)
api_router.include_router(external.router)
api_router.include_router(materials.router)
