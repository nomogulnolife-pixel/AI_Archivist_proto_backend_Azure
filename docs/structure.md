```mermaid

graph LR
  subgraph Frontend
    page["page.tsx (メインページ)"]
    header["Header.tsx (共通ヘッダー)"]
    searchForm["SearchForm.tsx (検索フォーム)"]
    resultList["SearchResultList.tsx (結果一覧)"]
    resultCard["ResultCard.tsx (結果カード)"]
    preview["FilePreview.tsx (プレビュー表示)"]
    useSearch["useFileSearch.ts (検索ロジック)"]
    config["config.ts (API設定)"]
  end
  subgraph Backend
    main["main.py (APIサーバ)"]
    retrieve["DocumentRetrieval モジュール"]
    llm["QA・LLM モジュール"]
  end

  page --> header
  page --> searchForm
  page --> resultList
  page --> preview
  searchForm --> useSearch
  useSearch --> config
  useSearch -->|GET /ask| main
  main --> retrieve
  retrieve --> llm
  llm --> main
  main --> useSearch
  useSearch --> resultList
  resultList --> resultCard
  resultCard --> preview
