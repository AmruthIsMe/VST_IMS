from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.database import engine, Base
from app.routers import products, suppliers, orders, users, dashboard, sap_sync, forecast, genie

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(suppliers.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(sap_sync.router)
app.include_router(forecast.router)
app.include_router(genie.router)


@app.get("/")
def root():
    return {"status": "healthy", "message": "VST IMS API is running", "app": settings.APP_NAME}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "app": settings.APP_NAME}

