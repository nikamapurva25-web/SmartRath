from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.events import router as events_router


app = FastAPI(
    title="SmartRath API | HexaBytes | SIH26124",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    events_router,
    prefix="/api",
)


@app.get("/")
def root():
    return {
        "message": "SmartRath API by HexaBytes is running",
        "problem_statement": "SIH26124",
    }