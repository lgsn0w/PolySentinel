(() => {
  const language = document.documentElement.lang;
  const dictionary = JSON.parse(
    document.getElementById("ui-translations").textContent,
  );
  const patterns = [
    [
      /^(BUY|SELL) (Yes|No|Unlabeled outcome)$/,
      (text) =>
        text
          .replace("BUY", "COMPRA")
          .replace("SELL", "VENDA")
          .replace("Yes", "Sim")
          .replace("No", "Não")
          .replace("Unlabeled outcome", "Resultado sem identificação"),
    ],
    [/^Last Update: (.*)$/, "Última atualização: $1"],
    [/^(\d+)([smh]) ago$/, "há $1$2"],
    [/^(.*) in the last 24h$/, "$1 nas últimas 24h"],
    [/^(.*) of (.*) observed edges$/, "$1 de $2 transferências observadas"],
    [
      /^(.*) of (.*) simple root transfers shown; use the evidence category filter for the rest\.$/,
      "$1 de $2 transferências simples da carteira principal exibidas; use o filtro de classificação para ver as demais.",
    ],
    [
      /^(.*) of (.*) distinct transfer relationships shown\. Full evidence is below and in the JSON export\.$/,
      "$1 de $2 relações de transferência exibidas. As evidências completas estão abaixo e na exportação JSON.",
    ],
    [/^Observed: (.*)$/, "Observado em: $1"],
    [/^Receipt log #(\d+)$/, "Log do recibo nº $1"],
    [/^Log #(.*)$/, "Log nº $1"],
    [
      /^Hop (\d+) · (.*) · sample transfer (.*)$/,
      "Etapa $1 · $2 · transferência da amostra $3",
    ],
    [/^Asset: (.*); (.*)$/, "Ativo: $1; $2"],
    [
      /^(\d+) sampled trades across (\d+) markets overlapped within 120 seconds on the same side and outcome\.$/,
      "$1 operações da amostra em $2 mercados coincidiram em até 120 segundos na mesma direção e resultado.",
    ],
    [
      /^(\d+) rows; (\d+) invalid; (\d+) ambiguous$/,
      "$1 linhas; $2 inválidas; $3 ambíguas",
    ],
    [
      /^Status: (.*)\. Root: (.*)\. (\d+) upstream calls; (\d+) address\/asset states\.$/,
      "Situação: $1. Carteira principal: $2. $3 consultas anteriores; $4 estados de endereço/ativo.",
    ],
    [
      /^Receipt classification: (.*)\. (\d+) verified receipts in the last job; (\d+) skipped; (\d+) unavailable; (\d+) failed executions\. Last checked: (.*)$/,
      "Classificação de recibos: $1. $2 recibos verificados na última tarefa; $3 ignorados; $4 indisponíveis; $5 execuções com falha. Última consulta: $6",
    ],
    [
      /^Traversal stopped at verified infrastructure (.*)$/,
      "Busca interrompida em infraestrutura verificada $1",
    ],
    [/^Depth limit reached at (.*)$/, "Limite de etapas atingido em $1"],
    [/^(\w+) unavailable for (0x\w+)(.*)$/, "$1 indisponível para $2$3"],
    [/^Repeated (\w+) page for (.*)$/, "Página repetida de $1 para $2"],
    [
      /^Expanded temporal cutoff revisited for (.*)$/,
      "Corte temporal ampliado revisitado para $1",
    ],
    [
      /^Previous transfer evidence retained from (.*) and merged with any new observations; the latest lookup was incomplete\.$/,
      "Evidências anteriores de $1 mantidas e combinadas com novas observações; a última consulta foi incompleta.",
    ],
  ];
  window.uiLocale = language === "pt-BR" ? "pt-BR" : "en-US";
  window.translateUI = (value) => {
    const text = String(value);
    if (language !== "pt-BR") return text;
    if (Object.hasOwn(dictionary, text)) return dictionary[text];
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(text)) return text.replace(pattern, replacement);
    }
    const checked = text.indexOf(" Last checked: ");
    if (checked !== -1)
      return (
        window.translateUI(text.slice(0, checked)) +
        text
          .slice(checked)
          .replace(" Last checked: ", " Última consulta: ")
          .replace(
            " Etherscan key is not configured.",
            " A chave Etherscan não está configurada.",
          )
      );
    if (/^[\d$.,\sA-Z]+ of [\d$.,\sA-Z]+$/.test(text))
      return text.replace(" of ", " de ");
    return text
      .replace(
        " · retained from a previous lookup",
        " · mantido de uma consulta anterior",
      )
      .replace(" · stale cached receipt", " · recibo em cache desatualizado")
      .replace(
        " (API-row total; event identity ambiguous)",
        " (total das linhas da API; identificação do evento ambígua)",
      );
  };
})();
