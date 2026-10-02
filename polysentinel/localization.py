from html import escape
from html.parser import HTMLParser

PT = {
    "New top whale detected": "Nova grande carteira em destaque detectada",
    "page_limit": "limite de páginas",
    "request_limit": "limite de consultas",
    "time_limit": "limite de tempo",
    "invalid_response": "resposta inválida",
    "repeated_page": "página repetida",
    "upstream_unavailable": "serviço externo indisponível",
    "No whale activity available.": "Nenhuma atividade de grandes carteiras disponível.",
    "No high-conviction activity available.": "Nenhuma atividade de alta convicção disponível.",
    "invalid edge": "Transferência inválida",
    "native and internal value movements do not prove a deposit": "Movimentações nativas e internas não comprovam um depósito",
    "no exact ERC-20 Transfer matched the edge": "Nenhum evento Transfer ERC-20 corresponde exatamente à transferência",
    "multiple receipt logs match the edge": "Vários logs do recibo correspondem à transferência",
    "protocol event was untrusted, malformed, or unrelated to the edge": "O evento do protocolo não era confiável, estava malformado ou não se relacionava à transferência",
    "verified simple direct collateral transfer": "Transferência direta simples de garantia verificada",
    "complex or unrecognized transfer cannot be attributed": "Não é possível atribuir uma transferência complexa ou não reconhecida",
    "Recent bounded Polygon sample, not complete lifetime history.": "Amostra recente e limitada da Polygon, não o histórico completo.",
    "Token symbols are untrusted metadata; compare contract addresses. Amounts are token units, not USD.": "Símbolos de tokens são metadados não confiáveis; compare os endereços dos contratos. Valores são unidades de tokens, não dólares.",
    "Gas transfers, settlement, minting, spam and unsolicited dust are not necessarily trading deposits.": "Transferências para taxas, liquidações, emissão de tokens, spam e pequenas quantias não solicitadas não são necessariamente depósitos para negociação.",
    "Unlabelled exchanges, bridges, mixers and shared services can create false relationship signals.": "Corretoras, pontes, mixers e serviços compartilhados sem identificação podem gerar falsos indícios de relações.",
    "No cross-chain continuity, wallet-controller verification, real-world identity or exact bet-funding attribution.": "Não há verificação de continuidade entre blockchains, de quem controla a carteira, de identidade real ou da origem exata dos recursos de uma aposta.",
    "Upstream timing is compatible with a path, not proof that the same funds flowed through it.": "Os horários anteriores são compatíveis com um caminho, mas não comprovam que os mesmos recursos o percorreram.",
    "Relationships compare saved investigations only; absence of a match proves nothing.": "As relações comparam apenas investigações salvas; a ausência de coincidências não prova nada.",
    "Transfers prove movement of assets, not common ownership, identity, insider knowledge, or the source of a specific bet.": "Transferências comprovam movimentação de ativos, não titularidade em comum, identidade, informação privilegiada ou a origem dos recursos de uma aposta específica.",
    "Unknown exchanges, bridges, and shared services are not identified or attributed": "Corretoras, pontes e serviços compartilhados desconhecidos não são identificados nem atribuídos",
    "ERC20 transfer log index unavailable; duplicate event indexing is ambiguous": "Índice de log da transferência ERC20 indisponível; a identificação de eventos duplicados é ambígua",
    "Native transfers may only fund gas and are not treated as capital attribution": "Transferências nativas podem servir apenas para pagar taxas e não são consideradas atribuição de capital",
    "Investigation is a bounded recent sample, not complete transaction history": "A investigação é uma amostra recente e limitada, não o histórico completo de transações",
    "Investigation failed; retry after the cooldown.": "A investigação falhou; tente novamente após o intervalo de espera.",
    "Display and JSON export are capped at the newest 10,000 stored edges. Older evidence remains in the database; displayed totals are incomplete.": "A exibição e a exportação JSON se limitam às 10.000 transferências salvas mais recentes. Evidências anteriores permanecem no banco; os totais exibidos são incompletos.",
    "Relationship comparison reached its result limit.": "A comparação de relações atingiu seu limite de resultados.",
    "Trading overlap reached its comparison limit.": "A análise de coincidência temporal atingiu seu limite de comparações.",
    "Dashboard": "Painel",
    "Insiders": "Carteiras sinalizadas",
    "Transfers": "Transferências",
    "Methodology": "Metodologia",
    "About": "Sobre",
    "Developer": "Desenvolvedor",
    "Disclaimer": "Aviso legal",
    "Documentation": "Documentação",
    "API response time": "Tempo de resposta da API",
    "Language": "Idioma",
    "Large and clustered trades on Polymarket political markets": "Operações grandes e concentradas nos mercados políticos da Polymarket",
    "CONNECTING": "CONECTANDO",
    "LIVE": "AO VIVO",
    "STALE": "DESATUALIZADO",
    "Syncing...": "Sincronizando...",
    "Syncing Failed": "Falha na sincronização",
    "Summary": "Resumo",
    "Flagged share of volume": "Participação do volume sinalizado",
    "Sentiment, last 100 bets": "Sentimento das últimas 100 apostas",
    "Yes": "Sim",
    "No": "Não",
    "Average trade, last hour": "Operação média na última hora",
    "Volume, last 30 min": "Volume nos últimos 30 min",
    "Volume": "Volume",
    "24h in 30-minute buckets, BRT": "24h em intervalos de 30 minutos, horário de Brasília",
    "Latest large bets": "Últimas apostas grandes",
    "Filter markets": "Filtrar mercados",
    "Market": "Mercado",
    "Wallet": "Carteira",
    "Source": "Fonte",
    "Size": "Valor",
    "High conviction": "Alta convicção",
    "Markets by average bet": "Mercados por aposta média",
    "Avg. size": "Valor médio",
    "LIVE TRADES": "OPERAÇÕES AO VIVO",
    "No recent activity.": "Nenhuma atividade recente.",
    "No volume yet": "Ainda sem volume",
    "Flagged": "Sinalizado",
    "Other": "Outros",
    "Volume (USD)": "Volume (USD)",
    "even": "equilibrado",
    "Unknown": "Desconhecido",
    "Untitled market": "Mercado sem título",
    "Unable to load dashboard data. Retrying automatically.": "Não foi possível carregar os dados do painel. Uma nova tentativa será feita automaticamente.",
    "Dashboard data is temporarily unavailable.": "Os dados do painel estão temporariamente indisponíveis.",
    "Wallets flagged for clustered large bets. A flag is a signal, not proof.": "Carteiras sinalizadas por apostas grandes e concentradas. Uma sinalização é um indício, não uma prova.",
    "Top position": "Principal posição",
    "Last active": "Última atividade",
    "Volume scanned": "Volume monitorado",
    "No flagged wallets yet": "Nenhuma carteira sinalizada ainda",
    "Wallets appear when trades meet the clustering thresholds described in Methodology.": "As carteiras aparecem quando suas operações atingem os critérios de concentração descritos na Metodologia.",
    "Insider data is temporarily unavailable": "Os dados das carteiras sinalizadas estão temporariamente indisponíveis",
    "The next refresh will retry automatically.": "A próxima atualização tentará novamente automaticamente.",
    "The request timed out. The next refresh will retry automatically.": "A solicitação excedeu o tempo limite. A próxima atualização tentará novamente automaticamente.",
    "Close dossier": "Fechar dossiê",
    "View on PolygonScan": "Ver no PolygonScan",
    "Explore transfers": "Explorar transferências",
    "Total volume tracked": "Volume total acompanhado",
    "Legacy sender hint (unverified)": "Indício antigo de remetente (não verificado)",
    "Last activity": "Última atividade",
    "Max single bet": "Maior aposta individual",
    "Recent flagged trades": "Operações sinalizadas recentes",
    "Dossier": "Dossiê",
    "Invalid wallet address": "Endereço de carteira inválido",
    "Update time unavailable": "Horário da atualização indisponível",
    "Loading...": "Carregando...",
    "No trade history available.": "Nenhum histórico de operações disponível.",
    "Dossier request timed out.": "A solicitação do dossiê excedeu o tempo limite.",
    "Unable to load trade history.": "Não foi possível carregar o histórico de operações.",
    "Transfer explorer": "Explorador de transferências",
    "Explore observed transfers and wallet relationships. This is not a funding-source or identity detector.": "Explore transferências observadas e relações entre carteiras. Isto não identifica a origem dos recursos nem a identidade de pessoas.",
    "Polygon wallet address": "Endereço da carteira na Polygon",
    "Open report": "Abrir relatório",
    "Investigate / refresh": "Investigar / atualizar",
    "Classify saved transfers": "Classificar transferências salvas",
    "Enter a wallet or explore transfers from its dossier.": "Informe uma carteira ou explore as transferências a partir do dossiê.",
    "Background investigations require the scanner and an Etherscan V2 key with Polygon access. Recent samples are bounded to three upstream hops; they are not a lifetime ledger.": "As investigações em segundo plano exigem o scanner e uma chave Etherscan V2 com acesso à Polygon. As amostras recentes se limitam a três etapas anteriores; não abrangem todo o histórico.",
    "Download evidence JSON": "Baixar evidências em JSON",
    "Receipt classification": "Classificação de recibos",
    "Verified simple transfers": "Transferências simples verificadas",
    "Exact on-chain token transfers in supported simple transactions. Inflows are deposit candidates, not proof of original funding, intent or ownership. Complex exchange withdrawals, bridges and smart-wallet operations may remain unknown.": "Transferências de tokens confirmadas na blockchain em transações simples compatíveis. Entradas são possíveis depósitos, não provas da origem dos recursos, intenção ou titularidade. Saques complexos de corretoras, pontes e carteiras inteligentes podem continuar sem classificação.",
    "Observed direct inflows": "Entradas diretas observadas",
    "API-row totals for each sender and token contract, not an audited balance. Missing log indices make event identity ambiguous. Native POL can be gas funding. Tokens are not valued in dollars.": "Totais das linhas da API por remetente e contrato de token, não um saldo auditado. A ausência de índices de log torna a identificação dos eventos ambígua. POL nativo pode servir para pagar taxas. Os tokens não são avaliados em dólares.",
    "Verified simple-transfer links": "Relações de transferências simples verificadas",
    "Only receipt-classified simple transfers appear here. Unknown and trading-related transactions remain in the evidence table. These links do not prove ownership or continuity of particular funds.": "Aqui aparecem apenas transferências simples classificadas por recibos. Transações desconhecidas e relacionadas a negociações permanecem na tabela de evidências. Essas relações não comprovam titularidade nem continuidade dos recursos.",
    "Relationships across saved investigations": "Relações entre investigações salvas",
    "Trading-time overlap": "Coincidência nos horários de negociação",
    "Up to 500 tracked trades in the previous seven days. Repeated overlap is descriptive, not proof of coordination.": "Até 500 operações acompanhadas nos últimos sete dias. Coincidências repetidas são descritivas, não provas de coordenação.",
    "Transfer evidence": "Evidências de transferências",
    "Direction": "Direção",
    "All observed edges": "Todas as transferências observadas",
    "Direct inflows": "Entradas diretas",
    "Direct outflows": "Saídas diretas",
    "Upstream": "Etapas anteriores",
    "Asset": "Ativo",
    "All contracts": "Todos os contratos",
    "Classification": "Classificação",
    "All categories": "Todas as categorias",
    "Verified simple transfer": "Transferência simples verificada",
    "Trading-related": "Relacionada a negociações",
    "Payout redemption": "Resgate de pagamento",
    "Position split": "Divisão de posição",
    "Positions merge": "Fusão de posições",
    "Coverage and limitations": "Cobertura e limitações",
    "Time": "Horário",
    "Hop": "Etapa",
    "From → To": "De → Para",
    "Token units": "Unidades do token",
    "Asset contract": "Contrato do ativo",
    "Evidence": "Evidência",
    "Unknown address": "Endereço desconhecido",
    "Invalid transaction": "Transação inválida",
    "Not available": "Indisponível",
    "Unknown token": "Token desconhecido",
    "Native POL; not necessarily trading capital": "POL nativo; não necessariamente capital para negociar",
    "Event identity incomplete": "Identificação do evento incompleta",
    "Receipt not classified": "Recibo não classificado",
    "Cached receipt is older than one hour; refresh before relying on it.": "O recibo em cache tem mais de uma hora; atualize antes de utilizá-lo.",
    "Show 100 more": "Mostrar mais 100",
    "Verified simple inflow": "Entrada simples verificada",
    "Verified simple outflow": "Saída simples verificada",
    "Trading-related (not a deposit claim)": "Relacionada a negociações (não comprova depósito)",
    "Redemption-related": "Relacionada a resgate",
    "Position split-related": "Relacionada a divisão de posição",
    "Position merge-related": "Relacionada a fusão de posições",
    "Observed edges": "Transferências observadas",
    "Inflow / deposit candidate": "Entrada / possível depósito",
    "Outflow / withdrawal candidate": "Saída / possível retirada",
    "From": "De",
    "To": "Para",
    "Contract": "Contrato",
    "Log identity": "Identificação do log",
    "No supported simple transfers confirmed in the classified sample. This is not proof that no deposits exist.": "Nenhuma transferência simples compatível foi confirmada na amostra classificada. Isto não prova a ausência de depósitos.",
    "No investigation yet. Choose Investigate / refresh to start.": "Ainda não há investigação. Selecione Investigar / atualizar para iniciar.",
    "Queued. Keep the scanner running; this report refreshes automatically.": "Na fila. Mantenha o scanner em execução; este relatório é atualizado automaticamente.",
    "Tracing transfers in the background. Previous evidence, if shown, is retained until the result arrives.": "Buscando transferências em segundo plano. As evidências anteriores, se exibidas, são mantidas até a chegada do resultado.",
    "Bounded investigation finished. This is not a claim of complete lifetime coverage.": "Investigação limitada concluída. Isto não significa cobertura de todo o histórico.",
    "Partial evidence. Inspect coverage and warnings before drawing conclusions.": "Evidências parciais. Confira a cobertura e os avisos antes de tirar conclusões.",
    "The API key or plan cannot access these Polygon endpoints.": "A chave ou o plano da API não permite acesso a estes endpoints da Polygon.",
    "Set ETHERSCAN_API_KEY in .env and restart the web server and scanner.": "Configure ETHERSCAN_API_KEY no .env e reinicie o servidor web e o scanner.",
    "Configure ETHERSCAN_API_KEY with Polygon access and restart both processes.": "Configure ETHERSCAN_API_KEY com acesso à Polygon e reinicie os dois processos.",
    "Investigation failed. Previous evidence may be retained; retry after the cooldown.": "A investigação falhou. As evidências anteriores podem ser mantidas; tente novamente após o intervalo de espera.",
    "Sender": "Remetente",
    "First in sample": "Primeira na amostra",
    "Last in sample": "Última na amostra",
    "No direct inflows in the available evidence. This does not mean the wallet was never funded.": "Nenhuma entrada direta nas evidências disponíveis. Isto não significa que a carteira nunca recebeu recursos.",
    "No paths available.": "Nenhum caminho disponível.",
    "Shared observed sender": "Remetente observado em comum",
    "Shared observed destination": "Destino observado em comum",
    "Root transaction evidence:": "Evidências de transações da carteira principal:",
    "Peer transaction evidence:": "Evidências de transações da outra carteira:",
    "No matching counterparties among saved investigations. Investigate other wallets to expand this comparison.": "Nenhuma contraparte em comum entre as investigações salvas. Investigue outras carteiras para ampliar a comparação.",
    "These are raw transfer matches, not deposit-only comparisons. Unlabelled shared services, trading and unsolicited transfers can produce these links. No common-owner conclusion is made.": "São coincidências em transferências brutas, não comparações apenas de depósitos. Serviços compartilhados sem identificação, negociações e transferências não solicitadas podem gerar essas relações. Não se conclui que há um titular em comum.",
    "Descriptive overlap only. Shared news, bots and active markets can explain it; no statistical significance or coordination is established.": "Apenas coincidência descritiva. Notícias em comum, robôs e mercados ativos podem explicá-la; não há comprovação de significância estatística ou coordenação.",
    "No repeated cross-market timing overlap in the bounded locally tracked trade sample.": "Nenhuma coincidência temporal repetida entre mercados na amostra limitada de operações acompanhadas localmente.",
    "Endpoint sample exhausted": "Amostra do endpoint esgotada",
    "Limited / unavailable": "Limitada / indisponível",
    "All assets": "Todos os ativos",
    "Root / no cutoff": "Principal / sem corte temporal",
    "Unlabelled wallet": "Carteira sem identificação",
    "Official contract source": "Fonte oficial do contrato",
    "Stream": "Fluxo",
    "Pages": "Páginas",
    "Rows": "Linhas",
    "Coverage": "Cobertura",
    "Problem": "Problema",
    "Asset filter": "Filtro de ativo",
    "Before": "Antes de",
    "Enter a valid 0x Polygon address (40 hexadecimal characters).": "Informe um endereço Polygon válido iniciado por 0x (40 caracteres hexadecimais).",
    "Requesting investigation…": "Solicitando investigação…",
    "Loading saved evidence…": "Carregando evidências salvas…",
    "Report request timed out. You can retry.": "A solicitação do relatório excedeu o tempo limite. Você pode tentar novamente.",
    "Unable to load evidence. You can retry.": "Não foi possível carregar as evidências. Você pode tentar novamente.",
    "Wait ten minutes between requests for this wallet.": "Aguarde dez minutos entre solicitações para esta carteira.",
    "The investigation queue is full (ten jobs).": "A fila de investigação está cheia (dez tarefas).",
    "The daily investigation budget is exhausted (30 requests per 24 hours).": "O limite diário de investigações foi atingido (30 solicitações a cada 24 horas).",
    "Investigate transfers first; no saved evidence to classify.": "Investigue as transferências primeiro; não há evidências salvas para classificar.",
    "Please wait ten minutes between investigations of the same wallet.": "Aguarde dez minutos entre investigações da mesma carteira.",
    "The investigation queue is full. Try again shortly.": "A fila de investigação está cheia. Tente novamente em breve.",
    "Receipt not fetched": "Recibo ainda não consultado",
    "receipt not verified": "Recibo não verificado",
    "transaction execution failed": "A execução da transação falhou",
    "trusted protocol context is wallet-related but does not prove this transfer is settlement or a deposit": "O contexto de um protocolo confiável envolve a carteira, mas não comprova que esta transferência seja liquidação ou depósito",
    "queued": "na fila",
    "running": "em andamento",
    "complete": "concluída",
    "partial": "parcial",
    "not_requested": "não solicitada",
    "unknown": "desconhecido",
    "unsupported": "não compatível",
    "error": "erro",
    "no_key": "sem chave",
    "verified_infrastructure": "infraestrutura verificada",
    "depth_limit": "limite de etapas",
}


