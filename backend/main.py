from fastapi import FastAPI
from dotenv import load_dotenv
import os
from backend.models.db_models import Base
from backend.database import engine
from backend.api.routes import router as api_router

# Load environment variables
load_dotenv()

# Create all database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fantasy Football Prediction API", version="1.0.0")
app.include_router(api_router)

@app.get("/")
async def root():
    return {"message": "Fantasy Football Prediction API"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
