```mermaid
graph TD
  FE[フロントエンド]
  ASK[ask_api]
  RET[Document Retrieval<br/>search_chunks]
  VEC[ベクトルDB / 検索インデックス]
  PDF[PDFチャンクデータ]

  FE -->|q=質問| ASK
  ASK --> RET
  RET -->|検索クエリ| VEC
  VEC -->|類似チャンク| RET
  RET --> ASK
  ASK -->|sources| FE

  PDF -->|/indexで登録| VEC
