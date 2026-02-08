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
from fastapi import FastAPI, BackgroundTasks, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import os
import re
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests


# 許可するオリジンを取得
def get_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]

# 認証
BFF_SECRET = os.getenv("BFF_BACKEND_SHARED_SECRET")
GOOGLE_CLIENT_ID = os.getenv("AUTH_GOOGLE_ID") or os.getenv("GOOGLE_CLIENT_ID")

# 管理者パスワード（環境変数）
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

def require_admin_password(x_admin_password: str | None):
    """
    /index, /search 専用の簡易認証。
    HTTPヘッダ 'X-ADMIN-PASSWORD' が環境変数 ADMIN_PASSWORD と一致するかを確認する。
    """
    if not ADMIN_PASSWORD:
        # 設定漏れは危険なので止める（運用で必ず設定する）
        raise HTTPException(status_code=500, detail="Server misconfig: ADMIN_PASSWORD is not set")

    if not x_admin_password or x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized (invalid X-ADMIN-PASSWORD)")

def require_bff_secret(x_bff_secret: str | None):
    if not BFF_SECRET:
        # 設定漏れは危険なので 500 にして止めるのが安全
        raise HTTPException(status_code=500, detail="Server misconfig: BFF_BACKEND_SHARED_SECRET is not set")
    if not x_bff_secret or x_bff_secret != BFF_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized (invalid X-BFF-SECRET)")

def verify_google_id_token_and_digit_email(authorization: str | None):
    """
    Authorization: Bearer <google id_token>
    を検証し、email に数字が含まれるユーザーのみ許可する。
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Server misconfig: AUTH_GOOGLE_ID is not set")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        info = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,  # aud を検証
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google id_token")

    # 推奨：メール検証済みのみ
    if not info.get("email_verified"):
        raise HTTPException(status_code=403, detail="Email is not verified")

    email = info.get("email") or ""

    # mo か fu か 数字いずれも含まないと認証NG
    if not ((re.search(r"\d", email) or re.search(r"mo", email)) or re.search(r"fu", email)):
        raise HTTPException(status_code=403, detail="Digits required in email")

    return info  # {email, sub, name, ...}


 # FastAPI起動
app = FastAPI(title="MOF2 Prototype API")
# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-BFF-SECRET", "X-USER-EMAIL"],
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
def index_api(
    req: IndexRequest,
    bg: BackgroundTasks,
    x_admin_password: str | None = Header(default=None, alias="X-ADMIN-PASSWORD"),
):
    # ★管理者認証（/index はデータ更新系なので必須）
    require_admin_password(x_admin_password)

    # 既存の非同期インデックス処理を実行
    bg.add_task(run_index, req)
    return {"status": "accepted"}



@app.get("/search")
def search_api(
    question: str = Query(..., description="検索クエリ"),
    k: int = Query(3, ge=1, le=50, description="取得件数"),
    x_admin_password: str | None = Header(default=None, alias="X-ADMIN-PASSWORD"),
):
    # ★管理者認証（/search はデバッグ/運用用途なら管理者限定にする）
    require_admin_password(x_admin_password)

    # 既存の検索関数を呼び出し
    return search_chunks(question, k)

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
        # PDFとして開くために追加
        content_type="application/pdf",
        content_disposition="inline",
    )

#    return f"{parsed.scheme}://{parsed.netloc}/{container_name}/{blob_name_enc}?{sas}"
    return f"{parsed.scheme}://{parsed.netloc}/{container_name}/{blob_name}?{sas}"


@app.get("/ask")
def ask_api(
    q: str = Query(..., description="質問文"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_bff_secret: str | None = Header(default=None, alias="X-BFF-SECRET"),
    x_user_email: str | None = Header(default=None, alias="X-USER-EMAIL"),
):
    # バックエンドのパスワードによる BFF認証
    #vSrequire_bff_secret(x_bff_secret)

    # ② Google IDトークン検証＋「メールに数字」チェック
    user = verify_google_id_token_and_digit_email(authorization)
    print("ASK by:", user.get("email"))

    results = search_chunks(q, 3)

    sources = [
        {
            "file_name": r["documentName"],
            "uri": build_sas_blob_url(r["blobUrl"]),
            "category": "unknown",
            "page": None,
            "chunk_id": r["chunkIndex"],
            "text": r["content"],
        }
        for r in results
    ]

    return JSONResponse(
        content={"answer": "", "sources": sources},
        media_type="application/json; charset=utf-8",
    )