class LocalizedHTML(HTMLParser):
    def __init__(self, language):
        super().__init__(convert_charrefs=False)
        self.language = language
        self.parts = []
        self.stack = []

    def blocked(self):
        return any(item[1] for item in self.stack)

    def handle_starttag(self, tag, attrs):
        language = dict(attrs).get("lang")
        blocked = self.blocked() or (
            tag != "html"
            and not dict(attrs).get("data-language-link")
            and language in ("en", "pt-BR")
            and language != self.language
        )
        if not blocked:
            raw = self.get_starttag_text()
            if self.language == "pt-BR":
                for name, value in attrs:
                    if name in ("placeholder", "aria-label", "title") and value in PT:
                        raw = raw.replace(
                            escape(value, quote=True), escape(PT[value], quote=True)
                        )
            self.parts.append(raw)
        if tag not in (
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ):
            self.stack.append((tag, blocked))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if not self.blocked():
            self.parts.append(f"</{tag}>")
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.blocked():
            return
        stripped = data.strip()
        if self.language == "pt-BR" and not any(
            tag in ("script", "style") for tag, _ in self.stack
        ):
            translated = PT.get(stripped)
            if translated is None and stripped.endswith(" · PolySentinel"):
                title = stripped.removesuffix(" · PolySentinel")
                translated = PT.get(title, title) + " · PolySentinel"
            if translated is not None:
                data = data.replace(stripped, escape(translated, quote=False))
        self.parts.append(data)

    def handle_entityref(self, name):
        if not self.blocked():
            self.parts.append(f"&{name};")

    def handle_charref(self, name):
        if not self.blocked():
            self.parts.append(f"&#{name};")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")


def localize_html(html, language):
    parser = LocalizedHTML(language)
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)
