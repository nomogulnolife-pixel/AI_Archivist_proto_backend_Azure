#ローカル実行用
from dotenv import load_dotenv
load_dotenv()
###############

from fastapi import FastAPI, BackgroundTasks
from app.models import IndexRequest, SearchRequest
from app.blob import load_pdfs_from_blob
from app.chunk import chunk_pages
from app.embedding import get_embedding
from app.search import index_chunks, search_chunks
from fastapi.middleware.cors import CORSMiddleware



 # FastAPI起動
app = FastAPI(title="MOF2 Prototype API")
# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)



@app.get("/")
def health():
    return {"status": "ok"}

def run_index(req: IndexRequest):
    pages = load_pdfs_from_blob(req.container, req.prefix)
    print("DEBUG pages[0]:", pages[0])
    print("DEBUG keys:", pages[0].keys())
    chunks = chunk_pages(pages)

    for c in chunks:
        c["embedding"] = get_embedding(c["text"])

    index_chunks(chunks)

@app.post("/index")
def index_api(req: IndexRequest, bg: BackgroundTasks):
    bg.add_task(run_index, req)
    return {"status": "accepted"}

@app.get("/search")
def search_api(req: SearchRequest):
    return search_chunks(req.question, req.k)

from fastapi import Query
from fastapi.responses import JSONResponse 
from app.search import search_chunks

# 26-01-25 PDFリンクのアクセス権を渡すために追加
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import os
from urllib.parse import urlparse, unquote

def build_sas_blob_url(blob_url: str) -> str:
    #  Blob の素URLから、read専用・期限付きの SAS URL を生成する
    parsed = urlparse(blob_url)

    # ★追加：/container/blob を取り出す
    container_name, blob_name_enc = parsed.path.lstrip("/").split("/", 1)

    # ★修正：SAS生成用はデコードした名前（日本語対策）
    blob_name = unquote(blob_name_enc)


    # ★重要：URLエンコードを戻す（日本語ファイル名対策）
    sas = generate_blob_sas(
        account_name=os.environ["AZURE_STORAGE_ACCOUNT_NAME"],
        container_name=container_name,
        blob_name=blob_name,
        account_key=os.environ["AZURE_STORAGE_ACCOUNT_KEY"].strip(),
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=1500),  # 有効期限
    )

#    return f"{parsed.scheme}://{parsed.netloc}/{container_name}/{blob_name_enc}?{sas}"
    return f"{parsed.scheme}://{parsed.netloc}/{container_name}/{blob_name}?{sas}"


@app.get("/ask")
def ask_api(
    q: str = Query(..., description="質問文") 
    #,
    #k: int = Query(5, ge=1, le=20)
 #   k: int = Query(5, description="取得件数")
):
    results = search_chunks(q, 3)

    #return {
        # "answer": "",  # ← 次のステップで LLM 回答を入れる
       # "sources": [
    sources = [
            {
                "file_name": r["documentName"],
                # "uri": r["blobUrl"], 元のコード。ただのURIではアクセス拒否になる。
                "uri": build_sas_blob_url(r["blobUrl"]),
                "category": "unknown",   # index未変更のため固定
                "page": None,            # index未変更のためNone
                "chunk_id": r["chunkIndex"],
                "text": r["content"],
            }
            for r in results
        ]
   # }
    return JSONResponse(
        content={
            "answer": "",
            "sources": sources
        },
        media_type="application/json; charset=utf-8"
    )
