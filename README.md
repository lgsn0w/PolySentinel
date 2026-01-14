<div align="center">
  <img src="assets/image_aa5448.png" alt="PolySentinel Dashboard" width="100%">
  
  <h1>PolySentinel</h1>
  
  <h3>Inteligência em Tempo Real & Forense Financeira para Polymarket</h3>

  <p>
    <img src="https://img.shields.io/badge/Status-Live-success?style=for-the-badge&logo=statuspage" alt="Status Live">
    <img src="https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python Version">
    <img src="https://img.shields.io/badge/Flask-Backend-lightgrey?style=for-the-badge&logo=flask" alt="Flask">
    <img src="https://img.shields.io/badge/SQLite-WAL_Mode-blue?style=for-the-badge&logo=sqlite" alt="SQLite WAL">
  </p>
</div>

---

## Visão Geral

**PolySentinel** é uma ferramenta de engenharia de dados projetada para monitorar, agregar e analisar fluxos de capital no Polymarket em tempo real. O sistema opera sob a premissa de que movimentos financeiros relevantes frequentemente antecedem a divulgação de notícias nos meios tradicionais.

> "O projeto transforma a curiosidade sobre grandes movimentações em um fluxo contínuo de observação estruturada."

---

## Funcionalidades Principais

| Recurso | Descrição |
| :--- | :--- |
| ** Dashboard Live** | Visualização de velocidade de mercado, sentimento (Bulls vs Bears) e ticker de apostas ao vivo. |
| ** Insider Zone** | Rastreamento de "Whales" com alto volume de acumulação e verificação de fontes de financiamento (ex: Binance, Tornado Cash). |
| ** Dossiês Forenses** | Geração automática de perfis baseados no histórico de transações e idade da carteira. |
| ** Dual Pipeline** | Arquitetura híbrida para ingestão de alta frequência (Varejo) e análise profunda (Institucional). |

---

## Screenshots

### Dashboard & Métricas de Mercado
*Visão geral da velocidade de apostas e sentimento em tempo real.*
![Dashboard](assets/image_aa5448.png)

### Rastreamento de Insiders
*Detecção de carteiras institucionais e análise de origem de fundos.*
![Insider Info](assets/image_aa5463.png)

---

## Arquitetura do Sistema

O backend utiliza um **Sistema de Duplo Pipeline** para garantir latência mínima (<200ms) sem perder dados críticos.

```mermaid
graph TD
  A[Polymarket API] -->|Stream| B(Sentinel Bot)
  B -->|<$20 - Varejo| C[Pipeline A: Alta Frequência]
  B -->|>$1k - Whales| D[Pipeline B: Análise Forense]
  C --> E[(Main DB)]
  D --> F{Acumulação > $3k?}
  F -- Sim --> G[(Insider DB + Forensics)]
  F -- Não --> E
  E --> H[Flask API]
  G --> H
  H --> I[Dashboard Frontend]
