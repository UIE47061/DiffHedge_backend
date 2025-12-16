import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from bitcoinutils.setup import setup

from service.database import init_db
from router import contract_router, websocket_router

# 設定比特幣環境
setup('testnet') 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown (if needed)

app = FastAPI(title="HashHedge Trust-Minimized Oracle", lifespan=lifespan)

# 允許 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(contract_router.router)
app.include_router(websocket_router.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

