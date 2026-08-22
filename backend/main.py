from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
import os
from backend.models.db_models import Base
from backend.database import engine
from backend.api.routes import router as api_router

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Create all database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fantasy Football Prediction API", version="1.0.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
logger.info("Fantasy Football Prediction API started; CORS origins=%s", allowed_origins)

@app.get("/")
async def root():
    logger.debug("root() called: basic liveness check hit")
    return {"message": "Fantasy Football Prediction API"}

@app.get("/health")
async def health():
    logger.debug("health() called: health check hit")
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
